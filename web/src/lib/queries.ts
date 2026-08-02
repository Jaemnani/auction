import { unstable_cache } from "next/cache";
import { supabase, publicStorageUrl, PHOTO_BUCKET } from "./supabase";
import type { Property, PropertyDetail, PropertyEstimateBrief, PropertyFilters, PropertyScoreBrief } from "./types";

// 목록용 — JSON path 0 (17k row × jsonb 추출 = 타임아웃)
// 배지는 detail 페이지에서만. 목록은 컬럼만 사용해 인덱스로 빠름.
const LIST_PROPERTY_SELECT = `
  id, case_id, docid, maemul_ser, mokmul_ser,
  appraisal_amount, min_sale_price, current_sale_price, fail_count,
  sale_date, sale_decision_date, status_cd,
  usage_lcl_cd, usage_mcl_cd, usage_scl_cd, usage_nm, derived_category,
  sd_code, sgg_code, emd_code, conv_addr, road_addr, lot_addr,
  building_summary, area_summary, longitude, latitude, detail_synced_at,
  final_result, sold_amount, sold_date, deleted_at,
  cases:case_id!inner ( id, court_code, case_no, case_name, jdbn_name, is_real_estate, receipt_date,
                  claim_amount,
                  courts:court_code ( code, name ) ),
  property_photos ( seq, storage_path )
`;

const PROPERTY_SELECT = LIST_PROPERTY_SELECT;

// 지도 마커용 — 팝업이 쓰는 필드만 (photos/courts 조인 없음).
// 실측: 1000행 full select+photos = 2.7s/2MB → 최소 select = 0.9s/0.25MB.
const MAP_PROPERTY_SELECT = `
  id, docid, maemul_ser, appraisal_amount, min_sale_price, fail_count,
  sale_date, usage_lcl_cd, conv_addr, road_addr, lot_addr, building_summary,
  longitude, latitude, final_result, sold_amount, sold_date,
  cases:case_id!inner ( case_no, claim_amount )
`;

export type PropertyListResult = {
  rows: Property[];
  total: number;
  page: number;
  pageSize: number;
};

// 공통 필터 적용 — list/map 모두 사용. supabase-js 빌더 타입이 무한 재귀라 any로 우회.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
type FilterableQuery = any;
function applyFilters(q: FilterableQuery, filters: PropertyFilters): FilterableQuery {
  if (filters.court)    q = q.eq("cases.court_code", filters.court);
  if (filters.sd)       q = q.eq("sd_code", filters.sd);
  if (filters.sgg)      q = q.eq("sgg_code", filters.sgg);
  if (filters.usage_lcl) q = q.eq("usage_lcl_cd", filters.usage_lcl);
  if (filters.usage_mcl) q = q.eq("usage_mcl_cd", filters.usage_mcl);
  if (filters.usage_scl) q = q.eq("usage_scl_cd", filters.usage_scl);

  const wonMin = (mw?: number) => (mw ? mw * 10000 : undefined);
  const minAppraisal = wonMin(filters.min_appraisal);
  const maxAppraisal = wonMin(filters.max_appraisal);
  const minSale = wonMin(filters.min_sale);
  const maxSale = wonMin(filters.max_sale);
  if (minAppraisal !== undefined) q = q.gte("appraisal_amount", minAppraisal);
  if (maxAppraisal !== undefined) q = q.lte("appraisal_amount", maxAppraisal);
  if (minSale !== undefined) q = q.gte("min_sale_price", minSale);
  if (maxSale !== undefined) q = q.lte("min_sale_price", maxSale);

  if (filters.min_fail !== undefined) q = q.gte("fail_count", filters.min_fail);
  if (filters.max_fail !== undefined) q = q.lte("fail_count", filters.max_fail);

  // 매수 안전도 최소 (0023) — safety_score NULL(미채점)은 gte에서 자동 제외.
  if (filters.min_score !== undefined) q = q.gte("safety_score", filters.min_score);

  // 매각가율(%) — DB generated column(sale_rate_pct, 마이그레이션 0014)으로 필터.
  // 감정가 0/NULL 또는 최저가 NULL인 row는 sale_rate_pct=NULL → gte/lte에서 자동 제외
  // (= 과거 JS 후처리의 "데이터 없으면 제외" 동작과 동일).
  if (filters.min_rate !== undefined) q = q.gte("sale_rate_pct", filters.min_rate);
  if (filters.max_rate !== undefined) q = q.lte("sale_rate_pct", filters.max_rate);

  if (filters.sale_from) q = q.gte("sale_date", filters.sale_from);
  if (filters.sale_to)   q = q.lte("sale_date", filters.sale_to);

  if (filters.upcoming_only && filters.status !== "sold_only") {
    // sold_only 는 매각기일이 전부 과거라 upcoming 필터가 결과를 전멸시킴 — 무시.
    const today = new Date().toISOString().slice(0, 10);
    q = q.gte("sale_date", today);
  }

  if (filters.addr_state === "with_road") q = q.not("road_addr", "is", null);
  else if (filters.addr_state === "no_road") q = q.is("road_addr", null);

  if (filters.q && filters.q.trim()) {
    // PostgREST .or()/.ilike() 문자열에 raw 보간 → 메타문자 injection 위험.
    //  ',' '(' ')' : 는 or 그룹/연산자 구분자, '%' '_' '\' 는 LIKE 와일드카드/이스케이프,
    //  '*' 는 PostgREST ilike 와일드카드. 검색어에선 모두 리터럴 의미가 없으므로 공백 치환.
    const kw = filters.q.trim().replace(/[,()%_\\:*]/g, " ").trim();
    if (kw) {
      const looksLikeCaseNo = /타경|^\d{4}/.test(kw);
      if (looksLikeCaseNo) {
        q = q.ilike("cases.case_no", `%${kw}%`);
      } else {
        q = q.or(
          `road_addr.ilike.%${kw}%,conv_addr.ilike.%${kw}%,lot_addr.ilike.%${kw}%`,
        );
      }
    }
  }

  // (usage_nm 칩 / derived / exclude_flags 필터는 2026-07-26 제거 — 재설계 예정.
  //  URL로 주입돼도 무시된다. 과거 구현은 git 이력 참조.)
  return q;
}

