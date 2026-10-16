#!/usr/bin/env python3
"""Fetch blog posts from RSS/Atom where available, otherwise parse the blog homepage."""
from __future__ import annotations

import json
import html
import re
import time
import hashlib
import csv
import io
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag

import feedparser
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
SITES_FILE = ROOT / "sites.txt"
SHEETS_FEEDS_FILE = ROOT / "spreadsheet_feeds.txt"
OUTPUT_FILE = ROOT / "articles.json"
LOG_FILE = ROOT / "fetch-log.txt"
MAX_PER_SITE = 5
MAX_SCAN_PER_SITE = 100
TIMEOUT = 18
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; MugenBlogArticleIndex/1.0; +https://github.com/)"
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

def normalize_url(url: str) -> str:
    url = urldefrag(url.strip())[0]
    return url.rstrip("/") if urlparse(url).path not in ("", "/") else url

def get_site_name(url: str) -> str:
    host = urlparse(url).netloc.lower()
    host = host.removeprefix("www.")
    return host or url

def parse_date(value):
    if not value:
        return ""
    try:
        if isinstance(value, time.struct_time):
            dt = datetime(*value[:6], tzinfo=timezone.utc)
        else:
            dt = parsedate_to_datetime(value)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc).isoformat()
        except Exception:
            return ""

def is_future_date(value, now=None):
    """Return True only when a parseable publication date is later than now (UTC)."""
    if not value:
        return False
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc) > (now or datetime.now(timezone.utc))
    except (TypeError, ValueError):
        return False

def fetch(url):
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return None
        r.encoding = r.apparent_encoding or r.encoding
        return r
    except requests.RequestException:
        return None

def feed_candidates(site_url, homepage_html=None):
    """Known feed paths plus autodiscovery links from HTML."""
    p = urlparse(site_url)
    origin = f"{p.scheme}://{p.netloc}"
    path = p.path.rstrip("/")
    candidates = []

    # If a supplied URL is already a feed-like endpoint, try it first.
    if any(x in p.path.lower() for x in ("atom.xml", "rss", "feed", "index.rdf")):
        candidates.append(site_url)

    if homepage_html:
        soup = BeautifulSoup(homepage_html, "html.parser")
        for tag in soup.find_all("link", href=True):
            typ = (tag.get("type") or "").lower()
            rel = " ".join(tag.get("rel", [])).lower()
            href = tag["href"]
            if "alternate" in rel and ("rss" in typ or "atom" in typ or "xml" in typ):
                candidates.append(urljoin(site_url, href))

    # Common endpoints used by Japanese blog platforms.
    candidates += [
        origin + "/atom.xml",
        origin + "/rss",
        origin + "/rss.xml",
        origin + "/feed",
        origin + "/feed.xml",
        origin + "/index.rdf",
        origin + "/?xml",
    ]

    host = p.netloc.lower()
    if "fc2.com" in host or "fc2.net" in host:
        candidates += [origin + "/?xml", origin + "/?xml&all", origin + "/rss"]
    if "hatenablog.com" in host or "hatenadiary.com" in host or "hateblo.jp" in host or "blog.jp" in host:
        candidates += [origin + "/rss", origin + "/feed", origin + "/atom.xml"]
    if "livedoor.blog" in host or host == "blog.livedoor.jp":
        candidates += [origin + "/index.rdf", origin + "/atom.xml", origin + "/rss"]
    if "seesaa.net" in host:
        # Seesaa documents index.rdf (RSS/RDF) and index20.rdf (RSS 2.0).
        candidates += [
            origin + "/index20.rdf",
            origin + "/index.rdf",
            origin + "/atom.xml",
            origin + "/rss",
        ]
    if "ameblo.jp" in host:
        candidates += [origin + "/rss.html", origin + "/atom.xml"]

    # Preserve order while removing duplicates.
    return list(dict.fromkeys(candidates))

def parse_feed(feed_url, site_url):
    response = fetch(feed_url)
    if not response:
        return []
    parsed = feedparser.parse(response.content)
    if not parsed.entries:
        return []
    blog_name = parsed.feed.get("title") or get_site_name(site_url)
    out = []
    for entry in parsed.entries[:MAX_SCAN_PER_SITE]:
        link = entry.get("link")
        title = (entry.get("title") or "").strip()
        if not link or not title:
            continue
        date = parse_date(entry.get("published_parsed") or entry.get("updated_parsed")
                          or entry.get("published") or entry.get("updated"))
        if is_future_date(date):
            continue
        out.append({
            "title": BeautifulSoup(title, "html.parser").get_text(" ", strip=True),
            "url": urljoin(feed_url, link),
            "site": blog_name,
            "site_url": site_url,
            "published": date,
            "source": "RSS",
        })
    return out

