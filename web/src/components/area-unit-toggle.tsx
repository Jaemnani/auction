"use client";

import { useAreaUnit } from "@/lib/area-unit";

export function AreaUnitToggle() {
  const { unit, toggle } = useAreaUnit();
  return (
    <button
      type="button"
      onClick={toggle}
      title="면적 단위 전환 (㎡ ↔ 평)"
      className="inline-flex items-center rounded-md border bg-background hover:bg-muted px-2 py-1 text-xs font-medium tabular-nums"
    >
      <span className={unit === "sqm" ? "font-bold" : "text-muted-foreground"}>㎡</span>
      <span className="mx-1 text-muted-foreground">|</span>
      <span className={unit === "pyeong" ? "font-bold" : "text-muted-foreground"}>평</span>
    </button>
  );
}
