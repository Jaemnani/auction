import { Pagination } from "@/components/pagination";
import { PropertyTable } from "@/components/property-table";
import { fetchProperties, fetchUsageList } from "@/lib/queries";
import { parseFiltersFromSearchParams } from "@/lib/url";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "최근 낙찰 매물",
  description: "최근 30일 내 낙찰된 법원경매 매물 — 낙찰가·매각가율 확인",
};

/**
 * 최근 낙찰 매물 — 종결(낙찰) 후 30일 유예창(RLS 0018) 안의 매물만.
 * 이후엔 목록·상세 모두 자동 비공개되고, 낙찰 데이터는 sale_results에 영구 보존.
 */
export default async function SoldPage(props: PageProps<"/sold">) {
  const sp = await props.searchParams;
  const filters = { ...parseFiltersFromSearchParams(sp), status: "sold_only" as const };

  const [usageLcl, list] = await Promise.all([
    fetchUsageList(1),
    fetchProperties(filters),
  ]);

  const usageNames: Record<string, string> = {};
  for (const u of usageLcl) usageNames[u.code] = u.name;

  return (
    <div className="space-y-4 min-w-0">
      <div className="rounded-lg border bg-card p-4">
        <h1 className="text-lg font-semibold">최근 낙찰 매물</h1>
        <p className="text-sm text-muted-foreground mt-1">
          최근 30일 안에 낙찰(매각)로 종결된 매물입니다. 낙찰가와 감정가 대비 비율을
          확인할 수 있으며, 30일이 지나면 목록에서 내려갑니다.
        </p>
      </div>
      <Pagination
        filters={filters}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        basePath="/sold"
      />
      <PropertyTable rows={list.rows} usageNames={usageNames} />
      <Pagination
        filters={filters}
        page={list.page}
        pageSize={list.pageSize}
        total={list.total}
        basePath="/sold"
      />
    </div>
  );
}
