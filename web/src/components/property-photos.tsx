"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";

type Photo = { seq: number; kind: string; desc: string; url: string };

export function PropertyPhotos({
  photos,
  countLabel,
  closeLabel = "닫기",
  gridClassName = "grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5",
}: {
  photos: Photo[];
  countLabel?: string;
  closeLabel?: string;
  gridClassName?: string;
}) {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);
  const isOpen = activeIdx !== null;

  // 라이트박스 열림 동안 키보드 탐색 — ←/→ 순환, Esc 닫기
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowRight") {
        setActiveIdx((i) => (i === null ? i : (i + 1) % photos.length));
      } else if (e.key === "ArrowLeft") {
        setActiveIdx((i) => (i === null ? i : (i - 1 + photos.length) % photos.length));
      } else if (e.key === "Escape") {
        setActiveIdx(null);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, photos.length]);

  if (photos.length === 0) return null;

  const active = activeIdx !== null ? photos[activeIdx] : null;

  return (
    <div>
      <div className="text-sm text-muted-foreground mb-2">
        {countLabel ?? `사진 ${photos.length}장`}
      </div>
      <div className={`grid ${gridClassName} gap-2`}>
        {photos.map((ph, i) => (
          <button
            key={ph.seq}
            onClick={() => setActiveIdx(i)}
            className="group relative aspect-[4/3] overflow-hidden rounded-md border bg-muted/30 hover:border-primary transition"
            type="button"
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={ph.url}
              alt={ph.desc || `사진 ${ph.seq}`}
              loading="lazy"
              className="h-full w-full object-cover group-hover:scale-105 transition"
            />
            {ph.kind && (
              <Badge
                variant="secondary"
                className="absolute top-1 left-1 text-caption-xs"
              >
                {ph.kind}
              </Badge>
            )}
            <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1.5 py-0.5 text-caption-xs text-white">
              #{ph.seq}
            </span>
          </button>
        ))}
      </div>

      {/* 라이트박스 */}
      {active && activeIdx !== null && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 cursor-zoom-out"
          onClick={() => setActiveIdx(null)}
          role="dialog"
        >
          <div className="relative max-w-6xl max-h-[90vh] w-full">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={active.url}
              alt={active.desc || `사진 ${active.seq}`}
              className="max-h-[90vh] w-full object-contain"
              onClick={(e) => e.stopPropagation()}
            />
            <div className="absolute bottom-2 left-2 text-white text-sm bg-black/60 rounded px-2 py-1">
              {activeIdx + 1}/{photos.length} · #{active.seq}
              {active.kind && ` · ${active.kind}`}
              {active.desc && <span className="opacity-80"> · {active.desc}</span>}
            </div>
            {photos.length > 1 && (
              <>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setActiveIdx((activeIdx - 1 + photos.length) % photos.length);
                  }}
                  className="absolute left-2 top-1/2 -translate-y-1/2 rounded-full bg-black/60 text-white w-10 h-10 text-xl hover:bg-black/80"
                  type="button"
                  aria-label="previous"
                >
                  ‹
                </button>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setActiveIdx((activeIdx + 1) % photos.length);
                  }}
                  className="absolute right-2 top-1/2 -translate-y-1/2 rounded-full bg-black/60 text-white w-10 h-10 text-xl hover:bg-black/80"
                  type="button"
                  aria-label="next"
                >
                  ›
                </button>
              </>
            )}
            <button
              onClick={() => setActiveIdx(null)}
              className="absolute top-2 right-2 rounded-full bg-black/60 text-white px-3 py-1 text-sm hover:bg-black/80"
              type="button"
            >
              {closeLabel}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
