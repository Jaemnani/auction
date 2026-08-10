-- 0027: 일본 매각결과(売却結果) — 낙찰가·개찰결과.
--
-- 배경: BIT 의 매물 검색 피드(競売物件 탭)에는 낙찰가가 없다. 낙찰 결과는
-- 별도 「売却結果」 섹션에만 있어 그동안 일본은 낙찰가 자체를 못 가져왔다.
--   수집: crawler/src/bit/result.py, docs/bit_sale_result_recon.md
--
-- ⚠ 조회 가능한 開札期日가 법원당 최근 4회분뿐이라 **과거 소급이 불가능**하다.
--    일일 크론으로 지금부터 쌓아야 하고, 놓친 회차는 영구 손실이다.
--
-- 매물(jp_properties) 연결은 (court_code, case_no) → jp_cases 조인.
-- 物件番号가 복수("1,2")인 행이 많아 사건 단위가 1차 매칭 단위다.

create table if not exists jp_sale_results (
  id                   uuid primary key default uuid_generate_v4(),

  court_code           text not null references jp_courts(code) on delete restrict,
  case_no              text not null,          -- 令和08年(ケ)第48号
  property_no          text not null default '',  -- '1,2' (전각 쉼표 반각 정규화)
  open_bid_date        date,                   -- 開札期日 (期間入札) / 売却期間 종료일
  -- 期間入札(period) / 特別売却(special) — 같은 사건이 양쪽에 나올 수 있다
  sale_type            text not null default 'period'
                         check (sale_type in ('period', 'special')),

  sale_cls_label       text,                   -- 土地 / 戸建て / マンション / その他
  -- 落札価格. 開札結果가 売却일 때만 값이 있고 不売·取下면 NULL.
  -- ⚠ 0 과 NULL 은 다르다 — NULL 은 "낙찰 안 됨", 0 은 존재하지 않는 값.
  sale_price           numeric(20,0),
  sale_standard_price  numeric(20,0),          -- 売却基準価額 (낙찰가/기준가 비율용)
  address_text         text,

  result_cls           text,                   -- 売却 / 不売 / 取下 / …
  bidder_count         int,                    -- 入札者数(人) — 경쟁 강도
  winner_kind          text,                   -- 落札者資格: 法人 / 個人

  raw                  jsonb,
  fetched_at           timestamptz not null default now(),
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now(),

  -- 같은 법원·사건·물건번호·개찰기일·구분이면 같은 결과 (재수집 시 멱등 upsert)
  unique (court_code, case_no, property_no, open_bid_date, sale_type)
);

create trigger trg_jp_sale_results_updated_at before update on jp_sale_results
  for each row execute function set_updated_at();

comment on column jp_sale_results.sale_price is
  '売却価額(낙찰가). 開札結果=売却 일 때만. 不売·取下 는 NULL';
comment on column jp_sale_results.property_no is
  '物件番号. 복수면 "1,2" — 사건 단위 결과라 매물 1:1 이 아닐 수 있음';

-- 사건 단위 조인 (jp_cases.court_code + case_no)
create index if not exists jp_sale_results_case_idx
  on jp_sale_results (court_code, case_no);
-- 최근 낙찰 목록 — 낙찰된 것만 최신순
create index if not exists jp_sale_results_sold_idx
  on jp_sale_results (open_bid_date desc)
  where sale_price is not null;

alter table jp_sale_results enable row level security;
do $$ begin
  drop policy if exists "public read" on jp_sale_results;
  create policy "public read" on jp_sale_results
    for select to anon, authenticated using (true);
end $$;

notify pgrst, 'reload schema';
