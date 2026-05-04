"use client";

import { convertAreaText, useAreaUnit } from "@/lib/area-unit";

/** 텍스트 안의 "N㎡" 패턴을 현재 면적 단위에 맞게 변환해서 표시. */
export function AreaText({
  children, className,
}: { children: string | null | undefined; className?: string }) {
  const { unit } = useAreaUnit();
  if (!children) return null;
  return <span className={className}>{convertAreaText(children, unit)}</span>;
}
