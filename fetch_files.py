
import json
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

# 取得対象のアップローダー
BASE_URL = "https://uu.getuploader.com/kyouakuchar22/"

# data.json の保存先
OUTPUT_FILE = Path(__file__).resolve().parent / "data.json"


def fetch_files():
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/130.0.0.0 Safari/537.36"
        )
    }

    # ページを取得
    response = requests.get(
        BASE_URL,
        headers=headers,
        timeout=30,
    )

    # 文字コードを設定
    response.encoding = response.apparent_encoding

    # アクセス状況をログに出力
    print("HTTP status:", response.status_code)
    print("Response URL:", response.url)
    print("Response body:", response.text[:1000])

    # HTTPエラーがあれば、ここで停止
    response.raise_for_status()

    # HTMLを解析
    soup = BeautifulSoup(response.text, "html.parser")

    table = soup.select_one("table.table-small-font")

    if table is None:
        raise RuntimeError(
            "ファイル一覧のテーブルが見つかりません。"
            "元サイトのHTML構造を確認してください。"
        )

    files = []

    # ファイル一覧の各行を取得
    for row in table.select("tbody tr"):
        cells = row.find_all("td")

        # 必要な列が5列未満ならスキップ
        if len(cells) < 5:
            continue

        # ファイル名のリンクを取得
        link = cells[0].find("a", href=True)

        if link is None:
            continue

        file_url = urljoin(BASE_URL, link["href"])
        file_name = link.get_text(" ", strip=True)
        comment = cells[1].get_text(" ", strip=True)
        date = cells[4].get_text(" ", strip=True)

        if not file_name:
            continue

        # 必要な4項目だけを保存
        files.append({
            "url": file_url,
            "name": file_name,
            "comment": comment,
            "date": date,
        })

    # 0件の場合は既存データを上書きしない
    if not files:
        raise RuntimeError(
            "ファイル情報を1件も取得できませんでした。"
            "サイトのHTML構造やアクセス制限を確認してください。"
        )

    # JSONとして保存
    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            files,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"{len(files)}件のファイル情報を保存しました。")
    print(f"保存先: {OUTPUT_FILE}")


if __name__ == "__main__":
    fetch_files()
