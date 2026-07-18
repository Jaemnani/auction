"use client";

import { useEffect, useRef, useState } from "react";
import {
  GOOGLE_MAPS_API_KEY,
  GOOGLE_MAP_ID,
  loadGoogleMaps,
  makePin,
} from "@/lib/google-maps";
import { MapKeyNotice } from "@/components/map-key-notice";

type Props = {
  lng: number;
  lat: number;
  /** 도로명 주소가 있으면 외부 지도 검색에 사용 (권장). */
  addr?: string | null;
};

export function PropertyLocation({ lng, lat, addr }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<google.maps.Map | null>(null);
  const markerRef = useRef<google.maps.marker.AdvancedMarkerElement | null>(null);
  const [mapError, setMapError] = useState<string | null>(null);

  useEffect(() => {
    if (!GOOGLE_MAPS_API_KEY || !ref.current) return;
    let cancelled = false;

    loadGoogleMaps()
      .then(() => {
        if (cancelled || !ref.current) return;
        if (mapRef.current) {
          // 좌표만 바뀐 경우 — 지도 재생성 없이 이동 (Google Maps는 destroy 불가)
          mapRef.current.setCenter({ lat, lng });
          if (markerRef.current) markerRef.current.position = { lat, lng };
          return;
        }
        const map = new google.maps.Map(ref.current, {
          mapId: GOOGLE_MAP_ID,
          center: { lat, lng },
          zoom: 16,
          gestureHandling: "greedy",
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          scaleControl: true,
        });
        markerRef.current = new google.maps.marker.AdvancedMarkerElement({
          map,
          position: { lat, lng },
          content: makePin("#dc2626").element,
        });
        mapRef.current = map;
      })
      .catch((e: unknown) => {
        if (!cancelled) setMapError(e instanceof Error ? e.message : String(e));
      });

    return () => { cancelled = true; };
  }, [lng, lat]);

  // 컴포넌트 언마운트 시 정리 (StrictMode 재마운트 대비 DOM 비움)
  useEffect(() => {
    const container = ref.current;
    return () => {
      if (mapRef.current) google.maps.event.clearInstanceListeners(mapRef.current);
      if (markerRef.current) markerRef.current.map = null;
      markerRef.current = null;
      mapRef.current = null;
      if (container) container.innerHTML = "";
    };
  }, []);

  // 외부 지도 URL — 주소가 있으면 텍스트 검색(핀 + 정보 표시 잘됨), 없으면 좌표.
  // 좌표 폴백도 각 앱에서 핀이 찍히는 형식 사용:
  //   네이버: /p/search/{lat},{lng} — 좌표 문자열 검색이 정확히 그 지점에 핀
  //   카카오: /link/map/{이름},{lat},{lng} — 라벨 핀
  //   구글:   ?q={lat},{lng} — 핀
  const q = addr?.trim();
  const naver = q
    ? `https://map.naver.com/p/search/${encodeURIComponent(q)}`
    : `https://map.naver.com/p/search/${encodeURIComponent(`${lat},${lng}`)}`;
  const kakao = q
    ? `https://map.kakao.com/?q=${encodeURIComponent(q)}`
    : `https://map.kakao.com/link/map/매물,${lat},${lng}`;
  const google_ = q
    ? `https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(q)}`
    : `https://www.google.com/maps?q=${lat},${lng}`;

  return (
    <div className="space-y-2">
      {!GOOGLE_MAPS_API_KEY || mapError ? (
        <MapKeyNotice error={mapError} className="h-[280px] min-h-[280px]" />
      ) : (
        <div ref={ref} className="h-[280px] w-full rounded-md border bg-muted/20" />
      )}
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="text-muted-foreground text-xs">
          {q ? "주소로 외부 지도 열기:" : "좌표로 외부 지도 열기:"}
        </span>
        <a href={naver}   target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">네이버지도</a>
        <span className="text-muted-foreground">·</span>
        <a href={kakao}   target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">카카오맵</a>
        <span className="text-muted-foreground">·</span>
        <a href={google_} target="_blank" rel="noopener noreferrer" className="text-blue-600 hover:underline">구글맵</a>
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {lat.toFixed(5)}, {lng.toFixed(5)}
        </span>
      </div>
    </div>
  );
}
