import asyncio
import io
import base64
import markdown
import urllib.parse
import re
import html
import time
from typing import Dict, List
import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from dotenv import load_dotenv
import uvicorn

import github_client

load_dotenv()

app = FastAPI(
    title="Mini GitHub Client",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")



ZIP_SEMAPHORE = asyncio.Semaphore(3)
ASSET_SEMAPHORE = asyncio.Semaphore(5)
RAW_SEMAPHORE = asyncio.Semaphore(10)


RATE_LIMITS = {
    "search": (30, 60),
    "raw": (60, 60),
    "download": (5, 60),
}
rate_store: Dict[str, Dict[str, List[float]]] = {
    "search": {},
    "raw": {},
    "download": {},
}


def get_client_ip(request: Request) -> str:
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_rate_limit(kind: str, ip: str):
    if kind not in RATE_LIMITS:
        return
    limit, window = RATE_LIMITS[kind]
    now = time.time()
    store = rate_store[kind].setdefault(ip, [])
    # پاک کردن timestampهای قدیمی
    store[:] = [t for t in store if now - t < window]
    if len(store) >= limit:
        raise HTTPException(status_code=429, detail="Too Many Requests")
    store.append(now)


# ----------------------------------------------------
# blob → raw (URL-level)
# ----------------------------------------------------
def convert_blob_to_raw(url: str) -> str:
    pattern = r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*)"
    match = re.match(pattern, url)
    if not match:
        return url
    owner, repo, branch, path = match.groups()
    return f"/raw/{owner}/{repo}/{branch}/{path}"


# ----------------------------------------------------
# Utility
# ----------------------------------------------------
def sanitize_query(q: str) -> str:
    q = re.sub(r"<.*?>", "", q)
    q = re.sub(r"[^a-zA-Z0-9_\-\.\s]", "", q)
    q = q[:80]
    q = html.escape(q)
    return q


def fix_readme_paths(html_text: str, owner: str, repo: str, branch: str) -> str:
    base = f"/raw/{owner}/{repo}/{branch}/"

    def repl_src(match):
        url = match.group(1)
        if url.startswith(("http://", "https://", "/")):
            return f'src="{url}"'
        full = urllib.parse.urljoin(base, url)
        return f'src="{full}"'

    def repl_href(match):
        url = match.group(1)
        if url.startswith(("http://", "https://", "/")):
            return f'href="{url}"'
        full = urllib.parse.urljoin(base, url)
        return f'href="{full}"'

    html_text = re.sub(r'src="([^"]+)"', repl_src, html_text)
    html_text = re.sub(r'href="([^"]+)"', repl_href, html_text)
    return html_text


def convert_blob_urls_in_html(
    html_text: str, owner: str, repo: str, branch: str
) -> str:
    def repl_full(match):
        attr = match.group(1)
        o = match.group(2)
        r = match.group(3)
        b = match.group(4)
        p = match.group(5)
        return f'{attr}="/raw/{o}/{r}/{b}/{p}"'

    return re.sub(
        r'(src|href)="https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.*?)"',
        repl_full,
        html_text,
    )


# ----------------------------------------------------
# Status Dashboard
# ----------------------------------------------------
@app.get("/status-data")
async def status_data():
    return JSONResponse(github_client.get_cache_stats())


# ----------------------------------------------------
# Avatar Proxy (User + Org) via Proxy
# ----------------------------------------------------
@app.get("/avatar/{name}")
async def avatar_proxy(name: str):
    headers = github_client.get_headers()
    client = github_client.get_http_client_api()

    try:
        user_url = f"https://api.github.com/users/{name}"
        user_res = await client.get(user_url, headers=headers)

        if user_res.status_code == 200:
            avatar_url = user_res.json().get("avatar_url")
            if avatar_url:
                img = await client.get(avatar_url)
                return Response(content=img.content, media_type="image/jpeg")

        org_url = f"https://api.github.com/orgs/{name}"
        org_res = await client.get(org_url, headers=headers)

        if org_res.status_code == 200:
            avatar_url = org_res.json().get("avatar_url")
            if avatar_url:
                img = await client.get(avatar_url)
                return Response(content=img.content, media_type="image/jpeg")
    except Exception as e:
        print(f"[AVATAR ERROR] {e}")

    return Response(status_code=404)


