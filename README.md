# 법원경매 검색 — auction

> 🔗 **Live demo: https://auction-seven-omega.vercel.app**
> _법원경매정보(courtauction.go.kr)의 공고중 매물을 무료로 빠르게 검색·분석할 수 있는 사이트입니다._

[![Deployed on Vercel](https://img.shields.io/badge/Vercel-deployed-black?logo=vercel)](https://auction-seven-omega.vercel.app)

## Tagline-ko
법원경매정보(courtauction.go.kr)의 공고중 매물을 무료로 검색·필터링·권리분석. 지도·인근 실거래가·위험 배지까지 한 화면에.

## Tagline-en
Free, filterable Korean court auction search — map view, nearby comps, and 25 auto risk flags. No fee-gated APIs.

## Tagline-ja
韓国の法院競売情報(courtauction.go.kr)を無料で検索・絞り込み・権利分析。地図、周辺取引事例、リスクバッジを一画面で確認できます。

## 프로젝트 개요
유료 사이트들이 잠가둔 공공 데이터(법원경매정보)를 다시 무료로 돌려놓는 프로젝트입니다.

- 매일 새벽 자동 크롤링으로 전국 **약 17,000건의 공고중 매물**을 유지
- 빠른 필터·정렬 + **인터랙티브 지도** + 사진 그리드 + 매각기일 이력 + 감정평가 요항
- **위험 키워드 25종 자동 추출** — 유치권 / 법정지상권 / 선순위 임차인 / 위반건축물 / 맹지 / 농지 / 분묘기지권 / 지분매각 등
- **인근 실거래가** (국토교통부 9종 OpenAPI) + 인근 낙찰 통계
- **등기부등본·감정평가서 등 건당 수수료가 발생하는 API는 일체 사용하지 않음** — 무료 운영
- **㎡ ↔ 평** 단위 토글, courtauction·네이버지도·카카오맵·구글맵 딥링크
- 같은 코드베이스로 일본 BIT(`bit.courts.go.jp`) 매물 지원 준비 중 — 헤더 [한국 | 日本] 토글 이미 배포

스택: Python 크롤러(httpx async) → Supabase(PostgreSQL + PostGIS + Storage) → Next.js 16(App Router) on Vercel. 지도 타일은 OpenFreeMap, 외부 시세는 data.go.kr / Kakao Local (서버 라우트로 키 가림).

## Summary-en
A free, fast search experience for Korea's official court auction listings (courtauction.go.kr) — the kind of data that paid sites have kept behind paywalls.

- About **17,000 active listings** refreshed daily by an automated crawler
- Filters, sorting, **interactive map**, photo gallery, sale-date history, appraisal summaries
- **25 auto-extracted risk flags** — liens, statutory ground rights, senior tenants, illegal buildings, landlocked plots, farmland, share sales, and more
- **Nearby comparable sales** via 9 government real-estate APIs (MOLIT) + nearby auction-result stats
- **No fee-gated APIs** (e.g., per-query property registries) — the service stays free
- Stack: Python crawler (httpx async) → Supabase (PostgreSQL + PostGIS + Storage) → Next.js 16 on Vercel. Map tiles from OpenFreeMap; market data proxied server-side
- Japan support (BIT `bit.courts.go.jp`) coming next on the same codebase — header toggle [한국 | 日本] already live

## Summary-ja
韓国の法院競売情報(courtauction.go.kr)を無料で素早く検索できるサイト。有料サイトが囲い込んでいた公共データを再び公共に開放します。

- 公告中の物件 約 **17,000件**を毎日自動クロールで更新
- 絞り込み・並び替え・**インタラクティブ地図**・写真ギャラリー・売却期日履歴・鑑定評価要項
- **危険キーワード25種を自動抽出** — 留置権・法定地上権・先順位賃借人・違反建築物・盲地・農地・持分売却 など
- **周辺取引事例**(国土交通部 9種 公開API)+ 周辺落札統計
- **有料API(登記簿等)は一切不使用** — 無料運営
- スタック: Python クローラー(httpx async)→ Supabase(PostgreSQL + PostGIS + Storage)→ Next.js 16 on Vercel。地図タイルは OpenFreeMap、外部時価データはサーバールートで proxy
- 同じコードベースで日本 BIT(`bit.courts.go.jp`) 対応を準備中 — ヘッダー [한국 | 日本] トグルは既に公開済み

---

## 무엇을 할 수 있나

- 전국 ~17,000건 공고중 매물을 **즉시 필터·정렬**로 탐색
  - 법원 / 시·도 / 시·군·구 / 용도(대·중) / 감정가·최저가·매각가율 범위 / 유찰횟수 / 매각기일 / 미래 기일 토글 / 도로명 보유 여부
  - 키워드(주소·사건번호) 자유검색
- **인터랙티브 지도** — 매물 위치를 빨간 핀으로. pan/zoom 시 "이 지역에서 검색" / 자동 새로고침 토글
- **상세 페이지** — 사진 그리드(라이트박스) + 매각기일 이력 + 감정평가 요항 + 인근 실거래가(국토부 OpenAPI 9종) + 인근 낙찰 통계
- **권리분석 자동 추출** — 위험 키워드 배지(유치권/법정지상권/공실/위반건축물 등), 말소기준권리 후보, 청구금액, 매수신청 보증금률, 사건 진행상태
- **㎡ ↔ 평** 면적 단위 토글 (전역, localStorage 저장)
- **공식 사이트 딥링크** — courtauction.go.kr / 네이버지도 / 카카오맵 / 구글맵 한 번에 열기
- 매일 새벽 4시 자동 갱신 (cron)

## 스크린·동선 한눈에

| 페이지 | 핵심 요소 |
|---|---|
| `/` | 상단 가로 필터 + 썸네일 카드 목록 (D-day 컬러, 유찰/할인 배지) |
| `/map` | MapLibre + OpenFreeMap, viewport bbox 기반 동적 마커 새로고침 |
| `/p/[docid]` | 입찰 전 핵심 정보 카드 → 사진 → 핵심지표 → 물건기본내역 → 매각이력 → 감정평가 → 실거래가 → 낙찰통계 → 위치 미니맵 |

---

## 스택

- **웹**: Next.js 16 (App Router) · TypeScript · Tailwind v4 · shadcn/ui · MapLibre GL
- **폰트**: Barlow (영문) + Pretendard Variable (한글)
- **DB / Storage**: Supabase (PostgreSQL + PostGIS + Object Storage)
- **지도 타일**: OpenFreeMap (무료, 키 0)
- **외부 데이터** (모두 무료):
  - 국토교통부 실거래가 9종 (data.go.kr) — apt / apt_dev / apt_resale / rh / sh / offi / land / nrg / indu
  - Kakao Local API — 좌표→주소 역지오코딩
- **크롤러**: Python 3.12 + httpx async + Pillow (썸네일)
- **호스팅**: Vercel (web), Supabase (DB+Storage), 로컬 Mac (cron 크롤러)

---

## 실행 방법 (개발자용)

### 1. 저장소 + 환경

```bash
git clone https://github.com/Jaemnani/auction.git
cd auction

# Python 의존성 (공용 venv 또는 프로젝트 전용)
PY=/Users/<user>/workspace/venv_common/bin/python
$PY -m pip install httpx beautifulsoup4 lxml python-dotenv supabase Pillow pyproj
```

### 2. 환경변수

루트의 [.env](.env) 와 [web/.env.local](web/.env.local)는 git에 안 올라갑니다. 직접 만드세요.

**`.env` (크롤러용)**
```
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<anon JWT>
SUPABASE_SERVICE_KEY=sb_secret_...     # ingest는 service_role 필수
KAKAO_REST_API_KEY=<32자>              # 역지오코딩
DATA_GO_KR_API_KEY=<URL-encoded key>   # 실거래가 (서버 라우트에서도 사용)
```

**`web/.env.local`**
```
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon JWT>
DATA_GO_KR_API_KEY=<URL-encoded key>   # /api/molit-deals 서버 라우트
KAKAO_REST_API_KEY=<32자>              # 필요시 server-side
```

### 3. DB 마이그레이션

[supabase/migrations/](supabase/migrations/) 의 `0001_init.sql` ~ `0011_kr_risk_flags.sql` 을 순서대로 Supabase Dashboard SQL Editor에 붙여 Run.

요약:
- `0001_init`: 핵심 테이블 (courts, regions, usage_codes, cases, properties, sale_dates, photos, raw_responses, crawl_runs, dead_letters) + PostGIS
- `0002_public_read_policies`: anon read RLS
- `0003_storage`: `auction-photos` 버킷 + 정책
- `0004_address_columns`: `road_addr` / `lot_addr` + pg_trgm 인덱스
- `0005_auction_results`: 매각결과 캐시 + 통계 view
- `0006_fix_sgg_pk`: `regions_sgg` 복합키 PK
- `0007_normalize_sgg_codes`: 같은 이름 중복 sgg 코드 합치기
- `0008_backfill_sale_dates`: 매각기일 이력 백필 보조
- `0009_jp_init`: 일본 BIT 초기 스키마 (한·일 동거)
- `0010_jp_storage`: 일본 매물 사진 storage 버킷 + 정책
- `0011_kr_risk_flags`: `properties.risk_flags text[]` 컬럼 + GIN 인덱스

### 4. 첫 적재 (~6시간, 대부분은 detail 백필)

```bash
PY=/Users/<user>/workspace/venv_common/bin/python

# 마스터 코드 (5초)
$PY crawler/scripts/ingest.py masters

# 전국 매물 search (~12분, 17k+ 매물)
$PY crawler/scripts/ingest.py search --split-sd

# 사건 상세 (~6시간, concurrency=2 + IP 차단 자동 회복)
$PY crawler/scripts/ingest.py backfill-details --limit 20000 --concurrency 2

# 사진 base64 → Supabase Storage (~30분, 매물당 1장 정책)
$PY crawler/scripts/ingest.py backfill-photos --limit 20000

# 썸네일 320×240 생성 (~20분)
$PY crawler/scripts/ingest.py backfill-thumbs --limit 20000

# Kakao 역지오코딩 도로명 보강 (~13분, 14k건)
$PY crawler/scripts/ingest.py reverse-geocode --limit 20000 --concurrency 8

# 좌표 KATEC→WGS84 정규화 (검증, ingest 단계서 자동되긴 함)
$PY crawler/scripts/ingest.py backfill-coords

# 매각결과 (인근 낙찰 통계용, ~3분)
$PY crawler/scripts/ingest.py sales-results
```

### 5. 매일 자동 갱신 (cron)

```bash
# 기본 — 매일 04:00 (시스템 로컬타임)
./crawler/install_cron.sh

# 옵션
SCHEDULE="0 5 * * *" ./crawler/install_cron.sh   # 시간 변경
COURT=B000210 ./crawler/install_cron.sh           # 특정 법원만
PHOTOS_PER_PROPERTY=3 ./crawler/install_cron.sh   # 매물당 사진 N장 (기본 1)

# 상태 / 제거 / 수동 실행
./crawler/install_cron.sh show
./crawler/install_cron.sh uninstall
./crawler/run_daily.sh   # 즉시 1회
```

`run_daily.sh`가 매 실행 시 `.env`를 자동 source 하므로 새 키 추가만 하면 cron 재설치 불필요. 로그는 `crawler/data/logs/daily_*.log` (30일 자동 정리), 동시 실행은 mkdir 락으로 방지.

> ⚠️ macOS는 노트북이 sleep 시 cron 미동작. 항상-켜진 환경(iMac/서버) 권장. Privacy & Security → Full Disk Access에 `cron` 추가가 필요할 수 있음.

### 6. 웹 로컬 실행

```bash
cd web
npm install
npm run dev   # http://localhost:3000
```

---

## 데이터 흐름

```
courtauction.go.kr (JSON API)
       ↓
crawler/ingest.py (Python async)
       ↓
Supabase Postgres ── public read (RLS) ──→ Next.js (Vercel)
       ↓                                         ↓
auction-photos bucket                        MapLibre + 외부 API
                                            (data.go.kr / Kakao Local)
```

- **공고중 매물**: `properties` 테이블 (~17k)
- **종결 매물 (인근 통계용)**: `sale_results` 테이블 (~8k+, 90일 누적)
- **사진**: 원본 + 320×240 썸네일 (Supabase Storage public 버킷)
- **외부 시세·역지오코딩**: 서버 측 Next.js Route 프록시 (키 클라이언트 노출 X)

---

## 아키텍처 노트

- **`detail_result` jsonb는 슬림화** — `csPicLst[].picFile` (base64) 제거하고 텍스트 키만 보존. 17k row × ~500KB 사진 base64 = 8GB+ DB 폭증을 방지
- **list query는 JSON path 미사용** — 17k × ㎡ jsonb 추출은 Postgres 8s timeout 초과. 위험배지·말소기준권리 등은 detail 페이지에서만
- **PostgREST count: "estimated"** — `exact`는 두 번째 풀스캔이라 다중 필터에서 timeout
- **지도 마커 동적 새로고침** — `/api/map/markers?bbox=...` API + `moveend` 이벤트로 viewport 안의 매물만 fetch
- **IP 차단 자동 회복** — courtauction이 `해당 IP는 비정상적인 접속...` 메시지 반환 시 90초 대기 후 재시도
- **search 페이징 안정화** — 시도(17개) split-sd 호출로 페이지 경계 누락 방지
- **KATEC → WGS84 좌표 변환** — courtauction의 `xCordi/yCordi`는 한국 좌표계(EPSG:5181 변형). pyproj로 정확한 WGS84 변환

---

## 정찰 / 발굴 노트

- [docs/api_recon.md](docs/api_recon.md) — courtauction.go.kr API 정찰 (검색·상세·마스터)
- 매각결과검색 endpoint `/pgj/pgjsearch/selectDspslSchdRsltSrch.on` (PGJ158M02 W2X 분석으로 발굴)
- WebSquare RIA 패턴: `dma_*` nested JSON, 인증/세션 불필요, UA + Referer만 권장

## 🇯🇵 일본 확장 로드맵 (Coming Soon)

같은 코드베이스로 일본 BIT(`bit.courts.go.jp`) 매물 지원 예정. 한·일 경매제도가 거의 같은 구조라 *현지화 수준*의 작업으로 가능합니다.

- 분석: [docs/jp_market_analysis.md](docs/jp_market_analysis.md)
- 라이브: 헤더 [한국 | 日本] 토글로 전환 가능. 현재 `/jp`는 비교표·로드맵·BIT 정찰 체크리스트 노출
- 핵심 차이: 자동 유찰 차감 없음 / 三点セット PDF / 1만엔 함정 매물 / 빈집률 결합
- 차별화 후보: 삼점세트 LLM 요약 (한국판보다 가치 ↑), 외국인 투자자 모드, 평가 변경 이력 추적

## 확인된 사실 (2026-05-04 기준)

- courtauction.go.kr: 인증/세션 불필요 JSON API (WebSquare RIA)
- 매물 카운트 = (매물 × 목적물) — 사이트 totalCnt 29,844는 docid 기준, 실제 매물은 ~17,000
- 검색 page_size 상한: 50 (60+ → HTTP 400)
- 마스터: 법원 60(B)+60(O), 시도 17, 시군구 178~193 (사용자 데이터 정규화 후)
- detail 한 호출 = 99컬럼 (csBaseInfo / dspslGdsDxdyInfo / 매각기일 이력 / 사진 / 감정평가요항)

---

## 관련 사이트

- 데이터 출처: https://www.courtauction.go.kr
- 외부 API: https://www.data.go.kr · https://developers.kakao.com
- 지도 타일: https://openfreemap.org

## 라이선스 / 주의

- **라이선스**: [MIT](LICENSE) — 자유로운 사용·수정·배포 (저작권 표시 유지)
- 본 서비스는 **공식 사이트 데이터를 표시하는 보조 도구**입니다. 입찰 전 반드시 **courtauction.go.kr 공식 사이트의 매각물건명세서·현황조사서·감정평가서**를 직접 확인하세요. 자동 추출된 위험 배지·말소기준권리는 보조 정보일 뿐 법적 효력은 없습니다.
