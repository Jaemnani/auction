import { FilterSidebar } from "@/components/filter-sidebar";
import { PropertyMap } from "@/components/property-map";
import {
  fetchCourts, fetchPropertiesForMap, fetchSdList, fetchUsageList,
} from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";

export const dynamic = "force-dynamic";

export default async function MapPage(props: PageProps<"/map">) {
  const sp = await props.searchParams;
  const filters = parseFiltersFromSearchParams(sp);

  const [courts, sdList, usageLcl, rows] = await Promise.all([
    fetchCourts(),
    fetchSdList(),
    fetchUsageList(1),
    fetchPropertiesForMap(filters, 500),
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
        좌표가 있는 매물 <strong>{rows.length}</strong>건 (최대 500개 표시)
      </div>
      <PropertyMap rows={rows} />
    </div>
  );
}
