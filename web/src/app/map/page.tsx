import nextDynamic from "next/dynamic";
import { FilterSidebar } from "@/components/filter-sidebar";
import {
  fetchCourts, fetchPropertiesForMap, fetchSdList, fetchUsageList,
} from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";

// MapLibre 무거운 의존성 — 청크 분리.
const PropertyMap = nextDynamic(() => import("@/components/property-map").then((m) => ({ default: m.PropertyMap })));

export const dynamic = "force-dynamic";

export default async function MapPage(props: PageProps<"/map">) {
  const sp = await props.searchParams;
  const filters = parseFiltersFromSearchParams(sp);

  const [courts, sdList, usageLcl, rows] = await Promise.all([
    fetchCourts(),
    fetchSdList(),
    fetchUsageList(1),
    fetchPropertiesForMap(filters, 1000),
  ]);

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
      <PropertyMap rows={rows} />
    </div>
  );
}
