import { Card, CardContent } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { buttonVariants } from "@/components/ui/button";
import {
  type JpFilters,
  SALE_CLS_OPTIONS, STATUS_OPTIONS, CASE_KIND_OPTIONS,
} from "@/lib/jp-filters";
import { getT } from "@/lib/i18n-server";

type Props = {
  action: string;                           // "/jp" or "/jp/map"
  filters: JpFilters;
  prefs: { code: string; name: string }[];
  courts: { code: string; name: string }[];
  /** 三点セット PDF 통계 — 토글 옆에 비율 표시 (현재 1069/1073 ≈ 99.6%로 거의 전부).
   *  사용자가 "필터 효과 없음 → 오류"로 인식하는 것 방지. */
  pdfStats?: { total: number; withPdf: number };
};

/**
 * 일본 매물 필터 — 목록·지도 양쪽에서 동일하게 사용.
 * Server component (form submit으로 URL 변경) — 클라이언트 JS 불필요.
 * 라벨은 lib/i18n으로 자동 일본어 (path /jp/* 컨텍스트).
 */
export async function JpFilterBar({ action, filters, prefs, courts, pdfStats }: Props) {
  const t = await getT();
  const pdfRatio = pdfStats && pdfStats.total > 0
    ? Math.round((pdfStats.withPdf / pdfStats.total) * 1000) / 10  // 소수점 1자리
    : null;
  return (
    <Card>
      <CardContent className="p-3">
        <form method="get" action={action} className="grid grid-cols-2 sm:grid-cols-12 gap-2 text-sm">
          <select name="pref" defaultValue={filters.pref ?? ""}
                  aria-label={t("filter.pref")}
                  className="sm:col-span-3 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">{t("filter.pref")} — {t("common.all")}</option>
            {prefs.map((p) => (
              <option key={p.code} value={p.code}>{p.code} {p.name}</option>
            ))}
          </select>
          <select name="court" defaultValue={filters.court ?? ""}
                  aria-label={t("filter.court")}
                  className="sm:col-span-3 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">{t("filter.court")} — {t("common.all")}</option>
            {courts.map((c) => (
              <option key={c.code} value={c.code}>{c.name}</option>
            ))}
          </select>
          <select name="sale_cls" defaultValue={filters.sale_cls ?? ""}
                  aria-label={t("filter.sale_cls")}
                  className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">{t("filter.sale_cls")} — {t("common.all")}</option>
            {SALE_CLS_OPTIONS.map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
          <select name="status" defaultValue={filters.status ?? ""}
                  aria-label={t("filter.status")}
                  className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">{t("filter.status")} — {t("common.all")}</option>
            {STATUS_OPTIONS.map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>
          <select name="case_kind" defaultValue={filters.case_kind ?? ""}
                  aria-label={t("filter.case_kind")}
                  className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm">
            <option value="">{t("filter.case_kind")} — {t("common.all")}</option>
            {CASE_KIND_OPTIONS.map((o) => (
              <option key={o.code} value={o.code}>{o.label}</option>
            ))}
          </select>

          <input name="price_min" type="number"
                 placeholder={`${t("filter.price_min")} (円)`}
                 aria-label={t("filter.price_min")}
                 defaultValue={filters.price_min ?? ""}
                 className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
          <input name="price_max" type="number"
                 placeholder={`${t("filter.price_max")} (円)`}
                 aria-label={t("filter.price_max")}
                 defaultValue={filters.price_max ?? ""}
                 className="sm:col-span-2 h-9 rounded-md border bg-background px-2 text-sm" />
          <input name="q"
                 placeholder={t("filter.kw")}
                 aria-label={t("filter.kw")}
                 defaultValue={filters.q ?? ""}
                 className="sm:col-span-4 h-9 rounded-md border bg-background px-2 text-sm" />

          {/* 체크박스 그룹 */}
          <div className="sm:col-span-3 flex items-center gap-3 text-xs">
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="yen_10k" value="1"
                     defaultChecked={filters.yen_10k === "1"} />
              <span>{t("filter.yen10k")}</span>
            </label>
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="has_pdf" value="1"
                     defaultChecked={filters.has_pdf === "1"} />
              <span>{t("filter.has_pdf")}</span>
              {pdfStats && (
                <span className="text-muted-foreground">
                  ({pdfStats.withPdf.toLocaleString()}/{pdfStats.total.toLocaleString()}
                  {pdfRatio != null ? ` · ${pdfRatio}%` : ""})
                </span>
              )}
            </label>
            <label className="inline-flex items-center gap-1 cursor-pointer select-none">
              <input type="checkbox" name="with_geo" value="1"
                     defaultChecked={filters.with_geo === "1"} />
              <span>{t("filter.with_geo")}</span>
            </label>
          </div>

          {/* sort/dir 보존 — hidden */}
          {filters.sort && <input type="hidden" name="sort" value={filters.sort} />}
          {filters.dir && <input type="hidden" name="dir" value={filters.dir} />}

          <button type="submit"
                  className={cn(buttonVariants({ size: "sm" }), "sm:col-span-2 h-9")}>
            {t("common.apply")}
          </button>

          <a href={action}
             className={cn(buttonVariants({ variant: "outline", size: "sm" }), "sm:col-span-2 h-9")}>
            {t("common.reset")}
          </a>
        </form>
      </CardContent>
    </Card>
  );
}
