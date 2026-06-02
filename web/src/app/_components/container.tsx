// DESIGN.md 의 단일 컨테이너 SOT.
// - default: max-w-[1280px] (페이지 기본 — 목록/상세/지도)
// - wide:    max-w-[1440px] (Hero/Marketing 용; 별도 페이지에서만)
// 모든 페이지가 `Container`로 wrap → 페이지마다 mx-auto/max-w/px 반복 제거.

import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

type Variant = "default" | "wide";

const MAX_W: Record<Variant, string> = {
  default: "max-w-[1280px]",
  wide: "max-w-[1440px]",
};

export function Container({
  children,
  className,
  maxW = "default",
}: {
  children: ReactNode;
  className?: string;
  maxW?: Variant;
}) {
  return (
    <div className={cn("w-full", MAX_W[maxW], "mx-auto px-5", className)}>
      {children}
    </div>
  );
}
