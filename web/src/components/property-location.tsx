"use client";

import { useEffect, useRef } from "react";
import maplibregl, { Map as MlMap, Marker } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

type Props = {
  lng: number;
  lat: number;
  /** 도로명 주소가 있으면 외부 지도 검색에 사용 (권장). */
  addr?: string | null;
};

export function PropertyLocation({ lng, lat, addr }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MlMap | null>(null);

  useEffect(() => {
    if (!ref.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: ref.current,
      style: "https://tiles.openfreemap.org/styles/liberty",
      center: [lng, lat],
      zoom: 16,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({}), "top-right");
    new Marker({ color: "#dc2626" }).setLngLat([lng, lat]).addTo(map);
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; };
  }, [lng, lat]);

  // 외부 지도 URL — 주소가 있으면 텍스트 검색(핀 + 정보 표시 잘됨), 없으면 좌표
  const q = addr?.trim();
  const naver = q
    ? `https://map.naver.com/p/search/${encodeURIComponent(q)}`
    : `https://map.naver.com/p/?c=${lng},${lat},17,0,0,0,0`;
  const kakao = q
    ? `https://map.kakao.com/?q=${encodeURIComponent(q)}`
    : `https://map.kakao.com/link/map/매물,${lat},${lng}`;
  const google = q
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`
    : `https://www.google.com/maps?q=${lat},${lng}`;

  return (
    <div className="space-y-2">
      <div ref={ref} className="h-[280px] w-full rounded-md border bg-muted/20" />
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground text-xs">
          {q ? "주소로 외부 지도 열기:" : "좌표로 외부 지도 열기:"}
        </span>
        <a href={naver}  target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">네이버지도</a>
        <span className="text-muted-foreground">·</span>
        <a href={kakao}  target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">카카오맵</a>
        <span className="text-muted-foreground">·</span>
        <a href={google} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">구글맵</a>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {lat.toFixed(5)}, {lng.toFixed(5)}
        </span>
      </div>
    </div>
  );
}
