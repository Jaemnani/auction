# 일본 확장을 위한 DB 스키마 설계 검토

> 한국 매물(`properties`)과 일본 매물의 차이를 어떻게 DB에 담을지 결정. 마이그레이션 실행 전 결정 문서.

## 옵션 비교

### A. 단일 테이블 + `country_code` 컬럼 (generalize)

```sql
alter table properties add column country_code text not null default 'KR';
-- 신규 일본 매물도 같은 properties 테이블, country_code='JP'로 구분
```

**장점**
- web/queries.ts 한 군데서 처리. 필터에 `country` 추가하면 끝
- 사이드 인덱스(좌표·용도·가격) 그대로 재사용
- shadow 트래픽으로 점진 도입 쉬움

**단점**
- 한·일 필드 다름 — 일본은 `sale_standard_price`, `purchase_possible_price` 추가 필요
- 한국 row엔 항상 NULL인 컬럼이 늘어남 → 스키마 sparse
- 사건번호 포맷·법원 코드 체계 완전히 달라 자연키(`court_code`, `case_no`) 충돌 위험. court_code prefix로 회피 가능 (`JP_TKY_001` 등)
- detail_result jsonb 구조도 다름 (csBaseInfo/dspslGdsDxdyInfo는 한국 전용)

### B. 테이블 분리 (`jp_properties` 별도)

```sql
create table jp_properties (
  id uuid primary key default uuid_generate_v4(),
  bit_id text unique,                       -- BIT 시스템 docid
  court_code text references jp_courts(code),
  case_no text,                             -- 令和○○年(ケ)○○号
  appraisal_value numeric(20,0),            -- 鑑定評価額
  sale_standard_price numeric(20,0),        -- 売却基準価額
  purchase_possible_price numeric(20,0),    -- 買受可能価額 (= 매각기준 × 80%)
  ...
);
create table jp_cases (...);
create table jp_sale_dates (...);
-- etc.
```

**장점**
- 일본 특유 필드(3종 가격, 4단계 상태머신, 평가 변경 이력)를 깔끔하게 모델링
- 한국 코드/마이그레이션 영향 0 — 위험 없음
- 일본 검색·통계 쿼리 최적화 별도

**단점**
- 코드 중복 — store.py/queries.ts 거의 똑같은 거 두 벌
- 두 코드베이스 동기화 부담 (한국 fix 적용 시 일본도 같이)

### C. 하이브리드 — 공통 추상 + 국가별 확장 (relational inheritance)

```sql
-- 공통 (PK + 국가 식별 + 좌표 + 사진 등 공통 필드만)
create table real_properties (
  id uuid primary key,
  country_code text not null,
  longitude double precision,
  latitude double precision,
  road_addr text,
  ...
);
-- 국가별 디테일 (1:1 link)
create table kr_property_detail (
  property_id uuid primary key references real_properties(id),
  appraisal_amount numeric(20,0),
  min_sale_price numeric(20,0),
  ...
);
create table jp_property_detail (
  property_id uuid primary key references real_properties(id),
  sale_standard_price numeric(20,0),
  purchase_possible_price numeric(20,0),
  ...
);
```

**장점**
- 좌표·사진·주소처럼 공통적인 건 하나로 관리
- 국가별 차이는 별도 테이블로 격리

**단점**
- JOIN 비용 추가 — 모든 detail 조회가 2-table join
- ORM/PostgREST 사용 복잡도 ↑
- 마이그레이션 한 번에 큼

---

## 추천: **A → B의 하이브리드 (단계적)**

**Phase 1 (지금)**: 일본 데이터 수집 시작 시점에는 **B (별도 테이블 `jp_*`)** — 한국에 영향 0, 안전한 시작.

**Phase 2 (충분히 안정화된 후)**: 공통 부분이 명확해지면 **C (real_properties + 국가별 detail)** 로 점진적 마이그레이션.

이유:
- 지금 한국 데이터(~20k 매물, ~80k 매각기일)는 운영 중. A로 가면 마이그레이션 위험
- 일본 BIT 정찰이 안 끝나서 어떤 필드가 중요한지 미정. B로 시작하면 일본 측 자유롭게 실험 가능
- "공통 부분"의 경계는 일본 데이터 한 달 정도 운영해보고 결정해야 명확해짐

---

## Phase 1 — 일본 전용 테이블 스케치

