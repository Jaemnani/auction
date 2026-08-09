-- 0026: 매각물건명세서에서 추출한 임차·권리 사실 (인수액 판정 근거).
--
-- 배경: 인수액(대항력 임차인 보증금 중 낙찰자 부담분) 판정에 필요한
-- 전입신고일·확정일자·보증금·배당요구는 법원 API 가 제공하지 않고
-- **매각물건명세서에만** 있다. 명세서는 매각기일 1주 전부터 공개되며,
-- StreamDocs 뷰어에서 좌표 텍스트로 추출한다.
--   수집·파싱: crawler/src/spec_sheet/parse.py, docs/spec_sheet_automation.md
--
-- ⚠ 이 테이블은 **사실만** 담는다. 인수액 금액 계산은 web 의 assumption.ts
--    simulate() 가 담당한다 (이미 검산 완료 — 두 벌로 나뉘면 어긋난다).

create table if not exists property_tenancy (
  property_id       uuid primary key references properties(id) on delete cascade,

  -- 최선순위 설정 = 말소기준권리. 대항력 판정의 기준일.
  lien_date         date,
  lien_kind         text,           -- 근저당/가압류/전세권 등
  demand_deadline   date,           -- 배당요구종기

  -- 임차인 배열 — [{name, deposit, move_in_dates[], other_dates[], raw}]
  -- move_in_dates 만 대항력 판정에 쓴다 (임대차기간은 법적으로 무관).
  tenants           jsonb not null default '[]'::jsonb,
  has_tenant_block  boolean not null default false,

  -- 판정: none(인수 없음) / risk(인수 가능) / unknown(판단 불가)
  -- ⚠ unknown 을 none 으로 뭉개지 말 것 — 사용자가 인수액 0 으로 믿고 입찰한다.
  verdict           text not null default 'unknown'
                      check (verdict in ('none', 'risk', 'unknown')),
  confidence        text not null default 'low'
                      check (confidence in ('high', 'low')),
  notes             jsonb not null default '[]'::jsonb,

  -- 원문 — 추출이 틀렸을 때 사람이 대조할 수 있어야 한다
  raw_text          text,
  -- 명세서 뷰어 직행 링크용 (encParam 은 만료 가능 → 재발급 필요할 수 있음)
  viewer_url        text,

  spec_written_ymd  date,           -- 명세서 작성일 (gdsSpcfcWrtYmd)
  fetched_at        timestamptz not null default now(),
  created_at        timestamptz not null default now()
);

comment on table property_tenancy is
  '매각물건명세서 추출 사실 — 인수액 판정 근거. 금액 계산은 web assumption.ts 담당';
comment on column property_tenancy.verdict is
  'none=인수 없음 / risk=인수 가능 / unknown=판단 불가. unknown 을 none 으로 취급 금지';
comment on column property_tenancy.tenants is
  '[{name, deposit, move_in_dates[], other_dates[], raw}] — move_in_dates 만 대항력 판정에 사용';

-- 재수집 대상 선별 (오래된 것부터) + 판정별 집계
create index if not exists property_tenancy_fetched_idx
  on property_tenancy (fetched_at);
create index if not exists property_tenancy_verdict_idx
  on property_tenancy (verdict);

alter table property_tenancy enable row level security;
do $$ begin
  drop policy if exists "public read" on property_tenancy;
  create policy "public read" on property_tenancy
    for select to anon, authenticated using (true);
end $$;

notify pgrst, 'reload schema';
