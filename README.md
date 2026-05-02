# auction

법원경매정보(courtauction.go.kr) 무료 검색 서비스.

## 구조

- `crawler/` — Python 크롤러 (로컬 Mac + cron)
  - `src/courtauction/` — httpx async 클라이언트 (retry / rate limit / schema validation / dead-letter)
  - `scripts/seed.py` — 마스터/검색/상세 적재 CLI
  - `scripts/recon.py`, `fetch_w2x.py`, `extract_*.py` — 정찰용 (정찰 완료 후 보존)
  - `data/raw/`, `data/seed/`, `data/dead_letter.jsonl` — 산출물 (gitignore)
- `web/` — Next.js (Vercel)
- `supabase/migrations/` — DB 스키마
- `docs/api_recon.md` — API 정찰 노트 (v2 완성)

## 스택

- 크롤러: Python 3.12 (공용 venv `/Users/jaemoonyeah/workspace/venv_common`) + httpx async
- DB / Storage / Auth: Supabase (PostgreSQL + PostGIS + Storage)
- 웹: Next.js + TypeScript / Vercel
- 외부 데이터: 무료 OpenAPI만 (실거래가/공시지가/VWorld). 수수료 API 일체 미사용

## 다른 Mac에서 이어서 작업하기

```bash
# 1) clone
git clone git@github.com:Jaemnani/auction.git
cd auction

# 2) Python 환경 — 의존성: httpx beautifulsoup4 lxml python-dotenv (정찰용 playwright 옵션)
# (a) 공용 venv 사용 (이 프로젝트 표준 — iMac에 같은 경로 있으면)
PY=/Users/jaemoonyeah/workspace/venv_common/bin/python
$PY -m pip install httpx beautifulsoup4 lxml python-dotenv playwright
$PY -m playwright install chromium  # 정찰 다시 돌릴 때만 필요

# (b) 프로젝트 전용 venv (공용 venv 없으면)
python3 -m venv .venv
source .venv/bin/activate
pip install httpx beautifulsoup4 lxml python-dotenv playwright
playwright install chromium
```

크롤링 데이터(`crawler/data/`)는 git에서 제외됨 — 새 머신에서 `seed.py masters` 한 번 돌리면 재생성.

## 빠른 실행

```bash
PY=/Users/jaemoonyeah/workspace/venv_common/bin/python

# 마스터 코드 적재 (~5초)
$PY crawler/scripts/seed.py masters

# 검색 결과 (서울중앙 1페이지 검증)
$PY crawler/scripts/seed.py search --court B000210 --max-pages 1

# 단일 상세
$PY crawler/scripts/seed.py detail B000210 2023타경6292 1
```

## 검증된 사실 (2026-05-02)

- courtauction.go.kr는 인증/세션 불필요한 JSON API (WebSquare RIA)
- 부동산 공고중 전체 매물 수: **24,915건** (전국)
- 검색 page_size 상한: **50** (60+ → HTTP 400)
- 마스터 코드: 법원 60(B)+60(O), 시도 17, 시군구 179, 용도 대분류 4
- 사건/물건 detail 한 호출에 99컬럼 + 사진/매각기일/건물표제부/감정평가요항 모두 포함