def looks_like_article(url, title, site_url):
    if not title or len(title.strip()) < 2:
        return False
    u, root = urlparse(url), urlparse(site_url)
    if u.scheme not in ("http", "https") or u.netloc.lower() != root.netloc.lower():
        return False
    path = u.path.lower()
    if path in ("", "/", "/index.html", "/index.htm"):
        return False
    bad = ("#","javascript:", "/category/", "/tag/", "/archives/", "/page/", "/profile",
           "/about", "/contact", "/rss", "/atom", "/search", "/admin", "/login")
    if any(x in path for x in bad):
        return False
    if title.strip().lower() in {"トップページ", "ホーム", "home", "次のページ", "前のページ", "続きを読む"}:
        return False
    return True

def parse_homepage(site_url):
    response = fetch(site_url)
    if not response:
        return []
    actual_home = response.url
    soup = BeautifulSoup(response.text, "html.parser")
    site_name = (soup.title.get_text(" ", strip=True) if soup.title else "") or get_site_name(site_url)
    out, seen = [], set()

    # Many blogs use h1/h2/h3 or article elements around post titles.
    selectors = [
        "article h1 a[href]", "article h2 a[href]", "article h3 a[href]",
        "h1.entry-title a[href]", "h2.entry-title a[href]", "h3.entry-title a[href]",
        ".entry-title a[href]", ".article-title a[href]", ".post-title a[href]",
        ".entry h2 a[href]", ".entry h3 a[href]", ".article h2 a[href]",
        ".article h3 a[href]", ".blogbody h3 a[href]", ".title a[href]",
        "h2 a[href]", "h3 a[href]", "h4 a[href]"
    ]
    anchors = []
    for selector in selectors:
        anchors.extend(soup.select(selector))
    # fallback: inspect ordinary links if theme-specific selectors found nothing
    if not anchors:
        anchors = soup.find_all("a", href=True)

    scanned = 0
    for a in anchors:
        scanned += 1
        if scanned > MAX_SCAN_PER_SITE:
            break
        title = a.get_text(" ", strip=True)
        href = urljoin(actual_home, a.get("href", ""))
        href = normalize_url(href)
        if not looks_like_article(href, title, actual_home) or href in seen:
            continue
        # Avoid generic image-only anchors and navigation labels.
        if len(title) > 220:
            title = title[:217] + "..."
        seen.add(href)

        published = ""
        # Search nearby containers for a date/time element or a recognizable date string.
        container = a.find_parent(["article", "li", "div"])
        if container:
            time_tag = container.find("time")
            if time_tag:
                published = parse_date(time_tag.get("datetime") or time_tag.get_text(" ", strip=True))
            if not published:
                text = container.get_text(" ", strip=True)
                match = re.search(r"(20\d{2})[年/.-](\d{1,2})[月/.-](\d{1,2})", text)
                if match:
                    try:
                        dt = datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)), tzinfo=timezone.utc)
                        published = dt.isoformat()
                    except ValueError:
                        pass

        if is_future_date(published):
            continue

        out.append({
            "title": title,
            "url": href,
            "site": site_name,
            "site_url": site_url,
            "published": published,
            "source": "HTML",
        })
    return out

