"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useT } from "@/lib/i18n-client";

/**
 * 헤더 좌측 목록/지도 nav.
 * 라우트 기반 국가 컨텍스트 자동 감지:
 *   - /jp, /jp/* → 일본 (지도=/jp, 목록=/jp/list)
 *   - 그 외       → 한국 (지도=/,   목록=/list)
 *
 * 지도가 기본 랜딩 — 탭 순서도 지도 → 목록.
 *
 * 현재 페이지에 해당하는 탭은 활성 스타일 적용.
 */
export function PrimaryNav() {
  const pathname = usePathname() ?? "/";
  const isJp = pathname === "/jp" || pathname.startsWith("/jp/");
  const t = useT();

  const mapHref = isJp ? "/jp" : "/";
  const listHref = isJp ? "/jp/list" : "/list";

  const isMapActive = pathname === mapHref;
  const isListActive = isJp
    ? pathname === "/jp/list" || pathname.startsWith("/jp/p/") || pathname === "/jp/about"
    : pathname === "/list" || pathname.startsWith("/p/");
  // 최근 낙찰 탭 — 한·일 모두 (일본은 BIT 開札結果 수집 후 노출)
  const soldHref = isJp ? "/jp/sold" : "/sold";
  const isSoldActive = pathname === soldHref;

  // shrink-0 + whitespace-nowrap 필수 — 없으면 좁은 화면에서 flex 가
  // "최근 낙찰" 을 세로로 접는다(모바일 헤더 깨짐의 직접 원인).
  const cls = (active: boolean) =>
    "rounded-md px-1.5 sm:px-3 py-1.5 transition shrink-0 whitespace-nowrap " +
    (active
      ? "bg-muted text-foreground font-semibold"
      : "text-muted-foreground hover:bg-muted hover:text-foreground");

  return (
    <nav className="flex items-center gap-0 sm:gap-1 text-sm min-w-0 overflow-x-auto no-scrollbar">
      <Link href={mapHref} className={cls(isMapActive)}>{t("nav.map")}</Link>
      <Link href={listHref} className={cls(isListActive)}>{t("nav.list")}</Link>
      <Link href={soldHref} className={cls(isSoldActive)}>
        {/* 모바일은 짧은 라벨 — "최근 낙찰" 은 390px 헤더에서 잘린다 */}
        <span className="sm:hidden">{t("nav.sold_short")}</span>
        <span className="hidden sm:inline">{t("nav.sold")}</span>
      </Link>
    </nav>
  );
}
