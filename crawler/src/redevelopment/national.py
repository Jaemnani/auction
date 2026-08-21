"""전국 정비구역 폴리곤 — 국토교통부 SHP(브이월드 공간정보 다운로드).

데이터: `(연속주제)_도시및주거환경정비/정비구역` (dsId=30335)
  파일 `LSMD_CONT_UD602_5174_<시도>.zip` → `LSMD_CONT_UD602_5174_<시도코드>_<YYYYMM>.shp`
  EPSG:5174 / EUC-KR / 도시 및 주거환경정비법 제16조 지정·고시 구역.
  라이선스 CC BY-NC-ND — 표시용 사본만 두고 출처 명시, 원본 재배포 금지
  (공항소음 레이어와 동일 방침). 정찰 근거는 docs/redev_layer_recon.md.

다운로드가 로그인·전용 솔루션 경유라 자동 수집이 불가해, 사람이 받아 둔 폴더를
읽는다(기본 ~/Downloads/download). 경로는 REDEV_SHP_DIR 로 바꿀 수 있다.

폴리곤 속성에는 사업 단계가 없다(`ALIAS` 구역명도 30~60% 만 채워짐). 단계는
지자체 API(서울 정비몽땅 / 부산 / 경기)에서 와서 이름·위치로 매칭되며,
매칭 안 된 구역은 **단계 미확인**으로 정직하게 표시한다(추정 금지).
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from .phases import normalize_stage  # noqa: F401  (소비자 편의 재수출)
from .proj5174 import to_wgs84
from .shapefile import read_shapefile

DEFAULT_SHP_DIR = Path(os.path.expanduser("~/Downloads/download"))
SOURCE = "국토교통부 도시및주거환경정비 정비구역(브이월드 공간정보 다운로드)"
SOURCE_URL = "https://www.vworld.kr/dtmk/dtmk_ntads_s002.do?dsId=30335"

# 구역이 아닌 도형 — 정비기반시설(도로 등)은 구역 경계가 아니라 제외한다.
_NOT_A_ZONE = re.compile(r"기반시설")


def shp_dir() -> Path:
    return Path(os.environ.get("REDEV_SHP_DIR") or DEFAULT_SHP_DIR)


def _transform(x: float, y: float) -> tuple[float, float]:
    return to_wgs84(x, y)


def load_polygons(root: Path | None = None) -> dict[str, list[dict[str, Any]]]:
    """받아 둔 SHP 전체 → {시도코드2자리: [{alias, ntfdate, sggcd, mnum, coordinates}]}.

    시도 구분은 폴더명이 아니라 속성의 시군구코드(COL_ADM_SE) 앞 2자리로 한다
    (폴더명이 '전남광주통합특별시'처럼 복수 시도를 담을 수 있어서).
    """
    root = root or shp_dir()
    out: dict[str, list[dict[str, Any]]] = {}
    if not root.exists():
        return out
    for shp in sorted(root.glob("LSMD_CONT_UD602_*/*.shp")):
        for attrs, mp in read_shapefile(shp, transform=_transform):
            alias = (attrs.get("ALIAS") or "").strip()
            if alias and _NOT_A_ZONE.search(alias):
                continue
            sgg = (attrs.get("COL_ADM_SE") or "").strip()
            sido = sgg[:2]
            if not sido:
                continue
            out.setdefault(sido, []).append({
                "alias": alias or None,
                "ntfdate": (attrs.get("NTFDATE") or "").strip() or None,
                "sggcd": sgg or None,
                "mnum": (attrs.get("MNUM") or "").strip() or None,
                "coordinates": mp,
            })
    return out


# ---- 매칭 (이름 exact → 위치 포함) ----------------------------------------

def canon_name(s: str | None) -> str:
    """구역명 보수적 정규화 — exact 비교 전용(fuzzy 금지)."""
    s = re.sub(r"\s+", "", s or "")
    s = re.sub(r"(주택)?(재개발|재건축)(정비)?(사업)?(구역)?$", "", s)
    s = re.sub(r"(정비)?구역$", "", s)
    s = re.sub(r"(지구|사업)$", "", s)
    return s


def _bbox(mp: list) -> tuple[float, float, float, float]:
    xs = [c[0] for poly in mp for ring in poly for c in ring]
    ys = [c[1] for poly in mp for ring in poly for c in ring]
    return min(xs), min(ys), max(xs), max(ys)


def _in_ring(x: float, y: float, ring: list) -> bool:
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[i + 1][0], ring[i + 1][1]
        if (y1 > y) != (y2 > y):
            if x < x1 + (y - y1) * (x2 - x1) / (y2 - y1):
                inside = not inside
    return inside


def contains(mp: list, x: float, y: float) -> bool:
    for poly in mp:
        if _in_ring(x, y, poly[0]) and not any(_in_ring(x, y, h) for h in poly[1:]):
            return True
    return False


def merge(polygons: list[dict[str, Any]],
          biz_features: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    """공식 폴리곤 + 지자체 사업장(점 Feature) → 결합 FeatureCollection.

    - 사업장 ↔ 폴리곤: ① 구역명 exact ② 점 포함(point-in-polygon)
    - 매칭된 폴리곤: 사업장의 단계·이름·유형을 얹는다
    - 미매칭 폴리곤: 단계 미확인(unknown)으로 경계만 표시
    - 미매칭 사업장: 기존처럼 점으로 유지 (단계 정보를 잃지 않기 위해)
    한 폴리곤에는 사업장 하나만 붙인다(단계 충돌 방지 — 나머지는 점으로 남김).
    """
    prepared = []
    by_name: dict[str, int] = {}
    for i, p in enumerate(polygons):
        prepared.append((p, _bbox(p["coordinates"])))
        key = canon_name(p["alias"])
        if key and key not in by_name:
            by_name[key] = i

    taken: dict[int, dict[str, Any]] = {}
    leftover: list[dict[str, Any]] = []
    stat = {"by_name": 0, "by_point": 0, "leftover_points": 0}

    for f in biz_features:
        props = f["properties"]
        idx = by_name.get(canon_name(props.get("name")))
        how = "by_name"
        if idx is None or idx in taken:
            idx = None
            x, y = f["geometry"]["coordinates"]
            for i, (p, bb) in enumerate(prepared):
                if i in taken:
                    continue
                if bb[0] <= x <= bb[2] and bb[1] <= y <= bb[3] and contains(p["coordinates"], x, y):
                    idx = i
                    how = "by_point"
                    break
        if idx is None:
            leftover.append(f)
            stat["leftover_points"] += 1
        else:
            taken[idx] = props
            stat[how] += 1

    features: list[dict[str, Any]] = []
    for i, p in enumerate(polygons):
        props = taken.get(i)
        if props:
            merged = {**props, "area_m2": props.get("area_m2"),
                      "ntfdate": p["ntfdate"], "boundary_source": "molit"}
            merged.pop("loc_precision", None)
        else:
            merged = {
                "name": p["alias"],          # 없으면 None → 웹이 "정비구역"으로 표시
                "kind": None,
                "phase": "unknown",
                "phase_raw": None,
                "sigungu": None,
                "jibun": None,
                "area_m2": None,
                "record_code": p["mnum"],
                "ntfdate": p["ntfdate"],
                "boundary_source": "molit",
            }
        features.append({
            "type": "Feature",
            "properties": merged,
            "geometry": {"type": "MultiPolygon", "coordinates": p["coordinates"]},
        })
    features.extend(leftover)

    stat["polygons"] = len(polygons)
    stat["features"] = len(features)
    return {"type": "FeatureCollection", "features": features}, stat