// 낙찰 노출 모드 (0018) — RLS가 "삭제 30일 이내 sold"까지만 열어주므로 여기 날짜
// 계산이 다소 어긋나도 만료 매물이 새어나오지는 않음 (이중 방어).
function applyStatus(q: FilterableQuery, status: PropertyFilters["status"]): FilterableQuery {
  if (status === "sold_only") {
    return q.eq("final_result", "sold").not("deleted_at", "is", null);
  }
  if (status === "with_sold") {
    const cutoff = new Date(Date.now() - 30 * 86400 * 1000).toISOString();
    return q.or(`deleted_at.is.null,and(final_result.eq.sold,deleted_at.gte.${cutoff})`);
  }
  return q.is("deleted_at", null);  // 기본: 진행중만
}

// 매수 안전도 점수 (0023) — 별도 조회로 attach. 목록/지도 select 에 임베드하지 않는 이유:
// 0023 미적용 상태에서 임베드하면 관계 없음 오류로 목록/지도 전체가 깨짐(웹은 push 시
// 즉시 배포되나 마이그레이션은 NAS 수동 적용 → 시차). 조회 실패 시 점수 없이 degrade.
async function fetchScoresByIds(
  ids: string[],
): Promise<Record<string, PropertyScoreBrief>> {
  const out: Record<string, PropertyScoreBrief> = {};
  if (ids.length === 0) return out;
  const CHUNK = 150; // uuid .in_() 150 초과 시 NAS nginx 414 (memo 주의사항)
  try {
    for (let i = 0; i < ids.length; i += CHUNK) {
      const { data, error } = await supabase
        .from("property_scores")
        .select("property_id, score, confidence")
        .in("property_id", ids.slice(i, i + CHUNK));
      if (error) return out;  // 0023 미적용 등 — 점수 없이 진행
      for (const r of (data ?? []) as Array<{ property_id: string } & PropertyScoreBrief>) {
        out[r.property_id] = { score: r.score, confidence: r.confidence };
      }
    }
  } catch {
    return out;
  }
  return out;
}

async function attachScores<T extends Property>(rows: T[]): Promise<T[]> {
  const scores = await fetchScoresByIds(rows.map((r) => r.id));
  for (const r of rows) r.scores = scores[r.id] ?? null;
  return rows;
}

