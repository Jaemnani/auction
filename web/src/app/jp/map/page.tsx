import nextDynamic from "next/dynamic";
import type { JpMapRow } from "@/components/jp-property-map";
import { supabase } from "@/lib/supabase";
import { JpFilterBar } from "@/components/jp-filter-bar";
import { MapFilterOverlay } from "@/components/map-filter-overlay";
import { type JpFilters, parseJpFilters } from "@/lib/jp-filters";

// MapLibre 청크 분리
const JpPropertyMap = nextDynamic(() => import("@/components/jp-property-map").then((m) => ({ default: m.JpPropertyMap })));

export const metadata = {
  title: "物件マップ — BIT",
  description: "BIT 物件マップ (座標あり物件)",
};

export const dynamic = "force-dynamic";

async function fetchMapRows(filters: JpFilters): Promise<{ rows: JpMapRow[]; courts: { code: string; name: string }[]; prefs: { code: string; name: string }[] }> {
  let q = supabase
    .from("jp_properties")
    .select(
      "sale_unit_id, longitude, latitude, sale_cls, sale_cls_label, sale_standard_price, " +
      "address_text, status, prefecture_code, " +
      "jp_cases!inner(case_no, jp_courts!inner(code, name))"
    )
    .not("longitude", "is", null)
    .not("latitude", "is", null)
    .limit(1000);

  if (filters.pref) q = q.eq("prefecture_code", filters.pref);
  if (filters.sale_cls) q = q.eq("sale_cls", filters.sale_cls);
  if (filters.status) q = q.eq("status", filters.status);
  if (filters.court) q = q.eq("jp_cases.jp_courts.code", filters.court);
  if (filters.case_kind) q = q.eq("jp_cases.case_kind", filters.case_kind);
  if (filters.price_min != null) q = q.gte("sale_standard_price", filters.price_min);
  if (filters.price_max != null) q = q.lte("sale_standard_price", filters.price_max);
  if (filters.q) {
    // 注意: 元は [(令和|平成|...)] と character-class で書かれていたが
    // [] 内 alternation は単一文字マッチ → "(" だけでも一致する偽陽性。
    // 正しいのは alternation group。
    if (/(令和|平成|\(ケ\)|\(ヌ\))/.test(filters.q)) {
      q = q.ilike("jp_cases.case_no", `%${filters.q}%`);
    } else {
      q = q.ilike("address_text", `%${filters.q}%`);
    }
  }
  if (filters.yen_10k === "1") q = q.eq("yen_10k_trap", true);
  if (filters.has_pdf === "1") q = q.eq("detail_result->>has_three_set_pdf", "true");
  if (filters.derived && filters.derived.length > 0) {
    q = q.overlaps("derived_category", filters.derived);
  }

  const { data, error } = await q;
  if (error) {
    console.error("jp map fetch error:", error.message);
    return { rows: [], courts: [], prefs: [] };
  }

  type Raw = {
    sale_unit_id: string;
    longitude: number;
    latitude: number;
    sale_cls_label: string | null;
    sale_standard_price: number | null;
    address_text: string | null;
    jp_cases: { case_no: string | null; jp_courts: { name: string | null } | null } | null;
  };
  const rows: JpMapRow[] = (data as unknown as Raw[]).map((r) => ({
    sale_unit_id: r.sale_unit_id,
    longitude: r.longitude,
    latitude: r.latitude,
    case_no: r.jp_cases?.case_no ?? null,
    court_name: r.jp_cases?.jp_courts?.name ?? null,
    sale_cls_label: r.sale_cls_label,
    sale_standard_price: r.sale_standard_price,
    address_text: r.address_text,
  }));

  const [courtsRes, prefsRes] = await Promise.all([
    supabase.from("jp_courts").select("code, name").order("code"),
    supabase.from("jp_prefectures").select("code, name").order("code"),
  ]);

  return {
    rows,
    courts: (courtsRes.data || []) as { code: string; name: string }[],
    prefs: (prefsRes.data || []) as { code: string; name: string }[],
  };
}

// has_three_set_pdf 통계 (전체·보유) — 토글 옆 비율 표시용.
// head:true 로 row 없이 count 만 가져옴 — 부담 없음. ISR 캐시(부모 page revalidate)에 합산.
async function fetchPdfStats(): Promise<{ total: number; withPdf: number }> {
  const [t, w] = await Promise.all([
    supabase.from("jp_properties").select("sale_unit_id", { count: "exact", head: true }),
    supabase.from("jp_properties").select("sale_unit_id", { count: "exact", head: true })
      .eq("detail_result->>has_three_set_pdf", "true"),
  ]);
  return { total: t.count ?? 0, withPdf: w.count ?? 0 };
}

export default async function JpMapPage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;
  const filters = parseJpFilters(sp);
  const [{ rows, courts, prefs }, pdfStats] = await Promise.all([
    fetchMapRows(filters),
    fetchPdfStats(),
  ]);

  return (
    // 전체 화면 지도 — KR /map 과 동일 패턴. Container px/py 상쇄 + 헤더 아래 전부.
    // isolate z-0: 내부 오버레이가 sticky 헤더를 가리지 않게 스태킹 격리.
    <div
      className="relative isolate z-0 -mx-5 -my-6 min-w-0 overflow-hidden"
      style={{ height: "calc(100vh - 3.5rem)" }}
    >
      <JpPropertyMap rows={rows} fill />
      <MapFilterOverlay>
        {/* 필터 — 목록과 동일한 컴포넌트 */}
        <JpFilterBar action="/jp/map" filters={filters} prefs={prefs} courts={courts} pdfStats={pdfStats} />
      </MapFilterOverlay>
    </div>
  );
}
