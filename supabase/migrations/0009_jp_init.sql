-- ============================================================================
-- 0009 — 일본 BIT(bit.courts.go.jp) 데이터 1차 스키마
-- 설계: docs/jp_schema_design.md Phase 1 (옵션 B — jp_* 별도 테이블)
-- 정찰: docs/bit_api_recon.md
-- 한국 schema와 분리: 한·일 간섭 0, 일본 측 자유롭게 실험
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 마스터 — 도도부현 / 법원 / 시구정촌
-- ----------------------------------------------------------------------------

create table jp_prefectures (
  code            text primary key,                           -- JIS 도도부현 (예: 13 東京都, 91-94 北海道지점)
  name            text not null,                              -- 東京都
  block_cls       text not null,                              -- BIT 블록 (01-09)
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create trigger trg_jp_prefectures_updated_at before update on jp_prefectures
  for each row execute function set_updated_at();

create table jp_courts (
  code            text primary key,                           -- BIT courtId 5자리 (예: 31111 東京本庁)
  name            text not null,                              -- 東京地方裁判所本庁
  prefecture_code text references jp_prefectures(code),
  prefix          text,                                       -- 사진 URL prefix (예: TAC=立川)
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);
create trigger trg_jp_courts_updated_at before update on jp_courts
  for each row execute function set_updated_at();

create table jp_municipalities (
  code            text not null,                              -- BIT municipalityId
  prefecture_code text not null references jp_prefectures(code) on delete cascade,
  name            text not null,                              -- 八王子市
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  primary key (prefecture_code, code)
);
create trigger trg_jp_municipalities_updated_at before update on jp_municipalities
  for each row execute function set_updated_at();

-- ----------------------------------------------------------------------------
-- 사건 (cases) — court_code + case_no 자연키
-- ----------------------------------------------------------------------------

create table jp_cases (
  id              uuid primary key default uuid_generate_v4(),
  court_code      text not null references jp_courts(code) on delete restrict,
  case_no         text not null,                              -- 令和07年(ケ)第221号
  case_year       smallint,                                   -- 7 (令和)
  case_era        text check (case_era in ('令和','平成')),
  case_kind       text check (case_kind in ('ケ','ヌ')),       -- 担保 / 強制
  case_kind_no    int,                                        -- 221
  raw             jsonb,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (court_code, case_no)
);
create trigger trg_jp_cases_updated_at before update on jp_cases
  for each row execute function set_updated_at();

create index jp_cases_court_idx on jp_cases(court_code);

-- ----------------------------------------------------------------------------
-- 매물 (properties) — BIT saleUnitId 자연키
-- ----------------------------------------------------------------------------

create table jp_properties (
  id              uuid primary key default uuid_generate_v4(),
  case_id         uuid not null references jp_cases(id) on delete cascade,
  sale_unit_id    text not null unique,                       -- BIT saleUnitId 11자리 (예: 00000021169)
  property_seq    smallint,                                   -- 매물 순번 (1부터)

  -- 종별
  sale_cls        text check (sale_cls in ('1','2','3','4')), -- 1=土地 2=戸建て 3=マンション 4=その他
  sale_cls_label  text,                                       -- '土地'

  -- 일본 3종 가격 (円 단위, 만엔 아님)
  appraisal_value           numeric(20,0),                    -- 鑑定評価額 (상세에서 채워짐)
  sale_standard_price       numeric(20,0),                    -- 売却基準価額 (검색 카드에서)
  purchase_possible_price   numeric(20,0),                    -- 買受可能価額 (= 매각기준 × 80%, 상세)
  bid_deposit               numeric(20,0),                    -- 買受申出保証金

  -- 4단계 상태머신
  status                    text check (status in
    ('period_bid','special_sale','reval_pending','re_bid','closed','aborted')),

  -- 매각기일 (현행)
  bid_view_start            date,                             -- 閲覧開始日
  bid_period_start          date,                             -- 入札期間 시작
  bid_period_end            date,                             -- 入札期間 종료
  open_bid_date             date,                             -- 開札期日
  special_sale_start        date,                             -- 特別売却期間 시작
  special_sale_end          date,                             -- 特別売却期間 종료

  -- 주소·좌표
  prefecture_code           text references jp_prefectures(code),
  municipality_code         text,                             -- jp_municipalities.code
  address_text              text,                             -- 八王子市川町１３番１３ (전각 그대로)
  address_normalized        text,                             -- 八王子市川町13番13 (반각 변환)
  longitude                 double precision,                 -- WGS84 (BIT 응답이 JGD2011일 경우 변환)
  latitude                  double precision,
  location                  geography(point, 4326) generated always as (
    case
      when longitude is not null and latitude is not null
        then st_setsrid(st_makepoint(longitude, latitude), 4326)::geography
    end
  ) stored,
  transit_info              text,                             -- ＪＲ中央線「西八王子」駅 北西方...

  -- 일본 특화 플래그
  yen_10k_trap              boolean default false,            -- 1만엔 함정 의심 (sale_standard_price ≤ 100,000)
  has_special_rights        boolean default false,            -- 유치권·법정지상권 등
  fail_count                smallint default 0,               -- 미낙찰 횟수 (자동 차감 없음)

  -- raw + 추적
  search_row                jsonb,                            -- 검색 카드 HTML/dict
  detail_result             jsonb,                            -- 상세 페이지 dict
  fetched_at                timestamptz default now(),
  created_at                timestamptz not null default now(),
  updated_at                timestamptz not null default now()
);
create trigger trg_jp_properties_updated_at before update on jp_properties
  for each row execute function set_updated_at();

create index jp_properties_status_idx on jp_properties(status);
create index jp_properties_pref_muni_idx on jp_properties(prefecture_code, municipality_code);
create index jp_properties_price_idx on jp_properties(sale_standard_price);
create index jp_properties_case_idx on jp_properties(case_id);
create index jp_properties_location_gist on jp_properties using gist(location);

-- ----------------------------------------------------------------------------
-- 평가 재조정 이력 (일본 특유 — 자동 차감 없는 대신 평가 변경 추적)
-- ----------------------------------------------------------------------------

create table jp_valuation_history (
  id              uuid primary key default uuid_generate_v4(),
  property_id     uuid not null references jp_properties(id) on delete cascade,
  valued_at       date,
  appraisal_value          numeric(20,0),
  sale_standard_price      numeric(20,0),
  purchase_possible_price  numeric(20,0),
  reason          text,
  raw             jsonb,
  created_at      timestamptz not null default now()
);
create index jp_valuation_history_prop_idx on jp_valuation_history(property_id);

-- ----------------------------------------------------------------------------
-- 매각기일 이력
-- ----------------------------------------------------------------------------

create table jp_sale_dates (
  id              uuid primary key default uuid_generate_v4(),
  property_id     uuid not null references jp_properties(id) on delete cascade,
  seq             smallint,                                   -- 회차 (1부터)
  bid_period_start date,
  bid_period_end   date,
  open_bid_date    date,
  result_cd        text,                                      -- 売却 / 不調 / 特別売却 / ...
  sale_amount      numeric(20,0),                             -- 落札額
  bidder_count     smallint,                                  -- 入札者数
  raw              jsonb,
  created_at       timestamptz not null default now(),
  unique (property_id, seq)
);

-- ----------------------------------------------------------------------------
-- 사진 (BIT는 정적 URL — 한국과 달리 base64 아님)
-- ----------------------------------------------------------------------------

create table jp_property_photos (
  id              uuid primary key default uuid_generate_v4(),
  property_id     uuid not null references jp_properties(id) on delete cascade,
  seq             smallint,                                   -- 사진 순번
  bit_url         text,                                       -- /data/image/TAC_R07K00221_1_l.jpg (BIT 원본)
  storage_path    text,                                       -- jp-auction-photos 버킷 경로 (다운로드 후)
  thumb_path      text,                                       -- jp-auction-photos 썸네일 경로
  kind            text,                                       -- list / detail / sankakushiki / ...
  size_label      text,                                       -- l / s
  description     text,
  raw             jsonb,
  created_at      timestamptz not null default now(),
  unique (property_id, seq)
);

-- ----------------------------------------------------------------------------
-- RLS — anon 공개 읽기 (한국과 동일 정책)
-- ----------------------------------------------------------------------------

alter table jp_prefectures        enable row level security;
alter table jp_courts             enable row level security;
alter table jp_municipalities     enable row level security;
alter table jp_cases              enable row level security;
alter table jp_properties         enable row level security;
alter table jp_valuation_history  enable row level security;
alter table jp_sale_dates         enable row level security;
alter table jp_property_photos    enable row level security;

do $$
declare t text;
begin
  for t in select unnest(array[
    'jp_prefectures','jp_courts','jp_municipalities','jp_cases','jp_properties',
    'jp_valuation_history','jp_sale_dates','jp_property_photos'
  ])
  loop
    execute format($f$
      drop policy if exists "public read" on %I;
      create policy "public read" on %I
        for select to anon, authenticated
        using (true);
    $f$, t, t);
  end loop;
end $$;

-- ----------------------------------------------------------------------------
-- 기본 마스터 시드 — 47 도도부현 + 北海道 4지점
-- ----------------------------------------------------------------------------

insert into jp_prefectures (code, name, block_cls) values
  -- 北海道 (지점별 분리 — BIT 특이사항)
  ('91','北海道(札幌)','01'), ('92','北海道(函館)','01'),
  ('93','北海道(旭川)','01'), ('94','北海道(釧路)','01'),
  -- 東北 (02-07)
  ('02','青森県','02'), ('03','岩手県','02'), ('04','宮城県','02'),
  ('05','秋田県','02'), ('06','山形県','02'), ('07','福島県','02'),
  -- 関東 (08-14)
  ('08','茨城県','03'), ('09','栃木県','03'), ('10','群馬県','03'),
  ('11','埼玉県','03'), ('12','千葉県','03'), ('13','東京都','03'),
  ('14','神奈川県','03'),
  -- 北陸甲信越 (15-20)
  ('15','新潟県','04'), ('16','富山県','04'), ('17','石川県','04'),
  ('18','福井県','04'), ('19','山梨県','04'), ('20','長野県','04'),
  -- 東海 (21-24)
  ('21','岐阜県','05'), ('22','静岡県','05'), ('23','愛知県','05'),
  ('24','三重県','05'),
  -- 近畿 (25-30)
  ('25','滋賀県','06'), ('26','京都府','06'), ('27','大阪府','06'),
  ('28','兵庫県','06'), ('29','奈良県','06'), ('30','和歌山県','06'),
  -- 中国 (31-35)
  ('31','鳥取県','07'), ('32','島根県','07'), ('33','岡山県','07'),
  ('34','広島県','07'), ('35','山口県','07'),
  -- 四国 (36-39)
  ('36','徳島県','08'), ('37','香川県','08'), ('38','愛媛県','08'),
  ('39','高知県','08'),
  -- 九州沖縄 (40-47)
  ('40','福岡県','09'), ('41','佐賀県','09'), ('42','長崎県','09'),
  ('43','熊本県','09'), ('44','大分県','09'), ('45','宮崎県','09'),
  ('46','鹿児島県','09'), ('47','沖縄県','09')
on conflict (code) do nothing;
