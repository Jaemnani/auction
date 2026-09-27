"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 국가 선택 토글 — 헤더 우측. 라우트 기반:
 *   - /, /list, /p/* → 한국 (KR)
 *   - /jp, /jp/list, /jp/p/* → 일본 (JP)
 */
export function CountryToggle() {
  const pathname = usePathname() ?? "/";
  const isJp = pathname === "/jp" || pathname.startsWith("/jp/");

  // 같은 페이지의 카운터파트 — 매핑 단순화: 그냥 / 또는 /jp (각국 지도 = 기본 랜딩) 로 이동
  const krHref = "/";
  const jpHref = "/jp";

  return (
    <div className="inline-flex items-center rounded-md border bg-background overflow-hidden text-[11px] sm:text-xs shrink-0">
      <Link
        href={krHref}
        className={
          "flex items-center gap-1 px-1.5 sm:px-2 py-1 transition whitespace-nowrap " +
          (!isJp
            ? "bg-primary text-primary-foreground font-semibold"
            : "text-muted-foreground hover:bg-muted hover:text-foreground")
        }
      >
        <span aria-hidden>🇰🇷</span>
        <span className="hidden min-[400px]:inline">한국</span>
      </Link>
      <Link
        href={jpHref}
        className={
          "flex items-center gap-1 px-1.5 sm:px-2 py-1 transition whitespace-nowrap " +
          (isJp
            ? "bg-primary text-primary-foreground font-semibold"
            : "text-muted-foreground hover:bg-muted hover:text-foreground")
        }
      >
        <span aria-hidden>🇯🇵</span>
        <span className="hidden min-[400px]:inline">日本</span>
      </Link>
    </div>
  );
}
