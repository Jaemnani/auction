"use client";

import { usePathname } from "next/navigation";
import { useAreaUnit } from "@/lib/area-unit";
import { localeFromPath } from "@/lib/i18n";

export function AreaUnitToggle() {
  const { unit, toggle } = useAreaUnit();
  const locale = localeFromPath(usePathname());
  // 한국 = 평, 일본 = 坪 (음 つぼ). 동일 단위 1 = 3.305785㎡.
  const pyeongLabel = locale === "ja" ? "坪" : "평";
  const title = locale === "ja"
    ? "面積単位の切替 (㎡ ↔ 坪)"
    : "면적 단위 전환 (㎡ ↔ 평)";
  return (
    <button
      type="button"
      onClick={toggle}
      title={title}
      aria-label={title}
      className="inline-flex items-center rounded-md border bg-background hover:bg-muted px-2 py-1 text-xs font-medium tabular-nums"
    >
      <span className={unit === "sqm" ? "font-bold" : "text-muted-foreground"}>㎡</span>
      <span className="mx-1 text-muted-foreground">|</span>
      <span className={unit === "pyeong" ? "font-bold" : "text-muted-foreground"}>{pyeongLabel}</span>
    </button>
  );
}
