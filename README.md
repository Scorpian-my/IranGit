<div align="center">

<img src="https://github.com/Scorpian-my/IranGit/blob/main/static/icon/logo.webp" width="180" alt="IranGit Logo">

<h1>IranGit</h1>

<p><strong>دسترسی سریع، پایدار و بدون VPN به GitHub</strong></p>
<p>یک کلاینت سبک، امن و استریم‌محور برای مشاهده و دانلود محتوای GitHub در ایران</p>

<br>

<img src="https://img.shields.io/badge/IranGit-Fast%20%26%20Secure-blueviolet?style=for-the-badge">
<img src="https://img.shields.io/badge/No%20Proxy-Direct%20GitHub-green?style=for-the-badge">
<img src="https://img.shields.io/badge/Streaming-Enabled-orange?style=for-the-badge">
<img src="https://img.shields.io/badge/Cache-LRU%20%7C%20RAM-yellow?style=for-the-badge">

<br><br>

</div>

---

<div dir="rtl">

## 🚀 دربارهٔ ایران‌گیت

**ایران‌گیت** یک کلاینت مستقل و بسیار سریع برای GitHub است که به کاربران ایرانی اجازه می‌دهد بدون نیاز به VPN، محتوای GitHub را مشاهده و دانلود کنند.

ایران گیت هیچ داده‌ای را روی دیسک ذخیره نمی‌کند و تمام فایل‌ها به‌صورت **استریم واقعی** منتقل می‌شوند.  
تمام درخواست‌ها **مستقیم به GitHub** ارسال می‌شوند و هیچ تغییری در محتوای اصلی ایجاد نمی‌شود.

---

## ✨ ویژگی‌ها

---

### 🛰️ دسترسی و مشاهده

#### 🔹 بدون نیاز به VPN  
تمام داده‌ها مستقیم از GitHub دریافت می‌شوند.

#### 🔹 مشاهدهٔ کامل پروفایل‌ها  
- اطلاعات کاربر  
- آواتار  
- ریپازیتوری‌ها (مرتب‌شده بر اساس ستاره‌ها)

#### 🔹 مرور کامل ریپازیتوری  
- رندر حرفه‌ای README  
- تبدیل خودکار لینک‌های `blob` → `raw`  
- نمایش فایل‌ها و فولدرها  
- نمایش ساختار پروژه (Tree View)  
- نمایش ریلیزها با Markdown HTML

---

### 📥 دانلود و استریم

#### 🔹 دانلود ZIP  
- دانلود ZIP ریپازیتوری  
- استریم واقعی بدون ذخیره‌سازی  
- پشتیبانی از ادامه دانلود (Range)

#### 🔹 دانلود Asset  
- پشتیبانی از فایل‌های حجیم  
- استریم chunk-based  
- کنترل همزمانی با Semaphore

---

### ⚡ عملکرد و بهینه‌سازی

#### 🔹 کش هوشمند در RAM  
- LRU Cache  
- TTL  
- Circuit Breaker  
- کاهش شدید تعداد درخواست‌های GitHub  
- افزایش سرعت و پایداری

#### 🔹 Circuit Breaker  
- جلوگیری از overload  
- بازگشت خودکار پس از زمان مشخص

#### 🔹 Rate Limit داخلی  
برای جلوگیری از سوءاستفاده:
- جستجو  
- RAW  
- دانلودها  


## 🖼️ نمونه تصاویر (Screenshots)

<div align="center">

### صفحه اصلی
<img src="https://github.com/Scorpian-my/IranGit/blob/main/example/1.png" width="80%" style="border-radius: 12px; margin: 10px 0;">

### صفحه پروفایل کاربر
<img src="https://github.com/Scorpian-my/IranGit/blob/main/example/2.png" width="80%" style="border-radius: 12px; margin: 10px 0;">

