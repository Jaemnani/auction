"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import type { Property } from "@/lib/types";
import { fmtDate, fmtMoneyShort } from "@/lib/format";
import { convertAreaText, useAreaUnit } from "@/lib/area-unit";
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

// 지도 시작 위치 — 서울시청. 매물이 많은 지역에서 시작하면 즉시 마커 보임.
// (이전엔 한국 전체 중심 [127.8, 36.5] → 첫 화면이 비어 보였음)
const DEFAULT_CENTER = { lat: 37.5666, lng: 126.9784 };
const DEFAULT_ZOOM = 11;

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
  const mapRef = useRef<google.maps.Map | null>(null);
  const markersRef = useRef<google.maps.marker.AdvancedMarkerElement[]>([]);
  const infoWindowRef = useRef<google.maps.InfoWindow | null>(null);
  const projectionRef = useRef<google.maps.OverlayView | null>(null);
  // fitBounds·InfoWindow auto-pan 등 프로그램 이동이 만드는 idle 이벤트를
  // 새로고침 트리거에서 제외. 카운터 대신 시간 창 — 이동이 실제로 일어나지
  // 않아도 (idle 미발생) 억제 상태가 새지 않음.
  const suppressUntilRef = useRef(0);
  const sp = useSearchParams();
  const { unit } = useAreaUnit();

  const [rows, setRows] = useState<Property[]>(initialRows);
  const [loading, setLoading] = useState(false);
  const [autoMode, setAutoMode] = useState(autoRefresh);
  const [showRefreshBtn, setShowRefreshBtn] = useState(false);
  const [count, setCount] = useState<number>(initialRows.length);
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
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
    const b = map.getBounds();
    if (!b) return;
    setLoading(true);
    try {
      const ne = b.getNorthEast();
      const sw = b.getSouthWest();
      const params = new URLSearchParams(sp.toString());
      params.set("min_lng", String(sw.lng()));
      params.set("max_lng", String(ne.lng()));
      params.set("min_lat", String(sw.lat()));
      params.set("max_lat", String(ne.lat()));
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

  // idle 핸들러가 항상 최신 상태를 보도록 ref로 전달 (map은 1회만 생성).
  const refreshRef = useRef(refresh);
  const autoModeRef = useRef(autoMode);
  useEffect(() => {
    refreshRef.current = refresh;
    autoModeRef.current = autoMode;
  });

  // Map 인스턴스 1회 생성 (Google Maps는 destroy API가 없어 재생성하지 않음)
  useEffect(() => {
    if (!GOOGLE_MAPS_API_KEY) return;
    if (!containerRef.current || mapRef.current) return;
    let cancelled = false;
    let debounce: ReturnType<typeof setTimeout> | undefined;

    loadGoogleMaps()
      .then(() => {
        if (cancelled || !containerRef.current || mapRef.current) return;
        const map = new google.maps.Map(containerRef.current, {
          mapId: GOOGLE_MAP_ID,
          // 항상 서울에서 시작 (이전엔 매물 0건 시 전국 bounds로 fit → 첫 화면 비어보임).
          center: DEFAULT_CENTER,
          zoom: DEFAULT_ZOOM,
          gestureHandling: "greedy",
          streetViewControl: false,
          mapTypeControl: false,
          fullscreenControl: true,
          scaleControl: true,
          clickableIcons: false, // POI 클릭이 마커 클릭을 가로채지 않게
        });
        mapRef.current = map;
        projectionRef.current = createProjectionHelper(map);
        infoWindowRef.current = new google.maps.InfoWindow({ maxWidth: 340 });
        // 초기 로드 직후 타일 로드·레이아웃 변동으로 오는 idle 연쇄는 무시
        suppressUntilRef.current = performance.now() + 2000;

        // idle은 pan/zoom 종료마다 발생하고 초기 로드에서도 여러 번 올 수 있음.
        // bounds가 실제로 변했을 때만 트리거 (초기 로드 idle 연쇄 방지) +
        // 프로그램 이동(suppressUntilRef 시간 창)은 제외.
        let lastBoundsKey: string | null = null;
        map.addListener("idle", () => {
          const b = map.getBounds();
          if (!b) return;
          const ne = b.getNorthEast(), sw = b.getSouthWest();
          const key = [sw.lng(), sw.lat(), ne.lng(), ne.lat()]
            .map((v) => v.toFixed(4)).join(",");
          if (lastBoundsKey === null) { lastBoundsKey = key; return; }
          if (key === lastBoundsKey) return;
          lastBoundsKey = key;
          if (performance.now() < suppressUntilRef.current) return;
          if (autoModeRef.current) {
            clearTimeout(debounce);
            debounce = setTimeout(() => refreshRef.current(), 800);
          } else {
            setShowRefreshBtn(true);
          }
        });
        setMapReady(true);
      })
      .catch((e: unknown) => {
        if (!cancelled) setMapError(e instanceof Error ? e.message : String(e));
      });

    const container = containerRef.current;
    return () => {
      cancelled = true;
      clearTimeout(debounce);
      if (mapRef.current) google.maps.event.clearInstanceListeners(mapRef.current);
      projectionRef.current?.setMap(null);
      projectionRef.current = null;
      infoWindowRef.current?.close();
      infoWindowRef.current = null;
      markersRef.current.forEach((m) => { m.map = null; });
      markersRef.current = [];
      mapRef.current = null;
      // StrictMode 재마운트 시 이전 지도 DOM이 남지 않게 비움
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
    const rect = e.currentTarget.getBoundingClientRect();
    const x1 = e.clientX - rect.left;
    const y1 = e.clientY - rect.top;
    const center = containerPxToLatLng(projectionRef.current, drawing.x0, drawing.y0);
    const edge = containerPxToLatLng(projectionRef.current, x1, y1);
    setDrawing(null);
    if (!center || !edge) { setDrawMode(false); return; }
    const radiusM = distanceM(center.lng(), center.lat(), edge.lng(), edge.lat());
    if (radiusM > 50) {
      setCircle({ centerLng: center.lng(), centerLat: center.lat(), radiusM });
      // 원 내부로 fit
      setTimeout(() => {
        const m = mapRef.current;
        if (!m) return;
        // 반경 기반 대략 bbox
        const dLat = (radiusM / 111320);
        const dLng = (radiusM / (111320 * Math.cos(center.lat() * Math.PI / 180)));
        suppressUntilRef.current = performance.now() + 1500;
        m.fitBounds(
          new google.maps.LatLngBounds(
            { lat: center.lat() - dLat, lng: center.lng() - dLng },
            { lat: center.lat() + dLat, lng: center.lng() + dLng },
          ),
          40,
        );
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
    if (!map || !mapReady) return;

    markersRef.current.forEach((m) => { m.map = null; });
    markersRef.current = [];
    infoWindowRef.current?.close();

    if (points.length === 0) return;

    // 한 매물의 팝업 카드 HTML (겹침 시 목록의 한 항목으로도 재사용).
    const cardHtml = (p: Property) => {
      const addrPlain = p.road_addr;
      const addrFallback = p.lot_addr || p.conv_addr;
      const addr = addrPlain || (addrFallback ? convertAreaText(addrFallback, unit) : "-");
      const subAddr = p.lot_addr && p.road_addr && p.lot_addr !== p.road_addr
        ? `<div style="color:#71717a;font-size:11px;margin-top:2px">지번: ${escapeHtml(p.lot_addr)}</div>`
        : "";
      const buildingNote = p.building_summary
        ? `<div style="color:#a1a1aa;font-size:10px;margin-top:2px">${escapeHtml(convertAreaText(p.building_summary.split("\\n")[0].slice(0, 60), unit))}</div>`
        : "";
      return `
        <div style="font-family:monospace;color:#71717a;font-size:11px">${escapeHtml(p.cases?.case_no ?? "-")}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}</div>
        <div style="font-weight:600;margin-top:2px;word-break:keep-all">${escapeHtml(addr)}</div>
        ${subAddr}
        ${buildingNote}
        <div style="margin-top:4px">최저: <strong>${escapeHtml(fmtMoneyShort(p.min_sale_price))}</strong></div>
        <div style="color:#71717a">매각: ${escapeHtml(fmtDate(p.sale_date))}</div>
        ${p.docid ? `<a href="/p/${encodeURIComponent(p.docid)}" style="color:#2563eb;text-decoration:underline;display:inline-block;margin-top:4px">상세 →</a>` : ""}`;
    };

    // 좌표별로 묶어 겹침을 처리 (겹치면 개수 배지 + 선택 목록 팝업).
    for (const grp of groupByCoord(points, (p) => p.longitude!, (p) => p.latitude!)) {
      const p0 = grp[0];
      const lng = p0.longitude!, lat = p0.latitude!;

      let html: string;
      let content: HTMLElement;
      if (grp.length === 1) {
        html = `<div style="font-size:12px;line-height:1.5;min-width:240px;max-width:300px">${cardHtml(p0)}</div>`;
        content = makePin(markerColor(p0.usage_lcl_cd)).element;
      } else {
        const shown = grp.slice(0, CLUSTER_LIST_MAX);
        const more = grp.length - shown.length;
        html = `<div style="font-size:12px;line-height:1.5;min-width:240px;max-width:320px;max-height:320px;overflow-y:auto">
            <div style="font-weight:700;margin-bottom:6px">이 위치에 ${grp.length}건</div>
            ${shown.map((p, i) => `<div style="${i > 0 ? "border-top:1px solid #e4e4e7;padding-top:6px;margin-top:6px" : ""}">${cardHtml(p)}</div>`).join("")}
            ${more > 0 ? `<div style="color:#71717a;font-size:11px;margin-top:8px;border-top:1px solid #e4e4e7;padding-top:6px">외 ${more}건 (지도 확대·필터로 좁혀보세요)</div>` : ""}
          </div>`;
        content = makeCountBadgeEl(grp.length);
      }
      const marker = new google.maps.marker.AdvancedMarkerElement({
        map,
        position: { lat, lng },
        content,
        gmpClickable: true,
      });
      marker.addListener("click", () => {
        const iw = infoWindowRef.current;
        if (!iw) return;
        // InfoWindow auto-pan이 idle을 발생시키므로 새로고침 트리거에서 제외
        suppressUntilRef.current = performance.now() + 1200;
        iw.setContent(html);
        iw.open({ map, anchor: marker });
      });
      markersRef.current.push(marker);
    }
    // initialRows 변경 시 (필터 변경 등) 마커 영역으로 줌은 하지 않음
    // bbox refresh로 들어온 새 rows에도 fit 안 함 (사용자 viewport 유지)
    // unit 변경 시에도 popup 재생성 — popup HTML이 unit에 의존
  }, [pointsKey, unit, mapReady]);

  // 어떤 lcl이 결과에 존재하는지 — legend에서 해당 항목만 굵게 강조
  const presentLcls = useMemo(() => {
    const s = new Set<string>();
    for (const p of points) if (p.usage_lcl_cd) s.add(p.usage_lcl_cd);
    return s;
  }, [points]);

  if (!GOOGLE_MAPS_API_KEY || mapError) {
    return <MapKeyNotice error={mapError} className="h-[480px]" />;
  }

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
      <div className="absolute left-3 bottom-8 z-30 rounded-md bg-background/95 border px-2.5 py-1.5 text-caption-sm shadow-sm space-y-0.5">
        <div className="text-muted-foreground font-medium text-caption-xs uppercase tracking-wide mb-0.5">
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
