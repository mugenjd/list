
import csv
import io
import json
import sys
from urllib.parse import quote

import requests

# 3つのスプレッドシートの設定
SHEETS = [
    {
        "group": "凶悪キャラスレアップローダ",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "239931589",
    },
    {
        "group": "ターゲット倉庫",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "0",
    },
    {
        "group": "むげん代理公開場",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "1931694445",
    },
        "group": "闇鍋ロダ",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "1031532254",
]

# スプレッドシートの見出し名
ALIASES = {
    "page": ["ページタイトル", "ページ名", "サイト名", "ページ"],
    "url": ["リンクURL", "URL", "リンク", "公開リンク"],
    "name": ["ファイル名", "名前", "タイトル"],
    "comment": ["コメント", "備考", "説明"],
    "date": ["日時", "登録日時", "公開日時", "更新日時"],
}

OUTPUT = "data.json"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "GitHubPages-Sheets-Sync/1.0"
})


def normalize_header(value):
    return (value or "").strip().replace("\ufeff", "")


def pick(row, candidates):
    normalized = {
        normalize_header(k): (v or "").strip()
        for k, v in row.items()
    }

    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]

    return ""


def fetch_sheet(sheet):
    sid = sheet["spreadsheet_id"].strip()
    gid = str(sheet["gid"]).strip()

    if not sid or sid.startswith("ここに"):
        raise ValueError(
            f'{sheet["group"]}: spreadsheet_id が未設定です。'
            "SHEETS の設定を確認してください。"
        )

    url = (
        "https://docs.google.com/spreadsheets/d/"
        f"{quote(sid, safe='')}/export?format=csv"
        f"&gid={quote(gid, safe='')}"
    )

    response = SESSION.get(url, timeout=45)
    response.raise_for_status()

    body = response.text.lstrip()

    # CSVではなくGoogleのHTML画面が返された場合
    if (
        "<html" in body[:500].lower()
        or "<!doctype html" in body[:500].lower()
    ):
        raise RuntimeError(
            f'{sheet["group"]}: CSVを取得できませんでした。'
            "シートの共有設定、spreadsheet_id、gid を確認してください。"
        )

    reader = csv.DictReader(
        io.StringIO(response.content.decode("utf-8-sig"))
    )

    if not reader.fieldnames:
        raise RuntimeError(
            f'{sheet["group"]}: CSVに見出し行がありません。'
        )

    rows = []
    current_page = ""

    for raw in reader:
        page = pick(raw, ALIASES["page"])
        
        # ページ名末尾の「 | uploader.jp」を削除
        page = page.removesuffix(" | uploader.jp")

        url_value = pick(raw, ALIASES["url"])
        name = pick(raw, ALIASES["name"])
        comment = pick(raw, ALIASES["comment"])
        date = pick(raw, ALIASES["date"])

        # ページタイトルだけの行を検出して記憶
        if page and not any([url_value, name, comment, date]):
            current_page = page
            continue

        # ファイル行にページタイトルがない場合は、
        # 直前のページタイトルを引き継ぐ
        if page:
            current_page = page
        else:
            page = current_page

        # 完全な空行は除外
        if not any([page, url_value, name, comment, date]):
            continue

        rows.append({
            "group": sheet["group"],
            "page": page,
            "url": url_value,
            "name": name,
            "comment": comment,
            "date": date,
        })

    return rows


def main():
    all_rows = []
    errors = []

    for sheet in SHEETS:
        try:
            rows = fetch_sheet(sheet)
            all_rows.extend(rows)
            print(f'OK: {sheet["group"]} - {len(rows)} rows')

        except Exception as exc:
            errors.append(f'{sheet["group"]}: {exc}')
            print(
                f'ERROR: {sheet["group"]}: {exc}',
                file=sys.stderr
            )

    # 1つでも取得に失敗したら、既存のdata.jsonを上書きしない
    if errors:
        print(
            "\n取得に失敗しました。data.json は更新しません。",
            file=sys.stderr
        )
        sys.exit(1)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"完了: {len(all_rows)} rows -> {OUTPUT}")


if __name__ == "__main__":
    main()
