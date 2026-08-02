"use client";

import { useEffect, useMemo, useRef, useState, useCallback, useSyncExternalStore } from "react";
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
import { MapSearchBox } from "@/components/map-search-box";

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

// 최근 낙찰(종결 후 30일 유예창, 0018) — 용도색보다 우선하는 고유색.
// 목록/상세의 낙찰 배지(blue-600)와 통일.
const SOLD = { color: "#2563eb", label: "최근 낙찰 (30일)" };

/** 마커가 속한 토글 분류 키 — legend 토글과 1:1. markerColor와 같은 우선순위. */
function markerKey(p: Property): string {
  if (p.final_result === "sold") return "sold";
  if (p.usage_lcl_cd && LCL_COLORS[p.usage_lcl_cd]) return p.usage_lcl_cd;
  return "unknown";
}

function markerColor(p: Property): string {
  if (p.final_result === "sold") return SOLD.color;
  return (p.usage_lcl_cd && LCL_COLORS[p.usage_lcl_cd]?.color) || LCL_UNKNOWN.color;
}

// legend = 마커 색 토글 목록. markerKey가 낼 수 있는 모든 분류를 나열.
const LEGEND_ITEMS: { key: string; color: string; label: string }[] = [
  ...Object.entries(LCL_COLORS).map(([key, v]) => ({ key, ...v })),
  { key: "unknown", ...LCL_UNKNOWN },
  { key: "sold", ...SOLD },
];
// 기본 표시 분류 — 건물(20000)만 켜고 나머지는 꺼둠.
const DEFAULT_ENABLED_KEYS = ["20000"];

// legend 기본 펼침 기준 — sm 브레이크포인트와 동일.
const DESKTOP_MQ = "(min-width: 640px)";
function subscribeDesktopMq(cb: () => void): () => void {
  const mq = window.matchMedia(DESKTOP_MQ);
  mq.addEventListener("change", cb);
  return () => mq.removeEventListener("change", cb);
}

export type ActiveFilter = { label: string; value: string };

type Props = {
  rows: Property[];
  /** true면 viewport 이동 시 자동 새로고침, false면 버튼 노출 (기본 ON) */
  autoRefresh?: boolean;
  /** 활성 필터 — 지도 상단에 chip 으로 표시.
   *  사용자가 어떤 필터가 적용 중인지 즉시 인식 가능 (특히 "lcl 필터 안 켰는데
   *  건물만 보고 싶었다" 같은 UX 오해 방지). */
  activeFilters?: ActiveFilter[];
  /** true면 부모 높이를 100% 채움 (전체 화면 지도) — 필터 칩은 오버레이로 전환 */
  fill?: boolean;
};

