"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import maplibregl, { LngLatBoundsLike, Map as MlMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Property } from "@/lib/types";
import { fmtDate, fmtMoneyShort } from "@/lib/format";
import { convertAreaText, useAreaUnit } from "@/lib/area-unit";

/** Haversine distance in meters. */
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

type CircleSel = { centerLng: number; centerLat: number; radiusM: number } | null;

const KOREA_BOUNDS: [[number, number], [number, number]] = [
  [124.5, 33.0],
  [131.9, 38.7],
];
const KOREA_CENTER: [number, number] = [127.8, 36.5];
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

/** usage_lcl_cd 별 마커 색.
 * 사용자가 lcl 필터를 적용 안 한 상태에서도 차량/토지/건물이 한눈에 구분되도록.
 * 4종 + null. legend와 1:1 매칭. */
const LCL_COLORS: Record<string, { color: string; label: string }> = {
  "10000": { color: "#16a34a", label: "토지" },          // green-600
  "20000": { color: "#dc2626", label: "건물" },          // red-600 (기존)
  "30000": { color: "#f97316", label: "차량·운송장비" }, // orange-500
  "40000": { color: "#737373", label: "기타" },          // neutral-500
};
const LCL_UNKNOWN = { color: "#525252", label: "미분류" }; // neutral-600

function markerColor(lclCd: string | null | undefined): string {
  return (lclCd && LCL_COLORS[lclCd]?.color) || LCL_UNKNOWN.color;
}

export type ActiveFilter = { label: string; value: string };

type Props = {
  rows: Property[];
  /** true면 viewport 이동 시 자동 새로고침, false면 버튼 노출 */
  autoRefresh?: boolean;
  /** 활성 필터 — 지도 상단에 chip 으로 표시.
   *  사용자가 어떤 필터가 적용 중인지 즉시 인식 가능 (특히 "lcl 필터 안 켰는데
   *  건물만 보고 싶었다" 같은 UX 오해 방지). */
  activeFilters?: ActiveFilter[];
};