// 낙찰 예상가 (0022) — 점수와 동일한 별도 attach 패턴 (0022 미적용/미예측 시 degrade).
// 지도 팝업 표시용 요약 컬럼만 조회.
async function fetchEstimatesByIds(
  ids: string[],
): Promise<Record<string, PropertyEstimateBrief>> {
  const out: Record<string, PropertyEstimateBrief> = {};
  if (ids.length === 0) return out;
  const CHUNK = 150; // uuid .in_() 150 초과 시 NAS nginx 414 (memo 주의사항)
  try {
    for (let i = 0; i < ids.length; i += CHUNK) {
      const { data, error } = await supabase
        .from("property_estimates")
        .select("property_id, estimated_price, estimated_rate_pct, method")
        .in("property_id", ids.slice(i, i + CHUNK));
      if (error) return out;  // 0022 미적용 등 — 예상가 없이 진행
      for (const r of (data ?? []) as Array<{ property_id: string } & PropertyEstimateBrief>) {
        out[r.property_id] = {
          estimated_price: r.estimated_price,
          estimated_rate_pct: r.estimated_rate_pct,
          method: r.method,
        };
      }
    }
  } catch {
    return out;
  }
  return out;
}

async function attachEstimates<T extends Property>(rows: T[]): Promise<T[]> {
  const estimates = await fetchEstimatesByIds(rows.map((r) => r.id));
  for (const r of rows) r.estimate = estimates[r.id] ?? null;
  return rows;
}

// 상세용 — breakdown 포함 단건. 실패 시 null(카드 숨김), EstimateCard 와 동일 패턴.
export async function fetchScore(propertyId: string): Promise<PropertyScoreBrief | null> {
  const { data, error } = await supabase
    .from("property_scores")
    .select("score, confidence, breakdown")
    .eq("property_id", propertyId)
    .maybeSingle();
  if (error) return null;  // 0023 미적용 등
  return (data as PropertyScoreBrief) ?? null;
}

export async function fetchProperties(
  filters: PropertyFilters,
): Promise<PropertyListResult> {
  const page = Math.max(1, filters.page ?? 1);
  const pageSize = Math.min(100, Math.max(10, filters.page_size ?? 30));
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  let q: FilterableQuery = supabase
    .from("properties")
    .select(LIST_PROPERTY_SELECT, { count: "exact" })
    // 썸네일은 최소 seq 1장만 필요 — 임베드 photos를 1건으로 제한 (전체 조인 방지).
    // storage_path 있는 것만 — 첫 사진이 아직 미업로드면 다음 업로드된 걸로 폴백.
    .not("property_photos.storage_path", "is", null)
    .order("seq", { referencedTable: "property_photos", ascending: true })
    .limit(1, { referencedTable: "property_photos" });
  q = applyStatus(q, filters.status);
  q = applyFilters(q, filters);

  // 정렬 — 사용자가 컬럼별 오름/내림 선택. discount는 min_sale_price 대리(낮을수록 할인 큼).
  switch (filters.sort) {
    case "sale_date_desc":
      q = q.order("sale_date", { ascending: false, nullsFirst: false }); break;
    case "appraisal_desc":
      q = q.order("appraisal_amount", { ascending: false, nullsFirst: false }); break;
    case "appraisal_asc":
      q = q.order("appraisal_amount", { ascending: true, nullsFirst: false }); break;
    case "min_sale_asc":
      q = q.order("min_sale_price", { ascending: true, nullsFirst: false }); break;
    case "min_sale_desc":
      q = q.order("min_sale_price", { ascending: false, nullsFirst: false }); break;
    case "fail_desc":
      q = q.order("fail_count", { ascending: false, nullsFirst: false }); break;
    case "fail_asc":
      q = q.order("fail_count", { ascending: true, nullsFirst: false }); break;
    case "discount_desc":
      // 할인율 높은 순 = 매각가율 낮은 순 (sale_rate_pct asc). 마이그레이션 0014.
      q = q.order("sale_rate_pct", { ascending: true, nullsFirst: false }); break;
    case "discount_asc":
      q = q.order("sale_rate_pct", { ascending: false, nullsFirst: false }); break;
    case "score_desc":  // 매수 안전도 높은 순 (안전한 매물 먼저) — 0023 safety_score
      q = q.order("safety_score", { ascending: false, nullsFirst: false }); break;
    case "score_asc":
      q = q.order("safety_score", { ascending: true, nullsFirst: false }); break;
    case "sale_date":
    default:
      // 낙찰만 보기는 "최근 낙찰"이 기본 — 낙찰일 내림차순
      if (filters.status === "sold_only") {
        q = q.order("sold_date", { ascending: false, nullsFirst: false });
      } else {
        q = q.order("sale_date", { ascending: true, nullsFirst: false });
      }
  }

  q = q.range(from, to);

  const { data, error, count } = await q;
  if (error) throw error;
  // 매각가율 필터는 이제 DB(sale_rate_pct)에서 적용 → count/페이지네이션 정확.
  const rows = (data ?? []) as unknown as Property[];
  await attachScores(rows);  // 매수 안전도(0023) — 실패 시 점수 없이 진행

  return {
    rows,
    total: count ?? 0,
    page,
    pageSize,
  };
}

