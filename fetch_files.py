
import json
import time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://uu.getuploader.com/kyouakuchar22/"
SOURCE_FILE = Path("source.html")
DATA_FILE = Path("data.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; GitHubPagesCatalog/1.0)"
}


def fetch_source():
    response = requests.get(
        BASE_URL,
        headers=HEADERS,
        timeout=30,
    )
    response.raise_for_status()

    # 元ページのHTMLを保存
    SOURCE_FILE.write_bytes(response.content)

    return response.encoding or "utf-8"


def extract_files(encoding):
    html = SOURCE_FILE.read_text(
        encoding=encoding,
        errors="replace",
    )
    soup = BeautifulSoup(html, "html.parser")

    results = []

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        if not rows:
            continue

        headers = [
            cell.get_text(" ", strip=True)
            for cell in rows[0].find_all(["th", "td"])
        ]

        # ファイル一覧らしいテーブルだけ処理
        if not any("ファイル" in h for h in headers):
            continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if not cells:
                continue

            values = [
                cell.get_text(" ", strip=True)
                for cell in cells
            ]

            if len(values) != len(headers):
                continue

            item = dict(zip(headers, values))

            # ファイル名のリンクを取得
            link = None
            for cell in cells:
                for a in cell.find_all("a", href=True):
                    text = a.get_text(" ", strip=True)
                    if text:
                        link = urljoin(BASE_URL, a["href"])
                        break
                if link:
                    break

            filename = item.get("ファイル", "")
            if not filename:
                continue

            results.append({
                "name": filename,
                "comment": item.get("コメント", ""),
                "original": item.get("オリジナル", ""),
                "size": item.get("容量", ""),
                "date": item.get("日時", ""),
                "url": link or BASE_URL,
            })

        if results:
            break

    DATA_FILE.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"取得件数: {len(results)}")
    print(f"HTML保存: {SOURCE_FILE}")
    print(f"一覧保存: {DATA_FILE}")


if __name__ == "__main__":
    encoding = fetch_source()
    time.sleep(1)
    extract_files(encoding)
