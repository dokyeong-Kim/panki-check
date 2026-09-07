#!/usr/bin/env python3
"""매일 실행 진입점. 순서: 수동 원자료 임포트 → 기온 수집(가능하면) → 판정.

  1) import_manual.py  — uploads/ 또는 data/inbox/ 에 새 데이터랩 xlsx / ASOS CSV가 있으면 반영
  2) fetch_datalab.py  — API가 열려 있으면 검색지수 갱신 (막혀 있으면 건너뜀)
  3) fetch_weather.py  — 기상청 실측+예보. 막혀 있으면 건너뜀 (실측 CSV로 판정)
  4) judge.py          — 4단계 판정 + 브리핑

수집 실패는 판정을 막지 않는다. 마지막 성공분으로 판정하고 브리핑 상단에 데이터 기준일을 찍는다.
"""
import subprocess, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

def run(name, *args, optional=False):
    print(f"\n=== {name} ===")
    r = subprocess.run([sys.executable, str(HERE / name), *args])
    if r.returncode != 0 and optional:
        print(f"({name} 실패 — 건너뜀)")
    return r.returncode == 0

run("import_manual.py")
run("fetch_datalab.py", optional=True)
run("fetch_weather.py", optional=True)
run("fetch_weathernews.py", optional=True)
print()
run("judge.py")