# ----------------------------------------------------
# Git Clone Proxy (Streaming) via Proxy
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}.git/info/refs")
async def proxy_info_refs(owner: str, repo: str, service: str):
    url = f"https://github.com/{owner}/{repo}.git/info/refs?service={service}"
    client = github_client.get_http_client_download()

    head = await client.get(url, headers={"User-Agent": "git/2.0"})
    content_type = head.headers.get(
        "content-type", "application/x-git-upload-pack-advertisement"
    )

    async def stream():
        async with client.stream("GET", url, headers={"User-Agent": "git/2.0"}) as r:
            async for chunk in r.aiter_bytes(chunk_size=8192):
                if chunk:
                    yield chunk

    return StreamingResponse(stream(), media_type=content_type)


@app.post("/repos/{owner}/{repo}.git/git-upload-pack")
async def proxy_upload_pack(owner: str, repo: str, request: Request):
    url = f"https://github.com/{owner}/{repo}.git/git-upload-pack"
    body = await request.body()
    client = github_client.get_http_client_download()

    async def stream_body():
        async with client.stream(
            "POST",
            url,
            content=body,
            headers={"User-Agent": "git/2.0"},
        ) as r:
            async for chunk in r.aiter_bytes(chunk_size=8192):
                if chunk:
                    yield chunk

    return StreamingResponse(
        stream_body(),
        media_type="application/x-git-upload-pack-result",
    )


# ----------------------------------------------------
# Home
# ----------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


# ----------------------------------------------------
# User Profile
# ----------------------------------------------------
@app.get("/users/{username}", response_class=HTMLResponse)
async def user_profile(request: Request, username: str):
    try:
        user = await github_client.get_user(username)
        repos = await github_client.get_user_repos(username)
        repos = sorted(repos, key=lambda r: r.get("stargazers_count", 0), reverse=True)
    except Exception:
        raise HTTPException(status_code=404, detail="User not found")

    return templates.TemplateResponse(
        "user.html",
        {"request": request, "user": user, "repos": repos},
    )


# ----------------------------------------------------
# Repo Detail Page
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}", response_class=HTMLResponse)
async def repo_detail(request: Request, owner: str, repo: str):
    try:
        repo_data = await github_client.get_repo(owner, repo)
    except Exception:
        raise HTTPException(status_code=404, detail="Repository not found")

    try:
        default_branch = await github_client.get_default_branch(owner, repo)
    except Exception:
        default_branch = repo_data.get("default_branch", "main")

    readme_html = ""
    readme_text = ""

    try:
        readme_data = await github_client.get_readme(owner, repo)
        if "content" in readme_data:
            decoded = base64.b64decode(readme_data["content"]).decode("utf-8")
            readme_text = decoded

            readme_html = markdown.markdown(
                decoded,
                output_format="html5",
                extensions=[
                    "extra",
                    "fenced_code",
                    "tables",
                    "toc",
                    "sane_lists",
                ],
            )

            readme_html = fix_readme_paths(readme_html, owner, repo, default_branch)
            readme_html = convert_blob_urls_in_html(
                readme_html, owner, repo, default_branch
            )

    except Exception:
        readme_html = "<p>README یافت نشد.</p>"

    def contains_farsi(text: str) -> bool:
        return any("\u0600" <= ch <= "\u06ff" for ch in text)

    is_farsi = contains_farsi(readme_text)

    try:
        contents = await github_client.get_repo_contents(owner, repo)
        contents = sorted(
            contents, key=lambda x: (x["type"] != "dir", x["name"].lower())
        )
    except Exception:
        contents = []

    try:
        releases = await github_client.get_repo_releases(owner, repo)
        for rel in releases:
            body = rel.get("body") or ""
            rel["body_html"] = markdown.markdown(
                body,
                output_format="html5",
                extensions=[
                    "extra",
                    "fenced_code",
                    "tables",
                    "sane_lists",
                    "nl2br",
                ],
            )
            rel["body_html"] = convert_blob_urls_in_html(
                rel["body_html"], owner, repo, default_branch
            )
    except Exception:
        releases = []

    return templates.TemplateResponse(
        "repo.html",
        {
            "request": request,
            "repo": repo_data,
            "contents": contents,
            "readme_html": readme_html,
            "readme_text": readme_text,
            "is_farsi": is_farsi,
            "owner": owner,
            "repo_name": repo,
            "releases": releases,
        },
    )


