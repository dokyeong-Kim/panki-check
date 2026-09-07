# 최초 1회 설정

키는 본인이 직접 발급받아 파일에 넣습니다. **키 값을 대화창에 붙여넣지
마세요** — 스크립트가 파일에서 직접 읽으므로 그럴 필요가 없고, 대화
기록에 남으면 재발급해야 합니다.

넣는 위치는 스킬이 도는 환경에 따라 다릅니다. `scripts/_creds.py`가
아래 순서로 자동 탐색하므로, 둘 중 편한 쪽 하나만 하면 됩니다.

## A. Cowork 데스크톱 / Claude Code

스킬 폴더가 로컬 디스크에 있고 세션이 끝나도 유지됩니다.

```bash
cp config/.env.example config/.env
# 편집기로 열어 세 줄을 채운다
python scripts/daily_check.py
```

한 번만 하면 계속 유지됩니다. `.gitignore`에 이미 들어가 있습니다.

## B. claude.ai 웹 / 앱

**스킬은 매 세션 새로 펼쳐지므로 스킬 폴더에 써둔 파일은 다음 세션에
사라집니다.** 키는 스킬이 아니라 프로젝트에 둡니다.

1. 메모장에 아래 세 줄을 쓰고 `panki_keys.txt` 로 저장

   ```
   NAVER_CLIENT_ID=값
   NAVER_CLIENT_SECRET=값
   KMA_SERVICE_KEY=값
   ```

2. 프로젝트를 하나 만들고 이 파일을 프로젝트 지식에 올린다
3. 같은 프로젝트에서 스킬을 켜고 매일 그 안에서 대화한다

파일명은 `panki`, `key`, `env`, `키` 중 하나만 들어가면 됩니다.
`.env` 확장자도 인식합니다.

## 탐색 순서

1. 환경변수
2. `config/.env`
3. `/mnt/user-data/uploads/` 안의 키 파일
4. `~/.panki-check.env`
5. 현재 작업 폴더

`export` 접두어, 따옴표, `#` 주석 모두 허용합니다. 실행하면 어느
파일에서 키를 읽었는지 출력되므로, 의도한 곳에서 읽혔는지 확인하세요.
값은 앞 세 글자만 찍히고 나머지는 가려집니다.

---

## 1. 네이버 데이터랩 (검색어 트렌드)

1. developers.naver.com → 애플리케이션 등록
2. 사용 API에서 **데이터랩(검색어 트렌드)** 선택
3. 환경은 웹 서비스, URL은 `http://localhost` 로 두면 됩니다
4. 발급된 Client ID / Client Secret을 `.env`에 입력

무료이고 승인 대기도 없습니다. 하루 호출 한도가 있지만
이 스킬은 하루 1회만 부르므로 여유롭습니다.

### 데이터랩을 다룰 때 반드시 지킬 것

**상대지수지 절대 검색량이 아닙니다.** 요청한 기간 안의 최댓값이 100이
되도록 정규화됩니다. 여기서 사고가 두 갈래로 납니다.

- **키워드를 따로 조회하면 안 됩니다.** 각각 자기 기준으로 100이 되어
  품목 간 비교가 무의미해집니다. 세 개를 반드시 한 요청에 묶으세요.
- **하루치만 덧붙이면 안 됩니다.** 새로 더 높은 날이 들어오면 과거 값이
  전부 다시 축소됩니다. 어제 기록한 숫자와 오늘 숫자의 기준이 달라지죠.
  `fetch_datalab.py`가 매번 `window_start`부터 전체를 다시 받아 덮어쓰는
  이유입니다.

절대 검색량이 필요하면 네이버 **검색광고 키워드도구 API**를 따로 붙여야
합니다. 이건 검색광고센터 계정과 별도 인증이 필요합니다.

---

## 2. 기상청 (공공데이터포털)

data.go.kr 가입 후 아래 **세 개를 각각** 활용신청합니다.
스킬이 세 소스를 합쳐 쓰므로 하나만 신청하면 반쪽만 돌아갑니다.

| API | 용도 |
|---|---|
| 단기예보 조회서비스 (VilageFcstInfoService_2.0) | 오늘~+3일 최저/최고 |
| 중기예보 조회서비스 (MidFcstInfoService) | +4~+10일 최저/최고 |
| 종관기상관측(ASOS) 일자료 | 확정 실측 소급 |

- 대부분 자동승인이지만 ASOS는 승인까지 시간이 걸릴 수 있습니다
- 마이페이지의 **Decoding 키**를 `.env`에 넣으세요. Encoding 키를 넣으면
  이중 인코딩되어 인증 오류가 납니다
- 신청 직후 1시간 정도는 키가 활성화되지 않을 수 있습니다

### 지역을 바꾸려면

`config/triggers.json`의 `region`만 고치면 됩니다.

| 항목 | 서울 값 | 설명 |
|---|---|---|
| `asos_stn` | 108 | ASOS 지점번호 |
| `mid_temp_regId` | 11B10101 | 중기기온 구역코드 |
| `nx` / `ny` | 60 / 127 | 동네예보 격자 |

---

## 3. 동작 확인

```bash
python scripts/fetch_datalab.py   # data/datalab.json 생성
python scripts/fetch_weather.py   # data/weather.json 생성
python scripts/judge.py           # 브리핑 출력
```

`fetch_weather.py`는 세 소스 중 일부만 실패해도 계속 진행하고
실패 내역을 `failures`에 남깁니다. 브리핑 맨 아래에 경고로 뜨니
그게 보이면 해당 API 신청 상태를 확인하세요.

---

## 알려진 제약

이 스크립트들은 **실제 API 응답으로 검증되지 않았습니다.** 개발 환경에서
naver.com과 data.go.kr에 접근할 수 없었기 때문입니다. 판정 로직은
합성 데이터로 검증했지만, 응답 필드명이나 파라미터가 실제와 다를 수
있습니다. 첫 실행 때 오류가 나면 그 지점만 고치면 됩니다.

---

## 4. Cowork에서 네이버가 `hostname_blocked`일 때

`Network access = All domains`여도 Anthropic egress proxy가 `*.naver.com`을
상위 정책에서 막으면 직접 API 호출은 실패할 수 있습니다. 이 경우 키를
재발급하지 말고 `references/github_sync.md` 방식으로 GitHub Actions에 수집을
맡기세요.

Cowork 프로젝트의 키 파일에는 아래 선택값을 추가할 수 있습니다.

```text
PANKI_SEARCH_CSV_URL=https://raw.githubusercontent.com/USERNAME/REPO/main/data/search_daily.csv
PANKI_GITHUB_TOKEN=        # 공개 repo면 불필요
```

`fetch_datalab.py`는 직접 API가 실패하면 이 CSV를 받아
`data/search_daily.csv`로 저장합니다.