export async function fetchProperty(docid: string): Promise<PropertyDetail | null> {
  // 단건 fetch라 JSON path 비용 무시 가능 — 한 select로 베이스 + jsonb path 모두 발췌.
  // (이전엔 두 번 호출했음. 단건 단순화로 latency 절반 + 동시성 단순화.)
  const DETAIL_SELECT = `
    id, case_id, docid, maemul_ser, mokmul_ser,
    appraisal_amount, min_sale_price, current_sale_price, fail_count,
    sale_date, sale_decision_date, status_cd,
    usage_lcl_cd, usage_mcl_cd, usage_scl_cd,
    sd_code, sgg_code, emd_code, lot_no, conv_addr, road_addr, lot_addr,
    building_summary, area_summary, longitude, latitude, detail_synced_at,
    final_result, sold_amount, sold_date, deleted_at,
    rmk:detail_result->dspslGdsDxdyInfo->>dspslGdsRmk,
    spc_rmk:detail_result->dspslGdsDxdyInfo->>gdsSpcfcRmk,
    dpos_rate:detail_result->dspslGdsDxdyInfo->>prchDposRate,
    primary_liens:detail_result->dspslGdsDxdyInfo->>tprtyRnkHypthcStngDts,
    case_prog:detail_result->csBaseInfo->>csProgStatCd,
    susp_stat:detail_result->csBaseInfo->>auctnSuspStatCd,
    susp_rsn:detail_result->csBaseInfo->>csProgSuspRsn,
    claim_amt:detail_result->csBaseInfo->>clmAmt,
    spcfc_ecdoc_id:detail_result->dspslGdsDxdyInfo->>dspslGdsSpcfcEcdocId,
    csBaseInfo:detail_result->csBaseInfo,
    dspslGdsDxdyInfo:detail_result->dspslGdsDxdyInfo,
    aeeWevlMnpntLst:detail_result->aeeWevlMnpntLst,
    rgltLandLstAll:detail_result->rgltLandLstAll,
    bldSdtrDtlLstAll:detail_result->bldSdtrDtlLstAll,
    gdsRletStLtnoLstAll:detail_result->gdsRletStLtnoLstAll,
    dstrtDemnInfo:detail_result->dstrtDemnInfo,
    gdsDspslObjctLst:detail_result->gdsDspslObjctLst,
    cases:case_id ( id, court_code, case_no, case_name, jdbn_name, is_real_estate, receipt_date,
                    courts:court_code ( code, name ) ),
    property_sale_dates ( seq, sale_date, hour, place, min_price, result_cd, raw ),
    property_photos ( seq, photo_kind_cd, photo_kind_name, description, storage_path )
  `;
  const { data, error } = await supabase
    .from("properties")
    .select(DETAIL_SELECT)
    .eq("docid", docid)
    .maybeSingle();

  if (error) throw error;
  if (!data) return null;

  const row = data as unknown as Record<string, unknown>;
  const detail: PropertyDetail = {
    ...(row as unknown as PropertyDetail),
    search_row: null,
    detail_result: {
      csBaseInfo: row.csBaseInfo,
      dspslGdsDxdyInfo: row.dspslGdsDxdyInfo,
      aeeWevlMnpntLst: row.aeeWevlMnpntLst,
      rgltLandLstAll: row.rgltLandLstAll,
      bldSdtrDtlLstAll: row.bldSdtrDtlLstAll,
      gdsRletStLtnoLstAll: row.gdsRletStLtnoLstAll,
      dstrtDemnInfo: row.dstrtDemnInfo,
      gdsDspslObjctLst: row.gdsDspslObjctLst,
    },
  };
  detail.scores = await fetchScore(detail.id);  // 매수 안전도(0023, breakdown 포함)
  return detail;
}