# ----------------------------------------------------
# Releases Page
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}/releases", response_class=HTMLResponse)
async def repo_releases(request: Request, owner: str, repo: str):
    try:
        try:
            default_branch = await github_client.get_default_branch(owner, repo)
        except Exception:
            repo_data_tmp = await github_client.get_repo(owner, repo)
            default_branch = repo_data_tmp.get("default_branch", "main")

        releases = await github_client.get_repo_releases(owner, repo)
        for rel in releases:
            body = rel.get("body") or ""
            if body:
                rel["body_html"] = markdown.markdown(
                    body,
                    extensions=["extra", "fenced_code", "tables"],
                )
            else:
                rel["body_html"] = "<p>No description.</p>"

            rel["body_html"] = convert_blob_urls_in_html(
                rel["body_html"], owner, repo, default_branch
            )

        repo_data = await github_client.get_repo(owner, repo)
    except Exception:
        raise HTTPException(status_code=404, detail="Releases not found")

    return templates.TemplateResponse(
        "releases.html",
        {
            "request": request,
            "owner": owner,
            "repo_name": repo,
            "releases": releases,
            "repo": repo_data,
        },
    )


# ----------------------------------------------------
# Tree View
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}/tree/{path:path}", response_class=HTMLResponse)
async def repo_tree(request: Request, owner: str, repo: str, path: str):
    try:
        contents = await github_client.get_repo_contents(owner, repo, path)
    except Exception:
        raise HTTPException(status_code=404, detail="Path not found")

    return templates.TemplateResponse(
        "tree.html",
        {
            "request": request,
            "contents": contents,
            "owner": owner,
            "repo": repo,
            "path": path,
        },
    )


# ----------------------------------------------------
# Blob Viewer (متن)
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}/blob/{path:path}", response_class=HTMLResponse)
async def view_file(request: Request, owner: str, repo: str, path: str):
    try:
        file_data = await github_client.get_repo_contents(owner, repo, path)
        if file_data["type"] != "file":
            raise HTTPException(status_code=400, detail="Not a file")

        content = await github_client.download_file(file_data["download_url"])
        decoded = content.decode("utf-8", errors="ignore")
    except Exception:
        raise HTTPException(status_code=404, detail="File not found")

    return templates.TemplateResponse(
        "file_viewer.html",
        {
            "request": request,
            "content": decoded,
            "filename": path.split("/")[-1],
            "owner": owner,
            "repo": repo,
            "path": path,
        },
    )


# ----------------------------------------------------
# Internal ZIP Download Proxy (با محدودیت همزمانی)
# ----------------------------------------------------
async def github_zip_stream(owner: str, repo: str):
    api_url = f"https://api.github.com/repos/{owner}/{repo}/zipball"

    headers = {
        "User-Agent": "IranGit-Downloader",
        "Accept": "application/vnd.github+json",
    }

    if github_client.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {github_client.GITHUB_TOKEN}"

    client = github_client.get_http_client_download()

    async with ZIP_SEMAPHORE:
        r = await client.get(api_url, headers=headers, follow_redirects=False)

        if r.status_code not in (301, 302):
            print("GitHub ZIP Error:", r.status_code, r.content)
            raise HTTPException(status_code=404, detail="Repository not found")

        zip_url = r.headers.get("Location")
        if not zip_url:
            raise HTTPException(status_code=404, detail="Invalid redirect")

        async with client.stream("GET", zip_url) as stream:
            if stream.status_code != 200:
                print("GitHub ZIP Final Error:", stream.status_code)
                raise HTTPException(status_code=404, detail="Cannot download ZIP")

            async for chunk in stream.aiter_bytes(chunk_size=1024 * 256):
                if chunk:
                    yield chunk


