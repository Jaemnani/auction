// DB row types — supabase/migrations/0001_init.sql 스키마와 일치
export type Court = {
  code: string;
  prefix: "B" | "O";
  name: string;
};

export type RegionSd = { code: string; name: string };
export type RegionSgg = { code: string; sd_code: string; name: string };

export type UsageCode = {
  code: string;
  level: 1 | 2 | 3;
  parent_code: string | null;
  name: string;
};

export type Property = {
  id: string;
  case_id: string;
  docid: string | null;
  maemul_ser: number;
  mokmul_ser: number | null;
  appraisal_amount: number | null;
  min_sale_price: number | null;
  current_sale_price: number | null;
  fail_count: number | null;
  sale_date: string | null;
  sale_decision_date: string | null;
  status_cd: string | null;
  usage_lcl_cd: string | null;
  usage_mcl_cd: string | null;
  usage_scl_cd: string | null;
  sd_code: string | null;
  sgg_code: string | null;
  emd_code: string | null;
  conv_addr: string | null;
  road_addr: string | null;
  lot_addr: string | null;
  building_summary: string | null;
  area_summary: string | null;
  longitude: number | null;
  latitude: number | null;
  detail_synced_at: string | null;
  property_photos?: Array<{ seq: number; storage_path: string | null }> | null;
  cases: {
    id: string;
    court_code: string;
    case_no: string;
    case_name: string | null;
    jdbn_name: string | null;
    is_real_estate: boolean | null;
    receipt_date: string | null;
    courts: { code: string; name: string } | null;
  } | null;
};

export type PropertyDetail = Omit<Property, "property_photos"> & {
  search_row: Record<string, unknown> | null;
  detail_result: Record<string, unknown> | null;
  property_sale_dates: Array<{
    seq: number;
    sale_date: string | null;
    hour: string | null;
    place: string | null;
    min_price: number | null;
    result_cd: string | null;
  }>;
  property_photos: Array<{
    seq: number;
    photo_kind_cd: string | null;
    photo_kind_name: string | null;
    description: string | null;
    storage_path: string | null;
  }>;
};

export type PropertyFilters = {
  q?: string; // 사건번호/주소 키워드
  court?: string; // 법원 코드
  sd?: string; // 시도
  sgg?: string; // 시군구
  usage_lcl?: string; // 용도 대분류
  usage_mcl?: string;
  usage_scl?: string;
  min_appraisal?: number; // 감정가 최소 (만원)
  max_appraisal?: number;
  min_sale?: number; // 최저매각가 최소
  max_sale?: number;
  min_fail?: number; // 유찰횟수 최소
  max_fail?: number;
  sale_from?: string; // 매각기일 from
  sale_to?: string;
  page?: number;
  page_size?: number;
  sort?: "sale_date" | "appraisal_desc" | "appraisal_asc" | "fail_desc" | "discount_desc";
};
