import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import {
  type JpFilters,
  SALE_CLS_OPTIONS, STATUS_OPTIONS, CASE_KIND_OPTIONS,
} from "@/lib/jp-filters";

type Props = {
  action: string;                           // "/jp" or "/jp/map"
  filters: JpFilters;
  prefs: { code: string; name: string }[];
  courts: { code: string; name: string }[];
};

/**
 * 일본 매물 필터 — 목록·지도 양쪽에서 동일하게 사용.
 * Server component (form submit으로 URL 변경) — 클라이언트 JS 불필요.
 */
export function JpFilterBar({ action, filters, prefs, courts }: Props) {
  return (
    <Card>
      <CardContent className="p-3">
        <form method="get" action={action} className="grid grid-cols-2 sm:grid-cols-12 gap-2 text-sm">
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
          <select name="case_kind" defaultValue={filters.case_kind ?? ""}
                  className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">사건 종류 — 전체</option>
            {CASE_KIND_OPTIONS.map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>

          <input name="price_min" type="number" placeholder="가격 최저 (円)"
                 defaultValue={filters.price_min ?? ""}
                 className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
          <input name="price_max" type="number" placeholder="가격 최고 (円)"
                 defaultValue={filters.price_max ?? ""}
                 className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
          <input name="q" placeholder="주소 / 사건번호"
                 defaultValue={filters.q ?? ""}
                 className="sm:col-span-4 h-9 rounded-md border bg-background px-2 text-sm" />

          {/* 체크박스 그룹 */}
          <div className="sm:col-span-3 flex items-center gap-3 text-xs">
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="yen_10k" value="1"
                     defaultChecked={filters.yen_10k === "1"} />
              <span>⚠ 1万円 함정만</span>
            </label>
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="has_pdf" value="1"
                     defaultChecked={filters.has_pdf === "1"} />
              <span>📑 三点セット 보유</span>
            </label>
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="with_geo" value="1"
                     defaultChecked={filters.with_geo === "1"} />
              <span>🗺 좌표 보유만</span>
            </label>
          </div>

          {/* sort/dir 보존 — hidden */}
          {filters.sort && <input type="hidden" name="sort" value={filters.sort} />}
          {filters.dir && <input type="hidden" name="dir" value={filters.dir} />}

          <button type="submit"
                  className={cn(buttonVariants({ size: "sm" }), "sm:col-span-2 h-9")}>
            검색
          </button>

          <a href={action}
             className={cn(buttonVariants({ variant: "outline", size: "sm" }), "sm:col-span-2 h-9")}>
            초기화
          </a>
        </form>
      </CardContent>
    </Card>
  );
}
