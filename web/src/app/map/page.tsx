import nextDynamic from "next/dynamic";
import { FilterSidebar } from "@/components/filter-sidebar";
import {
  fetchCourts, fetchPropertiesForMap, fetchSdList, fetchSggList, fetchUsageList,
} from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";
import type { ActiveFilter } from "@/components/property-map";
import type { PropertyFilters } from "@/lib/types";

// MapLibre 무거운 의존성 — 청크 분리.
const PropertyMap = nextDynamic(() => import("@/components/property-map").then((m) => ({ default: m.PropertyMap })));

export const dynamic = "force-dynamic";

type Opt = { code: string; name: string };

// PropertyFilters → 사람이 읽는 chip 배열.
// 사용자가 지도 진입 시 "건물 필터 안 켰네" 같은 UX 오해를 즉시 인식하기 위함.
function buildActiveFilters(
  f: PropertyFilters,
  m: { courts: Opt[]; sd: Opt[]; sgg: Opt[]; usageLcl: Opt[] },
): ActiveFilter[] {
  const out: ActiveFilter[] = [];
  const nm = (code: string | undefined, list: Opt[]) =>
    code ? (list.find((o) => o.code === code)?.name ?? code) : "";
  if (f.usage_lcl) out.push({ label: "용도", value: nm(f.usage_lcl, m.usageLcl) });
  if (f.court)     out.push({ label: "법원", value: nm(f.court, m.courts) });
  if (f.sd)        out.push({ label: "시·도", value: nm(f.sd, m.sd) });
  if (f.sgg)       out.push({ label: "시·군·구", value: nm(f.sgg, m.sgg) });
  if (f.q)         out.push({ label: "키워드", value: f.q });
  if (f.min_appraisal != null || f.max_appraisal != null) {
    out.push({ label: "감정가(만)", value: `${f.min_appraisal ?? 0}~${f.max_appraisal ?? "∞"}` });
  }
  if (f.min_sale != null || f.max_sale != null) {
    out.push({ label: "최저가(만)", value: `${f.min_sale ?? 0}~${f.max_sale ?? "∞"}` });
  }
  if (f.min_fail != null || f.max_fail != null) {
    out.push({ label: "유찰", value: `${f.min_fail ?? 0}~${f.max_fail ?? "∞"}회` });
  }
  if (f.min_rate != null || f.max_rate != null) {
    out.push({ label: "매각가율%", value: `${f.min_rate ?? 0}~${f.max_rate ?? "∞"}` });
  }
  if (f.upcoming_only) out.push({ label: "미래기일만", value: "ON" });
  if (f.addr_state === "with_road") out.push({ label: "도로명", value: "있음" });
  if (f.addr_state === "no_road")   out.push({ label: "도로명", value: "미수집" });
  if (f.exclude_flags?.length)      out.push({ label: "제외 키워드", value: `${f.exclude_flags.length}종` });
  if (f.usage_nm?.length) {
    out.push({ label: "세부분류", value: f.usage_nm.length === 1 ? f.usage_nm[0] : `${f.usage_nm.length}종` });
  }
  if (f.derived?.length) {
    const labels: Record<string, string> = {
      country_house: "전원주택", townhouse: "도심단독",
      farm_house: "농가주택", vacation_home: "별장·펜션",
    };
    out.push({ label: "파생", value: f.derived.map((c) => labels[c] ?? c).join(", ") });
  }
  return out;
}

export default async function MapPage(props: PageProps<"/map">) {
  const sp = await props.searchParams;
  const filters = parseFiltersFromSearchParams(sp);

  // sgg 는 sd 있을 때만 의미 — 조건부 fetch
  const [courts, sdList, usageLcl, sggList, rows] = await Promise.all([
    fetchCourts(),
    fetchSdList(),
    fetchUsageList(1),
    filters.sd ? fetchSggList(filters.sd) : Promise.resolve([]),
    fetchPropertiesForMap(filters, 1000),
  ]);

  const activeFilters = buildActiveFilters(filters, {
    courts, sd: sdList, sgg: sggList, usageLcl,
  });

  return (
    <div className="space-y-3 min-w-0">
      <FilterSidebar
        courts={courts}
        sdList={sdList}
        usageLcl={usageLcl}
        initial={filters}
      />
      <div className="text-sm text-muted-foreground">
        좌표가 있는 매물 <strong>{rows.length}</strong>건 (최대 1,000개 표시 — 더 많으면 필터로 좁히세요)
      </div>
      <PropertyMap rows={rows} activeFilters={activeFilters} />
    </div>
  );
}
