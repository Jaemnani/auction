"use client";

import { useState } from "react";

/**
 * 지도 위치 검색 박스 — Google Geocoder (core JS API, 추가 라이브러리 불필요).
 * 주소·지명 입력 → 첫 결과의 viewport로 지도 이동. 이동 후 idle 이 발생하므로
 * 기존 자동 새로고침/"이 지역에서 검색" 흐름이 그대로 이어진다.
 */
export function MapSearchBox({ region, onLocate }: {
  region: "kr" | "jp";
  onLocate: (r: {
    location: google.maps.LatLngLiteral;
    viewport: google.maps.LatLngBounds | null;
    label: string;
  }) => void;
}) {
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const search = () => {
    const query = q.trim();
    if (!query || busy) return;
    if (typeof google === "undefined" || !google.maps?.Geocoder) return;
    setBusy(true);
    setError(null);
    new google.maps.Geocoder().geocode(
      { address: query, region },
      (results, status) => {
        setBusy(false);
        if (status === "OK" && results && results[0]) {
          const g = results[0].geometry;
          onLocate({
            location: g.location.toJSON(),
            viewport: g.viewport ?? null,
            label: results[0].formatted_address ?? query,
          });
        } else if (status === "ZERO_RESULTS") {
          setError("검색 결과가 없습니다");
        } else {
          // REQUEST_DENIED 등 — 키에 Geocoding API 미활성일 때
          setError("위치 검색 사용 불가 (Geocoding API 설정 확인)");
        }
      },
    );
  };

  return (
    // 지도를 덜 가리도록 컴팩트 — 모바일은 우상단 필터 버튼과 같은 줄이라 더 좁게
    <div className="rounded-md bg-background/95 border px-2 py-1 text-caption-sm shadow-sm w-36 sm:w-44">
      <div className="flex items-center gap-1">
        <input
          value={q}
          onChange={(e) => { setQ(e.target.value); setError(null); }}
          onKeyDown={(e) => e.key === "Enter" && search()}
          placeholder="위치 검색"
          aria-label="위치 검색"
          className="flex-1 min-w-0 bg-transparent outline-none placeholder:text-muted-foreground"
        />
        <button
          type="button"
          onClick={search}
          disabled={busy}
          aria-label="검색"
          className="shrink-0 text-muted-foreground hover:text-foreground disabled:opacity-50"
        >
          {busy ? "…" : "🔍"}
        </button>
      </div>
      {error && <div className="text-red-600 mt-1">{error}</div>}
    </div>
  );
}
