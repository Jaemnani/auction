"""경기 정비사업 — 경기데이터드림 GenrlimprvBizpropls (일반 정비사업 추진현황).

정찰 근거: docs/redev_layer_recon.md. 2026-08 실측 533건.
좌표·폴리곤이 없어 LOCPLC_ADDR 를 Kakao 지오코딩해 **대표 위치 점**으로 표시.

⚠ 경기데이터드림은 서버형 클라이언트 기본 UA 를 WAF 로 차단 — 브라우저 UA 필수.
"""
from __future__ import annotations

import os
import time

import httpx

from .geocode import geocode, save_cache
from .phases import GG_STAGE_MAP, normalize_stage

ENDPOINT = "https://openapi.gg.go.kr/GenrlimprvBizpropls"
SOURCE = "경기데이터드림 일반 정비사업 추진현황"

# WAF 가 기본 python-httpx UA 를 차단 페이지(EUC-KR html)로 돌려보낸다.
# ⚠ Accept/Referer 헤더를 추가하면 서버가 500 을 내는 것을 실측 — UA 만 보낸다.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
}


def _get_page(client: httpx.Client, api_key: str, page: int, size: int) -> dict:
    r = client.get(ENDPOINT, params={"KEY": api_key, "Type": "json",
                                     "pIndex": page, "pSize": size},
                   headers=_HEADERS)
    r.raise_for_status()
    try:
        d = r.json()
    except ValueError as e:
        raise RuntimeError(f"경기 API non-JSON (WAF 차단?): {r.text[:200]}") from e
    if "GenrlimprvBizpropls" not in d:
        raise RuntimeError(f"경기 API error: {str(d)[:300]}")
    return d


def fetch_rows(api_key: str | None = None) -> list[dict]:
    api_key = api_key or os.environ.get("GG_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("GG_DATA_API_KEY env required")
    rows: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            d = _get_page(client, api_key, page, 100)
            parts = d["GenrlimprvBizpropls"]
            batch = parts[1].get("row", []) if len(parts) > 1 else []
            rows.extend(batch)
            if len(batch) < 100:
                return rows
            page += 1
            time.sleep(0.2)


def source_count() -> int:
    api_key = os.environ.get("GG_DATA_API_KEY")
    if not api_key:
        raise RuntimeError("GG_DATA_API_KEY env required")
    with httpx.Client(timeout=30) as client:
        d = _get_page(client, api_key, 1, 1)
    head = d["GenrlimprvBizpropls"][0]["head"]
    return int(head[0]["list_total_count"])


def build_features(*, precision: int = 6) -> tuple[dict, dict]:  # noqa: ARG001
    rows = fetch_rows()
    features = []
    report = {"biz_total": len(rows), "no_addr": 0, "geocode_failed": 0,
              "loc_dong": 0}
    with httpx.Client(timeout=30) as client:
        for r in rows:
            addr = (r.get("LOCPLC_ADDR") or "").strip()
            if not addr:
                report["no_addr"] += 1
                continue
            g = geocode(client, addr)
            if not g:
                report["geocode_failed"] += 1
                continue
            if g["precision"] == "dong":
                report["loc_dong"] += 1
            stage_raw = (r.get("BIZ_STEP_NM") or "").strip()
            area = r.get("ZONE_AR")
            features.append({
                "type": "Feature",
                "properties": {
                    "name": (r.get("IMPRV_ZONE_NM") or "").strip() or None,
                    "kind": (r.get("BIZ_TYPE_NM") or "").strip() or None,
                    "phase": normalize_stage(stage_raw, GG_STAGE_MAP),
                    "phase_raw": stage_raw or None,
                    "sigungu": (r.get("SIGUN_NM") or "").strip() or None,
                    "jibun": addr,
                    "area_m2": round(area) if isinstance(area, (int, float)) and area > 0 else None,
                    "record_code": None,
                    "loc_precision": g["precision"],
                },
                "geometry": {"type": "Point",
                             "coordinates": [round(g["lng"], 6), round(g["lat"], 6)]},
            })
    save_cache()
    unknown_raw = sorted({
        f["properties"]["phase_raw"] for f in features
        if f["properties"]["phase"] == "unknown" and f["properties"]["phase_raw"]
    })
    report["features"] = len(features)
    report["unmapped_stage_values"] = unknown_raw
    return {"type": "FeatureCollection", "features": features}, report
