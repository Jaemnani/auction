import { supabase } from "./supabase";
import type { Property, PropertyDetail, PropertyFilters } from "./types";

// 목록용 — JSON path 0 (17k row × jsonb 추출 = 타임아웃)
// 배지는 detail 페이지에서만. 목록은 컬럼만 사용해 인덱스로 빠름.
const LIST_PROPERTY_SELECT = `
  id, case_id, docid, maemul_ser, mokmul_ser,
  appraisal_amount, min_sale_price, current_sale_price, fail_count,
  sale_date, sale_decision_date, status_cd,
  usage_lcl_cd, usage_mcl_cd, usage_scl_cd,
  sd_code, sgg_code, emd_code, conv_addr, road_addr, lot_addr,
  building_summary, area_summary, longitude, latitude, detail_synced_at,
  cases:case_id ( id, court_code, case_no, case_name, jdbn_name, is_real_estate, receipt_date,
                  courts:court_code ( code, name ) ),
  property_photos ( seq, storage_path )
`;

const PROPERTY_SELECT = LIST_PROPERTY_SELECT;

export type PropertyListResult = {
  rows: Property[];
  total: number;
  page: number;
  pageSize: number;
};

export async function fetchProperties(
  filters: PropertyFilters,
): Promise<PropertyListResult> {
  const page = Math.max(1, filters.page ?? 1);
  const pageSize = Math.min(100, Math.max(10, filters.page_size ?? 30));
  const from = (page - 1) * pageSize;
  const to = from + pageSize - 1;

  let q = supabase
    .from("properties")
    .select(LIST_PROPERTY_SELECT, { count: "estimated" })  // exact는 17k+ JSON path와 함께 타임아웃
    .is("deleted_at", null);

  // 법원
  if (filters.court) q = q.eq("cases.court_code", filters.court);

  // 지역
  if (filters.sd) q = q.eq("sd_code", filters.sd);
  if (filters.sgg) q = q.eq("sgg_code", filters.sgg);

  // 용도
  if (filters.usage_lcl) q = q.eq("usage_lcl_cd", filters.usage_lcl);
  if (filters.usage_mcl) q = q.eq("usage_mcl_cd", filters.usage_mcl);
  if (filters.usage_scl) q = q.eq("usage_scl_cd", filters.usage_scl);

  // 가격 (만원 단위 입력 → 원 단위 비교; 만원 = 10000)
  const wonMin = (mw?: number) => (mw ? mw * 10000 : undefined);
  const minAppraisal = wonMin(filters.min_appraisal);
  const maxAppraisal = wonMin(filters.max_appraisal);
  const minSale = wonMin(filters.min_sale);
  const maxSale = wonMin(filters.max_sale);
  if (minAppraisal !== undefined) q = q.gte("appraisal_amount", minAppraisal);
  if (maxAppraisal !== undefined) q = q.lte("appraisal_amount", maxAppraisal);
  if (minSale !== undefined) q = q.gte("min_sale_price", minSale);
  if (maxSale !== undefined) q = q.lte("min_sale_price", maxSale);

  // 유찰횟수
  if (filters.min_fail !== undefined) q = q.gte("fail_count", filters.min_fail);
  if (filters.max_fail !== undefined) q = q.lte("fail_count", filters.max_fail);

  // 매각기일 범위
  if (filters.sale_from) q = q.gte("sale_date", filters.sale_from);
  if (filters.sale_to) q = q.lte("sale_date", filters.sale_to);

  // 매각기일 미래만 (이미 끝난 회차 제외)
  if (filters.upcoming_only) {
    const today = new Date().toISOString().slice(0, 10);
    q = q.gte("sale_date", today);
  }

  // 주소(도로명) 보유 여부 필터
  if (filters.addr_state === "with_road") {
    q = q.not("road_addr", "is", null);
  } else if (filters.addr_state === "no_road") {
    q = q.is("road_addr", null);
  }

  // 매각가율 (%) — DB에 별도 컬럼이 없으니 PostgREST 식 비교 어려움
  // → 클라이언트에서 row 받은 후 후처리 필터로 적용 (아래 fetchProperties에서)

  // 키워드 — 사건번호처럼 보이면 case_no로 직접 매칭, 아니면 주소들 OR
  // (PostgREST OR 안에서는 nested 테이블 ilike 미지원)
  if (filters.q && filters.q.trim()) {
    const kw = filters.q.trim();
    const looksLikeCaseNo = /타경|^\d{4}/.test(kw);
    if (looksLikeCaseNo) {
      // foreign table 직접 ilike — PostgREST는 .eq처럼 지원
      q = q.ilike("cases.case_no", `%${kw}%`);
    } else {
      q = q.or(
        `road_addr.ilike.%${kw}%,conv_addr.ilike.%${kw}%,lot_addr.ilike.%${kw}%`,
      );
    }
  }

  // 정렬
  switch (filters.sort) {
    case "appraisal_desc":
      q = q.order("appraisal_amount", { ascending: false, nullsFirst: false });
      break;
    case "appraisal_asc":
      q = q.order("appraisal_amount", { ascending: true, nullsFirst: false });
      break;
    case "fail_desc":
      q = q.order("fail_count", { ascending: false, nullsFirst: false });
      break;
    case "discount_desc":
      // 매각가율 = min_sale_price / appraisal_amount (할인율 큰 순 = ratio 작은 순)
      q = q.order("min_sale_price", { ascending: true, nullsFirst: false });
      break;
    case "sale_date":
    default:
      q = q.order("sale_date", { ascending: true, nullsFirst: false });
  }

  q = q.range(from, to);

  const { data, error, count } = await q;
  if (error) throw error;
  let rows = (data ?? []) as unknown as Property[];

  // 매각가율 후처리 필터 (DB 인덱스 없는 비율 기반)
  if (filters.min_rate !== undefined || filters.max_rate !== undefined) {
    const lo = filters.min_rate ?? 0;
    const hi = filters.max_rate ?? 1000;
    rows = rows.filter((r) => {
      if (!r.appraisal_amount || !r.min_sale_price) return false;
      const rate = (r.min_sale_price / r.appraisal_amount) * 100;
      return rate >= lo && rate <= hi;
    });
  }
  return {
    rows,
    total: count ?? 0,
    page,
    pageSize,
  };
}

