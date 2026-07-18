"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { makeCountBadgeEl, groupByCoord, CLUSTER_LIST_MAX } from "@/lib/map-cluster";
import {
  GOOGLE_MAPS_API_KEY,
  GOOGLE_MAP_ID,
  loadGoogleMaps,
  createProjectionHelper,
  containerPxToLatLng,
  makePin,
} from "@/lib/google-maps";
import { MapKeyNotice } from "@/components/map-key-notice";

// 지도 시작 위치 — 도쿄都庁. 일본 매물의 대부분이 関東권에 집중 → 도쿄에서 시작.
// (이전엔 일본 중심 [138, 36.5] → 첫 화면이 太平洋 위로 보임)
const DEFAULT_CENTER = { lat: 35.6895, lng: 139.6917 };
const DEFAULT_ZOOM = 10;

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
  const mapRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);
  const projectionRef = useRef<google.maps.OverlayView | null>(null);

  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
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

  // map 인스턴스 1회 생성 (Google Maps는 destroy API가 없어 재생성하지 않음)
  useEffect(() => {
    if (!GOOGLE_MAPS_API_KEY) return;
    if (!containerRef.current || mapRef.current) return;
    let cancelled = false;

    loadGoogleMaps()
      .then(() => {
        if (cancelled || !containerRef.current || mapRef.current) return;
        const map = new google.maps.Map(containerRef.current, {
          mapId: GOOGLE_MAP_ID,
          // 항상 도쿄에서 시작 — 일본 매물 대부분이 関東권. 첫 화면에 즉시 마커 보임.
          center: DEFAULT_CENTER,
          zoom: DEFAULT_ZOOM,
          gestureHandling: "greedy",
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          scaleControl: true,
          clickableIcons: false,
        });
        mapRef.current = map;
        projectionRef.current = createProjectionHelper(map);
        infoWindowRef.current = new google.maps.InfoWindow({ maxWidth: 320 });
        setMapReady(true);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMapError(e instanceof Error ? e.message : String(e));
      });

    const container = containerRef.current;
    return () => {
      cancelled = true;
      if (mapRef.current) google.maps.event.clearInstanceListeners(mapRef.current);
      projectionRef.current?.setMap(null);
      projectionRef.current = null;
      infoWindowRef.current?.close();
      infoWindowRef.current = null;
      markersRef.current.forEach((m) => { m.map = null; });
      markersRef.current = [];
      mapRef.current = null;
      if (container) container.innerHTML = "";
      setMapReady(false);
    };
  }, []);

  // drawMode 변경 시 지도 제스처 토글 (오버레이가 이벤트를 가로채지만 안전망)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.setOptions({
      gestureHandling: drawMode ? "none" : "greedy",
      disableDoubleClickZoom: drawMode,
    });
  }, [drawMode, mapReady]);

  // 마커 렌더 — filteredRows 기준
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady) return;

    markersRef.current.forEach((m) => { m.map = null; });
    markersRef.current = [];
    infoWindowRef.current?.close();

    if (filteredRows.length === 0) return;

    // 같은 좌표에 겹친 매물(예: 같은 맨션·사건의 여러 물건)은 마커가 포개져
    // 클릭 시 엉뚱한 매물이 잡힘 → 좌표별로 묶어 개수 배지 + 선택 목록 팝업.
    const groups = groupByCoord(filteredRows, (r) => r.longitude, (r) => r.latitude);

    const rowCard = (r: JpMapRow) => `
      <div style="font-family:monospace;color:#71717a;font-size:11px">${r.case_no ?? r.sale_unit_id}</div>
      <div style="font-weight:600;margin-top:2px">${r.court_name ?? "—"}</div>
      ${r.address_text ? `<div style="color:#52525b;font-size:11px;margin-top:2px;word-break:keep-all">${r.address_text}</div>` : ""}
      <div style="margin-top:6px">
        <span style="display:inline-block;background:#fed7aa;color:#7c2d12;padding:1px 6px;border-radius:4px;font-size:10px">${r.sale_cls_label ?? "—"}</span>
        <span style="font-family:monospace;margin-left:6px;font-weight:600">${fmtJpy(r.sale_standard_price)}</span>
      </div>
      <a href="/jp/p/${r.sale_unit_id}" style="color:#2563eb;text-decoration:underline;display:inline-block;margin-top:6px">상세 →</a>`;

    for (const gr of groups) {
      const r0 = gr[0];
      let popupHtml: string;
      let content: HTMLElement;
      if (gr.length === 1) {
        popupHtml = `<div style="font-size:12px;min-width:200px">${rowCard(r0)}</div>`;
        content = makePin("#c2410c").element;
      } else {
        const shown = gr.slice(0, CLUSTER_LIST_MAX);
        const more = gr.length - shown.length;
        popupHtml = `<div style="font-size:12px;min-width:220px;max-width:300px;max-height:320px;overflow-y:auto">
             <div style="font-weight:700;margin-bottom:4px">이 위치에 ${gr.length}건</div>
             ${shown.map((r, i) => `<div style="${i > 0 ? "border-top:1px solid #e4e4e7;padding-top:6px;margin-top:6px" : ""}">${rowCard(r)}</div>`).join("")}
             ${more > 0 ? `<div style="color:#71717a;font-size:11px;margin-top:8px;border-top:1px solid #e4e4e7;padding-top:6px">외 ${more}건 (지도 확대·필터로 좁혀보세요)</div>` : ""}
           </div>`;
        content = makeCountBadgeEl(gr.length);
      }
      const marker = new google.maps.marker.AdvancedMarkerElement({
        map,
        position: { lat: r0.latitude, lng: r0.longitude },
        content,
        gmpClickable: true,
      });
      marker.addListener("click", () => {
        const iw = infoWindowRef.current;
        if (!iw) return;
        iw.setContent(popupHtml);
        iw.open({ map, anchor: marker });
      });
      markersRef.current.push(marker);
    }

    // 원 안 마커가 있고 사용자가 그린 직후라면 fit (maxZoom 14 상한)
    if (circle && filteredRows.length > 0) {
      const bounds = new google.maps.LatLngBounds();
      for (const r of filteredRows) bounds.extend({ lat: r.latitude, lng: r.longitude });
      map.fitBounds(bounds, 60);
      google.maps.event.addListenerOnce(map, "idle", () => {
        const z = map.getZoom();
        if (z != null && z > 14) map.setZoom(14);
      });
    }
  }, [pointsKey, filteredRows, circle, mapReady]);

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
    const rect = e.currentTarget.getBoundingClientRect();
    const x1 = e.clientX - rect.left;
    const y1 = e.clientY - rect.top;
    // px → lng/lat 변환
    const center = containerPxToLatLng(projectionRef.current, drawing.x0, drawing.y0);
    const edge = containerPxToLatLng(projectionRef.current, x1, y1);
    setDrawing(null);
    if (!center || !edge) { setDrawMode(false); return; }
    const radiusM = distanceM(center.lng(), center.lat(), edge.lng(), edge.lat());
    if (radiusM > 50) {  // 너무 작으면 무시 (실수 클릭)
      setCircle({
        centerLng: center.lng(),
        centerLat: center.lat(),
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

  if (!GOOGLE_MAPS_API_KEY || mapError) {
    return <MapKeyNotice error={mapError} className="h-[70vh] min-h-[500px]" />;
  }

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
