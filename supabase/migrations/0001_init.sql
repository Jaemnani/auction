-- ============================================================================
-- auction — 법원경매 정보 1차 스키마
-- 대상: Supabase (PostgreSQL 15+ / PostGIS)
-- 설계 원칙
--   * 자연키(법원코드+사건번호 등)는 UNIQUE로 보존, PK는 UUID
--   * 응답 raw는 jsonb로 함께 보존 (사이트 변경 시 reparse 가능)
--   * 1차안은 핵심 테이블 + jsonb. 정규화는 데이터 패턴 굳어진 뒤 2차 마이그레이션
--   * RLS는 일단 비활성 (서비스 키 전용). anon 공개 시 read-only 정책 별도 추가
-- ============================================================================

create extension if not exists "uuid-ossp";
create extension if not exists "postgis";

-- 공용 타임스탬프 트리거
create or replace function set_updated_at() returns trigger
language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end $$;

-- ============================================================================
-- 1. 마스터 코드
-- ============================================================================

create table courts (
  code            text primary key,                           -- 예 B000210, O000210
  prefix          char(1) not null check (prefix in ('B','O')),
  name            text    not null,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create trigger trg_courts_updated_at before update on courts
  for each row execute function set_updated_at();

create table regions_sd (                                     -- 시·도
  code            text primary key,                           -- 예 11
  name            text not null,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create trigger trg_regions_sd_updated_at before update on regions_sd
  for each row execute function set_updated_at();

create table regions_sgg (                                    -- 시·군·구
  code            text primary key,                           -- 예 11680
  sd_code         text not null references regions_sd(code) on delete cascade,
  name            text not null,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index regions_sgg_sd_idx on regions_sgg(sd_code);
create trigger trg_regions_sgg_updated_at before update on regions_sgg
  for each row execute function set_updated_at();

create table regions_emd (                                    -- 읍·면·동 (옵션 시드)
  code            text primary key,
  sgg_code        text not null references regions_sgg(code) on delete cascade,
  sd_code         text not null references regions_sd(code) on delete cascade,
  name            text not null,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index regions_emd_sgg_idx on regions_emd(sgg_code);
create trigger trg_regions_emd_updated_at before update on regions_emd
  for each row execute function set_updated_at();

create table usage_codes (                                    -- 용도 분류 (대/중/소)
  code            text primary key,
  level           smallint not null check (level in (1,2,3)),  -- 1=lcl, 2=mcl, 3=scl
  parent_code     text references usage_codes(code) on delete cascade,
  name            text not null,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create index usage_codes_parent_idx on usage_codes(parent_code);
create trigger trg_usage_codes_updated_at before update on usage_codes
  for each row execute function set_updated_at();

-- ============================================================================
-- 2. 사건 / 물건
-- ============================================================================

create table cases (
  id                  uuid primary key default uuid_generate_v4(),
  court_code          text not null references courts(code),
  case_no             text not null,                          -- srnSaNo, 예 "2023타경6292"
  sa_no               text,                                    -- saNo (내부키)
  case_name           text,                                    -- 부동산강제경매 등
  jdbn_cd             text,                                    -- 경매계 코드
  jdbn_name           text,                                    -- 경매계 이름
  claim_amount        numeric(20,0),
  receipt_date        date,
  command_date        date,
  progress_status_cd  text,
  suspension_cd       text,
  tel                 text,
  is_real_estate      boolean,                                 -- mvprpRletDvsCd=00031R
  base_info           jsonb,                                   -- csBaseInfo 통째 보존
  first_seen_at       timestamptz not null default now(),
  last_synced_at      timestamptz not null default now(),
  deleted_at          timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (court_code, case_no)
);
create index cases_progress_status_idx on cases(progress_status_cd);
create index cases_receipt_date_idx on cases(receipt_date);
create trigger trg_cases_updated_at before update on cases
  for each row execute function set_updated_at();

create table properties (                                     -- 매물(매각물건)
  id                  uuid primary key default uuid_generate_v4(),
  case_id             uuid not null references cases(id) on delete cascade,
  docid               text,                                    -- 시스템 유니크 (B0002102023...)
  maemul_ser          smallint not null,                       -- 매물순번
  mokmul_ser          smallint,                                -- 목적물순번
  appraisal_amount    numeric(20,0),                           -- 감정가
  min_sale_price      numeric(20,0),                           -- 최저매각가
  current_sale_price  numeric(20,0),                           -- 진행회차 매각가
  fail_count          smallint,                                -- 유찰횟수
  sale_date           date,                                    -- 매각기일
  sale_decision_date  date,                                    -- 매각결정기일
  status_cd           text,
  -- 용도 (lclsUtilCd 등)
  usage_lcl_cd        text,
  usage_mcl_cd        text,
  usage_scl_cd        text,
  -- 대표 주소
  sd_code             text,
  sgg_code            text,
  emd_code            text,
  rd_code             text,
  lot_no              text,
  conv_addr           text,                                    -- 표시용 주소 (convAddr)
  building_summary    text,                                    -- buldList 요약
  area_summary        text,                                    -- areaList 요약
  -- 좌표
  longitude           double precision,
  latitude            double precision,
  location            geography(point, 4326) generated always as (
    case
      when longitude is not null and latitude is not null
        then st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    end
  ) stored,
  -- raw
  search_row          jsonb,                                   -- 검색결과 row 통째 보존
  detail_result       jsonb,                                   -- detail dma_result 통째 보존
  detail_synced_at    timestamptz,
  first_seen_at       timestamptz not null default now(),
  last_synced_at      timestamptz not null default now(),
  deleted_at          timestamptz,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (case_id, maemul_ser)
);
create unique index properties_docid_idx on properties(docid) where docid is not null;
create index properties_sale_date_idx on properties(sale_date);
create index properties_usage_lcl_idx on properties(usage_lcl_cd);
create index properties_sd_sgg_idx on properties(sd_code, sgg_code);
create index properties_min_sale_price_idx on properties(min_sale_price);
create index properties_fail_count_idx on properties(fail_count);
create index properties_location_gist on properties using gist(location);
create trigger trg_properties_updated_at before update on properties
  for each row execute function set_updated_at();

-- 매각기일 이력 (자주 갱신, 회차별 분리 저장)
create table property_sale_dates (
  id                  uuid primary key default uuid_generate_v4(),
  property_id         uuid not null references properties(id) on delete cascade,
  seq                 smallint not null,                       -- 회차 순번
  sale_date           date,
  hour                text,                                    -- HHMM
  place               text,
  min_price           numeric(20,0),
  result_cd           text,                                    -- 매각/유찰/연기 등
  raw                 jsonb,
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),
  unique (property_id, seq)
);
create index property_sale_dates_pid_idx on property_sale_dates(property_id);
create trigger trg_property_sale_dates_updated_at before update on property_sale_dates
  for each row execute function set_updated_at();

-- 사진
create table property_photos (
  id                  uuid primary key default uuid_generate_v4(),
  property_id         uuid not null references properties(id) on delete cascade,
  seq                 smallint not null,
  photo_kind_cd       text,                                    -- cortAuctnPicDvsCd
  photo_kind_name     text,
  description         text,
  origin_cd           text,
  storage_path        text,                                    -- supabase storage 경로 (다운로드 후 채움)
  raw                 jsonb,
  created_at          timestamptz not null default now(),
  unique (property_id, seq)
);
create index property_photos_pid_idx on property_photos(property_id);

-- ============================================================================
-- 3. 운영 / 원본 보존
-- ============================================================================

create table raw_responses (
  id              bigserial primary key,
  endpoint        text    not null,                            -- 예 /pgj/pgjsearch/searchControllerMain.on
  payload         jsonb   not null,
  status          int,
  body            jsonb,
  bytes           int,
  fetched_at      timestamptz not null default now(),
  -- 사건/물건과 연결 (옵션)
  case_id         uuid references cases(id) on delete set null,
  property_id     uuid references properties(id) on delete set null
);
create index raw_responses_endpoint_idx on raw_responses(endpoint);
create index raw_responses_fetched_at_idx on raw_responses(fetched_at desc);
create index raw_responses_payload_gin on raw_responses using gin(payload);

create table crawl_runs (
  id              uuid primary key default uuid_generate_v4(),
  job_type        text not null,                                -- masters / search / detail
  params          jsonb,
  status          text not null check (status in ('running','done','failed')),
  totals          jsonb,                                        -- {pages, rows, errors, ...}
  started_at      timestamptz not null default now(),
  finished_at     timestamptz,
  error           text
);
create index crawl_runs_started_idx on crawl_runs(started_at desc);

create table dead_letters (
  id              bigserial primary key,
  endpoint        text not null,
  payload         jsonb not null,
  status          int,
  body            jsonb,
  note            text,
  occurred_at     timestamptz not null default now(),
  resolved_at     timestamptz
);
create index dead_letters_endpoint_idx on dead_letters(endpoint);
create index dead_letters_occurred_idx on dead_letters(occurred_at desc);

-- ============================================================================
-- 4. 권리분석 (자리만 — 2차 마이그레이션에서 채움)
-- ============================================================================
-- create table property_specifications (...)  -- 매각물건명세서
-- create table property_tenants (...)          -- 임차인
-- create table property_rights (...)           -- 등기 권리관계
-- create table property_risk_flags (...)       -- 자동 권리분석 결과