export async function fetchProperty(docid: string): Promise<PropertyDetail | null> {
  // 1) 가벼운 컬럼 + 관계 (큰 jsonb는 제외).
  //    PROPERTY_SELECT에 이미 property_photos(seq, storage_path)가 들어 있으니
  //    상세에 필요한 추가 필드만 따로 명시.
  const DETAIL_SELECT = `
    id, case_id, docid, maemul_ser, mokmul_ser,
    appraisal_amount, min_sale_price, current_sale_price, fail_count,
    sale_date, sale_decision_date, status_cd,
    usage_lcl_cd, usage_mcl_cd, usage_scl_cd,
    sd_code, sgg_code, emd_code, conv_addr, road_addr, lot_addr,
    building_summary, area_summary, longitude, latitude, detail_synced_at,
    cases:case_id ( id, court_code, case_no, case_name, jdbn_name, is_real_estate, receipt_date,
                    courts:court_code ( code, name ) ),
    property_sale_dates ( seq, sale_date, hour, place, min_price, result_cd ),
    property_photos ( seq, photo_kind_cd, photo_kind_name, description, storage_path )
  `;
  const { data: base, error } = await supabase
    .from("properties")
    .select(DETAIL_SELECT)
    .eq("docid", docid)
    .maybeSingle();

  if (error) throw error;
  if (!base) return null;

  // 2) detail_result는 jsonb 경로로 필요한 키만 발췌
  const { data: detail } = await supabase
    .from("properties")
    .select("detail_result->csBaseInfo, detail_result->dspslGdsDxdyInfo, detail_result->aeeWevlMnpntLst")
    .eq("docid", docid)
    .maybeSingle();

  return {
    ...(base as unknown as PropertyDetail),
    search_row: null,
    detail_result: detail
      ? {
          csBaseInfo: (detail as Record<string, unknown>).csBaseInfo,
          dspslGdsDxdyInfo: (detail as Record<string, unknown>).dspslGdsDxdyInfo,
          aeeWevlMnpntLst: (detail as Record<string, unknown>).aeeWevlMnpntLst,
        }
      : null,
  };
}

// 코드 → 이름 매핑 (지역/용도)
export async function fetchCodeNames(codes: string[]) {
  const filtered = Array.from(new Set(codes.filter(Boolean)));
  if (filtered.length === 0) return {} as Record<string, string>;

  const out: Record<string, string> = {};
  // 지역 (sd, sgg)
  const sd = await supabase.from("regions_sd").select("code, name").in("code", filtered);
  const sgg = await supabase.from("regions_sgg").select("code, name").in("code", filtered);
  const usage = await supabase.from("usage_codes").select("code, name").in("code", filtered);
  const courts = await supabase.from("courts").select("code, name").in("code", filtered);
  for (const r of [...(sd.data ?? []), ...(sgg.data ?? []), ...(usage.data ?? []), ...(courts.data ?? [])]) {
    out[r.code] = r.name;
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

// Storage public URL (원본)
export function photoPublicUrl(storagePath: string): string {
  return supabase.storage.from("auction-photos").getPublicUrl(storagePath).data.publicUrl;
}

// Storage public URL (썸네일 — thumbs/{path})
export function photoThumbUrl(storagePath: string): string {
  return supabase.storage.from("auction-photos")
    .getPublicUrl(`thumbs/${storagePath}`).data.publicUrl;
}

// ---------- 마스터 ----------

export async function fetchCourts() {
  const { data, error } = await supabase
    .from("courts")
    .select("code, prefix, name")
    .eq("prefix", "B")
    .order("name");
  if (error) throw error;
  return data ?? [];
}

export async function fetchSdList() {
  const { data, error } = await supabase
    .from("regions_sd")
    .select("code, name")
    .order("code");
  if (error) throw error;
  return data ?? [];
}

export async function fetchSggList(sdCode?: string) {
  let q = supabase.from("regions_sgg").select("code, sd_code, name").order("name");
  if (sdCode) q = q.eq("sd_code", sdCode);
  const { data, error } = await q;
  if (error) throw error;
  return data ?? [];
}

export async function fetchUsageList(level: 1 | 2 | 3, parentCode?: string) {
  let q = supabase.from("usage_codes")
    .select("code, level, parent_code, name")
    .eq("level", level)
    .order("code");
  if (parentCode) q = q.eq("parent_code", parentCode);
  const { data, error } = await q;
  if (error) throw error;
  return data ?? [];
}

// ---------- 지도용 좌표 ----------

export async function fetchPropertiesForMap(filters: PropertyFilters, max = 1000) {
  const page = await fetchProperties({ ...filters, page: 1, page_size: max });
  return page.rows.filter((r) =>
    r.longitude !== null && r.latitude !== null
    && r.longitude >= 124 && r.longitude <= 132.5
    && r.latitude  >= 33  && r.latitude  <= 39,
  );
}
