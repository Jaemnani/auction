"""부산 정비사업 — data.go.kr 부산광역시 정비사업 API (6260000).

정찰 근거: docs/redev_layer_recon.md. 2026-08 실측 343건.
좌표·폴리곤이 없어 location 주소를 Kakao 지오코딩해 **대표 위치 점**으로 표시.
사업 유형은 별도 필드가 없어 areaName 에 실재하는 키워드에서만 추출한다
(없으면 None — 임의 추정 금지).

⚠ ServiceKey 는 이미 URL-encoded → raw concat (재인코딩 금지, molit 선례).
"""
from __future__ import annotations

import os
import time

import httpx

from .geocode import geocode, save_cache
from .phases import BUSAN_STAGE_MAP, normalize_stage

ENDPOINT = ("https://apis.data.go.kr/6260000/MaintenanceBusinessStatus1"
            "/getMaintenanceBusiness1")
SOURCE = "부산광역시 정비사업 정보 (공공데이터포털)"

_KIND_KEYWORDS = ["소규모재건축", "소규모재개발", "가로주택", "재개발", "재건축",
                  "주거환경", "도시환경"]


def _kind_from_name(name: str) -> str | None:
    for kw in _KIND_KEYWORDS:
        if kw in name:
            return "가로주택정비" if kw == "가로주택" else kw
    return None


def fetch_rows(api_key: str | None = None) -> list[dict]:
    api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY")
    if not api_key:
        raise RuntimeError("DATA_GO_KR_API_KEY env required")
    rows: list[dict] = []
    page = 1
    with httpx.Client(timeout=30) as client:
        while True:
            url = (f"{ENDPOINT}?serviceKey={api_key}"
                   f"&pageNo={page}&numOfRows=100&resultType=json")
            body = client.get(url).json()
            resp = body.get("response") or {}
            header = resp.get("header") or {}
            if str(header.get("resultCode", "")).strip("0"):
                raise RuntimeError(f"부산 API error: {header}")
            b = resp.get("body") or {}
            items = (b.get("items") or {}).get("item") or []
            if isinstance(items, dict):
                items = [items]
            rows.extend(items)
            if len(rows) >= int(b.get("totalCount") or 0) or not items:
                return rows
            page += 1
            time.sleep(0.2)


def source_count() -> int:
    """check 용 — 원본 총 건수만."""
    api_key = os.environ.get("DATA_GO_KR_API_KEY")
    if not api_key:
        raise RuntimeError("DATA_GO_KR_API_KEY env required")
    url = f"{ENDPOINT}?serviceKey={api_key}&pageNo=1&numOfRows=1&resultType=json"
    body = httpx.get(url, timeout=30).json()
    return int(body["response"]["body"]["totalCount"])


def _num(v) -> float | None:
    try:
        f = float(str(v).replace(",", ""))
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def build_features(*, precision: int = 6) -> tuple[dict, dict]:  # noqa: ARG001
    """부산 FeatureCollection(Point) + 리포트. precision 은 시그니처 통일용."""
    rows = fetch_rows()
    features = []
    report = {"biz_total": len(rows), "no_addr": 0, "geocode_failed": 0,
              "loc_dong": 0}
    with httpx.Client(timeout=30) as client:
        for r in rows:
            addr = (r.get("location") or "").strip()
            if not addr:
                report["no_addr"] += 1
                continue
            g = geocode(client, addr)
            if not g:
                report["geocode_failed"] += 1
                continue
            if g["precision"] == "dong":
                report["loc_dong"] += 1
            name = (r.get("areaName") or "").strip()
            stage_raw = (r.get("step") or "").strip()
            features.append({
                "type": "Feature",
                "properties": {
                    "name": name or None,
                    "kind": _kind_from_name(name),
                    "phase": normalize_stage(stage_raw, BUSAN_STAGE_MAP),
                    "phase_raw": stage_raw or None,
                    "sigungu": None,
                    "jibun": addr,
                    "area_m2": _num(r.get("areaUnit")),
                    "record_code": (r.get("aCode") or "").strip() or None,
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
