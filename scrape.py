#!/usr/bin/env python3
"""Fetch listing metadata from uploader.jp warehouses 1–16. Never downloads file contents."""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

OUT = Path("data.json")
USER_AGENT = "Mozilla/5.0 (compatible; PublicMetadataIndex/1.0; +https://github.com/)"
TIMEOUT = 30
DELAY_SECONDS = 1.2
MAX_PAGES_PER_WAREHOUSE = 200


def warehouse_sources():
    for n in range(1, 17):
        slug = "mugen_target" if n == 1 else f"mugen_target{n}"
        yield n, f"ターゲット倉庫{n}", f"https://uu.getuploader.com/{slug}/"


def fetch(session: requests.Session, url: str) -> tuple[str, str]:
    last_error = None
    for attempt in range(4):
        try:
            response = session.get(url, timeout=TIMEOUT)
            if response.status_code in (429, 500, 502, 503, 504):
                raise requests.HTTPError(f"HTTP {response.status_code}", response=response)
            response.raise_for_status()
            response.encoding = response.apparent_encoding or response.encoding
            return response.text, response.url
        except (requests.RequestException, TimeoutError) as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 ** attempt * 2)
    raise RuntimeError(f"取得に失敗しました: {url}: {last_error}")


def safe_download_url(href: str, page_url: str) -> str | None:
    absolute = urljoin(page_url, href)
    parsed = urlparse(absolute)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith("getuploader.com"):
        return None
    if "/download/" not in parsed.path:
        return None
    return absolute


def parse_page(html: str, page_url: str, warehouse_name: str, warehouse_url: str):
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for tr in soup.select("tr"):
        cells = tr.find_all("td", recursive=False)
        if len(cells) < 5:
            continue
        first_link = cells[0].find("a", href=True)
        if not first_link:
            continue
        url = safe_download_url(first_link["href"], page_url)
        if not url:
            continue
        filename = first_link.get_text(" ", strip=True)
        comment = cells[1].get_text(" ", strip=True)
        original = cells[2].get_text(" ", strip=True) or filename
        date = cells[4].get_text(" ", strip=True)
        if not re.match(r"^\d{2}/\d{2}/\d{2}\s+\d{2}:\d{2}$", date):
            continue
        records.append({
            "original": original,
            "url": url,
            "date": date,
            "comment": comment,
            "warehouse": warehouse_name,
            "warehouse_url": warehouse_url,
        })
    return records, soup


def next_page_url(soup: BeautifulSoup, current_url: str, base_url: str) -> str | None:
    candidate = soup.find("link", rel=lambda value: value and "next" in value)
    if candidate and candidate.get("href"):
        next_url = urljoin(current_url, candidate["href"])
    else:
        anchor = soup.find("a", attrs={"title": "次へ"}, href=True)
        next_url = urljoin(current_url, anchor["href"]) if anchor else None
    if not next_url:
        return None
    # Do not follow links outside this warehouse's listing path.
    if urlparse(next_url).hostname not in {"uu.getuploader.com", "ux.getuploader.com"}:
        return None
    base_path = urlparse(base_url).path.rstrip("/")
    next_path = urlparse(next_url).path.rstrip("/")
    if not (next_path == base_path or next_path.startswith(base_path + "/index/")):
        return None
    if next_url.rstrip("/") == current_url.rstrip("/"):
        return None
    return next_url


def scrape_warehouse(session, number, name, base_url):
    print(f"[{number}/16] {name}: {base_url}", flush=True)
    url = base_url
    visited = set()
    records = []
    pages = 0
    while url:
        normalized = url.rstrip("/")
        if normalized in visited:
            break
        if pages >= MAX_PAGES_PER_WAREHOUSE:
            raise RuntimeError(f"ページ数上限に到達しました: {name}")
        visited.add(normalized)
        html, final_url = fetch(session, url)
        page_records, soup = parse_page(html, final_url, name, base_url)
        # A failed/blocked response must not silently replace the previous full dataset.
        page_text = soup.get_text(" ", strip=True)
        if "uploader.jp" not in page_text.lower() and "ファイル" not in page_text:
            raise RuntimeError(f"想定外のページ内容です（アクセス制限等の可能性）: {final_url}")
        records.extend(page_records)
        pages += 1
        print(f"  page {pages}: {len(page_records)} items", flush=True)
        url = next_page_url(soup, final_url, base_url)
        if url:
            time.sleep(DELAY_SECONDS)
    print(f"  合計 {len(records)} 件 / {pages} ページ", flush=True)
    return records


def date_sort_key(value):
    m = re.match(r"^(\d{2})/(\d{2})/(\d{2})\s+(\d{2}):(\d{2})$", value or "")
    if not m:
        return "0000-00-00 00:00"
    yy, mm, dd, hh, minute = map(int, m.groups())
    return f"{2000+yy:04d}-{mm:02d}-{dd:02d} {hh:02d}:{minute:02d}"


def main():
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    all_records = []
    seen_urls = set()
    for number, name, base_url in warehouse_sources():
        records = scrape_warehouse(session, number, name, base_url)
        for item in records:
            # Each download-page URL is a stable item identifier.
            if item["url"] not in seen_urls:
                seen_urls.add(item["url"])
                all_records.append(item)
        time.sleep(DELAY_SECONDS)
    all_records.sort(key=lambda x: date_sort_key(x["date"]), reverse=True)
    payload = {
        "updated_at": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z"),
        "count": len(all_records),
        "files": all_records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"完了: {len(all_records)} 件を {OUT} に保存しました", flush=True)

if __name__ == "__main__":
    main()