### صفحه مخزن
<img src="https://github.com/Scorpian-my/IranGit/blob/main/example/3.png" width="80%" style="border-radius: 12px; margin: 10px 0;">

</div>

---

## 🧠 معماری ایران گیت

ایران گیت از سه کلاینت مجزا استفاده می‌کند:

| نوع کلاینت | کاربرد | محدودیت |
|-----------|---------|----------|
| **API Client** | پروفایل، ریپو، سرچ | سریع، کم‌مصرف |
| **RAW Client** | فایل‌های raw.githubusercontent | محدودیت متوسط |
| **Download Client** | ZIP و Asset | محدودیت شدید + استریم |

ویژگی‌های معماری:

- بدون پروکسی  
- بدون ذخیره‌سازی  
- connection pool کنترل‌شده  
- semaphore برای کنترل دانلودهای همزمان  
- circuit breaker برای جلوگیری از overload  

---

## 📦 نصب و اجرا

### 1) کلون پروژه
</div>

```bash
git clone https://github.com/Scorpian-my/IranGit
cd IranGit
```

### 2) نصب وابستگی‌ها
(اختیاری) ساخت محیط مجازی:
```
python -m venv venv
venv\Scripts\activate   # Windows

source venv/bin/activate   # Linux / macOS
```
نصب کتابخانه‌ها:
```
pip install -r requirements.txt
```
### 3) افزودن توکن GitHub
فایل .env را ویرایش کرده و توکن خود را اضافه کنید
```
GITHUB_TOKEN=your_github_token_here
```
### 4) اجرای پروژه
```
python main.py

```
---

## 🤝 مشارکت در توسعهٔ IranGit

<div dir="rtl">

از مشارکت شما در توسعهٔ **IranGit** با آغوش باز استقبال می‌کنیم.  
این پروژه یک ابزار عمومی و آزاد است و هرگونه کمک شما—از گزارش باگ گرفته تا توسعهٔ قابلیت‌های جدید—مستقیماً به بهبود تجربهٔ کاربران ایرانی کمک می‌کند.

### 🔧 چگونه می‌توانید مشارکت کنید؟

#### 1) گزارش باگ‌ها  
اگر با خطا، رفتار غیرمنتظره یا مشکل عملکردی روبه‌رو شدید:  
- یک Issue باز کنید  
- توضیح کامل + اسکرین‌شات + لاگ (در صورت وجود) قرار دهید  

#### 2) پیشنهاد قابلیت‌های جدید  
اگر ایده‌ای برای بهبود سرعت، امنیت، UI یا معماری دارید:  
- در بخش Issues یک Feature Request ثبت کنید  
- توضیح دهید چرا این قابلیت مفید است  

#### 3) ارسال Pull Request  
اگر قصد دارید کد ارسال کنید:  
- ریپو را Fork کنید  
- یک Branch جدید بسازید  
- تغییرات را اعمال کنید  
- Pull Request با توضیحات کامل ارسال کنید  

#### 4) بهبود مستندات  
هرگونه کمک در موارد زیر ارزشمند است:  
- بهبود README  
- نوشتن راهنمای نصب  
- توضیح معماری  
- افزودن مثال‌ها و اسکرین‌شات‌ها  

### 📌 قوانین مشارکت (Contribution Guidelines)

برای حفظ کیفیت پروژه:

- کد باید تمیز، خوانا و قابل نگه‌داری باشد  
- از اضافه‌کردن وابستگی‌های غیرضروری خودداری کنید  
- برای قابلیت‌های جدید، تست و توضیح کافی ارائه دهید  
- تغییرات بزرگ را قبل از شروع، در Issue مطرح کنید  
- ساختار پوشه‌ها و معماری پروژه را رعایت کنید  

### ❤️ قدردانی

هر قدم کوچک شما در ادامه راه ایران گیت تاثیر زیادی دارد 
ما با **آغوش باز** از همراهی شما استقبال می‌کنیم.

</div>
