"use client";

import { useEffect, useMemo, useRef } from "react";
import maplibregl, { LngLatBoundsLike, Map as MlMap, Marker, Popup } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Property } from "@/lib/types";
import { fmtDate, fmtMoneyShort } from "@/lib/format";

// 한국 본토 + 제주 + 울릉/독도까지 포함하는 박스
const KOREA_BOUNDS: [[number, number], [number, number]] = [
  [124.5, 33.0],  // SW (제주 서남)
  [131.9, 38.7],  // NE (울릉/독도 + 휴전선)
];
const KOREA_CENTER: [number, number] = [127.8, 36.5];
const STYLE_URL = "https://tiles.openfreemap.org/styles/liberty";

export function PropertyMap({ rows }: { rows: Property[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MlMap | null>(null);
  const markersRef = useRef<Marker[]>([]);

  // 메모이즈 — 같은 rows 참조면 같은 배열, 새 rows면 새 배열
  const points = useMemo(
    () => rows.filter((r) => r.longitude != null && r.latitude != null),
    [rows],
  );
  // 마커 effect용 안정 키 (id 변경 시에만 트리거)
  const pointsKey = useMemo(
    () => points.map((p) => p.id).join(","),
    [points],
  );

  // 최초 1회 Map 인스턴스 생성
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: STYLE_URL,
      // 매물 없을 땐 한국 전국 박스에 fitBounds, 있으면 첫 마커 부근에서 시작
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
    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
    // 의존성에 points를 안 넣음 — points는 아래 effect에서 별도로 처리
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 마커 갱신 (필터 바뀔 때마다)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // 기존 마커 제거
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = [];

    if (points.length === 0) return;

    let minLng = Infinity, minLat = Infinity, maxLng = -Infinity, maxLat = -Infinity;
    for (const p of points) {
      const lng = p.longitude!;
      const lat = p.latitude!;
      const html = `
        <div style="font-size:12px;line-height:1.5;min-width:200px">
          <div style="font-family:monospace;color:#71717a;font-size:11px">${escapeHtml(p.cases?.case_no ?? "-")}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}</div>
          <div style="font-weight:600;margin-top:2px">${escapeHtml(p.conv_addr ?? "-")}</div>
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

    if (points.length > 1) {
      const bounds: LngLatBoundsLike = [[minLng, minLat], [maxLng, maxLat]];
      map.fitBounds(bounds, { padding: 60, duration: 600, maxZoom: 14 });
    } else if (points.length === 1) {
      map.flyTo({
        center: [points[0].longitude!, points[0].latitude!],
        zoom: 14,
        duration: 600,
      });
    } else {
      // 매물 0건 → 한국 전국으로 줌아웃
      map.fitBounds(KOREA_BOUNDS, { padding: 24, duration: 400 });
    }
    // pointsKey 의존: rows id 셋이 바뀔 때만 트리거 (참조 비교 X)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pointsKey]);

  return (
    <div
      ref={containerRef}
      style={{ width: "100%", height: "calc(100vh - 280px)", minHeight: 480 }}
      className="rounded-md border bg-muted/20 overflow-hidden"
    />
  );
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
