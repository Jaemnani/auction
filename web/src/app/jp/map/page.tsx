import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { JpPropertyMap, type JpMapRow } from "@/components/jp-property-map";
import { supabase } from "@/lib/supabase";
import { JpFilterBar } from "@/components/jp-filter-bar";
import { type JpFilters, parseJpFilters } from "@/lib/jp-filters";

export const metadata = {
  title: "일본 매물 지도 — BIT",
  description: "BIT 매물 위치 지도 (좌표 있는 매물만)",
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
    if (/[(令和|平成|\(ケ\)|\(ヌ\))]/.test(filters.q)) {
      q = q.ilike("jp_cases.case_no", `%${filters.q}%`);
    } else {
      q = q.ilike("address_text", `%${filters.q}%`);
    }
  }
  if (filters.yen_10k === "1") q = q.eq("yen_10k_trap", true);
  if (filters.has_pdf === "1") q = q.eq("detail_result->>has_three_set_pdf", "true");

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

export default async function JpMapPage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;
  const filters = parseJpFilters(sp);
  const { rows, courts, prefs } = await fetchMapRows(filters);

  return (
    <div className="space-y-4 max-w-6xl mx-auto">
      <section className="rounded-lg border bg-card p-5 space-y-2">
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-xs">좌표 매물 {rows.length}건</Badge>
          <Badge variant="outline" className="text-xs">OpenFreeMap 타일</Badge>
        </div>
        <h1 className="text-xl font-bold tracking-tight">🇯🇵 매물 지도</h1>
        <p className="text-sm text-muted-foreground">
          매물 위치를 일본 전역 지도에서 확인. 마커 클릭 시 사건번호·가격·주소·상세 링크 팝업.
          {" "}
          <Link href="/jp" className="text-primary hover:underline">목록 보기</Link>
        </p>
      </section>

      {/* 필터 — 목록과 동일한 컴포넌트 */}
      <JpFilterBar action="/jp/map" filters={filters} prefs={prefs} courts={courts} />

      <JpPropertyMap rows={rows} />
    </div>
  );
}
