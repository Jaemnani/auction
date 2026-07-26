import nextDynamic from "next/dynamic";
import { FilterSidebar } from "@/components/filter-sidebar";
import { MapFilterOverlay } from "@/components/map-filter-overlay";
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
  // (제외 키워드/세부분류/파생 칩은 2026-07-26 필터 제거와 함께 삭제)
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
    // 전체 화면 지도 — layout Container의 px-5/py-6을 음수 마진으로 상쇄하고
    // 헤더(h-14) 아래 나머지 viewport 전부를 채움. 필터는 우상단 버튼 → 오버레이.
    <div
      className="relative -mx-5 -my-6 min-w-0 overflow-hidden"
      style={{ height: "calc(100vh - 3.5rem)" }}
    >
      <PropertyMap rows={rows} activeFilters={activeFilters} fill />
      <MapFilterOverlay>
        <FilterSidebar
          courts={courts}
          sdList={sdList}
          usageLcl={usageLcl}
          initial={filters}
        />
      </MapFilterOverlay>
    </div>
  );
}
