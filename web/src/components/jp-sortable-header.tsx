"use client";

import Link from "next/link";
import { useSearchParams, usePathname } from "next/navigation";

type Props = {
  field: string;
  label: string;
  className?: string;
  align?: "left" | "right";
};

/**
 * 일본 목록 테이블 헤더 — 클릭 시 sort/dir 토글.
 * URL: ?sort=<field>&dir=asc|desc
 * 같은 field 다시 클릭 시 asc ↔ desc 토글.
 * 다른 field 클릭 시 asc로 시작.
 */
export function JpSortableHeader({ field, label, className = "", align = "left" }: Props) {
  const pathname = usePathname() ?? "/jp";
  const sp = useSearchParams();
  const curSort = sp?.get("sort");
  const curDir = sp?.get("dir");
  const isActive = curSort === field;
  const nextDir = isActive && curDir === "asc" ? "desc" : "asc";

  // 빌드 URL — page 리셋
  const params = new URLSearchParams(sp?.toString() ?? "");
  params.set("sort", field);
  params.set("dir", nextDir);
  params.delete("page");
  const href = `${pathname}?${params.toString()}`;

  const arrow = isActive ? (curDir === "desc" ? "▼" : "▲") : "↕";

  return (
    <Link
      href={href}
      className={
        `inline-flex items-center gap-1 cursor-pointer select-none hover:text-primary ${align === "right" ? "justify-end" : ""} ${className}`
      }
    >
      <span>{label}</span>
      <span className={isActive ? "text-primary text-xs" : "text-muted-foreground text-[10px]"}>
        {arrow}
      </span>
    </Link>
  );
}
