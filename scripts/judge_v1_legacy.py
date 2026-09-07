#!/usr/bin/env python3
"""기온 + 검색지수를 합쳐 품목별 상태를 판정하고 일일 브리핑을 출력한다.

판정에 쓰는 값은 원본 일간지수가 아니라 7일 이동평균이다.
데이터랩 일간지수는 일요일마다 튀기 때문에(2026-08 기준 8/2·8/9·8/16·8/23이
전부 국소 고점) 원본을 그대로 보면 주말마다 '급상승'으로 오판한다.

미검증 규칙으로 내려진 판정에는 반드시 [미검증] 표시가 붙는다.
검증된 것과 가설을 같은 톤으로 보고하면 봇을 믿을 수 없게 된다.
"""
import csv
import json
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WINDOW = 7


def load(name):
    p = ROOT / "data" / name
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def rolling(series, keys, window=WINDOW):
    """{날짜: {품목: 값}} → {날짜: {품목: 7일평균}}"""
    dates = sorted(series)
    out = {}
    for i, d in enumerate(dates):
        if i + 1 < window:
            continue
        chunk = dates[i - window + 1: i + 1]
        out[d] = {}
        for k in keys:
            vals = [series[c][k] for c in chunk if k in series[c]]
            if len(vals) == window:
                out[d][k] = round(sum(vals) / window, 1)
    return out


def streak(weather, dates, metric, threshold, direction):
    """각 날짜 기준 조건 충족 연속일수. 기온이 없는 날은 연속을 끊지 않고 건너뛴다."""
    out, run = {}, 0
    for d in dates:
        rec = weather.get(d, {})
        v = rec.get(metric)
        if v is None:
            out[d] = run
            continue
        hit = v <= threshold if direction == "below" else v >= threshold
        run = run + 1 if hit else 0
        out[d] = run
    return out


def first_hit(streaks, dates, need):
    for d in dates:
        if streaks.get(d, 0) >= need:
            return d
    return None


def is_plateau(avgs, dates, item, band, days):
    pts = [avgs[d][item] for d in dates[-days - 1:] if item in avgs.get(d, {})]
    if len(pts) < days + 1:
        return False
    base = pts[0]
    if base == 0:
        return False
    return all(abs(p - base) / base <= band for p in pts[1:])


def tag(rule):
    return " [미검증]" if rule.get("status") == "UNVERIFIED" else ""


