"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import maplibregl, { Map as MlMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

const JAPAN_BOUNDS: [[number, number], [number, number]] = [
  [122.0, 24.0],
  [153.0, 46.0],
];
// 지도 시작 위치 — 도쿄都庁. 일본 매물의 대부분이 関東권에 집중 → 도쿄에서 시작.
// (이전엔 일본 중심 [138, 36.5] → 첫 화면이 太平洋 위로 보임)
const DEFAULT_CENTER: [number, number] = [139.6917, 35.6895];
const DEFAULT_ZOOM = 10;
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

/** Haversine distance in meters between two lng/lat. */
function distanceM(lng1: number, lat1: number, lng2: number, lat2: number): number {
  const R = 6371000;
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLng = ((lng2 - lng1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLng / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

type CircleSel = {
  centerLng: number;
  centerLat: number;
  radiusM: number;
} | null;

export function JpPropertyMap({ rows }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  // 원형 선택 상태
  const [drawMode, setDrawMode] = useState(false);
  const [circle, setCircle] = useState<CircleSel>(null);
  // 현재 드래그 중인 임시 원 (px 좌표) — SVG 미리보기용
  const [drawing, setDrawing] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  // 원 안 매물만 (drawMode + circle 있을 때)
  const filteredRows = useMemo(() => {
    if (!circle) return rows;
    return rows.filter(
      (r) => distanceM(circle.centerLng, circle.centerLat, r.longitude, r.latitude) <= circle.radiusM,
    );
  }, [rows, circle]);

  const pointsKey = useMemo(
    () => filteredRows.map((r) => r.sale_unit_id).join(","),
    [filteredRows],
  );

  // map 인스턴스 1회 생성
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      // 항상 도쿄에서 시작 — 일본 매물 대부분이 関東권. 첫 화면에 즉시 마커 보임.
      center: DEFAULT_CENTER,
      zoom: DEFAULT_ZOOM,
      fitBoundsOptions: { padding: 40 },
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");
    map.once("load", () => map.resize());
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // drawMode 변경 시 maplibre dragPan / scrollZoom 토글
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    if (drawMode) {
      map.dragPan.disable();
      map.boxZoom.disable();
      map.dragRotate.disable();
    } else {
      map.dragPan.enable();
      map.boxZoom.enable();
      map.dragRotate.enable();
    }
  }, [drawMode]);

  // 마커 렌더 — filteredRows 기준
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    for (const m of markersRef.current) m.remove();
    markersRef.current = [];

    if (filteredRows.length === 0) return;

    for (const r of filteredRows) {
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
      const marker = new maplibregl.Marker({ color: "#c2410c" })
        .setLngLat([r.longitude, r.latitude])
        .setPopup(new Popup({ offset: 18, closeButton: true, maxWidth: "300px" }).setHTML(popupHtml))
        .addTo(map);
      markersRef.current.push(marker);
    }

    // 원 안 마커가 있고 사용자가 그린 직후라면 fit
    if (circle && filteredRows.length > 0) {
      const bounds = new maplibregl.LngLatBounds();
      for (const r of filteredRows) bounds.extend([r.longitude, r.latitude]);
      map.fitBounds(bounds, { padding: 60, maxZoom: 14, duration: 600 });
    }
  }, [pointsKey, filteredRows, circle]);

  // 오버레이 마우스 이벤트 — drawMode 시에만 활성
  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (!drawMode) return;
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setDrawing({ x0: x, y0: y, x1: x, y1: y });
    setCircle(null);  // 새 원 시작 시 이전 원 클리어
  }, [drawMode]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!drawing) return;
    const rect = e.currentTarget.getBoundingClientRect();
    setDrawing({
      x0: drawing.x0,
      y0: drawing.y0,
      x1: e.clientX - rect.left,
      y1: e.clientY - rect.top,
    });
  }, [drawing]);

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    if (!drawing || !mapRef.current) return;
    const map = mapRef.current;
    const rect = e.currentTarget.getBoundingClientRect();
    const x1 = e.clientX - rect.left;
    const y1 = e.clientY - rect.top;
    // px → lng/lat 변환
    const center = map.unproject([drawing.x0, drawing.y0]);
    const edge = map.unproject([x1, y1]);
    const radiusM = distanceM(center.lng, center.lat, edge.lng, edge.lat);
    setDrawing(null);
    if (radiusM > 50) {  // 너무 작으면 무시 (실수 클릭)
      setCircle({
        centerLng: center.lng,
        centerLat: center.lat,
        radiusM,
      });
    } else {
      setCircle(null);
    }
    // 그린 후 즉시 drawMode 해제 (재드래그하려면 다시 토글)
    setDrawMode(false);
  }, [drawing]);

  // 임시 원 SVG (드래그 중) — px 좌표 기준
  const drawingPxRadius = drawing
    ? Math.hypot(drawing.x1 - drawing.x0, drawing.y1 - drawing.y0)
    : 0;

  return (
    <div className="relative h-[70vh] min-h-[500px] rounded-lg border overflow-hidden">
      <div ref={containerRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />

      {/* 마우스 이벤트 오버레이 — drawMode에서만 pointer-events 활성 */}
      <div
        className="absolute inset-0 z-20"
        style={{
          cursor: drawMode ? "crosshair" : "auto",
          pointerEvents: drawMode ? "auto" : "none",
        }}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
      >
        {drawing && (
          <svg className="absolute inset-0 w-full h-full" style={{ pointerEvents: "none" }}>
            <circle
              cx={drawing.x0}
              cy={drawing.y0}
              r={drawingPxRadius}
              fill="rgba(194, 65, 12, 0.15)"
              stroke="#c2410c"
              strokeWidth={2}
              strokeDasharray="6 4"
            />
          </svg>
        )}
      </div>

      {/* 컨트롤 오버레이 */}
      <div className="absolute top-2 left-2 flex items-center gap-2 z-30">
        <div className="rounded-md bg-card/95 backdrop-blur px-3 py-1.5 text-xs border shadow">
          🇯🇵 매물 <strong>{filteredRows.length}</strong>건
          {circle && (
            <span className="text-muted-foreground ml-1">
              / 전체 {rows.length}건 (반경 {(circle.radiusM / 1000).toFixed(1)}km)
            </span>
          )}
        </div>
        <button
          type="button"
          onClick={() => {
            if (circle) {
              setCircle(null);
              setDrawMode(false);
            } else {
              setDrawMode((m) => !m);
            }
          }}
          className={
            "rounded-md px-3 py-1.5 text-xs border shadow font-medium " +
            (drawMode
              ? "bg-orange-600 text-white border-orange-600"
              : circle
                ? "bg-muted text-foreground border-border hover:bg-muted/80"
                : "bg-card text-foreground border-border hover:bg-muted")
          }
        >
          {drawMode ? "📍 드래그하여 원 그리기" : circle ? "✕ 원형 선택 해제" : "⭕ 원형 영역 선택"}
        </button>
      </div>
    </div>
  );
}
