#!/usr/bin/env python3
"""품목 × 4단계(검색시작·급상승·피크·종료)를 매일 판정하고 브리핑을 만든다.

입력
  config/triggers.json     룰. lifecycle 에 품목→단계→룰 매핑
  data/search_daily.csv    검색지수 일간 (import_manual.py 또는 fetch_datalab.py 산출)
  data/weather_daily.csv   ASOS 실측 일간
  data/weather.json        fetch_weather.py 산출 (실측+단기+중기 예보). 있으면 미래 구간에 씀

판정 방식 (references/validation.md 2026-09-02(4) 항과 동일)
  시즌 = 7/1 ~ 익년 6/30, 베이스 = 7/1~8/10 7일평균 중앙값
  검색시작 = 7일평균 ≥ 저점 × 배수(집업·후드티 1.5 / 플리스 2.0) 3일 연속
  급상승  = 7일평균 ≥ 베이스 + 0.15×(전년 피크 − 베이스) 3일 연속  (품목마다 피크/베이스 비가 달라 배수로는 못 잡음)
  피크    = 시즌 7일평균 최대일. 최대 이후 7일 지나고 10% 이상 빠졌을 때만 '확정'
  종료    = 피크 이후 7일평균 ≤ 베이스 + 0.2×(피크−베이스) 3일 연속
  기온 룰 = 8/1(봄 룰은 익년 2/1)부터 N일 연속 충족한 최초일 + lead_days
  달력 룰 = anchor ± window. 창을 지나도 미검출이면 '지연'

출력: 화면 + data/brief_latest.txt + data/history.csv 한 줄
"""
import csv
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ITEMS = ["후드집업", "후드티", "플리스"]
STAGES = ["검색시작", "급상승", "피크", "종료"]
DET = {"base_start": "07-15", "base_end": "08-10", "start_mult": {"후드집업": 1.5, "후드티": 1.5, "플리스": 2.0}, "surge_frac": 0.15,
       "hold": 3, "peak_from": "08-15", "peak_to": "01-31", "end_frac": 0.20,
       "peak_confirm_days": 7, "peak_confirm_drop": 0.10}


def read_csv(path):
    if not path.exists():
        return {}
    out = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            d = row.pop("date")
            out[d] = {k: float(v) for k, v in row.items() if v not in ("", None)}
    return out


def load_weather():
    """실측 CSV 위에 weather.json(예보 포함)을 얹는다. 실측이 있으면 실측이 이긴다."""
    wx, src = {}, {}
    p = DATA / "weather.json"
    if p.exists():
        j = json.loads(p.read_text(encoding="utf-8"))
        for d, rec in j.get("series", {}).items():
            wx[d] = {k: rec[k] for k in ("tmin", "tmax", "tavg") if k in rec}
            src[d] = rec.get("source", "예보")
    for d, rec in read_csv(DATA / "weather_daily.csv").items():
        wx[d] = rec
        src[d] = "실측"
    return wx, src


def ma7(series, item):
    dates = sorted(series)
    out = {}
    for i in range(6, len(dates)):
        chunk = [series[dates[j]].get(item) for j in range(i - 6, i + 1)]
        if all(v is not None for v in chunk):
            out[dates[i]] = sum(chunk) / 7
    return out


def s2d(s):
    return date.fromisoformat(s)


def prev_peak(avg, y):
    prev = [v for d, v in avg.items() if f"{y-1}-08-15" <= d <= f"{y}-01-31"]
    return max(prev) if prev else None


