import os
import time
from collections import OrderedDict

import httpx
from dotenv import load_dotenv

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


# -----------------------------
# LRU + TTL Cache + Metrics
# -----------------------------
CACHE_TTL = 300
MAX_CACHE_SIZE = 1000
CACHE_HIT = 0
CACHE_MISS = 0
GITHUB_REQUESTS = 0
GITHUB_ERRORS = 0


class LRUCache:
    def __init__(self, max_size=MAX_CACHE_SIZE, ttl=CACHE_TTL):
        self.cache = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl

    def get(self, key):
        global CACHE_HIT, CACHE_MISS
        item = self.cache.get(key)
        if not item:
            CACHE_MISS += 1
            return None

        data, timestamp = item
        if time.time() - timestamp > self.ttl:
            del self.cache[key]
            CACHE_MISS += 1
            return None

        self.cache.move_to_end(key)
        CACHE_HIT += 1
        return data

    def set(self, key, data):
        self.cache[key] = (data, time.time())
        self.cache.move_to_end(key)
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)


LRU = LRUCache()


def make_cache_key(url: str, params=None):
    if params:
        return url + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    return url


def get_headers():
    headers = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return headers


print("TOKEN LOADED:", GITHUB_TOKEN)

# -----------------------------
# Shared AsyncClients با محدودیت
# -----------------------------
_client_api: httpx.AsyncClient | None = None
_client_raw: httpx.AsyncClient | None = None
_client_download: httpx.AsyncClient | None = None


def get_http_client_api() -> httpx.AsyncClient:
    global _client_api
    if _client_api is None:
        limits = httpx.Limits(
            max_connections=80,
            max_keepalive_connections=20,
        )
        _client_api = httpx.AsyncClient(
            timeout=10,
            limits=limits
        )
    return _client_api


def get_http_client_raw() -> httpx.AsyncClient:
    global _client_raw
    if _client_raw is None:
        limits = httpx.Limits(
            max_connections=40,
            max_keepalive_connections=10,
        )
        _client_raw = httpx.AsyncClient(
            timeout=10,
            limits=limits
        )
    return _client_raw


def get_http_client_download() -> httpx.AsyncClient:
    global _client_download
    if _client_download is None:
        limits = httpx.Limits(
            max_connections=20,
            max_keepalive_connections=5,
        )
        _client_download = httpx.AsyncClient(
            timeout=None,
            limits=limits
        )
    return _client_download


# -----------------------------
# Circuit Breaker ساده برای API
# -----------------------------
CB_OPEN = False
CB_LAST_OPEN_TIME = 0.0
CB_FAIL_COUNT = 0
CB_FAIL_THRESHOLD = 5
CB_RESET_SECONDS = 30


def _circuit_allow() -> bool:
    global CB_OPEN, CB_LAST_OPEN_TIME, CB_FAIL_COUNT
    now = time.time()
    if CB_OPEN:
        if now - CB_LAST_OPEN_TIME > CB_RESET_SECONDS:
            CB_OPEN = False
            CB_FAIL_COUNT = 0
            return True
        return False
    return True


def _circuit_record_success():
    global CB_FAIL_COUNT, CB_OPEN
    CB_FAIL_COUNT = 0
    CB_OPEN = False


def _circuit_record_failure():
    global CB_FAIL_COUNT, CB_OPEN, CB_LAST_OPEN_TIME
    CB_FAIL_COUNT += 1
    if CB_FAIL_COUNT >= CB_FAIL_THRESHOLD:
        CB_OPEN = True
        CB_LAST_OPEN_TIME = time.time()


async def api_call(url, params=None, use_cache=True):
    global GITHUB_REQUESTS, GITHUB_ERRORS

    key = make_cache_key(url, params)
    if use_cache:
        cached = LRU.get(key)
        if cached is not None:
            return cached

    if not _circuit_allow():
        # Circuit باز است → فقط از کش جواب می‌دهیم
        if use_cache:
            cached = LRU.get(key)
            if cached is not None:
                return cached
        raise httpx.HTTPError("Circuit open for GitHub API")

    client = get_http_client_api()
    GITHUB_REQUESTS += 1

    try:
        r = await client.get(url, params=params, headers=get_headers())
        if r.status_code == 404:
            _circuit_record_success()
            return None
        r.raise_for_status()
        data = r.json()
        if use_cache and data is not None:
            LRU.set(key, data)
        _circuit_record_success()
        return data
    except Exception as e:
        GITHUB_ERRORS += 1
        _circuit_record_failure()
        print(f"[GITHUB ERROR] {url} -> {type(e).__name__}: {e}")
        raise