// 코드 → 이름 매핑 (지역/용도)
//
// 주의: regions_sgg는 PK가 (sd_code, code) 복합이라 같은 code가 여러 sd에 걸쳐 존재.
//   예: code=650 → sd=11일 때 "서초구", sd=41일 때 "포천시"
// 그래서 sgg는 단일 code 매칭이 아니라 (sd, code) 페어로 받아야 안전.
// sggPairs를 전달하면 그것으로 정확히 lookup, 그렇지 않으면 단일 code (sd 모호) 호환 모드.
export async function fetchCodeNames(
  codes: string[],
  sggPairs: Array<{ sd_code: string; sgg_code: string }> = [],
) {
  const filtered = Array.from(new Set(codes.filter(Boolean)));
  const out: Record<string, string> = {};
  if (filtered.length === 0 && sggPairs.length === 0) return out;

  // sd / usage / courts — code unique이므로 단일 in() 매칭으로 안전.
  // 서로 독립이므로 병렬 (기존엔 3개 순차 await → WAN 왕복 3배 지연).
  if (filtered.length > 0) {
    const [sdRes, usageRes, courtsRes] = await Promise.all([
      supabase.from("regions_sd").select("code, name").in("code", filtered),
      supabase.from("usage_codes").select("code, name").in("code", filtered),
      supabase.from("courts").select("code, name").in("code", filtered),
    ]);
    for (const r of [...(sdRes.data ?? []), ...(usageRes.data ?? []), ...(courtsRes.data ?? [])]) {
      out[r.code] = r.name;
    }
  }

  // sgg는 (sd, code) 페어로 정확 lookup
  if (sggPairs.length > 0) {
    const orFilter = sggPairs
      .map((p) => `and(sd_code.eq.${p.sd_code},code.eq.${p.sgg_code})`)
      .join(",");
    const sggRes = await supabase
      .from("regions_sgg")
      .select("sd_code, code, name")
      .or(orFilter);
    for (const row of sggRes.data ?? []) {
      // 입력 페어와 정확 매칭된 행만 (방어적)
      const pair = sggPairs.find(
        (p) => p.sd_code === row.sd_code && p.sgg_code === row.code,
      );
      if (pair) out[row.code] = row.name;
    }
  }
  return out;
}

// 인근 낙찰 통계 — 우리 sale_results 테이블 + auction_stats_by_region view
export type AuctionStat = {
  sd_code: string;
  sgg_code: string;
  usage_lcl_cd: string;
  total_count: number;
  sold_count: number;
  unsold_count: number;
  avg_sale_rate_pct: number | null;     // 평균 매각가율 (%)
  avg_fail_count_when_sold: number | null;
  avg_bidder_count: number | null;
  latest_sale_date: string | null;
  recent_sold_count: number;            // 90일 내 매각 건수 (신선도)
};

export async function fetchRegionStats(
  sd_code: string | null | undefined,
  sgg_code: string | null | undefined,
  usage_lcl_cd: string | null | undefined,
): Promise<AuctionStat | null> {
  if (!sd_code || !sgg_code) return null;
  let q = supabase.from("auction_stats_by_region")
    .select("*")
    .eq("sd_code", sd_code)
    .eq("sgg_code", sgg_code);
  if (usage_lcl_cd) q = q.eq("usage_lcl_cd", usage_lcl_cd);
  const { data, error } = await q.maybeSingle();
  if (error) {
    // 용도 정확히 매칭 안 되면 sd+sgg 전체로 폴백
    const fb = await supabase.from("auction_stats_by_region")
      .select("*")
      .eq("sd_code", sd_code)
      .eq("sgg_code", sgg_code)
      .order("total_count", { ascending: false })
      .limit(1);
    return (fb.data?.[0] as AuctionStat) ?? null;
  }
  return (data as AuctionStat) ?? null;
}