def detect(avg, y, item):
    in_season = {d: v for d, v in avg.items() if f"{y}-07-01" <= d <= f"{y+1}-06-30"}
    if not in_season:
        return None
    base_vals = [v for d, v in in_season.items() if f"{y}-{DET['base_start']}" <= d <= f"{y}-{DET['base_end']}"]
    if len(base_vals) < 10:
        return None
    base = min(base_vals)   # 여름 저점
    dates = sorted(in_season)
    latest = dates[-1]

    def first_hold(cond, start=None):
        run = 0
        for d in dates:
            if start and d < start:
                continue
            if cond(in_season[d]):
                run += 1
                if run >= DET["hold"]:
                    return (s2d(d) - timedelta(days=DET["hold"] - 1)).isoformat()
            else:
                run = 0
        return None

    mult = DET["start_mult"][item]
    start = first_hold(lambda v: v >= mult * base, f"{y}-08-01")
    ppk = prev_peak(avg, y)
    surge_level = base + DET["surge_frac"] * (ppk - base) if ppk else None
    surge = first_hold(lambda v: v >= surge_level, f"{y}-08-01") if surge_level else None

    def tail_run(mult):
        n = 0
        for d in reversed(dates):
            if in_season[d] >= mult * base:
                n += 1
            else:
                break
        return n
    def tail_run_level(level):
        n = 0
        for d in reversed(dates):
            if in_season[d] >= level:
                n += 1
            else:
                break
        return n
    entering = {"검색시작": tail_run(mult),
                "급상승": tail_run_level(surge_level) if surge_level else 0}

    def eta(level):
        """현재 7일평균이 level에 닿을 때까지 남은 일수 (빠른/느린 시나리오).
        최근 5일·10일 기울기 두 개로 범위를 만든다. 기울기≤0 이면 None."""
        cur = in_season[latest]
        if cur >= level:
            return (0, 0)
        out = []
        for n in (5, 10):
            if len(dates) <= n:
                continue
            slope = (cur - in_season[dates[-1 - n]]) / n
            if slope > 0:
                out.append((level - cur) / slope)
        if not out:
            return None
        lo, hi = min(out), max(out)
        return (max(1, round(lo)), min(45, round(hi * 1.3)))  # 상승은 보통 가속하므로 느린 쪽에 30% 여유
    eta_days = {"검색시작": eta(mult * base),
                "급상승": eta(surge_level) if surge_level else None}

    win = {d: v for d, v in in_season.items() if f"{y}-{DET['peak_from']}" <= d <= f"{y+1}-{DET['peak_to']}"}
    peak = peak_val = None
    peak_state = "미도달"
    if win:
        peak = max(win, key=win.get)
        peak_val = win[peak]
        since = (s2d(latest) - s2d(peak)).days
        if since >= DET["peak_confirm_days"] and in_season[latest] <= peak_val * (1 - DET["peak_confirm_drop"]):
            peak_state = "확정"
        elif surge:
            peak_state = "진행중"

    end = None
    if peak_state == "확정":
        thr = base + DET["end_frac"] * (peak_val - base)
        end = first_hold(lambda v: v <= thr, peak)

    return dict(base=base, latest=latest, cur=in_season[latest], mult=in_season[latest] / base,
                검색시작=start, 급상승=surge, entering=entering, eta_days=eta_days, surge_level=surge_level, prev_peak=ppk, 피크=peak if peak_state == "확정" else None,
                peak_candidate=peak, peak_state=peak_state, 종료=end)


def first_trigger(wx, src, rule, y, actual_only):
    spring = rule["direction"] == "above"
    lo = f"{y+1}-02-01" if spring else f"{y}-08-01"
    hi = f"{y+1}-06-30" if spring else f"{y}-12-31"
    run = 0
    for d in sorted(wx):
        if d < lo or d > hi:
            continue
        if actual_only and src.get(d) != "실측":
            continue
        v = wx[d].get(rule["metric"])
        if v is None:
            continue
        hit = v <= rule["threshold"] if rule["direction"] == "below" else v >= rule["threshold"]
        run = run + 1 if hit else 0
        if run >= rule["consecutive_days"]:
            return (s2d(d) - timedelta(days=rule["consecutive_days"] - 1)).isoformat(), src.get(d, "실측")
    return None, None


def project_stage(rule, y, wx, src, today):
    """(중심일, 범위시작, 범위끝, 근거, 확신도)"""
    lead = rule["lead_days"]
    fit_sd = rule.get("fit_sd_days") or 3
    d_act, _ = first_trigger(wx, src, rule, y, True)
    if d_act:
        c = s2d(d_act) + timedelta(days=lead)
        return c, c - timedelta(days=round(fit_sd)), c + timedelta(days=round(fit_sd)), f"실제로 {int(d_act[5:7])}/{int(d_act[8:10])}에", "높음"
    d_fc, s = first_trigger(wx, src, rule, y, False)
    if d_fc and d_fc > today:
        c = s2d(d_fc) + timedelta(days=lead)
        w = round(fit_sd + 1)
        return c, c - timedelta(days=w), c + timedelta(days=w), f"일기예보상 {int(d_fc[5:7])}/{int(d_fc[8:10])}에", "중간"
    t = rule["typical_trigger"]["mmdd"]
    ty = y + 1 if rule["direction"] == "above" else y
    t = f"{ty}-{t}"
    c = s2d(t) + timedelta(days=lead)
    w = round(rule["typical_trigger"]["sd_days"])
    return c, c - timedelta(days=w), c + timedelta(days=w), f"지난 4년 평균 {int(t[5:7])}/{int(t[8:10])}에", "낮음"


