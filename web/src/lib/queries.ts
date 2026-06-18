import { supabase, publicStorageUrl, PHOTO_BUCKET } from "./supabase";
import type { Property, PropertyDetail, PropertyFilters } from "./types";
import { DISABLED_RISK_FLAGS, DERIVED_FILTER_ENABLED } from "./filter-flags";

// 목록용 — JSON path 0 (17k row × jsonb 추출 = 타임아웃)
// 배지는 detail 페이지에서만. 목록은 컬럼만 사용해 인덱스로 빠름.
const LIST_PROPERTY_SELECT = `
  id, case_id, docid, maemul_ser, mokmul_ser,
  appraisal_amount, min_sale_price, current_sale_price, fail_count,
  sale_date, sale_decision_date, status_cd,
  usage_lcl_cd, usage_mcl_cd, usage_scl_cd, usage_nm, derived_category,
  sd_code, sgg_code, emd_code, conv_addr, road_addr, lot_addr,
  building_summary, area_summary, longitude, latitude, detail_synced_at,
  cases:case_id!inner ( id, court_code, case_no, case_name, jdbn_name, is_real_estate, receipt_date,
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

  // 매각가율(%) — DB generated column(sale_rate_pct, 마이그레이션 0014)으로 필터.
  // 감정가 0/NULL 또는 최저가 NULL인 row는 sale_rate_pct=NULL → gte/lte에서 자동 제외
  // (= 과거 JS 후처리의 "데이터 없으면 제외" 동작과 동일).
  if (filters.min_rate !== undefined) q = q.gte("sale_rate_pct", filters.min_rate);
  if (filters.max_rate !== undefined) q = q.lte("sale_rate_pct", filters.max_rate);

  if (filters.sale_from) q = q.gte("sale_date", filters.sale_from);
  if (filters.sale_to)   q = q.lte("sale_date", filters.sale_to);

  if (filters.upcoming_only) {
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

  // 한글 용도명 다중 — 매물의 usage_nm 이 set 안에 있으면 포함.
  // 한국 사이트의 dspslUsgNm 분류 (아파트/오피스텔/단독주택 등 20종) 그대로.
  if (filters.usage_nm && filters.usage_nm.length > 0) {
    q = q.in("usage_nm", filters.usage_nm);
  }
  // 파생 카테고리 다중 — derived_category 와 overlap (한 카테고리라도 매칭이면 포함).
  // 현재 비활성(데이터 0건) — DERIVED_FILTER_ENABLED=false 동안 URL 주입돼도 무시.
  if (DERIVED_FILTER_ENABLED && filters.derived && filters.derived.length > 0) {
    const safe = filters.derived.filter((c) => /^[a-z_]+$/.test(c));
    if (safe.length > 0) {
      q = q.overlaps("derived_category", safe);
    }
  }
  // 위험 플래그 제외 — exclude_flags 중 하나라도 risk_flags와 overlap이면 제외.
  // 주의: risk_flags가 NULL인 row(=detail 백필 전이거나 어떤 위험도 분석 안 된)는
  // "위험 없음"으로 간주해 결과에 **포함**해야 함. PostgreSQL의 NOT(NULL && X) = NULL
  // → 단순 not.ov 사용 시 NULL row가 결과에서 사라지는 버그.
  // OR로 risk_flags.is.null 케이스를 명시 포함.
  if (filters.exclude_flags && filters.exclude_flags.length > 0) {
    // 코드는 영문/언더스코어만 — injection 방지차 화이트리스트 검사 후 사용.
    // 오분류로 비활성된 코드(DISABLED_RISK_FLAGS)는 URL 주입돼도 무시.
    const safe = filters.exclude_flags
      .filter((f) => /^[a-z_]+$/.test(f))
      .filter((f) => !DISABLED_RISK_FLAGS.has(f));
    if (safe.length > 0) {
      // PostgREST 부정 어순: `col.not.op.val` (← `not.col.op.val` 아님).
      // 잘못된 어순은 "failed to parse logic tree" 400 → exclude 필터 전체가 깨짐 (라이브 검증으로 확인).
      q = q.or(`risk_flags.is.null,risk_flags.not.ov.{${safe.join(",")}}`);
    }
  }
  return q;
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
    .is("deleted_at", null);
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
    case "sale_date":
    default:
      q = q.order("sale_date", { ascending: true, nullsFirst: false });
  }

  q = q.range(from, to);

  const { data, error, count } = await q;
  if (error) throw error;
  // 매각가율 필터는 이제 DB(sale_rate_pct)에서 적용 → count/페이지네이션 정확.
  const rows = (data ?? []) as unknown as Property[];

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
    sd_code, sgg_code, emd_code, conv_addr, road_addr, lot_addr,
    building_summary, area_summary, longitude, latitude, detail_synced_at,
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
  return {
    ...(row as unknown as PropertyDetail),
    search_row: null,
    detail_result: {
      csBaseInfo: row.csBaseInfo,
      dspslGdsDxdyInfo: row.dspslGdsDxdyInfo,
      aeeWevlMnpntLst: row.aeeWevlMnpntLst,
    },
  };
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

  // sd / usage / courts — code unique이므로 단일 in() 매칭으로 안전
  if (filtered.length > 0) {
    const sdRes = await supabase.from("regions_sd").select("code, name").in("code", filtered);
    const usageRes = await supabase.from("usage_codes").select("code, name").in("code", filtered);
    const courtsRes = await supabase.from("courts").select("code, name").in("code", filtered);
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

// 지도용 — bbox(viewport) 안의 매물만 가져오면 한도 안에 풍부한 마커 노출 가능
export type Bbox = { minLng: number; minLat: number; maxLng: number; maxLat: number };

export async function fetchPropertiesForMap(
  filters: PropertyFilters, max = 1000, bbox?: Bbox,
): Promise<Property[]> {
  let q: FilterableQuery = supabase
    .from("properties")
    .select(LIST_PROPERTY_SELECT)
    .is("deleted_at", null)
    .not("longitude", "is", null)
    .not("latitude", "is", null);
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
  return out;
}
