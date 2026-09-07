#!/usr/bin/env python3
"""기상청에서 서울 최저/최고기온을 받아온다.

세 갈래를 합친다. 판기 체크는 '이미 내려간 날'보다 '언제 내려갈 것인가'가
중요하므로 예보가 실측보다 중요하다.

  1) 과거관측 (ASOS 일자료)  — 어제까지의 확정 실측
  2) 단기예보 (동네예보)      — 오늘 ~ +3일. TMN/TMX
  3) 중기예보 (중기기온)      — +4일 ~ +10일. taMin3~10 / taMax3~10

같은 날짜가 여러 소스에 있으면 실측 > 단기 > 중기 순으로 채택한다.
어느 값이 어디서 왔는지 source 필드에 남기므로, 브리핑에서
'실측인지 예보인지'를 반드시 같이 표기할 것.
"""
import json
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _creds

ROOT = Path(__file__).resolve().parent.parent
DATA_GO_KR = "https://apis.data.go.kr/1360000"


def load_config():
    return json.loads((ROOT / "config" / "triggers.json").read_text(encoding="utf-8"))


def load_key():
    c, src = _creds.require("KMA_SERVICE_KEY")
    print(f"기상청 키 출처: {src['KMA_SERVICE_KEY']}  "
          f"{_creds.mask(c['KMA_SERVICE_KEY'])}")
    return c["KMA_SERVICE_KEY"]


def get(url, params):
    qs = urllib.parse.urlencode(params, safe="%")
    try:
        with urllib.request.urlopen(f"{url}?{qs}", timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode('utf-8','replace')[:300]}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"연결 실패: {e.reason}")

    if raw.lstrip().startswith("<"):
        # 공공데이터포털은 키가 틀리면 JSON 대신 XML 오류를 돌려준다
        raise RuntimeError(f"JSON이 아닌 응답(키 또는 신청 상태 확인): {raw[:300]}")
    return json.loads(raw)


def base_datetime_for_village():
    """동네예보 발표 시각 중 지금 기준 사용 가능한 가장 최근 것.
    발표는 02/05/08/11/14/17/20/23시, 실제 배포는 +10분 뒤라 여유를 둔다."""
    now = datetime.now() - timedelta(minutes=45)
    slots = [23, 20, 17, 14, 11, 8, 5, 2]
    for h in slots:
        if now.hour >= h:
            return now.strftime("%Y%m%d"), f"{h:02d}00"
    y = now - timedelta(days=1)
    return y.strftime("%Y%m%d"), "2300"


def fetch_short_term(key, nx, ny):
    """단기예보에서 TMN(일최저) / TMX(일최고) 추출."""
    base_date, base_time = base_datetime_for_village()
    data = get(f"{DATA_GO_KR}/VilageFcstInfoService_2.0/getVilageFcst", {
        "serviceKey": key, "pageNo": 1, "numOfRows": 1000, "dataType": "JSON",
        "base_date": base_date, "base_time": base_time, "nx": nx, "ny": ny,
    })
    items = data["response"]["body"]["items"]["item"]
    out = {}
    for it in items:
        if it["category"] in ("TMN", "TMX"):
            d = f"{it['fcstDate'][:4]}-{it['fcstDate'][4:6]}-{it['fcstDate'][6:]}"
            slot = "tmin" if it["category"] == "TMN" else "tmax"
            out.setdefault(d, {})[slot] = float(it["fcstValue"])
    return out


def fetch_mid_term(key, reg_id):
    """중기기온에서 +4 ~ +10일 최저/최고 추출."""
    now = datetime.now()
    tm = now.strftime("%Y%m%d") + ("1800" if now.hour >= 18 else "0600")
    if now.hour < 6:
        tm = (now - timedelta(days=1)).strftime("%Y%m%d") + "1800"
    data = get(f"{DATA_GO_KR}/MidFcstInfoService/getMidTa", {
        "serviceKey": key, "pageNo": 1, "numOfRows": 10, "dataType": "JSON",
        "regId": reg_id, "tmFc": tm,
    })
    item = data["response"]["body"]["items"]["item"][0]
    announced = datetime.strptime(tm[:8], "%Y%m%d").date()
    out = {}
    for n in range(3, 11):
        lo, hi = item.get(f"taMin{n}"), item.get(f"taMax{n}")
        if lo is None and hi is None:
            continue
        d = (announced + timedelta(days=n)).isoformat()
        rec = {}
        if lo is not None:
            rec["tmin"] = float(lo)
        if hi is not None:
            rec["tmax"] = float(hi)
        out[d] = rec
    return out


def fetch_actuals(key, stn, days=45):
    """ASOS 일자료로 확정 실측을 채운다."""
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days)
    data = get(f"{DATA_GO_KR}/AsosDalyInfoService/getWthrDataList", {
        "serviceKey": key, "pageNo": 1, "numOfRows": 500, "dataType": "JSON",
        "dataCd": "ASOS", "dateCd": "DAY",
        "startDt": start.strftime("%Y%m%d"), "endDt": end.strftime("%Y%m%d"),
        "stnIds": stn,
    })
    items = data["response"]["body"]["items"]["item"]
    out = {}
    for it in items:
        rec = {}
        if it.get("minTa") not in (None, ""):
            rec["tmin"] = float(it["minTa"])
        if it.get("maxTa") not in (None, ""):
            rec["tmax"] = float(it["maxTa"])
        if rec:
            out[it["tm"]] = rec
    return out


def merge(actual, short, mid):
    """실측 > 단기예보 > 중기예보 순으로 우선 채택."""
    merged = {}
    for src, table in (("중기예보", mid), ("단기예보", short), ("실측", actual)):
        for d, rec in table.items():
            merged.setdefault(d, {}).update(rec)
            merged[d]["source"] = src
    return dict(sorted(merged.items()))


def main():
    cfg = load_config()
    key = load_key()
    r = cfg["region"]

    results, failures = {}, []
    for label, fn in (
        ("실측", lambda: fetch_actuals(key, r["asos_stn"])),
        ("단기예보", lambda: fetch_short_term(key, r["nx"], r["ny"])),
        ("중기예보", lambda: fetch_mid_term(key, r["mid_temp_regId"])),
    ):
        try:
            results[label] = fn()
        except Exception as e:
            results[label] = {}
            failures.append(f"{label}: {e}")

    merged = merge(results["실측"], results["단기예보"], results["중기예보"])

    out = ROOT / "data" / "weather.json"
    out.write_text(json.dumps(
        {"region": r["name"], "fetched_at": datetime.now().isoformat(timespec="seconds"),
         "failures": failures, "series": merged},
        ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"기온 {len(merged)}일치 저장 → {out}")
    for f in failures:
        print(f"  [실패] {f}")
    if not merged:
        sys.exit("세 소스 모두 실패했습니다. 키 상태와 API 신청 승인 여부를 확인하세요.")


if __name__ == "__main__":
    main()
