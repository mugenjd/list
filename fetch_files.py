
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 取得対象のアップローダー
BASE_URL = "https://uu.getuploader.com/kyouakuchar22/"

# 保存先
OUTPUT_FILE = Path(__file__).resolve().parent / "data.json"


def fetch_files():
    headers = {
        "User-Agent": "Mozilla/5.0 (compatible; UploaderListBot/1.0)"
    }

    response = requests.get(
        BASE_URL,
        headers=headers,
        timeout=30,
    )
    print("HTTP status:", response.status_code)
print("Response URL:", response.url)
print("Response body:", response.text[:1000])

response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select_one("table.table-small-font")

    if table is None:
        raise RuntimeError(
            "ファイル一覧のテーブルが見つかりません。"
            "サイトのHTML構造やアクセス制限を確認してください。"
        )

    files = []

    for row in table.select("tbody tr"):
        cells = row.find_all("td")

        # 必要な列が存在するか確認
        if len(cells) < 5:
            continue

        link = cells[0].find("a", href=True)

        if link is None:
            continue

        file_url = urljoin(BASE_URL, link["href"])
        file_name = link.get_text(" ", strip=True)
        comment = cells[1].get_text(" ", strip=True)
        date = cells[4].get_text(" ", strip=True)

        if not file_name:
            continue

        files.append({
            "url": file_url,
            "name": file_name,
            "comment": comment,
            "date": date,
        })

    if not files:
        raise RuntimeError(
            "ファイル情報を1件も取得できませんでした。"
            "取得結果を確認してください。"
        )

    # 取得日時の新しい順に表示できるよう、
    # 元サイトの掲載順はそのまま保存する
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(files, f, ensure_ascii=False, indent=2)

    print(f"{len(files)}件のファイル情報を保存しました。")


if __name__ == "__main__":
    fetch_files()
