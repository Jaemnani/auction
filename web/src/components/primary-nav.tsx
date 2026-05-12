"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/lib/i18n-client";

/**
 * 헤더 좌측 목록/지도 nav.
 * 라우트 기반 국가 컨텍스트 자동 감지:
 *   - /jp, /jp/* → 일본 (목록=/jp, 지도=/jp/map)
 *   - 그 외       → 한국 (목록=/,   지도=/map)
 *
 * 현재 페이지에 해당하는 탭은 활성 스타일 적용.
 */
export function PrimaryNav() {
  const pathname = usePathname() ?? "/";
  const isJp = pathname === "/jp" || pathname.startsWith("/jp/");
  const t = useT();

  const listHref = isJp ? "/jp" : "/";
  const mapHref = isJp ? "/jp/map" : "/map";

  const isListActive = isJp
    ? pathname === "/jp" || pathname.startsWith("/jp/p/") || pathname === "/jp/about"
    : pathname === "/" || pathname.startsWith("/p/");
  const isMapActive = isJp
    ? pathname === "/jp/map"
    : pathname === "/map";

  const cls = (active: boolean) =>
    "rounded-md px-3 py-1.5 transition " +
    (active
      ? "bg-muted text-foreground font-semibold"
      : "text-muted-foreground hover:bg-muted hover:text-foreground");

  return (
    <nav className="flex items-center gap-1 text-sm">
      <Link href={listHref} className={cls(isListActive)}>{t("nav.list")}</Link>
      <Link href={mapHref} className={cls(isMapActive)}>{t("nav.map")}</Link>
    </nav>
  );
}
