[2026/10/4 21:37] 5G: import os
import re
import time
import sqlite3
import logging
import html
import requests
import feedparser

from bs4 import BeautifulSoup
from dotenv import load_dotenv
from urllib.parse import urljoin

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "600"))

DB_FILE = "articles.db"

# =========================
# 采集源
# =========================

RSS_SOURCES = [
    {
        "name": "网站A",
        "url": "https://example.com/feed/",
        "tags": ["科技", "资讯"]
    },
    {
        "name": "网站B",
        "url": "https://example2.com/rss",
        "tags": ["AI"]
    },
]


# =========================
# 日志
# =========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


# =========================
# 数据库
# =========================

def init_db():
    conn = sqlite3.connect(DB_FILE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            title TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()


def article_exists(url):
    conn = sqlite3.connect(DB_FILE)

    row = conn.execute(
        "SELECT id FROM articles WHERE url = ?",
        (url,)
    ).fetchone()

    conn.close()

    return row is not None


def save_article(url, title):
    conn = sqlite3.connect(DB_FILE)

    try:
        conn.execute(
            "INSERT INTO articles (url, title) VALUES (?, ?)",
            (url, title)
        )

        conn.commit()

    except sqlite3.IntegrityError:
        pass

    conn.close()


# =========================
# RSS采集
# =========================

def get_rss_articles(source):
    try:
        logging.info("正在采集：%s", source["name"])

        response = requests.get(
            source["url"],
            timeout=20,
            headers={
                "User-Agent":
                "Mozilla/5.0 TelegramNewsBot/1.0"
            }
        )

        response.raise_for_status()

        feed = feedparser.parse(response.content)

        articles = []

        for entry in feed.entries[:20]:

            title = entry.get("title", "").strip()
            url = entry.get("link", "").strip()

            if not title or not url:
                continue

            summary = entry.get(
                "summary",
                entry.get("description", "")
            )

            summary = clean_html(summary)

            image = extract_rss_image(entry)

            articles.append({
                "title": title,
                "url": url,
                "summary": summary,
                "image": image,
                "source": source["name"],
                "tags": source.get("tags", [])
            })

        return articles

    except Exception as e:
        logging.error(
            "采集失败 %s: %s",
            source["name"],
            e
        )

        return []


# =========================
# HTML清理
# =========================

def clean_html(text):
    soup = BeautifulSoup(text or "", "html.parser")

    result = soup.get_text(
        " ",
        strip=True
    )

    result = re.sub(
        r"\s+",
        " ",
        result
    )

    return result.strip()


# =========================
# RSS图片
# =========================

def extract_rss_image(entry):

    # media_content
    if hasattr(entry, "media_content"):

        for media in entry.media_content:

            url = media.get("url")

            if url:
                return url

    # enclosure
    if hasattr(entry, "enclosures"):

        for item in entry.enclosures:

            url = item.get("href")

            if url:
                return url

    return None


# =========================
# 网页首图
# =========================

def get_article_image(url):

    try:

        response = requests.get(
            url,
            timeout=20,
            headers={
                "User-Agent":
[2026/10/4 21:37] 5G: "Mozilla/5.0"
            }
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        # OpenGraph图片
        og_image = soup.find(
            "meta",
            property="og:image"
        )

        if og_image:

            image = og_image.get("content")

            if image:
                return urljoin(url, image)

        # Twitter图片
        twitter_image = soup.find(
            "meta",
            attrs={
                "name": "twitter:image"
            }
        )

        if twitter_image:

            image = twitter_image.get("content")

            if image:
                return urljoin(url, image)

        # 第一张图片
        img = soup.find("img")

        if img:

            image = (
                img.get("src")
                or img.get("data-src")
            )

            if image:
                return urljoin(url, image)

    except Exception as e:

        logging.warning(
            "获取图片失败：%s",
            e
        )

    return None


# =========================
# Telegram API
# =========================

def telegram_request(method, data):

    url = (
        f"https://api.telegram.org/"
        f"bot{BOT_TOKEN}/{method}"
    )

    response = requests.post(
        url,
        data=data,
        timeout=30
    )

    result = response.json()

    if not result.get("ok"):

        logging.error(
            "Telegram API错误：%s",
            result
        )

    return result


# =========================
# 发布图片
# =========================

def send_photo(image_url, caption):

    return telegram_request(
        "sendPhoto",
        {
            "chat_id": CHANNEL_ID,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "HTML"
        }
    )


# =========================
# 发布文字
# =========================

def send_message(text):

    return telegram_request(
        "sendMessage",
        {
            "chat_id": CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False
        }
    )


# =========================
# 创建Telegram内容
# =========================

def build_message(article):

    title = html.escape(
        article["title"]
    )

    summary = html.escape(
        article["summary"]
    )

    if len(summary) > 500:
        summary = summary[:500] + "..."

    source = html.escape(
        article["source"]
    )

    url = html.escape(
        article["url"],
        quote=True
    )

    tags = " ".join(
        "#" + x.replace(" ", "")
        for x in article["tags"]
    )

    message = f"""
<b>📰 {title}</b>

{summary}

📌 来源：{source}

🔗 <a href="{url}">阅读原文</a>

{tags}
""".strip()

    return message


# =========================
# 处理文章
# =========================

def process_article(article):

    url = article["url"]

    if article_exists(url):

        logging.info(
            "已发布，跳过：%s",
            article["title"]
        )

        return

    logging.info(
        "发现新文章：%s",
        article["title"]
    )

    # 如果RSS没有图片，再去网页获取
    if not article["image"]:

        article["image"] = get_article_image(
            url
        )

    message = build_message(
        article
    )

    if article["image"]:

        result = send_photo(
            article["image"],
            message
        )

    else:

        result = send_message(
            message
        )

    if result.get("ok"):

        save_article(
            url,
            article["title"]
        )

        logging.info(
            "发布成功：%s",
            article["title"]
        )

    else:

        logging.error(
            "发布失败：%s",
            article["title"]
        )


# =========================
# 主程序
# =========================

def main():

    if not BOT_TOKEN:

        raise ValueError(
            "没有设置 BOT_TOKEN"
        )

    if not CHANNEL_ID:

        raise ValueError(
            "没有设置 CHANNEL_ID"
        )

    init_db()

    logging.info(
[2026/10/4 21:37] 5G: "Telegram自动采集机器人启动"
    )

    while True:

        for source in RSS_SOURCES:

            articles = get_rss_articles(
                source
            )

            # 倒序发布，避免旧文章先发布
            for article in reversed(
                articles
            ):

                process_article(
                    article
                )

                # 防止短时间大量发送
                time.sleep(2)

        logging.info(
            "本轮采集结束，%s秒后再次检查",
            CHECK_INTERVAL
        )

        time.sleep(
            CHECK_INTERVAL
        )


if name == "__main__":

    main()