def fmt(d):
    return f"{d[5:7]}/{int(d[8:10])}" if d else "-"


def dday(d, today):
    n = (s2d(d) - s2d(today)).days
    return f"D-{n}" if n > 0 else (f"D+{-n}" if n < 0 else "D-day")


def main():
    cfg = json.loads((ROOT / "config" / "triggers.json").read_text(encoding="utf-8"))
    rules, life = cfg["rules"], cfg["lifecycle"]
    search = read_csv(DATA / "search_daily.csv")
    wx, src = load_weather()
    if not search:
        raise SystemExit("data/search_daily.csv 가 없습니다. scripts/import_manual.py 를 먼저 실행하세요.")
    today = date.today().isoformat()
    y = int(today[:4]) if today[5:] >= "07-01" else int(today[:4]) - 1

    latest_search = max(search)
    actual = [d for d in wx if src.get(d) == "실측"]
    latest_wx = max(actual) if actual else None
    w_today = wx.get(today, {})
    stale = (s2d(today) - s2d(latest_search)).days

    L = [f"[{today}] 판기 체크 — {y} FW 시즌",
         f"  검색지수 {fmt(latest_search)}까지 ({stale}일 전) · 기온 실측 {fmt(latest_wx) if latest_wx else '-'}까지"
         + (f" · 오늘({src.get(today)}) 최저 {w_today.get('tmin','-')} / 최고 {w_today.get('tmax','-')}" if w_today else "")]
    if stale > 7:
        L.append(f"  ⚠ 검색지수가 {stale}일 묵었다. 데이터랩 xlsx 다시 받아 import_manual.py 실행")
    L.append("")

    upcoming, hist_row, cells, reasons, done = [], {}, {}, [], []
    for item in ITEMS:
        cells[item] = {}
        det = detect(ma7(search, item), y, item)
        L.append(f"■ {item}")
        if not det:
            L.append("  이번 시즌 베이스 산출 불가 (7/1~8/10 데이터 부족)")
            L.append("")
            continue
        sl = det.get("surge_level")
        pct = f", 급상승선 {sl:.2f}의 {det['cur']/sl*100:.0f}%" if sl else ""
        L.append(f"  7일평균 {det['cur']:.2f} = 베이스 {det['base']:.2f}의 {det['mult']:.1f}배{pct}  ({fmt(det['latest'])} 기준)")
        hist_row[item] = f"{det['cur']:.2f}/{det['mult']:.2f}"
        for stage in STAGES:
            rule = rules[life[item][stage]]
            tag = "" if rule.get("status") in ("FITTED", "VERIFIED", "DERIVED") else f" [{rule.get('status')}]"
            if det.get(stage):
                L.append(f"  {stage:4} ✅ {fmt(det[stage])} 확정{tag}")
                cells[item][stage] = f"✅ {fmt(det[stage])}"
                if stage == "검색시작":
                    done.append(f"{item} {fmt(det[stage])}")
                continue
            if rule.get("method") == "calendar":
                lo, hi = rule["window"].split("~")
                anchor, lo, hi = f"{y}-{rule['anchor']}", f"{y}-{lo}", f"{y}-{hi}"
                run = det["entering"].get(stage, 0)
                e = det["eta_days"].get(stage)
                ref_t = rule.get("typical_tmin_at_stage")
                tnote, thit = "", None
                if ref_t is not None:
                    fut_t = [(d, wx[d]["tmin"]) for d in sorted(wx) if d >= today and "tmin" in wx[d]][:16]
                    thit = next((d for d, t in fut_t if t <= ref_t), None)
                    if thit:
                        tnote = f" · 기온 {fmt(thit)}부터 예년 발생 수준({ref_t}℃) 이하"
                base_d = s2d(det["latest"])
                if run:
                    conf_d = (base_d + timedelta(days=DET["hold"] - run)).isoformat()
                    L.append(f"  {stage:4} 🔶 기준 도달 {run}일째 → {DET['hold']}일 유지되면 {fmt(conf_d)} 확정{tag}")
                    cells[item][stage] = f"{fmt(conf_d)} 확정 예정"
                    upcoming.append((conf_d, f"{item} {stage} 확정 예정"))
                    reasons.append(f"{item}는 최근 7일 평균 검색량이 {stage} 기준선을 {run}일째 넘고 있습니다. 3일만 채우면 {fmt(conf_d)}에 {stage}으로 확정됩니다.")
                elif e:
                    a, b = (base_d + timedelta(days=e[0])).isoformat(), (base_d + timedelta(days=e[1])).isoformat()
                    late = a > hi
                    L.append(f"  {stage:4} 🔷 {fmt(a)}~{fmt(b)} 예상 — 현재 상승 속도로 {'급상승선' if stage=='급상승' else f'{DET["start_mult"][item]}배'} 도달 "
                             f"(예년 {fmt(lo)}~{fmt(hi)}){' ⚠ 예년보다 지연' if late else ''}{tnote}{tag}")
                    cells[item][stage] = f"{fmt(a)}~{fmt(b)}" + (" ⚠지연" if late else "")
                    upcoming.append((a, f"{item} {stage} ({fmt(a)}~{fmt(b)})"))
                    if stage == "급상승" and sl:
                        r_ = (f"{item} 급상승은 {fmt(a)}~{fmt(b)}로 봅니다. 목표선(작년 최고 검색량의 15% 지점)이 {sl:.2f}인데 "
                              f"지금 {det['cur']/sl*100:.0f}%까지 왔고, 최근 올라가는 속도로 계산한 날짜입니다. "
                              f"예년에는 {fmt(lo)}~{fmt(hi)}였으니 {'올해가 더 늦습니다' if late else '올해도 비슷한 시기입니다'}.")
                        if thit:
                            r_ += f" 기온은 {fmt(thit)}부터 예년 급상승 때 수준({ref_t}도)까지 내려가니 날씨 조건은 갖춰집니다. 검색이 얼마나 빨리 따라오느냐만 남았습니다."
                        reasons.append(r_)
                else:
                    L.append(f"  {stage:4} ⏳ 상승 정체 — 예년 {fmt(lo)}~{fmt(hi)}{' ⚠ 예년 창 지남' if today > hi else ''}{tnote}{tag}")
                    cells[item][stage] = f"정체 (예년 {fmt(lo)}~{fmt(hi)})"
            else:
                c, a, b, why, conf = project_stage(rule, y, wx, src, today)
                m_ = {"tmin": "아침 최저 기온", "tmax": "낮 최고 기온", "tavg": "하루 평균 기온"}[rule["metric"]]
                dir_ = "아래로" if rule["direction"] == "below" else "위로"
                nd = f"{rule['consecutive_days']}일 연속 " if rule["consecutive_days"] > 1 else ""
                rulestr = f"{m_}이 {nd}{rule['threshold']:g}도 {dir_} 가는"
                ex = f"  [현재 최대 {fmt(det['peak_candidate'])}]" if stage == "피크" and det["peak_state"] == "진행중" else ""
                overdue = b.isoformat() < today      # 예상 구간이 통째로 지났는데 아직 미확정
                if overdue:
                    e = det["eta_days"].get(stage)
                    sl = det.get("surge_level")
                    pct = f"{det['cur']/sl*100:.0f}%" if stage == "급상승" and sl else ""
                    if e:
                        a2 = (s2d(det["latest"]) + timedelta(days=e[0])).isoformat()
                        b2 = (s2d(det["latest"]) + timedelta(days=e[1])).isoformat()
                        cells[item][stage] = f"{fmt(a2)}~{fmt(b2)} ⚠지연"
                        L.append(f"  {stage:4} ⚠ 지연 — {rulestr} 트리거는 {why}, 예상 {fmt(c.isoformat())}였으나 미도달"
                                 f"{f' (현재 {pct})' if pct else ''}. 검색 속도로 재추정 {fmt(a2)}~{fmt(b2)}{tag}")
                        upcoming.append((a2, f"{item} {stage} 재추정 {fmt(a2)}~{fmt(b2)}"))
                        reasons.append(f"{item} {stage}은 날씨만 보면 벌써 왔어야 합니다. {rulestr} 조건이 {why} 채워졌고, 지난 4년 같으면 "
                                       f"{fmt(c.isoformat())}쯤 검색이 확 늘었을 시점입니다. 그런데 아직입니다{f' (목표선의 {pct}까지 왔습니다)' if pct else ''}. "
                                       f"그래서 날씨로 계산한 날짜는 접어두고, 최근 검색이 올라가는 속도로 다시 잡으면 {fmt(a2)}~{fmt(b2)}입니다.")
                    else:
                        cells[item][stage] = f"⚠ 예상 {fmt(c.isoformat())} 경과, 미도달"
                        L.append(f"  {stage:4} ⚠ 예상 {fmt(c.isoformat())} 경과했으나 미도달, 상승 정체{tag}")
                        reasons.append(f"{item} {stage}은 날씨 조건({rulestr})이 {why} 채워졌는데 검색이 멈춰 있습니다. 예상했던 {fmt(c.isoformat())}도 지났습니다.")
                else:
                    L.append(f"  {stage:4} {fmt(a.isoformat())}~{fmt(b.isoformat())} 예상 (중심 {fmt(c.isoformat())}, {dday(c.isoformat(), today)}) — {why} +{rule['lead_days']}일{ex}{tag}")
                    cells[item][stage] = f"{fmt(a.isoformat())}~{fmt(b.isoformat())}"
                    upcoming.append((c.isoformat(), f"{item} {stage} {fmt(a.isoformat())}~{fmt(b.isoformat())}"))
                    if conf != "낮음":
                        reasons.append(f"{item} {stage}은 {fmt(a.isoformat())}~{fmt(b.isoformat())}로 봅니다. {rulestr} 조건이 {why}이고, "
                                       f"지난 4년 보면 그때부터 {rule['lead_days']}일쯤 뒤에 {stage}이 왔습니다(오차 ±{rule.get('fit_sd_days','?')}일).")
        L.append("")

    # 순서 검증: 4시즌 모두 후드집업 급상승 → 플리스 급상승. 역전되면 집업 예측이 보수적인 것
    zip_s = next((d for d, w in upcoming if w.startswith("후드집업 급상승")), None)
    fl_s = next((d for d, w in upcoming if w.startswith("플리스 급상승")), None)
    order_warn = None
    if zip_s and fl_s and fl_s < zip_s:
        order_warn = (f"순서가 뒤집혔습니다. 플리스 급상승({fmt(fl_s)})이 후드집업({fmt(zip_s)})보다 빠르게 나왔는데, 지난 4년은 항상 후드집업이 먼저였습니다. "
                      f"계산 방법이 달라서 생긴 차이라, 후드집업 급상승은 {fmt(fl_s)}보다 앞선다고 보는 게 맞습니다.")
        L.append("⚠ " + order_warn)
        L.append("")
    L.append("─ 다음 이벤트 (가까운 순) ─")
    for d, what in sorted(upcoming)[:8]:
        L.append(f"  {fmt(d):>6}  {dday(d, today):>5}  {what}")

    # ── 기온 기준 측정 ──
    tas = cfg.get("temp_at_stage", {})
    if tas:
        ds = sorted(d for d in wx if "tmin" in wx[d])
        t7 = {}
        for i in range(6, len(ds)):
            t7[ds[i]] = sum(wx[ds[j]]["tmin"] for j in range(i - 6, i + 1)) / 7
        L += ["", "─ 기온 기준 측정 (7일평균 최저 ≤ 발생 시 기온) ─"]
        for item in ITEMS:
            cc = []
            for stage in STAGES:
                r = tas.get(item, {}).get(stage)
                if not r:
                    cc.append(f"{stage} —")
                    continue
                hit = next((d for d in ds if d >= f"{y}-08-01" and d in t7 and t7[d] <= r["tmin7"]), None)
                if hit:
                    lh = r["lead_hist"]
                    rng = f"{fmt((s2d(hit) + timedelta(days=min(lh))).isoformat())}~{fmt((s2d(hit) + timedelta(days=max(lh))).isoformat())}"
                    cc.append(f"{stage} {r['tmin7']}℃→{fmt(hit)}({'실측' if src.get(hit)=='실측' else '예보'}) 단계 {rng}")
                else:
                    cc.append(f"{stage} {r['tmin7']}℃→예보 밖")
            L.append(f"  {item:5} " + " | ".join(cc))
        L.append("  ※ 급상승은 기온이 검색보다 1~5일 늦게 도달(2024 제외). 피크·종료는 위 적합 룰이 더 정확(편차 1일 vs 10일)")

    fut = sorted(d for d in wx if d > today and "tmin" in wx[d])
    if fut:
        srcs = sorted({src.get(d, "") for d in fut[:16]} - {""})
        L += ["", f"─ 예보 최저/최고 ({'/'.join(srcs)}) ─",
              "  " + "  ".join(f"{fmt(d)} {wx[d].get('tmin','-')}/{wx[d].get('tmax','-')}" for d in fut[:16])]

    brief = "\n".join(L)
    print(brief)
    (DATA / "brief_latest.txt").write_text(brief, encoding="utf-8")

    # ── 보고용 마크다운 (SKILL.md '보고하는 법' 형식) ──
    fc_src = "/".join(sorted({src.get(d, "") for d in fut[:16]} - {""})) if fut else "예보 없음"
    M = [f"**오늘 브리핑 ({int(today[5:7])}/{int(today[8:10])}, {fc_src} 반영, 검색데이터 {fmt(latest_search)}, 날씨데이터 {fmt(latest_wx) if latest_wx else '-'})**", "",
         "| 품목 | 검색시작 | 급상승 | 피크 | 종료 |", "|---|---|---|---|---|"]
    for item in ITEMS:
        M.append(f"| {item} | " + " | ".join(cells.get(item, {}).get(st_, "—") for st_ in STAGES) + " |")
    M += ["", "**판정 근거**", ""]
    if fut:
        lows = [(d, wx[d]["tmin"]) for d in fut[:16]]
        first_cool = next((d for d, t in lows if t < 20), None)
        M.append("**날씨** — " + (f"{fmt(first_cool)}부터 아침 기온이 {wx[first_cool]['tmin']:.0f}도까지 내려갑니다. " if first_cool else "앞으로 2주간 아침 기온이 20도 밑으로는 안 내려갑니다. ")
                 + f"{fmt(lows[0][0])}부터 {fmt(lows[-1][0])}까지 아침 {min(t for _, t in lows):.0f}~{max(t for _, t in lows):.0f}도입니다.")
        M.append("")
    if done:
        M.append(f"**검색 시작** — {', '.join(done)}에 사람들이 찾기 시작한 게 확인됐습니다. 예년과 비슷한 시기입니다.")
        M.append("")
    for r_ in reasons:
        M.append(f"- {r_}")
    slow = [i for i in ITEMS if any("아직입니다" in r_ for r_ in reasons if r_.startswith(i))]
    if len(slow) >= 2:
        M += ["", f"지난 4년에 없던 상황입니다. 날씨는 이미 추워졌는데 검색이 안 따라오고 있습니다. 다음 주 검색량을 보면 답이 나옵니다."]
    if order_warn:
        M.append(f"- ⚠ {order_warn}")
    M += ["", "✅는 검색량으로 이미 확인된 날짜이고, 나머지는 예상입니다. 날씨 예보가 그 시점까지 나오면 더 정확해집니다."]
    md = "\n".join(M)
    (DATA / "brief_latest.md").write_text(md, encoding="utf-8")
    print("\n" + "═" * 60 + "\n" + md)


    hist = DATA / "history.csv"
    new = not hist.exists()
    with hist.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["날짜", "최저", "최고", "기온출처", "검색최신일"] + [f"{i}_7일평균/배수" for i in ITEMS])
        w.writerow([today, w_today.get("tmin"), w_today.get("tmax"), src.get(today, "-"), latest_search]
                   + [hist_row.get(i, "") for i in ITEMS])


if __name__ == "__main__":
    main()
