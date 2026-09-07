#!/usr/bin/env python3
"""네이버 데이터랩 검색지수를 갱신한다.

우선순위
1) 네이버 DataLab API 직접 호출
2) 직접 호출이 Anthropic egress 등으로 막히면 PANKI_SEARCH_CSV_URL에서 최신 CSV 동기화

직접 API 성공 시 data/datalab.json과 data/search_daily.csv를 둘 다 갱신한다.
이전 버전은 datalab.json만 써서 judge.py가 새 데이터를 읽지 못하는 연결 문제가 있었다.

DataLab은 상대지수이므로 항상 window_start~어제 전체를 다시 받아 통째로 덮어쓴다.
세 키워드 그룹도 반드시 한 요청에 묶는다.
"""
import csv
import io
import json
import sys
import urllib.request
import urllib.error
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _creds

API_URL = "https://openapi.naver.com/v1/datalab/search"
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ITEMS = ["후드집업", "후드티", "플리스"]


def load_config():
    return json.loads((ROOT / "config" / "triggers.json").read_text(encoding="utf-8"))


def load_settings():
    creds, src = _creds.load()
    return creds, src


def fetch_api(start, end, keyword_groups, cid, secret):
    groups = [{"groupName": name, "keywords": kws} for name, kws in keyword_groups.items()]
    if len(groups) > 5:
        raise RuntimeError("데이터랩은 한 요청에 최대 5개 그룹까지만 받습니다.")

    body = json.dumps({
        "startDate": start,
        "endDate": end,
        "timeUnit": "date",
        "keywordGroups": groups,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=body,
        headers={
            "X-Naver-Client-Id": cid,
            "X-Naver-Client-Secret": secret,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"데이터랩 API HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"데이터랩 API 연결 실패: {e.reason}") from e


def to_table(payload):
    table = {}
    for group in payload.get("results", []):
        name = group["title"]
        for point in group.get("data", []):
            table.setdefault(point["period"], {})[name] = round(float(point["ratio"]), 5)
    return table


def write_search_csv(table):
    DATA.mkdir(exist_ok=True)
    out = DATA / "search_daily.csv"
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date"] + ITEMS)
        for d in sorted(table):
            w.writerow([d] + [table[d].get(k, "") for k in ITEMS])
    return out


def validate_csv_text(text):
    rows = list(csv.DictReader(io.StringIO(text.lstrip("\ufeff"))))
    if not rows:
        raise RuntimeError("fallback CSV가 비어 있습니다.")
    expected = {"date", *ITEMS}
    if not expected.issubset(set(rows[0].keys())):
        raise RuntimeError(f"fallback CSV 헤더가 다릅니다. 필요: {sorted(expected)}")
    table = {}
    for row in rows:
        d = (row.get("date") or "").strip()
        if not d:
            continue
        rec = {}
        for k in ITEMS:
            v = (row.get(k) or "").strip()
            if v != "":
                rec[k] = float(v)
        if rec:
            table[d] = rec
    if not table:
        raise RuntimeError("fallback CSV에서 유효한 검색지수를 읽지 못했습니다.")
    return table


def fetch_fallback_csv(url, token=None):
    headers = {"User-Agent": "panki-check/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["Accept"] = "application/vnd.github.raw+json"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8-sig")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"fallback CSV HTTP {e.code}: {detail}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"fallback CSV 연결 실패: {e.reason}") from e
    return validate_csv_text(text)


def main():
    cfg = load_config()
    settings, sources = load_settings()
    start = cfg["datalab"]["window_start"]
    end = (date.today() - timedelta(days=1)).isoformat()

    cid = settings.get("NAVER_CLIENT_ID")
    secret = settings.get("NAVER_CLIENT_SECRET")
    fallback_url = settings.get("PANKI_SEARCH_CSV_URL")
    github_token = settings.get("PANKI_GITHUB_TOKEN")

    direct_error = None
    if cid and secret:
        try:
            print(f"데이터랩 직접 API 시도 · ID={_creds.mask(cid)}")
            payload = fetch_api(start, end, cfg["datalab"]["keywords"], cid, secret)
            table = to_table(payload)
            if not table:
                raise RuntimeError("데이터랩 API 결과가 비어 있습니다.")

            DATA.mkdir(exist_ok=True)
            (DATA / "datalab.json").write_text(
                json.dumps({"start": start, "end": end, "series": table}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            out = write_search_csv(table)
            ds = sorted(table)
            print(f"데이터랩 API 성공: {ds[0]} ~ {ds[-1]} ({len(ds)}일) → {out}")
            return
        except Exception as e:
            direct_error = str(e)
            print(f"데이터랩 직접 API 실패: {direct_error}")
    else:
        direct_error = "NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 없음"
        print("데이터랩 직접 API 생략: 네이버 키 없음")

    if fallback_url:
        try:
            print("GitHub/외부 CSV fallback 시도")
            table = fetch_fallback_csv(fallback_url, github_token)
            out = write_search_csv(table)
            ds = sorted(table)
            print(f"검색지수 fallback 성공: {ds[0]} ~ {ds[-1]} ({len(ds)}일) → {out}")
            return
        except Exception as e:
            raise SystemExit(f"데이터랩 갱신 실패\n- 직접 API: {direct_error}\n- fallback: {e}")

    raise SystemExit(
        "데이터랩 갱신 실패: " + str(direct_error) + "\n"
        "Cowork에서 naver.com이 hostname_blocked라면 PANKI_SEARCH_CSV_URL을 설정하세요."
    )


if __name__ == "__main__":
    main()