def load_spreadsheet_feeds():
    """Load rows as: site URL, published CSV URL, optional display name.

    Accept tabs or ordinary spaces between the first two URL fields and the
    display name. URLs themselves must not contain spaces.
    """
    feeds = {}
    if not SHEETS_FEEDS_FILE.exists():
        return feeds
    for line in SHEETS_FEEDS_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(https?://\S+)\s+(https?://\S+)(?:\s+(.*?))?\s*$", line)
        if not match:
            continue
        site_url = match.group(1).strip()
        csv_url = match.group(2).strip()
        display_name = (match.group(3) or "").strip()
        if not site_url or not csv_url or "PASTE_PUBLISHED_CSV_URL_HERE" in csv_url:
            continue
        feeds[normalize_url(site_url)] = {"csv_url": csv_url, "display_name": display_name}
    return feeds


def parse_spreadsheet_csv(site_url, csv_url, display_name=""):
    """Read a published Google Sheets CSV containing IMPORTFEED item rows."""
    try:
        response = SESSION.get(csv_url, timeout=TIMEOUT, allow_redirects=True)
        if response.status_code >= 400:
            body_hint = re.sub(r"\s+", " ", response.text[:180]).strip()
            return [], f"HTTP {response.status_code} {response.url} body={body_hint}"
        response.encoding = "utf-8-sig"
        rows = list(csv.reader(io.StringIO(response.text)))
        if not rows:
            return [], "CSV is empty"

        def norm(value):
            return re.sub(r"[^a-z0-9ぁ-んァ-ン一-龥]", "", (value or "").strip().lower())

        headers = [norm(value) for value in rows[0]]
        title_idx = next((i for i, h in enumerate(headers) if h in ("title", "タイトル", "itemtitle")), 0)
        url_idx = next((i for i, h in enumerate(headers) if h in ("url", "link", "リンク", "記事url", "記事リンク")), 1)
        date_idx = next((i for i, h in enumerate(headers) if h in ("created", "published", "date", "pubdate", "公開日時", "投稿日", "日付", "更新日時")), 2)
        # If the first row is not a recognizable header, treat it as data.
        known_headers = {"title", "タイトル", "url", "link", "created", "published", "date", "pubdate", "author"}
        has_header = any(h in known_headers for h in headers)
        data_rows = rows[1:] if has_header else rows
        if not has_header:
            title_idx, url_idx, date_idx = 0, 1, 2

        site_name = display_name or get_site_name(site_url)
        articles = []
        for row in data_rows:
            if len(row) <= max(title_idx, url_idx):
                continue
            title = (row[title_idx] or "").strip()
            link = (row[url_idx] or "").strip()
            date_raw = row[date_idx].strip() if len(row) > date_idx else ""
            if not title or not link or title.lower() in {"title", "タイトル"}:
                continue
            if not link.startswith(("http://", "https://")):
                continue
            date = parse_date(date_raw)
            if is_future_date(date):
                continue
            articles.append({
                "title": BeautifulSoup(title, "html.parser").get_text(" ", strip=True),
                "url": link,
                "site": site_name,
                "site_url": site_url,
                "published": date,
                "source": "Google Sheets IMPORTFEED",
            })
        return articles[:MAX_SCAN_PER_SITE], f"{len(articles)} rows"
    except Exception as exc:
        return [], f"{type(exc).__name__}: {exc}"


def stable_id(item):
    return hashlib.sha256(item["url"].encode("utf-8")).hexdigest()[:16]

def main():
    sites = [line.strip() for line in SITES_FILE.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.strip().startswith("#")]
    all_articles, log_lines = [], []
    spreadsheet_feeds = load_spreadsheet_feeds()
    normalized_sites = []
    for site in sites:
        site = site.strip()
        if not site.startswith(("http://", "https://")):
            site = "https://" + site
        normalized_sites.append(site)

    # Fetch the three Seesaa feeds via public Google Sheets CSV when configured.
    spreadsheet_site_keys = set(spreadsheet_feeds)
    for site_url, feed_config in spreadsheet_feeds.items():
        csv_url = feed_config["csv_url"]
        display_name = feed_config["display_name"]
        articles, detail = parse_spreadsheet_csv(site_url, csv_url, display_name)
        if articles:
            log_lines.append(f"OK SHEETS\t{site_url}\t{detail}")
            all_articles.extend(articles)
        else:
            log_lines.append(f"FAIL SHEETS\t{site_url}\t{detail}")

    for i, site in enumerate(normalized_sites, 1):
        if normalize_url(site) in spreadsheet_site_keys:
            print(f"[{i}/{len(normalized_sites)}] {site}: handled via Google Sheets")
            continue
        # A provided feed URL may be used directly; otherwise fetch homepage and discover feeds.
        homepage = None
        if not any(x in urlparse(site).path.lower() for x in ("atom.xml", "rss", "feed", "index.rdf")):
            resp = fetch(site)
            if resp:
                homepage = resp.text
                effective_site = resp.url
            else:
                effective_site = site
        else:
            effective_site = site

        articles = []
        for candidate in feed_candidates(effective_site, homepage):
            articles = parse_feed(candidate, effective_site)
            if articles:
                log_lines.append(f"OK RSS\t{site}\t{candidate}\t{len(articles)}")
                break

        if not articles:
            # Parse HTML from the site homepage (if already fetched, avoid another request).
            if homepage is not None:
                # Reuse the first response content by parsing a small helper copy via BeautifulSoup.
                # parse_homepage is used for robustness and follows redirects.
                articles = parse_homepage(effective_site)
            else:
                articles = parse_homepage(effective_site)
            if articles:
                log_lines.append(f"OK HTML\t{site}\t{len(articles)}")
            else:
                log_lines.append(f"FAIL\t{site}\tNo RSS entries or article links found")

        all_articles.extend(articles)
        print(f"[{i}/{len(sites)}] {site}: {len(articles)} articles")
        time.sleep(0.25)  # be polite to the sites

    # Exclude future-dated entries and retain at most five articles per blog.
    now = datetime.now(timezone.utc)
    per_site = {}
    for item in all_articles:
        if is_future_date(item.get("published"), now):
            continue
        per_site.setdefault(item.get("site_url") or item.get("site") or "", []).append(item)

    limited_articles = []
    for site_items in per_site.values():
        # Known publication dates first, newest first; undated items follow.
        site_items.sort(key=lambda x: (bool(x.get("published")), x.get("published") or ""), reverse=True)
        limited_articles.extend(site_items[:MAX_PER_SITE])

    # Deduplicate by canonical URL.
    deduped = {}
    for item in limited_articles:
        item["id"] = stable_id(item)
        key = normalize_url(item["url"])
        if key not in deduped:
            deduped[key] = item
        elif not deduped[key].get("published") and item.get("published"):
            deduped[key] = item

    items = list(deduped.values())
    # Decode HTML entities in visible text, e.g. &#039; -> apostrophe and &amp; -> &.
    for item in items:
        for field in ("title", "site"):
            if item.get(field):
                item[field] = html.unescape(str(item[field]))
    items.sort(key=lambda x: x.get("published") or "", reverse=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "site_count": len(normalized_sites),
        "article_count": len(items),
        "articles": items,
    }
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    LOG_FILE.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    print(f"Done: {len(items)} unique articles from {len(sites)} sites")

if __name__ == "__main__":
    main()
