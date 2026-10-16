import csv
import io
import json
import sys
import time
from urllib.parse import quote

import requests

# 3つのスプレッドシートの設定を入力してください。
# spreadsheet_id: URLの /d/ と /edit の間にある文字列
# gid: 対象シートのURL末尾にある gid= の数字（通常は 0 など）
SHEETS = [
    {
        "group": "むげん代理公開場",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "0",
    },
    {
        "group": "凶悪キャラスレアップローダ",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "239931589",
    },
    {
        "group": "ターゲット倉庫",
        "spreadsheet_id": "1VH9nkUrtnHwZmnUsU_Bg5AkgQ6LFTEw_nT7tPoZfUtY",
        "gid": "1931694445",
    },
]

# スプレッドシートの1行目の見出しに合わせています。
# 実際の見出しが異なる場合は、ALIASES に候補を追加してください。
ALIASES = {
    "page": ["ページタイトル", "ページ名", "サイト名", "ページ"],
    "url": ["リンクURL", "URL", "リンク", "公開リンク"],
    "name": ["ファイル名", "名前", "タイトル"],
    "comment": ["コメント", "備考", "説明"],
}

OUTPUT = "data.json"
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "GitHubPages-Sheets-Sync/1.0"})


def normalize_header(value):
    return (value or "").strip().replace("\ufeff", "")


def pick(row, candidates):
    normalized = {normalize_header(k): (v or "").strip() for k, v in row.items()}
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return ""


def fetch_sheet(sheet):
    sid = sheet["spreadsheet_id"].strip()
    gid = str(sheet["gid"]).strip()
    if not sid or sid.startswith("ここに"):
        raise ValueError(f'{sheet["group"]}: spreadsheet_id が未設定です。fetch_sheets.py の SHEETS を編集してください。')

    url = f"https://docs.google.com/spreadsheets/d/{quote(sid, safe='')}/export?format=csv&gid={quote(gid, safe='')}"
    response = SESSION.get(url, timeout=45)
    response.raise_for_status()

    # 公開設定が正しくない場合、CSVではなくGoogleのHTML画面が返ることがある
    content_type = response.headers.get("Content-Type", "").lower()
    body = response.text.lstrip()
    if "<html" in body[:500].lower() or "<!doctype html" in body[:500].lower():
        raise RuntimeError(
            f'{sheet["group"]}: CSVを取得できませんでした。'
            "シートが「リンクを知っている全員が閲覧できる」設定か、spreadsheet_id と gid を確認してください。"
        )

    reader = csv.DictReader(io.StringIO(response.content.decode("utf-8-sig")))
    if not reader.fieldnames:
        raise RuntimeError(f'{sheet["group"]}: CSVに見出し行がありません。')

    rows = []
    for raw in reader:
        page = pick(raw, ALIASES["page"])
        url_value = pick(raw, ALIASES["url"])
        name = pick(raw, ALIASES["name"])
        comment = pick(raw, ALIASES["comment"])

        # 完全な空行を除外
        if not any([page, url_value, name, comment]):
            continue

        rows.append({
            "group": sheet["group"],
            "page": page,
            "url": url_value,
            "name": name,
            "comment": comment,
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
            print(f'ERROR: {sheet["group"]}: {exc}', file=sys.stderr)

    # 1つでも失敗した場合、部分的な data.json で既存データを上書きしない
    if errors:
        print("\n取得に失敗しました。data.json は更新しません。", file=sys.stderr)
        sys.exit(1)

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(all_rows, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(f"完了: {len(all_rows)} rows -> {OUTPUT}")


if __name__ == "__main__":
    main()
