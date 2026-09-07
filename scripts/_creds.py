#!/usr/bin/env python3
"""panki-check 자격증명/옵션 설정 탐색.

환경변수 → config/.env → 업로드된 키 파일 → ~/.panki-check.env → 현재 폴더 순으로 읽는다.
민감값은 로그에 원문 출력하지 않는다.
"""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = ("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET", "KMA_SERVICE_KEY")
OPTIONAL = ("PANKI_SEARCH_CSV_URL", "PANKI_GITHUB_TOKEN")
KNOWN = REQUIRED + OPTIONAL

SEARCH_PATHS = [
    ROOT / "config" / ".env",
    Path("/mnt/user-data/uploads"),
    Path.home() / ".panki-check.env",
    Path.cwd(),
]

FILENAME_HINTS = ("panki", "key", "env", "cred", "판기", "키")


def _parse(text):
    found = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        line = re.sub(r"^export\s+", "", line)
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in KNOWN and v:
            found[k] = v
    return found


def _candidate_files():
    for p in SEARCH_PATHS:
        if p.is_file():
            yield p
        elif p.is_dir():
            try:
                entries = sorted(p.iterdir())
            except OSError:
                continue
            for f in entries:
                try:
                    if not f.is_file() or f.stat().st_size > 64_000:
                        continue
                except OSError:
                    continue
                name = f.name.lower()
                if f.suffix.lower() in (".txt", ".env", "") or name.startswith(".env"):
                    if any(h in name for h in FILENAME_HINTS) or f.suffix.lower() == ".env":
                        yield f


def load(required=()):
    """KNOWN 값들을 읽고, required가 있으면 그 키의 존재만 검사한다."""
    creds = {k: os.environ[k] for k in KNOWN if os.environ.get(k)}
    sources = {k: "환경변수" for k in creds}

    for f in _candidate_files():
        try:
            parsed = _parse(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for k, v in parsed.items():
            if k not in creds:
                creds[k] = v
                sources[k] = str(f)

    missing = [k for k in required if k not in creds]
    if missing:
        raise SystemExit("키를 찾지 못했습니다: " + ", ".join(missing))
    return creds, sources


def require(*keys):
    creds, sources = load(required=keys)
    return {k: creds[k] for k in keys}, sources


def mask(value):
    if not value:
        return "(없음)"
    if len(value) <= 5:
        return "***"
    return f"{value[:3]}…{value[-2:]} ({len(value)}자)"
