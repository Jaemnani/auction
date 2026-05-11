import Link from "next/link";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { JpPropertyMap, type JpMapRow } from "@/components/jp-property-map";
import { supabase } from "@/lib/supabase";

export const metadata = {
  title: "일본 매물 지도 — BIT",
  description: "BIT 매물 위치 지도 (좌표 있는 매물만)",
};

export const dynamic = "force-dynamic";

type JpFilters = {
  sale_cls: string | null;
  status: string | null;
  court: string | null;
  q: string | null;
  price_max: number | null;
  pref: string | null;
};

const SALE_CLS_OPTIONS = [
  { code: "1", label: "土地" },
  { code: "2", label: "戸建て" },
  { code: "3", label: "マンション" },
  { code: "4", label: "その他" },
];

const STATUS_OPTIONS = [
  { code: "period_bid", label: "期間入札" },
  { code: "special_sale", label: "特別売却" },
  { code: "reval_pending", label: "評価再調整" },
  { code: "re_bid", label: "再入札" },
  { code: "closed", label: "終結" },
  { code: "aborted", label: "中止" },
];

function parseFilters(sp: Record<string, string | string[] | undefined>): JpFilters {
  const get = (k: string): string | null => {
    const v = sp[k];
    if (Array.isArray(v)) return v[0] ?? null;
    return v ?? null;
  };
  const num = (k: string): number | null => {
    const v = get(k);
    if (v == null) return null;
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  };
  return {
    sale_cls: get("sale_cls"),
    status: get("status"),
    court: get("court"),
    q: get("q"),
    price_max: num("price_max"),
    pref: get("pref"),
  };
}

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
    .limit(5000);

  if (filters.sale_cls) q = q.eq("sale_cls", filters.sale_cls);
  if (filters.status) q = q.eq("status", filters.status);
  if (filters.court) q = q.eq("jp_cases.jp_courts.code", filters.court);
  if (filters.pref) q = q.eq("prefecture_code", filters.pref);
  if (filters.price_max != null) q = q.lte("sale_standard_price", filters.price_max);
  if (filters.q) {
    if (/[(令和|平成|\(ケ\)|\(ヌ\))]/.test(filters.q)) {
      q = q.ilike("jp_cases.case_no", `%${filters.q}%`);
    } else {
      q = q.ilike("address_text", `%${filters.q}%`);
    }
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

export default async function JpMapPage(props: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const sp = await props.searchParams;
  const filters = parseFilters(sp);
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

      {/* 필터 */}
      <Card>
        <CardHeader className="py-3">
          <CardTitle className="text-sm">필터</CardTitle>
        </CardHeader>
        <CardContent className="pb-4">
          <form method="get" action="/jp/map" className="grid sm:grid-cols-12 gap-2">
            <select name="pref" defaultValue={filters.pref ?? ""}
                    className="sm:col-span-3 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">도도부현 — 전체</option>
              {prefs.map((p) => (
                <option key={p.code} value={p.code}>{p.code} {p.name}</option>
              ))}
            </select>
            <select name="court" defaultValue={filters.court ?? ""}
                    className="sm:col-span-3 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">법원 — 전체</option>
              {courts.map((c) => (
                <option key={c.code} value={c.code}>{c.name}</option>
              ))}
            </select>
            <select name="sale_cls" defaultValue={filters.sale_cls ?? ""}
                    className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">종별 — 전체</option>
              {SALE_CLS_OPTIONS.map((o) => (
                <option key={o.code} value={o.code}>{o.label}</option>
              ))}
            </select>
            <select name="status" defaultValue={filters.status ?? ""}
                    className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
              <option value="">상태 — 전체</option>
              {STATUS_OPTIONS.map((o) => (
                <option key={o.code} value={o.code}>{o.label}</option>
              ))}
            </select>
            <button type="submit"
                    className="sm:col-span-2 h-9 rounded-md bg-primary text-primary-foreground text-sm font-medium hover:opacity-90">
              적용
            </button>
          </form>
        </CardContent>
      </Card>

      <JpPropertyMap rows={rows} />
    </div>
  );
}
