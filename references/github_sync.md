# 네이버 DataLab 자동 동기화 (Cowork hostname_blocked 우회)

Cowork 코드 실행 환경에서 `*.naver.com`이 Anthropic egress proxy의
`hostname_blocked`로 막힐 수 있다. 이 경우 네이버 API는 GitHub Actions에서
호출하고, Cowork는 GitHub에 저장된 최신 `data/search_daily.csv`만 읽는다.

## 1. 이 panki-check 폴더를 GitHub 저장소 루트에 올리기

`.github/workflows/update-naver-search.yml`이 포함되어 있어야 한다.

## 2. GitHub Secrets 등록

Repository → Settings → Secrets and variables → Actions

- `NAVER_CLIENT_ID`
- `NAVER_CLIENT_SECRET`

실제 키는 코드나 대화창에 쓰지 않는다.

## 3. 최초 실행

Actions → **Update Naver Search Data** → **Run workflow**

성공하면 아래 두 파일이 매일 한국시간 약 07:17에 갱신된다.

- `data/search_daily.csv`
- `data/datalab.json`

`search_daily.csv`는 DataLab 특성상 하루치를 append하지 않고
`2022-01-01 ~ 어제` 전체를 다시 조회해 통째로 덮어쓴다.

## 4. Cowork에 CSV 주소 연결

### 공개 GitHub 저장소

`data/search_daily.csv` 파일의 **Raw** 주소를 복사한다.

예:

```text
https://raw.githubusercontent.com/USERNAME/REPO/main/data/search_daily.csv
```

프로젝트의 `panki_keys.txt` 또는 `config/.env`에 한 줄 추가한다.

```text
PANKI_SEARCH_CSV_URL=https://raw.githubusercontent.com/USERNAME/REPO/main/data/search_daily.csv
```

기존 키도 같은 파일에 둬도 된다.

```text
NAVER_CLIENT_ID=...
NAVER_CLIENT_SECRET=...
KMA_SERVICE_KEY=...
PANKI_SEARCH_CSV_URL=https://raw.githubusercontent.com/USERNAME/REPO/main/data/search_daily.csv
```

이후 `python scripts/daily_check.py`를 실행하면:

1. 네이버 직접 API 시도
2. Cowork egress에서 막히면 GitHub CSV fallback
3. `data/search_daily.csv` 갱신
4. 판기 판정

순서로 진행한다.

### 비공개 저장소

GitHub Contents API의 raw 응답 URL을 `PANKI_SEARCH_CSV_URL`로 넣고,
읽기 권한이 있는 fine-grained token을 `PANKI_GITHUB_TOKEN`으로 넣을 수 있다.
토큰은 절대 zip이나 저장소에 커밋하지 않는다.

## 5. 수동 xlsx는 계속 사용 가능

GitHub 동기화가 안 되는 날에는 기존 방식대로 네이버 데이터랩에서 xlsx를
다운로드해 Cowork에 올리면 `import_manual.py`가 이를 찾아
`data/search_daily.csv`를 전체 덮어쓴다.

현재 지원하는 DataLab xlsx 형식:

```text
날짜 | 후드티 | 날짜 | 후드집업 | 날짜 | 플리스
```

기간은 `2022-01-01 ~ 어제`, 일간, 전체 기기·성별·연령으로 유지한다.