export function PropertyMap({ rows: initialRows, autoRefresh = false, activeFilters = [] }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const sp = useSearchParams();
  const { unit } = useAreaUnit();

  const [rows, setRows] = useState<Property[]>(initialRows);
  const [loading, setLoading] = useState(false);
  const [autoMode, setAutoMode] = useState(autoRefresh);
  const [showRefreshBtn, setShowRefreshBtn] = useState(false);
  const [count, setCount] = useState<number>(initialRows.length);
  // 원형 영역 선택
  const [drawMode, setDrawMode] = useState(false);
  const [circle, setCircle] = useState<CircleSel>(null);
  const [drawing, setDrawing] = useState<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  // initialRows가 props로 갱신되면 (필터 변경 시) 동기화
  useEffect(() => {
    setRows(initialRows);
    setCount(initialRows.length);
    setShowRefreshBtn(false);
  }, [initialRows]);

  const points = useMemo(
    () => {
      const withGeo = rows.filter((r) => r.longitude != null && r.latitude != null);
      if (!circle) return withGeo;
      return withGeo.filter(
        (r) => distanceM(circle.centerLng, circle.centerLat, r.longitude!, r.latitude!) <= circle.radiusM,
      );
    },
    [rows, circle],
  );
  const pointsKey = useMemo(
    () => points.map((p) => p.id).join(","),
    [points],
  );

  // 원 적용/해제 시 표시 count 동기화
  useEffect(() => {
    setCount(points.length);
  }, [points.length]);

  // 현재 viewport bbox 기준 다시 가져오기
  const refresh = async () => {
    const map = mapRef.current;
    if (!map) return;
    setLoading(true);
    try {
      const b = map.getBounds();
      const params = new URLSearchParams(sp.toString());
      params.set("min_lng", String(b.getWest()));
      params.set("max_lng", String(b.getEast()));
      params.set("min_lat", String(b.getSouth()));
      params.set("max_lat", String(b.getNorth()));
      params.set("max", "2000");
      const r = await fetch(`/api/map/markers?${params.toString()}`);
      const j = await r.json();
      if (Array.isArray(j.rows)) {
        setRows(j.rows);
        setCount(j.count ?? j.rows.length);
        setShowRefreshBtn(false);
      }
    } finally {
      setLoading(false);
    }
  };

  // Map 인스턴스 1회 생성
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      bounds: points.length === 0 ? KOREA_BOUNDS : undefined,
      center: points.length > 0
        ? [points[0].longitude!, points[0].latitude!]
        : KOREA_CENTER,
      zoom: points.length > 0 ? 10 : undefined,
      fitBoundsOptions: { padding: 24 },
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");
    map.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    // 사용자 이동 종료 — moveend는 zoom/pan/회전 모두 트리거
    let userMoved = false;
    const onMoveStart = (e: maplibregl.MapLibreEvent) => {
      // originalEvent 있으면 사용자 액션, 없으면 프로그램 호출 (fitBounds 등)
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      if ((e as any).originalEvent) userMoved = true;
    };
    const onMoveEnd = () => {
      if (!userMoved) return;
      userMoved = false;
      if (autoMode) {
        // throttle: 800ms 디바운스
        clearTimeout(debounce);
        debounce = setTimeout(refresh, 800);
      } else {
        setShowRefreshBtn(true);
      }
    };
    let debounce: ReturnType<typeof setTimeout>;
    map.on("movestart", onMoveStart);
    map.on("moveend", onMoveEnd);

    mapRef.current = map;
    map.once("load", () => map.resize());
    return () => {
      clearTimeout(debounce);
      map.off("movestart", onMoveStart);
      map.off("moveend", onMoveEnd);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode]);

  // drawMode 변경 시 maplibre 인터랙션 토글 + 마우스 핸들러
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

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    if (!drawMode) return;
    e.preventDefault();
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setDrawing({ x0: x, y0: y, x1: x, y1: y });
    setCircle(null);
  }, [drawMode]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!drawing) return;
    const rect = e.currentTarget.getBoundingClientRect();
    setDrawing({
      x0: drawing.x0, y0: drawing.y0,
      x1: e.clientX - rect.left, y1: e.clientY - rect.top,
    });
  }, [drawing]);

  const onMouseUp = useCallback((e: React.MouseEvent) => {
    if (!drawing || !mapRef.current) return;
    const map = mapRef.current;
    const rect = e.currentTarget.getBoundingClientRect();
    const x1 = e.clientX - rect.left;
    const y1 = e.clientY - rect.top;
    const center = map.unproject([drawing.x0, drawing.y0]);
    const edge = map.unproject([x1, y1]);
    const radiusM = distanceM(center.lng, center.lat, edge.lng, edge.lat);
    setDrawing(null);
    if (radiusM > 50) {
      setCircle({ centerLng: center.lng, centerLat: center.lat, radiusM });
      // 원 내부로 fit
      setTimeout(() => {
        const m = mapRef.current;
        if (!m) return;
        // 반경 기반 대략 bbox
        const dLat = (radiusM / 111320);
        const dLng = (radiusM / (111320 * Math.cos(center.lat * Math.PI / 180)));
        m.fitBounds([
          [center.lng - dLng, center.lat - dLat],
          [center.lng + dLng, center.lat + dLat],
        ], { padding: 40, duration: 600 });
      }, 50);
    } else {
      setCircle(null);
    }
    setDrawMode(false);
  }, [drawing]);

  const drawingPxRadius = drawing
    ? Math.hypot(drawing.x1 - drawing.x0, drawing.y1 - drawing.y0)
    : 0;

  // 마커 갱신
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (points.length === 0) return;

    let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
    for (const p of points) {
      const lng = p.longitude!;
      const lat = p.latitude!;
      // road_addr 우선, 없으면 conv_addr/lot_addr는 단위 변환
      const addrPlain = p.road_addr;
      const addrFallback = p.lot_addr || p.conv_addr;
      const addr = addrPlain || (addrFallback ? convertAreaText(addrFallback, unit) : "-");
      const subAddr = p.lot_addr && p.road_addr && p.lot_addr !== p.road_addr
        ? `<div style="color:#71717a;font-size:11px;margin-top:2px">지번: ${escapeHtml(p.lot_addr)}</div>`
        : "";
      const buildingNote = p.building_summary
        ? `<div style="color:#a1a1aa;font-size:10px;margin-top:2px">${escapeHtml(convertAreaText(p.building_summary.split("\\n")[0].slice(0, 60), unit))}</div>`
        : "";
      const html = `
        <div style="font-size:12px;line-height:1.5;min-width:240px;max-width:300px">
          <div style="font-family:monospace;color:#71717a;font-size:11px">${escapeHtml(p.cases?.case_no ?? "-")}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}</div>
          <div style="font-weight:600;margin-top:2px;word-break:keep-all">${escapeHtml(addr)}</div>
          ${subAddr}
          ${buildingNote}
          <div style="margin-top:4px">최저: <strong>${escapeHtml(fmtMoneyShort(p.min_sale_price))}</strong></div>
          <div style="color:#71717a">매각: ${escapeHtml(fmtDate(p.sale_date))}</div>
          ${p.docid ? `<a href="/p/${encodeURIComponent(p.docid)}" style="color:#2563eb;text-decoration:underline;display:inline-block;margin-top:4px">상세 →</a>` : ""}
        </div>
      `;
      const popup = new Popup({ offset: 18, closeButton: true, maxWidth: "320px" }).setHTML(html);
      const marker = new Marker({ color: markerColor(p.usage_lcl_cd) })
        .setLngLat([lng, lat])
        .setPopup(popup)
        .addTo(map);
      markersRef.current.push(marker);

      if (lng < minLng) minLng = lng;
      if (lat < minLat) minLat = lat;
      if (lng > maxLng) maxLng = lng;
      if (lat > maxLat) maxLat = lat;
    }
    // initialRows 변경 시 (필터 변경 등) 마커 영역으로 줌
    // bbox refresh로 들어온 새 rows에는 fit 안 함 (사용자 viewport 유지)
    // unit 변경 시에도 popup 재생성 — popup HTML이 unit에 의존
  }, [pointsKey, unit]);

  // 어떤 lcl이 결과에 존재하는지 — legend에서 해당 항목만 굵게 강조
  const presentLcls = useMemo(() => {
    const s = new Set<string>();
    for (const p of points) if (p.usage_lcl_cd) s.add(p.usage_lcl_cd);
    return s;
  }, [points]);

  return (
    <div className="relative">
      {/* 활성 필터 칩 — 지도 상단 (사용자가 어떤 필터로 좁혔는지 즉시 보임) */}
      {activeFilters.length > 0 && (
        <div className="mb-2 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-muted-foreground">필터:</span>
          {activeFilters.map((f, i) => (
            <span key={i}
                  className="inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-xs">
              <span className="text-muted-foreground">{f.label}</span>
              <span className="font-medium">{f.value}</span>
            </span>
          ))}
        </div>
      )}

      <div
        ref={containerRef}
        style={{ width: "100%", height: "calc(100vh - 280px)", minHeight: 480 }}
        className="rounded-md border bg-muted/20 overflow-hidden"
      />

      {/* 마커 색 legend — 좌하단 (lcl 필터 적용 안 한 상태에서도 한눈에 구분) */}
      <div className="absolute left-3 bottom-8 z-30 rounded-md bg-background/95 border px-2.5 py-1.5 text-[11px] shadow-sm space-y-0.5">
        <div className="text-muted-foreground font-medium text-[10px] uppercase tracking-wide mb-0.5">
          마커 색
        </div>
        {Object.entries(LCL_COLORS).map(([code, { color, label }]) => (
          <div key={code} className="flex items-center gap-1.5">
            <span className="inline-block w-2.5 h-2.5 rounded-full" style={{ background: color }} />
            <span className={presentLcls.has(code) ? "font-medium" : "text-muted-foreground"}>
              {label}
            </span>
          </div>
        ))}
      </div>

      {/* 원형 드래그 오버레이 — drawMode에서만 pointer-events 활성 */}
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
              fill="rgba(220, 38, 38, 0.15)"
              stroke="#dc2626"
              strokeWidth={2}
              strokeDasharray="6 4"
            />
          </svg>
        )}
      </div>

      {/* 컨트롤 오버레이 — 좌상단 */}
      <div className="absolute left-3 top-3 flex flex-col gap-2 z-30">
        <div className="rounded-md bg-background/95 border px-3 py-1.5 text-xs shadow-sm">
          마커 <strong>{count.toLocaleString()}</strong>개
          {circle && (
            <span className="text-muted-foreground ml-1">
              (반경 {(circle.radiusM / 1000).toFixed(1)}km)
            </span>
          )}
          {loading && <span className="ml-2 text-muted-foreground">불러오는 중…</span>}
        </div>
        <label className="rounded-md bg-background/95 border px-3 py-1.5 text-xs shadow-sm flex items-center gap-1.5 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={autoMode}
            onChange={(e) => setAutoMode(e.target.checked)}
          />
          <span>지도 이동 시 자동 새로고침</span>
        </label>
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
            "rounded-md px-3 py-1.5 text-xs border shadow-sm font-medium text-left " +
            (drawMode
              ? "bg-red-600 text-white border-red-600"
              : circle
                ? "bg-background/95 text-foreground border-border hover:bg-muted"
                : "bg-background/95 text-foreground border-border hover:bg-muted")
          }
        >
          {drawMode ? "📍 드래그로 원 그리기" : circle ? "✕ 원형 선택 해제" : "⭕ 원형 영역 선택"}
        </button>
      </div>

      {/* 수동 새로고침 버튼 — 화면 중앙 상단 */}
      {showRefreshBtn && !autoMode && (
        <button
          onClick={refresh}
          disabled={loading}
          type="button"
          className="absolute left-1/2 top-3 -translate-x-1/2 z-10 rounded-full bg-primary text-primary-foreground px-4 py-2 text-sm font-medium shadow-lg hover:bg-primary/90 disabled:opacity-50"
        >
          {loading ? "검색 중…" : "이 지역에서 검색"}
        </button>
      )}
    </div>
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
