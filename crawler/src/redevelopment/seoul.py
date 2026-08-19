"""서울 정비사업 — 정비몽땅 사업장 목록 + 서울 도시공간포털 UPIS 정비구역 폴리곤.

정찰 근거: docs/redev_layer_recon.md (2026-08).

  현황(단계): cleanup.seoul.go.kr 사업장검색 — pageSize 를 키우면 전체가 한
    페이지에 온다(실측 1,152행). 컬럼: 자치구/사업구분/사업장명/대표지번/진행단계
    + 사업장 지도ID(WTNNC_SN, 376건).
  폴리곤: urban.seoul.go.kr 의 ArcGIS 프록시 — UPIS_C_UQ181(64, 현황) 정비구역
    3,305건. 목록의 지도ID 중 C 에 없는 것은 UPIS_H_UQ181(163, 이력) 에서 보강.
    outSR=4326 + geometryPrecision 서버 재투영이 되므로 좌표 변환 불필요.

폴리곤은 사업장과 매칭된 것만 산출한다 — UQ181 미매칭 도형(~2,900)은 이력·해제
·중복이 섞여 있어 "현재 정비사업" 으로 표시하면 오정보가 된다(recon 문서 참조).
"""
from __future__ import annotations

import html as _html
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .phases import SEOUL_STAGE_MAP, normalize_stage

CLEANUP_LIST_URL = (
    "https://cleanup.seoul.go.kr/cleanup/bsnssttus/lscrMainIndx.do"
    "?cpage=1&pageSize=3000"
)
# 내부 ArcGIS(98.33.2.225)는 urban.seoul.go.kr 의 공식 프록시로만 접근 가능.
ARCGIS_BASE = (
    "https://urban.seoul.go.kr/proxy/proxy.jsp?"
    "http://98.33.2.225:6080/arcgis/rest/services/UPIS/20200526_WFS/MapServer"
)
LAYER_CURRENT = 64   # UPIS_C_UQ181 (현황)
LAYER_HISTORY = 163  # UPIS_H_UQ181 (이력 — 목록 지도ID 의 1/3 이 여기에만 있음)

_REFERER = {"Referer": "https://urban.seoul.go.kr/"}
_MIN_INTERVAL_S = 0.3
_last_call = 0.0


@dataclass
class SeoulBiz:
    gu: str            # 자치구
    kind: str          # 사업구분 (재건축/재개발(주택정비형)/가로주택정비 ...)
    name: str          # 사업장명
    jibun: str         # 대표지번
    stage_raw: str     # 진행단계 원값
    record_code: str | None  # 지도ID = UPIS WTNNC_SN


def _get(url: str, timeout: float = 60) -> bytes:
    global _last_call
    wait = _MIN_INTERVAL_S - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()
    req = urllib.request.Request(url, headers=_REFERER)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


_ROW = re.compile(r"<tr>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_MAP_ID = re.compile(r"mapOpenPopup\('([^']+)'\)")
_TAG = re.compile(r"<[^>]+>")


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(_TAG.sub("", cell))).strip()


def fetch_biz_list() -> list[SeoulBiz]:
    """정비몽땅 사업장 전체 목록. 열 구조가 바뀌면 헤더 검증에서 실패한다."""
    src = _get(CLEANUP_LIST_URL).decode("utf-8", "replace")
    m = re.search(r'<table class="board-list-tbl.*?</table>', src, re.S)
    if not m:
        raise RuntimeError("정비몽땅 목록 테이블을 찾지 못함 — 화면 개편 여부 확인")
    rows = _ROW.findall(m.group(0))
    header = [_text(c) for c in _CELL.findall(rows[0])]
    expect = ["번호", "자치구", "사업구분", "사업장명", "대표지번", "진행단계"]
    if header[: len(expect)] != expect:
        raise RuntimeError(f"목록 컬럼이 예상과 다름: {header[:6]}")
    out: list[SeoulBiz] = []
    for r in rows[1:]:
        cells = _CELL.findall(r)
        if len(cells) < 6:
            continue
        mid = _MAP_ID.search(r)
        out.append(SeoulBiz(
            gu=_text(cells[1]), kind=_text(cells[2]), name=_text(cells[3]),
            jibun=_text(cells[4]), stage_raw=_text(cells[5]),
            record_code=mid.group(1) if mid else None,
        ))
    if len(out) < 500:  # 실측 1,152 — 급감하면 파싱 깨진 것
        raise RuntimeError(f"목록 행이 비정상적으로 적음: {len(out)}")
    return out


def _arcgis_query(layer: int, params: dict[str, str]) -> dict[str, Any]:
    qs = urllib.parse.urlencode({**params, "f": "json"})
    body = _get(f"{ARCGIS_BASE}/{layer}/query?{qs}")
    d = json.loads(body)
    if "error" in d:
        raise RuntimeError(f"ArcGIS layer {layer} error: {d['error']}")
    return d


def fetch_layer_attrs(layer: int) -> dict[str, dict[str, Any]]:
    """레이어 전체 속성(도형 제외) — WTNNC_SN 키. 속성만은 한 번에 다 온다(실측 3,305)."""
    d = _arcgis_query(layer, {
        "where": "1=1",
        "outFields": "OBJECTID,WTNNC_SN,DGM_NM,SIGNGU_SE,LCLAS_CL,ATRB_SE,DGM_AR",
        "returnGeometry": "false",
    })
    if d.get("exceededTransferLimit"):
        raise RuntimeError(f"layer {layer}: 속성 조회가 잘림 — 페이징 구현 필요")
    out: dict[str, dict[str, Any]] = {}
    for f in d.get("features", []):
        a = f["attributes"]
        sn = (a.get("WTNNC_SN") or "").strip()
        if sn:
            out.setdefault(sn, a)  # 동일 SN 복수 도형이면 첫 건 대표
    return out


