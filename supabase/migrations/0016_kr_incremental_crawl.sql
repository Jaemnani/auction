-- ============================================================================
-- 0016 — KR 증분 크롤 지원 컬럼 + 가격이력 테이블
-- 목적: 매 실행 전체 blind overwrite → 변경분만 갱신, 미변경은 cheap liveness만.
--       재경매 등 변경 시 detail 재수집 표시. 가격/유찰/기일/상태 전이 이력 보존.
--       (JP jp_valuation_history 패턴을 KR에 적용.)
-- 적용(시놀로지): docker exec -i auction-db psql -U postgres -d postgres < 0016_*.sql
-- DDL이므로 NAS에서 실행. RLS 정책 변경은 PostgREST 캐시와 무관(즉시).
-- ============================================================================

-- 1) liveness 타임스탬프 — 검색에 노출된 모든 행에 cheap 갱신.
--    close-aged가 이 컬럼으로 판정(미변경 행은 last_synced_at은 안 건드리므로 분리 필요).
--    기존 행은 last_synced_at에서 백필(첫 close-aged가 오삭제 안 하도록).
alter table properties add column if not exists last_seen_at timestamptz;
update properties set last_seen_at = last_synced_at where last_seen_at is null;

-- 2) detail 재수집 요청 시각 — 재경매/상태변경 감지 시 set, 재수집 성공 시 clear.
--    타임스탬프(불리언 X) → 오래된 stale 우선 처리 가능.
alter table properties add column if not exists detail_refresh_requested_at timestamptz;

-- 인덱스
create index if not exists properties_last_seen_idx
  on properties (last_seen_at) where deleted_at is null;
create index if not exists properties_detail_refresh_idx
  on properties (detail_refresh_requested_at)
  where detail_refresh_requested_at is not null;

-- 3) 가격/진행 이력 — 검색 재스캔에서 변경 감지 시 1행 insert.
create table if not exists kr_valuation_history (
  id                  uuid primary key default uuid_generate_v4(),
  property_id         uuid not null references properties(id) on delete cascade,
  observed_at         date not null default ((now() at time zone 'utc')::date),
  appraisal_amount    numeric(20,0),
  min_sale_price      numeric(20,0),
  current_sale_price  numeric(20,0),
  fail_count          smallint,
  sale_date           date,
  sale_decision_date  date,
  status_cd           text,
  reason              text,
  raw                 jsonb,                 -- {"prev":{...},"new":{...},"changed":[...]}
  created_at          timestamptz not null default now()
);
create index if not exists kr_valuation_history_prop_idx
  on kr_valuation_history(property_id);

-- RLS public read (jp_valuation_history와 동일 패턴; deleted 매물 이력은 부모 cascade로 제거됨)
alter table kr_valuation_history enable row level security;
drop policy if exists "public read" on kr_valuation_history;
create policy "public read" on kr_valuation_history
  for select to anon, authenticated using (true);

-- ★ 새 컬럼/테이블을 PostgREST가 write 스키마에 반영하도록 캐시 리로드.
--   (안 하면 last_seen_at write가 PGRST204 'column not in schema cache'로 실패 →
--    증분 크롤이 깨짐. 컬럼 추가 시 반드시 필요.)
notify pgrst, 'reload schema';
