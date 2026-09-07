#!/usr/bin/env python3
"""웨더뉴스 서울(장충동) 페이지에서 16일 일별 예보(최고/최저)를 긁어 data/weather.json 에 쓴다.

기상청 API가 막힌 환경의 예보 대체원. 페이지에 박힌 Nuxt 페이로드(devalue 직렬화)를
디코딩해 mrf(일별) 배열을 꺼낸다. 키 불필요.
평균기온(tavg)은 제공되지 않아 (최고+최저)/2 로 근사한다 — 플리스 급상승 룰(평균 22.5℃)에만 쓰인다.
기존 weather.json(기상청 산출)이 있으면 날짜별로 병합하고, 같은 날짜는 기상청 값이 이긴다.
"""
import json
import re
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = "웨더뉴스 예보"


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def decode_devalue(arr):
    def dev(i):
        v = arr[i]
        if isinstance(v, list):
            if v and isinstance(v[0], str) and v[0] in ("ShallowReactive", "Reactive", "Ref", "ShallowRef"):
                return dev(v[1])
            return [dev(x) if isinstance(x, int) else x for x in v]
        if isinstance(v, dict):
            return {k: (dev(x) if isinstance(x, int) else x) for k, x in v.items()}
        return v
    return dev(0)


def parse(html):
    m = re.search(r'id="__NUXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("__NUXT_DATA__ 페이로드를 찾지 못함 — 페이지 구조가 바뀌었을 수 있음")
    root = decode_devalue(json.loads(m.group(1)))
    data = root["data"]
    key = next(k for k in data if k.startswith("weather:"))
    node = data[key]
    inner = next(v for k, v in node.items() if k != "fetchedAt")
    out = {}
    for d in inner.get("mrf", []):
        day = d["tm"][:10]
        lo, hi = d.get("mint"), d.get("maxt")
        if lo is None or hi is None:
            continue
        out[day] = {"tmin": float(lo), "tmax": float(hi), "tavg": round((float(lo) + float(hi)) / 2, 1),
                    "source": SRC}
    return out


def main():
    cfg = json.loads((ROOT / "config" / "triggers.json").read_text(encoding="utf-8"))
    url = cfg.get("forecast", {}).get("weathernews_url")
    if not url:
        sys.exit("config/triggers.json 의 forecast.weathernews_url 이 없습니다")
    fc = parse(fetch_html(url))
    p = ROOT / "data" / "weather.json"
    existing = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"series": {}, "failures": []}
    series = dict(existing.get("series", {}))
    for d, rec in fc.items():
        if series.get(d, {}).get("source") in ("실측", "단기예보", "중기예보"):
            continue
        series[d] = rec
    p.write_text(json.dumps({"region": cfg["region"]["name"],
                             "fetched_at": datetime.now().isoformat(timespec="seconds"),
                             "failures": existing.get("failures", []),
                             "series": dict(sorted(series.items()))}, ensure_ascii=False, indent=2),
                 encoding="utf-8")
    ds = sorted(fc)
    print(f"웨더뉴스 예보 {ds[0]} ~ {ds[-1]} ({len(fc)}일) → {p}")
    print("  " + "  ".join(f"{d[5:]} {fc[d]['tmin']:.0f}/{fc[d]['tmax']:.0f}" for d in ds))


if __name__ == "__main__":
    main()