// 낙찰 예상가 — property_estimates (0022). 크롤러 배치 예측(estimate.py predict) 결과.
export type PropertyEstimate = {
  property_id: string;
  estimated_price: number | null;
  estimated_low: number | null;
  estimated_high: number | null;
  estimated_rate_pct: number | null;
  method: "model" | "region_avg";
  model_version: string | null;
  sample_count: number | null;
  features_used: Record<string, boolean> | null;
  predicted_at: string;
};

export async function fetchEstimate(propertyId: string): Promise<PropertyEstimate | null> {
  const { data, error } = await supabase
    .from("property_estimates")
    .select("*")
    .eq("property_id", propertyId)
    .maybeSingle();
  if (error) return null;  // 0022 미적용 등 — 카드 자체를 숨김
  return (data as PropertyEstimate) ?? null;
}

// 지역 과거 낙찰 사례 — sale_archive view (0019). RLS 유예창과 무관하게 영구 조회 가능.
export type SaleCase = {
  docid: string | null;
  case_no: string;
  maemul_ser: number;
  appraisal_amount: number | null;
  min_sale_price: number | null;
  sale_amount: number;
  fail_count: number | null;
  bidder_count: number | null;
  sale_date: string | null;
  sale_rate_pct: number | null;
  usage_nm: string | null;
  conv_addr: string | null;
  road_addr: string | null;
  lot_addr: string | null;
  area_summary: string | null;
};

export async function fetchRegionalSaleCases(opts: {
  sd_code: string | null | undefined;
  sgg_code: string | null | undefined;
  emd_code?: string | null;
  usage_lcl_cd?: string | null;
  limit?: number;
}): Promise<{ cases: SaleCase[]; scope: "emd" | "sgg" } | null> {
  const { sd_code, sgg_code, emd_code, usage_lcl_cd } = opts;
  const limit = opts.limit ?? 8;
  if (!sd_code || !sgg_code) return null;

  const base = () => {
    let q = supabase.from("sale_archive")
      .select("docid, case_no, maemul_ser, appraisal_amount, min_sale_price, sale_amount, "
        + "fail_count, bidder_count, sale_date, sale_rate_pct, usage_nm, "
        + "conv_addr, road_addr, lot_addr, area_summary")
      .eq("sd_code", sd_code)
      .eq("sgg_code", sgg_code)
      .order("sale_date", { ascending: false })
      .limit(limit);
    if (usage_lcl_cd) q = q.eq("usage_lcl_cd", usage_lcl_cd);
    return q;
  };

  // 읍면동 단위 우선 — 표본 3건 미만이면 시군구로 넓힘
  if (emd_code) {
    const { data, error } = await base().eq("emd_code", emd_code);
    if (!error && (data?.length ?? 0) >= 3) {
      return { cases: data as unknown as SaleCase[], scope: "emd" };
    }
  }
  const { data, error } = await base();
  if (error || !data || data.length === 0) return null;
  return { cases: data as unknown as SaleCase[], scope: "sgg" };
}

// (이전) courtauction의 selectAuctnTongSrchRslt 라이브 호출 — 발굴 미완으로 비활성
// detail 페이지에서 lazy-load 되는 보조 정보
export async function fetchAuctionStats(
  courtCode: string, caseNo: string,
): Promise<Record<string, unknown> | null> {
  try {
    const res = await fetch(
      "https://www.courtauction.go.kr/pgj/pgj15B/selectAuctnTongSrchRslt.on",
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json;charset=UTF-8",
          "Accept": "application/json",
          "Referer": "https://www.courtauction.go.kr/pgj/index.on?device=pc",
          "User-Agent": "Mozilla/5.0",
        },
        body: JSON.stringify({
          dma_srchGdsDtlSrch: {
            csNo: caseNo,
            cortOfcCd: courtCode,
            pgmId: "PGJ15BM01",
          },
        }),
        next: { revalidate: 3600 },  // 1시간 캐싱
      },
    );
    if (!res.ok) return null;
    const body = await res.json();
    return body?.data ?? null;
  } catch {
    return null;
  }
}

// Storage public URL (원본) — MinIO(self-host)/Supabase 공용 헬퍼 사용.
export function photoPublicUrl(storagePath: string): string {
  return publicStorageUrl(PHOTO_BUCKET, storagePath);
}

