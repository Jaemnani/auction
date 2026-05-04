"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import maplibregl, { LngLatBoundsLike, Map as MlMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Property } from "@/lib/types";
import { fmtDate, fmtMoneyShort } from "@/lib/format";

const KOREA_BOUNDS: [[number, number], [number, number]] = [
  [124.5, 33.0],
  [131.9, 38.7],
];
const KOREA_CENTER: [number, number] = [127.8, 36.5];
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

type Props = {
  rows: Property[];
  /** true면 viewport 이동 시 자동 새로고침, false면 버튼 노출 */
  autoRefresh?: boolean;
};

export function PropertyMap({ rows: initialRows, autoRefresh = false }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);
  const sp = useSearchParams();

  const [rows, setRows] = useState<Property[]>(initialRows);
  const [loading, setLoading] = useState(false);
  const [autoMode, setAutoMode] = useState(autoRefresh);
  const [showRefreshBtn, setShowRefreshBtn] = useState(false);
  const [count, setCount] = useState<number>(initialRows.length);

  // initialRows가 props로 갱신되면 (필터 변경 시) 동기화
  useEffect(() => {
    setRows(initialRows);
    setCount(initialRows.length);
    setShowRefreshBtn(false);
  }, [initialRows]);

  const points = useMemo(
    () => rows.filter((r) => r.longitude != null && r.latitude != null),
    [rows],
  );
  const pointsKey = useMemo(
    () => points.map((p) => p.id).join(","),
    [points],
  );

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
    return () => {
      clearTimeout(debounce);
      map.off("movestart", onMoveStart);
      map.off("moveend", onMoveEnd);
      map.remove();
      mapRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoMode]);

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
      const addr = p.road_addr || p.lot_addr || p.conv_addr || "-";
      const subAddr = p.lot_addr && p.road_addr && p.lot_addr !== p.road_addr
        ? `<div style="color:#71717a;font-size:11px;margin-top:2px">지번: ${escapeHtml(p.lot_addr)}</div>`
        : "";
      const buildingNote = p.building_summary
        ? `<div style="color:#a1a1aa;font-size:10px;margin-top:2px">${escapeHtml(p.building_summary.split("\\n")[0].slice(0, 60))}</div>`
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
      const marker = new Marker({ color: "#dc2626" })
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
  }, [pointsKey]);

  return (
    <div className="relative">
      <div
        ref={containerRef}
        style={{ width: "100%", height: "calc(100vh - 280px)", minHeight: 480 }}
        className="rounded-md border bg-muted/20 overflow-hidden"
      />

      {/* 컨트롤 오버레이 — 우상단 */}
      <div className="absolute left-3 top-3 flex flex-col gap-2 z-10">
        <div className="rounded-md bg-background/95 border px-3 py-1.5 text-xs shadow-sm">
          마커 <strong>{count.toLocaleString()}</strong>개
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
