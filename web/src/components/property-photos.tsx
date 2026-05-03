"use client";

import { useState } from "react";
import { Badge } from "@/components/ui/badge";

type Photo = { seq: number; kind: string; desc: string; url: string };

export function PropertyPhotos({ photos }: { photos: Photo[] }) {
  const [active, setActive] = useState<Photo | null>(null);

  if (photos.length === 0) return null;

  return (
    <div>
      <div className="text-sm text-muted-foreground mb-2">사진 {photos.length}장</div>
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-2">
        {photos.map((ph) => (
          <button
            key={ph.seq}
            onClick={() => setActive(ph)}
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
                className="absolute top-1 left-1 text-[10px]"
              >
                {ph.kind}
              </Badge>
            )}
            <span className="absolute bottom-1 right-1 rounded bg-black/60 px-1.5 py-0.5 text-[10px] text-white">
              #{ph.seq}
            </span>
          </button>
        ))}
      </div>

      {/* 라이트박스 */}
      {active && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4 cursor-zoom-out"
          onClick={() => setActive(null)}
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
              #{active.seq} {active.kind && `· ${active.kind}`}
              {active.desc && <span className="opacity-80"> · {active.desc}</span>}
            </div>
            <button
              onClick={() => setActive(null)}
              className="absolute top-2 right-2 rounded-full bg-black/60 text-white px-3 py-1 text-sm hover:bg-black/80"
              type="button"
            >
              닫기
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