// Storage public URL (썸네일 — thumbs/{path})
export function photoThumbUrl(storagePath: string): string {
  return publicStorageUrl(PHOTO_BUCKET, `thumbs/${storagePath}`);
}

// ---------- 마스터 ----------
// 법원/지역/용도 코드는 masters 크롤 때만 바뀜(거의 불변) → data cache로 감싸
// force-dynamic 페이지에서도 매 요청 WAN 왕복을 없앰. 6시간 revalidate.
const MASTER_TTL = 21600;

export const fetchCourts = unstable_cache(
  async () => {
    const { data, error } = await supabase
      .from("courts")
      .select("code, prefix, name")
      .eq("prefix", "B")
      .order("name");
    if (error) throw error;
    return data ?? [];
  },
  ["master:courts"],
  { revalidate: MASTER_TTL },
);

export const fetchSdList = unstable_cache(
  async () => {
    const { data, error } = await supabase
      .from("regions_sd")
      .select("code, name")
      .order("code");
    if (error) throw error;
    return data ?? [];
  },
  ["master:sd"],
  { revalidate: MASTER_TTL },
);

export const fetchSggList = unstable_cache(
  async (sdCode?: string) => {
    let q = supabase.from("regions_sgg").select("code, sd_code, name").order("name");
    if (sdCode) q = q.eq("sd_code", sdCode);
    const { data, error } = await q;
    if (error) throw error;
    return data ?? [];
  },
  ["master:sgg"],   // sdCode 인자는 unstable_cache가 캐시 키에 자동 포함
  { revalidate: MASTER_TTL },
);

export const fetchUsageList = unstable_cache(
  async (level: 1 | 2 | 3, parentCode?: string) => {
    let q = supabase.from("usage_codes")
      .select("code, level, parent_code, name")
      .eq("level", level)
      .order("code");
    if (parentCode) q = q.eq("parent_code", parentCode);
    const { data, error } = await q;
    if (error) throw error;
    return data ?? [];
  },
  ["master:usage"],  // level/parentCode 인자는 캐시 키에 자동 포함
  { revalidate: MASTER_TTL },
);

// ---------- 지도용 좌표 ----------

// 지도용 — bbox(viewport) 안의 매물만 가져오면 한도 안에 풍부한 마커 노출 가능
export type Bbox = { minLng: number; minLat: number; maxLng: number; maxLat: number };

export async function fetchPropertiesForMap(
  filters: PropertyFilters, max = 1000, bbox?: Bbox,
): Promise<Property[]> {
  let q: FilterableQuery = supabase
    .from("properties")
    .select(MAP_PROPERTY_SELECT)
    .not("longitude", "is", null)
    .not("latitude", "is", null);
  // 지도는 기본으로 최근 낙찰(30일 유예창)도 함께 표시 — 파란 마커로 구분.
  q = applyStatus(q, filters.status ?? "with_sold");
  q = applyFilters(q, filters);
  if (bbox) {
    q = q.gte("longitude", bbox.minLng).lte("longitude", bbox.maxLng)
         .gte("latitude",  bbox.minLat).lte("latitude",  bbox.maxLat);
  }
  q = q.order("sale_date", { ascending: true, nullsFirst: false });

  const PAGE = 1000;
  const collected: Property[] = [];
  let offset = 0;
  while (collected.length < max) {
    const lim = Math.min(PAGE, max - collected.length);
    const { data, error } = await q.range(offset, offset + lim - 1);
    if (error) throw error;
    const rows = (data ?? []) as unknown as Property[];
    if (rows.length === 0) break;
    collected.push(...rows);
    if (rows.length < lim) break;
    offset += lim;
  }
  // 한국 영토 박스 필터 (클라이언트). 매각가율은 applyFilters에서 DB 처리됨.
  // bbox가 명시되면 사용자 viewport이므로 한국 박스 재검사 불필요 (중복 비용).
  const out = bbox
    ? collected
    : collected.filter((r) =>
        r.longitude !== null && r.latitude !== null
        && r.longitude >= 124 && r.longitude <= 132.5
        && r.latitude  >= 33  && r.latitude  <= 39,
      );
  // 안전도(0023)·예상가(0022) attach — 각각 실패 시 해당 값 없이 진행
  await Promise.all([attachScores(out), attachEstimates(out)]);
  return out;
}
