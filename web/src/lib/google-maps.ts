// Google Maps JS API 로더 (싱글턴) + 지도 공용 헬퍼.
// KR/JP 지도 모두 구글 지도 사용 — 일본 매물 커버리지 때문에 국내 지도(카카오/네이버)
// 대신 구글로 통일. 키는 NEXT_PUBLIC_GOOGLE_MAPS_API_KEY (HTTP referrer 제한 권장).

export const GOOGLE_MAPS_API_KEY = process.env.NEXT_PUBLIC_GOOGLE_MAPS_API_KEY;

// Advanced Marker에는 mapId가 필수. 전용 Map ID 없으면 구글이 예제용으로 허용하는
// DEMO_MAP_ID로 동작 (클라우드 스타일링만 불가, 기능은 동일).
export const GOOGLE_MAP_ID =
  process.env.NEXT_PUBLIC_GOOGLE_MAPS_MAP_ID || "DEMO_MAP_ID";

let loadPromise: Promise<void> | null = null;

/** Maps JS API를 1회만 로드. marker 라이브러리 포함, 한국어 라벨. */
export function loadGoogleMaps(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("loadGoogleMaps는 브라우저 전용"));
  }
  if (typeof google !== "undefined" && google.maps?.marker) {
    return Promise.resolve();
  }
  if (!loadPromise) {
    loadPromise = new Promise<void>((resolve, reject) => {
      if (!GOOGLE_MAPS_API_KEY) {
        reject(new Error("NEXT_PUBLIC_GOOGLE_MAPS_API_KEY 미설정"));
        return;
      }
      const cbName = "__googleMapsOnLoad";
      (window as unknown as Record<string, unknown>)[cbName] = () => resolve();
      const s = document.createElement("script");
      const params = new URLSearchParams({
        key: GOOGLE_MAPS_API_KEY,
        v: "weekly",
        libraries: "marker",
        language: "ko",
        region: "KR",
        loading: "async",
        callback: cbName,
      });
      s.src = `https://maps.googleapis.com/maps/api/js?${params.toString()}`;
      s.async = true;
      s.onerror = () => {
        loadPromise = null;
        reject(new Error("Google Maps 스크립트 로드 실패"));
      };
      document.head.appendChild(s);
    });
  }
  return loadPromise;
}

/** 컨테이너 px → LatLng 변환용 OverlayView (구글엔 maplibre unproject가 없음).
 *  map에 붙인 뒤 getProjection()이 준비되면 fromContainerPixelToLatLng 사용 가능. */
export function createProjectionHelper(map: google.maps.Map): google.maps.OverlayView {
  const ov = new google.maps.OverlayView();
  ov.onAdd = () => {};
  ov.draw = () => {};
  ov.onRemove = () => {};
  ov.setMap(map);
  return ov;
}

export function containerPxToLatLng(
  helper: google.maps.OverlayView | null,
  x: number,
  y: number,
): google.maps.LatLng | null {
  const proj = helper?.getProjection();
  if (!proj) return null;
  return proj.fromContainerPixelToLatLng(new google.maps.Point(x, y));
}

/** 단색 핀 마커 (기존 maplibre Marker({color}) 대체). */
export function makePin(color: string): google.maps.marker.PinElement {
  return new google.maps.marker.PinElement({
    background: color,
    borderColor: "rgba(0,0,0,.35)",
    glyphColor: "#ffffff",
  });
}
