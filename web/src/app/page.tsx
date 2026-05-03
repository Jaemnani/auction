import { FilterSidebar } from "@/components/filter-sidebar";
import { Pagination } from "@/components/pagination";
import { PropertyTable } from "@/components/property-table";
import {
  fetchCourts, fetchProperties, fetchSdList, fetchUsageList,
} from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";

export const dynamic = "force-dynamic";

export default async function Home(props: PageProps<"/">) {
  const sp = await props.searchParams;
  const filters = parseFiltersFromSearchParams(sp);

  const [courts, sdList, usageLcl, list] = await Promise.all([
    fetchCourts(),
    fetchSdList(),
    fetchUsageList(1),
    fetchProperties(filters),
  ]);

  const usageNames: Record<string, string> = {};
  for (const u of usageLcl) usageNames[u.code] = u.name;

  return (
    <div className="space-y-4 min-w-0">
      <FilterSidebar
        courts={courts}
        sdList={sdList}
        usageLcl={usageLcl}
        initial={filters}
      />
      <Pagination
        filters={filters}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        basePath="/"
      />
      <PropertyTable rows={list.rows} usageNames={usageNames} />
      <Pagination
        filters={filters}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        basePath="/"
      />
    </div>
  );
}