```sql
-- supabase/migrations/0009_jp_init.sql (예정)

-- 일본 법원 마스터
create table jp_courts (
  code text primary key,                       -- 예: TKY (도쿄지방법원)
  name text not null,                          -- 東京地方裁判所
  prefecture_code text,                        -- JIS 도도부현 코드
  raw jsonb
);

create table jp_cases (
  id uuid primary key default uuid_generate_v4(),
  court_code text not null references jp_courts(code),
  case_no text not null,                       -- 令和○○年(ケ)○○号
  case_kind text,                              -- ケ=임의경매 / ヌ=강제경매
  base_info jsonb,
  ...
  unique(court_code, case_no)
);

create table jp_properties (
  id uuid primary key default uuid_generate_v4(),
  case_id uuid not null references jp_cases(id) on delete cascade,
  bit_docid text unique,                       -- BIT 시스템 유니크 ID
  property_seq smallint,
  -- 일본 3종 가격
  appraisal_value numeric(20,0),               -- 鑑定評価額
  sale_standard_price numeric(20,0),           -- 売却基準価額
  purchase_possible_price numeric(20,0),       -- 買受可能価額
  -- 4단계 상태머신
  status text check (status in
    ('period_bid', 'special_sale', 'reval_pending', 're_bid', 'closed', 'aborted')),
  fail_count smallint,                         -- 미낙찰 횟수 (자동 차감 없음)
  bid_period_start date,
  bid_period_end date,
  sale_decision_date date,
  -- 주소·좌표 (일본 측지계 JGD2011 → WGS84 변환)
  prefecture_code text,                        -- 都道府県
  city_code text,                              -- 市区町村
  road_addr text,
  longitude double precision,                  -- WGS84
  latitude double precision,
  -- 일본 특화 플래그
  yen_10k_trap boolean default false,          -- 1만엔 함정 의심
  has_special_rights boolean default false,    -- 유치권·법정지상권 등
  -- raw + 추적
  search_row jsonb,
  detail_result jsonb,
  fetched_at timestamptz default now(),
  ...
);

-- 평가 재조정 이력 (일본 특유 — 자동 차감 없는 대신 평가 변경 추적)
create table jp_valuation_history (
  id uuid primary key default uuid_generate_v4(),
  property_id uuid references jp_properties(id) on delete cascade,
  valued_at date,
  appraisal_value numeric(20,0),
  sale_standard_price numeric(20,0),
  reason text,
  raw jsonb
);

-- 매각기일 이력
create table jp_sale_dates (
  id uuid primary key default uuid_generate_v4(),
  property_id uuid references jp_properties(id) on delete cascade,
  seq smallint,
  bid_period_start date,
  bid_period_end date,
  result_cd text,                               -- 매각/미낙찰/특별매각 등
  sale_amount numeric(20,0),
  bidder_count smallint,
  raw jsonb,
  unique(property_id, seq)
);

-- 사진은 한국과 동일 패턴 — 별도 storage 버킷 jp-auction-photos
create table jp_property_photos (
  id uuid primary key default uuid_generate_v4(),
  property_id uuid references jp_properties(id) on delete cascade,
  seq smallint,
  storage_path text,
  kind text,
  description text,
  raw jsonb,
  unique(property_id, seq)
);

-- RLS — anon read
alter table jp_courts enable row level security;
alter table jp_cases enable row level security;
alter table jp_properties enable row level security;
alter table jp_valuation_history enable row level security;
alter table jp_sale_dates enable row level security;
alter table jp_property_photos enable row level security;

create policy "public read" on jp_courts for select to anon, authenticated using (true);
create policy "public read" on jp_cases for select to anon, authenticated using (true);
create policy "public read" on jp_properties for select to anon, authenticated using (true);
create policy "public read" on jp_valuation_history for select to anon, authenticated using (true);
create policy "public read" on jp_sale_dates for select to anon, authenticated using (true);
create policy "public read" on jp_property_photos for select to anon, authenticated using (true);

-- 인덱스
create index jp_properties_status_idx on jp_properties(status);
create index jp_properties_pref_city_idx on jp_properties(prefecture_code, city_code);
create index jp_properties_price_idx on jp_properties(sale_standard_price);
create index jp_properties_location_gist on jp_properties using gist(
  st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
);
```

---

## 한국 코드 재사용 전략

`crawler/src/courtauction/` 와 `crawler/src/bit/` 분리:

```
crawler/src/
├── courtauction/         # 한국 (현행)
│   ├── client.py
│   ├── store.py
│   └── ...
├── bit/                  # 일본 (신규)
│   ├── client.py         # BIT API 전용
│   ├── store.py          # jp_* 테이블 upsert
│   └── parser.py         # 사건번호·주소 일본식 파싱
└── common/               # 공통 (옵션)
    └── kakao.py          # Geocoding 등
```

ingest CLI:
```bash
# 한국 (현행)
python crawler/scripts/ingest.py search ...

# 일본 (신규)
python crawler/scripts/jp_ingest.py search ...
```

같은 패턴 (search → backfill-details → photos → ...) 유지. 외형은 똑같고 내부 client/store만 일본용으로.

---

## 미결정 사항

- **BIT API 형식**: WebSquare RIA 아닐 가능성 → 정찰 후 결정
- **좌표 체계**: BIT가 어떤 좌표 주는지 — JGD2011일 가능성 (KATEC와 다른 EPSG:6668)
- **사진 base64 vs URL**: BIT가 한국처럼 base64 통째로 줄지, URL만 줄지
- **삼점세트 PDF**: 직접 다운로드 가능 여부 (한국은 있음, 일본은 마스킹 때문에 다를 수도)
- **스토리지 분리**: `jp-auction-photos` 별도 버킷 vs 기존 `auction-photos` 안에 prefix

---

*Last updated: 2026-05-06*
