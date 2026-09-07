# 먼저 이것만 하세요

이 버전은 기존 panki-check에 **네이버 DataLab 자동 우회 수집**을 붙인 버전입니다.
현재 `data/search_daily.csv`에는 업로드한 `datalab.xlsx`의 **2026-09-06까지 데이터**가 반영돼 있습니다.

## A. Claude Skill

기존 panki-check 대신 이 폴더/zip을 사용합니다.
수동 xlsx 업로드 방식도 그대로 작동합니다.

## B. 네이버 자동수집용 GitHub

1. 이 폴더 내용을 GitHub 저장소 루트에 올립니다.
2. GitHub → Settings → Secrets and variables → Actions에 아래 2개를 등록합니다.
   - `NAVER_CLIENT_ID`
   - `NAVER_CLIENT_SECRET`
3. Actions → `Update Naver Search Data` → `Run workflow`를 한 번 실행합니다.
4. 공개 저장소라면 `data/search_daily.csv`의 **Raw** 주소를 복사합니다.
5. Claude 프로젝트의 `panki_keys.txt`에 아래 한 줄을 추가합니다.

```text
PANKI_SEARCH_CSV_URL=복사한_RAW_주소
```

이후 Cowork에서 네이버 직접 API가 `hostname_blocked`되어도 GitHub의 최신 CSV를 자동으로 받아 판정합니다.

자세한 설명: `references/github_sync.md`