def _rings_to_multipolygon(rings: list[list[list[float]]]) -> list:
    """ArcGIS rings → GeoJSON MultiPolygon coordinates.

    ArcGIS 는 외곽 링(시계방향) 뒤에 그 구멍(반시계)이 따라오는 순서 규약.
    signed area 로 방향을 판정해 외곽마다 폴리곤을 시작한다.
    """
    polys: list[list[list[list[float]]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        area = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i][0], ring[i][1]
            x2, y2 = ring[i + 1][0], ring[i + 1][1]
            area += x1 * y2 - x2 * y1
        if area <= 0 or not polys:  # 시계방향(외곽) — 새 폴리곤
            polys.append([ring])
        else:                        # 반시계(구멍) — 직전 폴리곤에 부착
            polys[-1].append(ring)
    return polys


def fetch_geometries(layer: int, object_ids: list[int], *, precision: int = 6,
                     batch: int = 50) -> dict[int, list]:
    """OBJECTID 배치로 도형 조회 (서버 재투영 outSR=4326)."""
    out: dict[int, list] = {}
    for i in range(0, len(object_ids), batch):
        ids = object_ids[i:i + batch]
        d = _arcgis_query(layer, {
            "objectIds": ",".join(str(v) for v in ids),
            "outFields": "OBJECTID",
            "returnGeometry": "true",
            "outSR": "4326",
            "geometryPrecision": str(precision),
        })
        for f in d.get("features", []):
            rings = (f.get("geometry") or {}).get("rings") or []
            mp = _rings_to_multipolygon(rings)
            if mp:
                out[f["attributes"]["OBJECTID"]] = mp
    return out


def _canon_name(s: str) -> str:
    """이름 2차 매칭용 보수적 정규화 — exact 비교 전용 (fuzzy 금지)."""
    s = re.sub(r"\s+", "", s)
    s = re.sub(r"(주택)?(재개발|재건축)(정비)?사업(조합)?$", "", s)
    s = re.sub(r"(정비사업)?조합$", "", s)
    return s


def build_features(*, precision: int = 6) -> tuple[dict[str, Any], dict[str, Any]]:
    """서울 FeatureCollection + 커버리지 리포트."""
    biz = fetch_biz_list()
    attrs_c = fetch_layer_attrs(LAYER_CURRENT)
    attrs_h = fetch_layer_attrs(LAYER_HISTORY)

    # 1차: 지도ID(WTNNC_SN) 조인 — C 우선, H 보강
    matched: list[tuple[SeoulBiz, dict[str, Any], int]] = []  # (사업장, attrs, layer)
    unmatched_with_id: list[SeoulBiz] = []
    for b in biz:
        if not b.record_code:
            continue
        if b.record_code in attrs_c:
            matched.append((b, attrs_c[b.record_code], LAYER_CURRENT))
        elif b.record_code in attrs_h:
            matched.append((b, attrs_h[b.record_code], LAYER_HISTORY))
        else:
            unmatched_with_id.append(b)

    # 2차: 지도ID 없는 사업장 ↔ 도형명(DGM_NM) 보수적 exact 매칭 (C 레이어만)
    taken_sns = {a["WTNNC_SN"] for _, a, _ in matched}
    by_name: dict[str, dict[str, Any]] = {}
    for sn, a in attrs_c.items():
        if sn in taken_sns:
            continue
        key = _canon_name(a.get("DGM_NM") or "")
        if key and key not in by_name:
            by_name[key] = a
    name_hits = 0
    for b in biz:
        if b.record_code:
            continue
        a = by_name.get(_canon_name(b.name))
        if a and a["WTNNC_SN"] not in taken_sns:
            matched.append((b, a, LAYER_CURRENT))
            taken_sns.add(a["WTNNC_SN"])
            name_hits += 1

    # 도형 조회 (레이어별 배치)
    need: dict[int, list[int]] = {}
    for _, a, layer in matched:
        need.setdefault(layer, []).append(a["OBJECTID"])
    geoms: dict[tuple[int, int], list] = {}
    for layer, oids in need.items():
        for oid, mp in fetch_geometries(layer, sorted(set(oids)),
                                        precision=precision).items():
            geoms[(layer, oid)] = mp

    features = []
    missing_geom = 0
    for b, a, layer in matched:
        mp = geoms.get((layer, a["OBJECTID"]))
        if not mp:
            missing_geom += 1
            continue
        features.append({
            "type": "Feature",
            "properties": {
                "name": b.name,
                "kind": b.kind,
                "phase": normalize_stage(b.stage_raw, SEOUL_STAGE_MAP),
                "phase_raw": b.stage_raw or None,
                "sigungu": b.gu,
                "jibun": b.jibun or None,
                "area_m2": round(a["DGM_AR"]) if a.get("DGM_AR") else None,
                "record_code": a["WTNNC_SN"],
            },
            "geometry": {"type": "MultiPolygon", "coordinates": mp},
        })

    unknown_raw = sorted({
        b.stage_raw for b, _, _ in matched
        if normalize_stage(b.stage_raw, SEOUL_STAGE_MAP) == "unknown" and b.stage_raw
    })
    report = {
        "biz_total": len(biz),
        "biz_with_map_id": sum(1 for b in biz if b.record_code),
        "joined_by_id": len(matched) - name_hits,
        "joined_by_name": name_hits,
        "map_id_unmatched": len(unmatched_with_id),
        "missing_geometry": missing_geom,
        "features": len(features),
        "unmapped_stage_values": unknown_raw,
    }
    fc = {"type": "FeatureCollection", "features": features}
    return fc, report