@app.get("/download/{owner}/{repo}.zip")
async def download_zip_proxy(request: Request, owner: str, repo: str):
    ip = get_client_ip(request)
    check_rate_limit("download", ip)

    try:
        filename = f"{repo}.zip"
        return StreamingResponse(
            github_zip_stream(owner, repo),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except Exception as e:
        print("ZIP Proxy Error:", e)
        raise HTTPException(status_code=500, detail="Failed to download ZIP")


# ----------------------------------------------------
# Release Asset Proxy (با محدودیت همزمانی)
# ----------------------------------------------------
@app.get("/download/asset/{owner}/{repo}/{asset_id:int}")
async def download_release_asset(
    request: Request, owner: str, repo: str, asset_id: int
):
    ip = get_client_ip(request)
    check_rate_limit("download", ip)

    client = github_client.get_http_client_download()
    try:
        url = f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{asset_id}"

        headers = github_client.get_headers()
        headers["Accept"] = "application/octet-stream"

        async with ASSET_SEMAPHORE:
            head_res = await client.head(url, headers=headers, follow_redirects=True)

            if head_res.status_code != 200:
                raise HTTPException(
                    status_code=head_res.status_code, detail="Asset download failed"
                )

            disposition = head_res.headers.get(
                "Content-Disposition", "attachment; filename=asset.bin"
            )
            filename = disposition.replace("attachment; filename=", "").strip('"')

            filesize = int(head_res.headers.get("Content-Length", 0))
            content_type = head_res.headers.get(
                "Content-Type", "application/octet-stream"
            )

            range_header = request.headers.get("range")

            if range_header:
                try:
                    units, _, range_spec = range_header.partition("=")
                    if units.strip().lower() != "bytes":
                        raise ValueError("Invalid range units")

                    start_str, _, end_str = range_spec.partition("-")
                    start = int(start_str) if start_str else 0
                    end = int(end_str) if end_str else filesize - 1

                    if start >= filesize or start < 0 or end < start:
                        raise HTTPException(
                            status_code=416, detail="Range Not Satisfiable"
                        )

                except ValueError:
                    raise HTTPException(status_code=416, detail="Invalid Range")

                range_headers = {"Range": f"bytes={start}-{end}"}

                async def range_stream():
                    async with client.stream(
                        "GET",
                        url,
                        headers={**headers, **range_headers},
                        follow_redirects=True,
                    ) as stream_res:
                        async for chunk in stream_res.aiter_bytes(
                            chunk_size=1024 * 256
                        ):
                            if chunk:
                                yield chunk

                content_length = end - start + 1

                return StreamingResponse(
                    range_stream(),
                    status_code=206,
                    media_type=content_type,
                    headers={
                        "Content-Disposition": f'attachment; filename="{filename}"',
                        "Content-Range": f"bytes {start}-{end}/{filesize}",
                        "Accept-Ranges": "bytes",
                        "Content-Length": str(content_length),
                    },
                )

            async def full_stream():
                async with client.stream(
                    "GET", url, headers=headers, follow_redirects=True
                ) as stream_res:
                    async for chunk in stream_res.aiter_bytes(chunk_size=1024 * 256):
                        if chunk:
                            yield chunk

            response_headers = {
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Accept-Ranges": "bytes",
            }

            if filesize:
                response_headers["Content-Length"] = str(filesize)

            return StreamingResponse(
                full_stream(),
                media_type=content_type,
                headers=response_headers,
            )

    except HTTPException:
        raise
    except Exception as e:
        print("Asset Proxy Error:", e)
        raise HTTPException(status_code=500, detail="Failed to download asset")


# ----------------------------------------------------
# RAW FILE PROXY (Convert blob → raw) با محدودیت + Rate Limit
# ----------------------------------------------------
@app.get("/raw/{owner}/{repo}/{branch}/{path:path}")
async def raw_file_proxy(
    request: Request, owner: str, repo: str, branch: str, path: str
):
    ip = get_client_ip(request)
    check_rate_limit("raw", ip)

    raw_url = f"https://raw.githubusercontent.com/{owner}/{repo}/{branch}/{path}"
    headers = github_client.get_headers()
    client = github_client.get_http_client_raw()

    async with RAW_SEMAPHORE:
        try:
            r = await client.get(raw_url, headers=headers, timeout=10.0)
        except httpx.TimeoutException as e:
            raise HTTPException(
                status_code=504, detail=f"timeout fetching from GitHub: {str(e)}"
            )
        except httpx.ConnectError as e:
            raise HTTPException(status_code=502, detail=f"connection error: {str(e)}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"error: {str(e)}")

    if r.status_code != 200:
        raise HTTPException(status_code=404, detail="Raw file not found")

    filename = path.lower()
    media_type = "application/octet-stream"

    if filename.endswith(".svg"):
        media_type = "image/svg+xml"
    elif filename.endswith(".png"):
        media_type = "image/png"
    elif filename.endswith(".jpg") or filename.endswith(".jpeg"):
        media_type = "image/jpeg"
    elif filename.endswith(".gif"):
        media_type = "image/gif"
    elif filename.endswith(".webp"):
        media_type = "image/webp"
    elif filename.endswith(".ico"):
        media_type = "image/x-icon"
    elif filename.endswith(".bmp"):
        media_type = "image/bmp"
    elif filename.endswith(".mp4"):
        media_type = "video/mp4"
    elif filename.endswith(".webm"):
        media_type = "video/webm"
    elif filename.endswith(".avi"):
        media_type = "video/x-msvideo"
    elif filename.endswith(".mov"):
        media_type = "video/quicktime"
    elif filename.endswith(".mp3"):
        media_type = "audio/mpeg"
    elif filename.endswith(".wav"):
        media_type = "audio/wav"
    elif filename.endswith(".ogg"):
        media_type = "audio/ogg"
    elif filename.endswith(".pdf"):
        media_type = "application/pdf"
    elif filename.endswith(".css"):
        media_type = "text/css"
    elif filename.endswith(".js"):
        media_type = "application/javascript"
    elif filename.endswith(".json"):
        media_type = "application/json"
    elif filename.endswith(".txt") or filename.endswith(".md"):
        media_type = "text/plain"

    return Response(content=r.content, media_type=media_type)


# ----------------------------------------------------
# Asset Route (MUST BE LAST)
# ----------------------------------------------------
@app.get("/repos/{owner}/{repo}/{path:path}")
async def repo_asset(owner: str, repo: str, path: str):
    try:
        file_data = await github_client.get_repo_contents(owner, repo, path)
        if file_data["type"] != "file":
            raise HTTPException(status_code=400, detail="Not a file")

        content = await github_client.download_file(file_data["download_url"])
    except Exception:
        raise HTTPException(status_code=404, detail="Asset not found")

    media_type = "application/octet-stream"
    lower = path.lower()
    if lower.endswith(".png"):
        media_type = "image/png"
    elif lower.endswith((".jpg", ".jpeg")):
        media_type = "image/jpeg"
    elif lower.endswith(".gif"):
        media_type = "image/gif"
    elif lower.endswith(".svg"):
        media_type = "image/svg+xml"

    return StreamingResponse(io.BytesIO(content), media_type=media_type)


# ----------------------------------------------------
# Search
# ----------------------------------------------------
@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", page: int = 1):
    ip = get_client_ip(request)
    check_rate_limit("search", ip)

    clean_q = sanitize_query(q)

    users = []
    repos = []
    has_more = False

    try:
        user_data = await github_client.search_users(clean_q, page=page, per_page=10)
        repo_data = await github_client.search_repos(clean_q, page=page, per_page=10)

        users = user_data.get("items", []) if user_data else []
        repos = repo_data.get("items", []) if repo_data else []
        has_more = len(users) == 10 or len(repos) == 10
    except Exception as e:
        print("Search Error:", e)

    return templates.TemplateResponse(
        "search_combined.html",
        {
            "request": request,
            "query": clean_q,
            "users": users,
            "repos": repos,
            "page": page,
            "has_more": has_more,
        },
    )


# -----------------------------
# 404 → صفحه 404.html
# -----------------------------
@app.exception_handler(404)
async def not_found_handler(request: Request, exc):
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


# -----------------------------
# سایر خطاهای HTTP
# -----------------------------
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 404:
        return templates.TemplateResponse(
            "404.html", {"request": request}, status_code=404
        )
    return Response(f"Error: {exc.detail}", status_code=exc.status_code)


# -----------------------------
# Validation Errors
# -----------------------------
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc):
    return Response("Validation Error", status_code=400)


# ----------------------------------------------------
# Run Server
# ----------------------------------------------------
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