# -----------------------------
# Search Users
# -----------------------------
async def search_users(q: str, page: int = 1, per_page: int = 10):
    url = f"{GITHUB_API_BASE}/search/users"
    params = {"q": q, "page": page, "per_page": per_page}
    return await api_call(url, params=params, use_cache=True)


# -----------------------------
# Get User Info
# -----------------------------
async def get_user(username: str):
    url = f"{GITHUB_API_BASE}/users/{username}"
    data = await api_call(url, use_cache=True)
    if data is None:
        raise httpx.HTTPStatusError("User not found", request=None, response=None)
    return data


# -----------------------------
# Get User Repositories
# -----------------------------
async def get_user_repos(username: str):
    url = f"{GITHUB_API_BASE}/users/{username}/repos"
    data = await api_call(url, use_cache=True)
    if data is None:
        return []
    return data


# -----------------------------
# Get Repository Info
# -----------------------------
async def get_repo(owner: str, repo: str):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
    data = await api_call(url, use_cache=True)
    if data is None:
        raise httpx.HTTPStatusError("Repo not found", request=None, response=None)
    return data


# -----------------------------
# Detect Default Branch
# -----------------------------
async def get_default_branch(owner: str, repo: str):
    repo_data = await get_repo(owner, repo)
    return repo_data.get("default_branch", "main")


# -----------------------------
# Download ZIP (بدون کش، فقط استریم)
# -----------------------------
async def download_repo_zip(owner: str, repo: str, ref: str = None):
    if ref is None:
        ref = await get_default_branch(owner, repo)

    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/zipball/{ref}"
    client = get_http_client_download()
    r = await client.get(url, headers=get_headers(), follow_redirects=True)
    r.raise_for_status()
    return r


# -----------------------------
# Get Repository Contents
# -----------------------------
async def get_repo_contents(owner: str, repo: str, path: str = ""):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/contents/{path}"
    data = await api_call(url, use_cache=True)
    if data is None:
        raise httpx.HTTPStatusError("Contents not found", request=None, response=None)
    return data


# -----------------------------
# Get README.md
# -----------------------------
async def get_readme(owner: str, repo: str):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"
    data = await api_call(url, use_cache=True)
    if data is None:
        raise httpx.HTTPStatusError("Readme not found", request=None, response=None)
    return data


# -----------------------------
# Search Repositories
# -----------------------------
async def search_repos(q: str, page: int = 1, per_page: int = 10):
    url = f"{GITHUB_API_BASE}/search/repositories"
    params = {"q": q, "page": page, "per_page": per_page}
    return await api_call(url, params=params, use_cache=True)


# -----------------------------
# Download Raw File (بدون کش، فقط استریم/بایت)
# -----------------------------
async def download_file(url: str) -> bytes:
    client = get_http_client_raw()
    r = await client.get(url, headers=get_headers())
    r.raise_for_status()
    return r.content


# -----------------------------
# Get Releases
# -----------------------------
async def get_repo_releases(owner: str, repo: str):
    url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/releases"
    data = await api_call(url, use_cache=True)
    if data is None:
        return []
    if isinstance(data, list):
        return data
    return []


# -----------------------------
# Stats for Status Dashboard
# -----------------------------
def get_cache_stats():
    return {
        "cache_size": len(LRU.cache),
        "cache_ttl_seconds": CACHE_TTL,
        "cache_max_size": MAX_CACHE_SIZE,
        "cache_hit": CACHE_HIT,
        "cache_miss": CACHE_MISS,
        "github_requests": GITHUB_REQUESTS,
        "github_errors": GITHUB_ERRORS,
        "circuit_open": CB_OPEN,
        "circuit_fail_count": CB_FAIL_COUNT,
    }