export function PropertyMap({
  rows: initialRows, autoRefresh = true, activeFilters = [], fill = false,
}: Props) {
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
  // 마커 색 토글 — 켜진 분류만 지도에 그림. 기본은 건물만.
  const [enabledKeys, setEnabledKeys] = useState<Set<string>>(
    () => new Set(DEFAULT_ENABLED_KEYS),
  );
  const toggleKey = useCallback((key: string) => {
    setEnabledKeys((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);
  // legend 펼침 — 모바일 세로모드에선 오버레이가 지도를 가려 기본 접힘, 데스크탑은 펼침.
  // matchMedia 구독(useSyncExternalStore)이라 SSR(false)→hydration 전환이 안전.
  const isDesktop = useSyncExternalStore(
    subscribeDesktopMq,
    () => window.matchMedia(DESKTOP_MQ).matches,
    () => false,
  );
  const [legendOverride, setLegendOverride] = useState<boolean | null>(null);
  const legendOpen = legendOverride ?? isDesktop;

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
  // 켜진 토글 분류만 남긴 실제 렌더 대상.
  const visiblePoints = useMemo(
    () => points.filter((p) => enabledKeys.has(markerKey(p))),
    [points, enabledKeys],
  );
  const visiblePointsKey = useMemo(
    () => visiblePoints.map((p) => p.id).join(","),
    [visiblePoints],
  );
  // 분류별 개수 — legend에 표시 (현재 viewport 기준).
  const typeCounts = useMemo(() => {
    const m: Record<string, number> = {};
    for (const p of points) {
      const k = markerKey(p);
      m[k] = (m[k] ?? 0) + 1;
    }
    return m;
  }, [points]);

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
        // 빈 지도(마커 아닌 곳) 클릭 시 열린 상세 InfoWindow 닫기.
        // AdvancedMarkerElement 클릭은 map click으로 전파되지 않으므로 마커 팝업엔 영향 없음.
        map.addListener("click", () => {
          infoWindowRef.current?.close();
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

    if (visiblePoints.length === 0) return;

    // 사건번호 + (안전도·낙찰/하락%) 배지 행 — 단일 매물 팝업에선 InfoWindow
    // 헤더(닫기 X와 같은 줄)로 올려 상단 공백을 없애고, 겹침 목록 카드에선
    // 카드 안 첫 줄로 그대로 쓴다.
    const headerRowHtml = (p: Property, forHeaderSlot = false) => {
      const isSold = p.final_result === "sold";
      // 할인율(감정가 대비 최저가) — 진행 매물에서만.
      const discountPct = !isSold && p.appraisal_amount && p.min_sale_price && p.appraisal_amount > 0
        ? Math.round((1 - p.min_sale_price / p.appraisal_amount) * 100)
        : null;
      const badge = isSold
        ? `<span style="background:#2563eb;color:#fff;border-radius:9999px;padding:2px 8px;font-size:10px;font-weight:600;white-space:nowrap">낙찰</span>`
        : discountPct != null && discountPct > 0
          ? `<span style="background:#fef2f2;color:#dc2626;border:1px solid #fecaca;border-radius:9999px;padding:1px 7px;font-size:10px;font-weight:700;white-space:nowrap">▼${discountPct}%</span>`
          : "";
      // 매수 안전도(0023) 칩 — 점수대별 색. ScoreBadge와 색 통일.
      const sc = p.scores;
      const scoreChip = sc
        ? (() => {
            const b = sc.score >= 80 ? ["#059669", "안전"]
              : sc.score >= 65 ? ["#65a30d", "양호"]
              : sc.score >= 45 ? ["#d97706", "주의"]
              : ["#dc2626", "위험"];
            const dim = sc.confidence === "low" ? "opacity:0.6;" : "";
            return `<span style="${dim}background:${b[0]}1a;color:${b[0]};border:1px solid ${b[0]}40;border-radius:9999px;padding:1px 7px;font-size:10px;font-weight:700;white-space:nowrap" title="매수 안전도 ${sc.score}/100">${b[1]} ${sc.score}${sc.confidence === "low" ? "?" : ""}</span>`;
          })()
        : "";
      // 헤더 슬롯은 부모가 내용 폭만큼만 잡으므로 min-width로 좌우 정렬 확보
      // (content min-width 240px − 닫기버튼 ≈ 200px).
      return `<div style="display:flex;justify-content:space-between;align-items:center;gap:8px;${forHeaderSlot ? "min-width:200px;font-size:12px;line-height:1.4;" : ""}">
          <span style="font-family:monospace;color:#a1a1aa;font-size:11px">${escapeHtml(p.cases?.case_no ?? "-")}${p.maemul_ser > 1 ? ` #${p.maemul_ser}` : ""}</span>
          <span style="display:flex;gap:4px;align-items:center">${scoreChip}${badge}</span>
        </div>`;
    };

    // 한 매물의 팝업 카드 HTML (겹침 시 목록의 한 항목으로도 재사용).
    // withHeader=false — 단일 매물 팝업: 배지 행이 InfoWindow 헤더로 올라가므로 제외.
    const cardHtml = (p: Property, withHeader = true) => {
      const addrPlain = p.road_addr;
      const addrFallback = p.lot_addr || p.conv_addr;
      const addr = addrPlain || (addrFallback ? convertAreaText(addrFallback, unit) : "-");
      const subAddr = p.lot_addr && p.road_addr && p.lot_addr !== p.road_addr
        ? `<div style="color:#71717a;font-size:11px;margin-top:2px">지번 ${escapeHtml(p.lot_addr)}</div>`
        : "";
      const buildingNote = p.building_summary
        ? `<div style="color:#a1a1aa;font-size:11px;margin-top:3px">${escapeHtml(convertAreaText(p.building_summary.split("\\n")[0].slice(0, 60), unit))}</div>`
        : "";
      const isSold = p.final_result === "sold";

      // D-day (진행 매물 매각기일까지 남은 일수)
      let dday = "";
      if (!isSold && p.sale_date) {
        const days = Math.ceil((new Date(p.sale_date + "T00:00:00").getTime() - Date.now()) / 86400000);
        if (days >= 0 && days <= 60) {
          const c = days <= 7 ? "#dc2626" : days <= 21 ? "#ea580c" : "#71717a";
          dday = `<span style="color:${c};font-weight:700;margin-left:6px">D-${days === 0 ? "day" : days}</span>`;
        }
      }

      const money = (v: number | null | undefined) => escapeHtml(fmtMoneyShort(v ?? null));
      const priceBlock = isSold
        ? `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
             <span style="color:#71717a;font-size:11px">낙찰가</span>
             <strong style="color:#2563eb;font-size:15px">${money(p.sold_amount)}</strong>
           </div>
           <div style="display:flex;justify-content:space-between;color:#71717a;font-size:11px;margin-top:3px">
             <span>낙찰일</span><span>${escapeHtml(fmtDate(p.sold_date ?? null))}</span>
           </div>`
        : `<div style="display:flex;justify-content:space-between;align-items:baseline;gap:8px">
             <span style="color:#71717a;font-size:11px">최저가</span>
             <span style="text-align:right">
               <strong style="font-size:15px">${money(p.min_sale_price)}</strong>
               ${p.appraisal_amount ? `<span style="color:#a1a1aa;font-size:10px;text-decoration:line-through;margin-left:5px">${money(p.appraisal_amount)}</span>` : ""}
             </span>
           </div>
           ${p.cases?.claim_amount ? `<div style="display:flex;justify-content:space-between;color:#71717a;font-size:11px;margin-top:3px"><span>청구액</span><span>${money(p.cases.claim_amount)}</span></div>` : ""}
           <div style="display:flex;justify-content:space-between;color:#71717a;font-size:11px;margin-top:3px">
             <span>매각기일</span><span>${escapeHtml(fmtDate(p.sale_date))}${dday}</span>
           </div>`;

      return `
        ${withHeader ? headerRowHtml(p) : ""}
        <div style="font-weight:650;font-size:13px;margin-top:${withHeader ? 3 : 0}px;line-height:1.35;word-break:keep-all;color:#18181b">${escapeHtml(addr)}</div>
        ${subAddr}
        ${buildingNote}
        <div style="height:1px;background:#f0f0f0;margin:9px 0"></div>
        ${priceBlock}
        ${p.docid ? `<a href="/p/${encodeURIComponent(p.docid)}" target="_blank" rel="noopener noreferrer" style="display:block;text-align:center;margin-top:10px;padding:6px;background:#f4f4f5;color:#2563eb;border-radius:6px;text-decoration:none;font-weight:600;font-size:12px">상세 보기 →</a>` : ""}`;
    };

    // 좌표별로 묶어 겹침을 처리 (겹치면 개수 배지 + 선택 목록 팝업).
    for (const grp of groupByCoord(visiblePoints, (p) => p.longitude!, (p) => p.latitude!)) {
      const p0 = grp[0];
      const lng = p0.longitude!, lat = p0.latitude!;

      // 팝업 첫 줄(배지 행/건수 제목)을 InfoWindow 헤더로 올려 닫기 X 버튼과
      // 같은 줄에 배치 — X 버튼 줄이 만들던 상단 공백 제거.
      let html: string;
      let headerHtml: string;
      let content: HTMLElement;
      if (grp.length === 1) {
        html = `<div style="font-size:12px;line-height:1.5;min-width:240px;max-width:300px">${cardHtml(p0, false)}</div>`;
        headerHtml = headerRowHtml(p0, true);
        content = makePin(markerColor(p0)).element;
      } else {
        const shown = grp.slice(0, CLUSTER_LIST_MAX);
        const more = grp.length - shown.length;
        html = `<div style="font-size:12px;line-height:1.5;min-width:240px;max-width:320px;max-height:320px;overflow-y:auto">
            ${shown.map((p, i) => `<div style="${i > 0 ? "border-top:1px solid #e4e4e7;padding-top:6px;margin-top:6px" : ""}">${cardHtml(p)}</div>`).join("")}
            ${more > 0 ? `<div style="color:#71717a;font-size:11px;margin-top:8px;border-top:1px solid #e4e4e7;padding-top:6px">외 ${more}건 (지도 확대·필터로 좁혀보세요)</div>` : ""}
          </div>`;
        headerHtml = `<div style="font-weight:700;font-size:13px;min-width:200px">이 위치에 ${grp.length}건</div>`;
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
        iw.setHeaderContent(htmlToEl(headerHtml));
        iw.setContent(html);
        iw.open({ map, anchor: marker });
      });
      markersRef.current.push(marker);
    }
    // initialRows 변경 시 (필터 변경 등) 마커 영역으로 줌은 하지 않음
    // bbox refresh로 들어온 새 rows에도 fit 안 함 (사용자 viewport 유지)
    // unit 변경 시에도 popup 재생성 — popup HTML이 unit에 의존
    // 토글 변경(visiblePoints) 시에도 재생성 — 꺼진 분류 마커 제거
  }, [visiblePointsKey, unit, mapReady]);

  if (!GOOGLE_MAPS_API_KEY || mapError) {
    return <MapKeyNotice error={mapError} className="h-[480px]" />;
  }

  const filterChips = activeFilters.length > 0 && (
    <div className={
      fill
        ? "absolute bottom-3 right-3 z-30 flex flex-wrap items-center justify-end gap-1.5 max-w-[60%]"
        : "mb-2 flex flex-wrap items-center gap-1.5"
    }>
      <span className={"text-xs text-muted-foreground" + (fill ? " bg-background/80 rounded px-1" : "")}>필터:</span>
      {activeFilters.map((f, i) => (
        <span key={i}
              className="inline-flex items-center gap-1 rounded-full border bg-card px-2 py-0.5 text-xs shadow-sm">
          <span className="text-muted-foreground">{f.label}</span>
          <span className="font-medium">{f.value}</span>
        </span>
      ))}
    </div>
  );

  return (
    <div className={fill ? "relative h-full" : "relative"}>
      {/* 활성 필터 칩 — 일반 모드는 지도 상단 플로우, fill 모드는 우하단 오버레이 */}
      {!fill && filterChips}

      <div
        ref={containerRef}
        style={fill
          ? { width: "100%", height: "100%" }
          : { width: "100%", height: "calc(100vh - 280px)", minHeight: 480 }}
        className={fill ? "bg-muted/20 overflow-hidden" : "rounded-md border bg-muted/20 overflow-hidden"}
      />
      {fill && filterChips}

      {/* 마커 색 legend = 표시 토글 — 좌하단. 켠 분류만 지도에 그림(기본 건물만).
          모바일에선 지도를 가려서 기본 접힘 (헤더 탭으로 펼침). */}
      <div className="absolute left-3 bottom-8 z-30 rounded-md bg-background/95 border text-caption-sm shadow-sm">
        <button
          type="button"
          onClick={() => setLegendOverride(!legendOpen)}
          aria-expanded={legendOpen}
          className="flex w-full items-center gap-1 px-2.5 py-1.5 text-left text-muted-foreground font-medium text-caption-xs uppercase tracking-wide"
        >
          <span>{legendOpen ? "마커 색 · 클릭 토글" : "마커 색"}</span>
          <span aria-hidden>{legendOpen ? "▾" : "▸"}</span>
        </button>
        {legendOpen && (
          <div className="px-2.5 pb-1.5 space-y-0.5">
            {LEGEND_ITEMS.map(({ key, color, label }) => {
              const on = enabledKeys.has(key);
              const n = typeCounts[key] ?? 0;
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => toggleKey(key)}
                  aria-pressed={on}
                  className="flex w-full items-center gap-1.5 text-left hover:opacity-80"
                >
                  <span
                    className="inline-block w-2.5 h-2.5 rounded-full shrink-0"
                    style={{
                      background: on ? color : "transparent",
                      border: `1.5px solid ${color}`,
                    }}
                  />
                  <span className={on ? "font-medium" : "text-muted-foreground"}>
                    {label}
                  </span>
                  {n > 0 && (
                    <span className="ml-auto pl-1.5 tabular-nums text-muted-foreground text-caption-xs">
                      {n.toLocaleString()}
                    </span>
                  )}
                </button>
              );
            })}
          </div>
        )}
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
        {mapReady && (
          <MapSearchBox
            region="kr"
            onLocate={({ location, viewport }) => {
              const m = mapRef.current;
              if (!m) return;
              if (viewport) m.fitBounds(viewport);
              else { m.panTo(location); m.setZoom(15); }
            }}
          />
        )}
        <div className="rounded-md bg-background/95 border px-3 py-1.5 text-xs shadow-sm">
          마커 <strong>{visiblePoints.length.toLocaleString()}</strong>개
          {visiblePoints.length < count && (
            <span className="text-muted-foreground ml-1">/ 전체 {count.toLocaleString()}</span>
          )}
          {circle && (
            <span className="text-muted-foreground ml-1">
              (반경 {(circle.radiusM / 1000).toFixed(1)}km)
            </span>
          )}
          {loading && <span className="ml-2 text-muted-foreground">불러오는 중…</span>}
        </div>
        {/* 모바일: 자동 새로고침이 기본 ON이라 토글 자체를 숨겨 지도 가림 최소화 */}
        <label className="rounded-md bg-background/95 border px-3 py-1.5 text-xs shadow-sm hidden sm:flex items-center gap-1.5 cursor-pointer select-none">
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
            // 원형 선택은 마우스 드래그 전용(터치 미지원) — 모바일에선 숨김
            "hidden sm:block rounded-md px-3 py-1.5 text-xs border shadow-sm font-medium text-left " +
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

/** InfoWindow headerContent용 — HTML 문자열을 Element로 (string은 plain text로만 렌더됨). */
function htmlToEl(html: string): HTMLElement {
  const d = document.createElement("div");
  d.innerHTML = html;
  return d;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