def main():
    cfg = json.loads((ROOT / "config" / "triggers.json").read_text(encoding="utf-8"))
    rules = cfg["rules"]

    dl = load("datalab.json")
    wx = load("weather.json")
    if dl is None or wx is None:
        raise SystemExit("data/datalab.json 또는 data/weather.json 이 없습니다. "
                         "fetch_datalab.py 와 fetch_weather.py 를 먼저 실행하세요.")

    series = dl["series"]
    weather = wx["series"]
    items = list(cfg["datalab"]["keywords"])

    avgs = rolling(series, items)
    idx_dates = sorted(avgs)
    all_dates = sorted(set(list(weather) + idx_dates))
    today = date.today().isoformat()
    latest = idx_dates[-1] if idx_dates else None

    gr, sg, fl = rules["gentle_rise"], rules["surge"], rules["fleece_start"]
    s_gentle = streak(weather, all_dates, gr["metric"], gr["threshold"], gr["direction"])
    s_surge = streak(weather, all_dates, sg["metric"], sg["threshold"], sg["direction"])
    s_fleece = streak(weather, all_dates, fl["metric"], fl["threshold"], fl["direction"])

    d_gentle = first_hit(s_gentle, all_dates, gr["consecutive_days"])
    d_surge = first_hit(s_surge, all_dates, sg["consecutive_days"])
    d_hold = first_hit(s_surge, all_dates, rules["peak"]["hold_days"])
    d_fleece = first_hit(s_fleece, all_dates, fl["consecutive_days"])
    d_peak = None
    if d_hold:
        d_peak = (datetime.fromisoformat(d_hold).date()
                  + timedelta(days=rules["peak"]["lag_days"])).isoformat()

    def trend(item):
        if len(idx_dates) < 4 or item not in avgs.get(latest, {}):
            return "데이터 부족"
        if is_plateau(avgs, idx_dates, item, rules["plateau"]["band"], rules["plateau"]["days"]):
            return "정체"
        prev = avgs.get(idx_dates[-4], {}).get(item)
        cur = avgs[latest][item]
        if prev is None:
            return "판단 보류"
        return "상승 중" if cur > prev else "하락 중"

    w_today = weather.get(today, {})
    tmin = w_today.get("tmin")
    tmax = w_today.get("tmax")
    src = w_today.get("source", "없음")

    L = []
    L.append(f"[{today}] {cfg['region']['name']}  최저 "
             f"{tmin if tmin is not None else '-'} / 최고 "
             f"{tmax if tmax is not None else '-'}  ({src})")
    L.append("")
    for item in items:
        a = avgs.get(latest, {}).get(item)
        L.append(f"{item:<6} 7일평균 {a if a is not None else '-':>6}  →  {trend(item)}")

    if "후드집업" in avgs.get(latest, {}) and "후드티" in avgs.get(latest, {}):
        z, t = avgs[latest]["후드집업"], avgs[latest]["후드티"]
        if t:
            ratio = round(z / t, 2)
            older = avgs.get(idx_dates[-8], {}) if len(idx_dates) >= 8 else {}
            note = ""
            if older.get("후드티"):
                prev = older["후드집업"] / older["후드티"]
                note = ("  (좁혀지는 중 — 후드티가 따라잡음)" if ratio < prev
                        else "  (벌어지는 중)")
            L.append(f"집업/후드티 비율 {ratio}{note}")

    L.append("")
    L.append("─ 트리거 상태 ─")
    L.append(f"완만상승 {gr['threshold']}℃  연속 {s_gentle.get(today, 0)}일"
             f"  최초발화 {d_gentle or '미발생'}")
    L.append(f"급상승   {sg['threshold']}℃  연속 {s_surge.get(today, 0)}일"
             f"  최초발화 {d_surge or '미발생'}{tag(sg)}")
    L.append(f"피크 예상 {d_peak or '미정'}{tag(rules['peak'])}")
    L.append(f"플리스   최고 {fl['threshold']}℃  최초발화 {d_fleece or '미발생'}{tag(fl)}")

    future = [(d, weather[d]) for d in all_dates if d > today and "tmin" in weather[d]]
    if future:
        L.append("")
        L.append("─ 예보 (최저) ─")
        L.append("  ".join(f"{d[5:]} {weather[d]['tmin']:.0f}" for d, _ in future[:10]))
        for label, rule in (("완만상승", gr), ("급상승", sg)):
            nxt = next((d for d, r in future if r["tmin"] <= rule["threshold"]), None)
            if nxt and not first_hit(
                {k: v for k, v in (s_gentle if label == "완만상승" else s_surge).items()
                 if k <= today}, [d for d in all_dates if d <= today],
                rule["consecutive_days"]):
                dd = (datetime.fromisoformat(nxt).date() - date.today()).days
                L.append(f"{label} 트리거 예상 진입: {nxt} (D-{dd}){tag(rule)}")

    if wx.get("failures"):
        L.append("")
        L.append("⚠ 기온 수집 일부 실패: " + " / ".join(wx["failures"]))

    brief = "\n".join(L)
    print(brief)

    (ROOT / "data" / "brief_latest.txt").write_text(brief, encoding="utf-8")

    hist = ROOT / "data" / "history.csv"
    new = not hist.exists()
    with hist.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["날짜", "최저", "최고", "기온출처"]
                       + [f"{i}_7일평균" for i in items]
                       + ["25도연속", "20도연속"])
        w.writerow([today, tmin, tmax, src]
                   + [avgs.get(latest, {}).get(i) for i in items]
                   + [s_gentle.get(today, 0), s_surge.get(today, 0)])


if __name__ == "__main__":
    main()
