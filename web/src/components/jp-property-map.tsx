"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { Map as MlMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const JAPAN_BOUNDS: [[number, number], [number, number]] = [
  [122.0, 24.0],   // 沖縄 남서
  [153.0, 46.0],   // 北海道 북동
];
const JAPAN_CENTER: [number, number] = [138.0, 36.5];   // 본토 중앙 근처
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

export type JpMapRow = {
  sale_unit_id: string;
  longitude: number;
  latitude: number;
  case_no: string | null;
  court_name: string | null;
  sale_cls_label: string | null;
  sale_standard_price: number | null;
  address_text: string | null;
};

type Props = {
  rows: JpMapRow[];
};

function fmtJpy(v: number | null | undefined): string {
  if (v == null) return "—";
  return v.toLocaleString("ja-JP") + "円";
}

export function JpPropertyMap({ rows }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  const pointsKey = useMemo(
    () => rows.map((r) => r.sale_unit_id).join(","),
    [rows],
  );

  // map 인스턴스 1회 생성 (한국 PropertyMap 패턴 차용)
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      bounds: rows.length === 0 ? JAPAN_BOUNDS : undefined,
      center: rows.length > 0 ? [rows[0].longitude, rows[0].latitude] : JAPAN_CENTER,
      zoom: rows.length > 0 ? 10 : undefined,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    // 컨테이너 사이즈가 hydration 직후 0일 수 있어 명시 resize
    map.once("load", () => map.resize());

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 마커 렌더 (rows 변경 시 갱신)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // clear
    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    if (rows.length === 0) return;

    for (const r of rows) {
      const popupHtml = `
        <div style="font-size:12px;min-width:200px">
          <div style="font-family:monospace;color:#71717a;font-size:11px">${r.case_no ?? r.sale_unit_id}</div>
          <div style="font-weight:600;margin-top:2px">${r.court_name ?? "—"}</div>
          ${r.address_text ? `<div style="color:#52525b;font-size:11px;margin-top:2px;word-break:keep-all">${r.address_text}</div>` : ""}
          <div style="margin-top:6px">
            <span style="display:inline-block;background:#fed7aa;color:#7c2d12;padding:1px 6px;border-radius:4px;font-size:10px">${r.sale_cls_label ?? "—"}</span>
            <span style="font-family:monospace;margin-left:6px;font-weight:600">${fmtJpy(r.sale_standard_price)}</span>
          </div>
          <a href="/jp/p/${r.sale_unit_id}" style="color:#2563eb;text-decoration:underline;display:inline-block;margin-top:6px">상세 →</a>
        </div>
      `;

      // 한국 PropertyMap과 동일: MapLibre 기본 SVG 핀.
      // 색상은 더 짙은 주황 (orange-700 = #c2410c)으로 일본 시각 구분.
      const marker = new maplibregl.Marker({ color: "#c2410c" })
        .setLngLat([r.longitude, r.latitude])
        .setPopup(new Popup({ offset: 18, closeButton: true, maxWidth: "300px" }).setHTML(popupHtml))
        .addTo(map);
      markersRef.current.push(marker);
    }

    // 마커 모두 들어오게 fit (1개면 zoom 14)
    if (rows.length === 1) {
      map.flyTo({ center: [rows[0].longitude, rows[0].latitude], zoom: 14 });
    } else {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of rows) bounds.extend([r.longitude, r.latitude]);
      map.fitBounds(bounds, { padding: 40, maxZoom: 13, duration: 600 });
    }
  }, [pointsKey, rows]);

  return (
    <div className="relative h-[70vh] min-h-[500px] rounded-lg border overflow-hidden">
      <div ref={containerRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
      <div className="absolute top-2 left-2 rounded-md bg-card/95 backdrop-blur px-3 py-1.5 text-xs border shadow z-10">
        🇯🇵 좌표 매물 <strong>{rows.length}</strong>건
      </div>
    </div>
  );
}
