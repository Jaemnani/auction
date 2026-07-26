"use client";

import { useState } from "react";

/**
 * 전체 화면 지도 위 플로팅 검색·필터 패널.
 * 버튼(우상단)을 누르면 FilterSidebar(children)가 오버레이로 열림 —
 * 필터의 "검색"이 URL을 갱신하면 서버 페이지가 새 rows로 재렌더된다.
 */
export function MapFilterOverlay({ children }: React.PropsWithChildren) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className={
          "absolute right-3 top-3 z-40 rounded-md border px-3 py-1.5 text-sm font-medium shadow-sm " +
          (open
            ? "bg-primary text-primary-foreground border-primary"
            : "bg-background/95 hover:bg-muted")
        }
      >
        {open ? "✕ 필터 닫기" : "🔍 검색 · 필터"}
      </button>
      {open && (
        <div className="absolute right-3 top-14 z-40 w-[min(640px,calc(100vw-24px))] max-h-[calc(100%-72px)] overflow-y-auto rounded-lg shadow-xl">
          {children}
        </div>
      )}
    </>
  );
}
