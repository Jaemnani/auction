"""한옥 레이어 소스 → GeoJSON feature. 네트워크 없는 순수 변환 계층.

소스 3종 (전부 사람이 받아 둔 파일을 읽는다 — 서울 포털은 자동 수집 대상 아님):

  preservation  한옥보전구역 공식 경계. 서울한옥포털 '한옥보전구역 지정 공고'
                PDF 를 연속지적도 위에서 QGIS 로 직접 딴 GeoJSON. 유일한 공식
                원본이라 공고일 없이는 받지 않는다.
  district      서울시 지구단위계획구역 SHP (열린데이터광장 OA-21161,
                EPSG:5174 / cp949). 한옥 밀집 동네만 골라 "대략 범위" 배경으로.
  registry      서울시 한옥등록 정보 CSV (OA-15415). 주소 → 지오코딩 점.

좌표 검증이 핵심이다. 5174 를 towgs84 없이 풀거나 QGIS 에서 투영좌표 그대로
내보내면 예외 없이 엉뚱한 곳에 그려진다 → 서울 박스 밖이면 build 를 멈춘다.
"""
from __future__ import annotations

import csv
import io
import re
import shutil
import struct
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Iterator

from redevelopment.national import contains
from redevelopment.proj5174 import to_wgs84
from redevelopment.shapefile import (
    detect_encoding, read_dbf, read_polygons, rings_to_multipolygon,
)

# 서울 경계(여유 포함). 변환 결과가 여기 밖이면 좌표계를 잘못 읽은 것.
SEOUL_BOX = (126.70, 37.40, 127.25, 37.75)

# 한옥 밀집 지구단위계획구역 — 이름에 이 키워드가 들어간 구역만 남긴다.
# (북촌, 경복궁서측=서촌, 인사동, 돈화문로, 익선, 운현궁·조계사 주변,
#  성북 선잠단지·앵두마을)
DISTRICT_KEYWORDS = (
    "북촌", "경복궁서측", "서촌", "인사동", "돈화문로", "익선",
    "운현궁", "조계사", "선잠단지", "앵두마을",
)

# 구역명이 담겼을 법한 필드 — 먼저 찾고, 없으면 모든 문자열 속성을 훑는다.
_NAME_FIELDS = ("DGM_NM", "ALIAS", "ZONE_NM", "NAME", "NM", "구역명", "명칭")

_DATE_RE = re.compile(r"^(\d{4})[-.](\d{1,2})[-.](\d{1,2})$")


class LayerError(ValueError):
    """사람이 고쳐야 하는 입력 문제 — 메시지를 그대로 보여 준다."""


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def in_seoul(lng: float, lat: float) -> bool:
    w, s, e, n = SEOUL_BOX
    return w <= lng <= e and s <= lat <= n


def _iter_coords(coords: Any) -> Iterator[tuple[float, float]]:
    if coords and isinstance(coords[0], (int, float)):
        yield float(coords[0]), float(coords[1])
        return
    for c in coords or []:
        yield from _iter_coords(c)


def _map_coords(coords: Any, fn) -> Any:
    if coords and isinstance(coords[0], (int, float)):
        return list(fn(float(coords[0]), float(coords[1])))
    return [_map_coords(c, fn) for c in coords]


def _round_coords(coords: Any, precision: int) -> Any:
    return _map_coords(coords, lambda x, y: (round(x, precision), round(y, precision)))


def assert_in_seoul(coords: Any, what: str) -> None:
    for lng, lat in _iter_coords(coords):
        if not in_seoul(lng, lat):
            raise LayerError(
                f"{what}: 좌표 ({lng:.5f}, {lat:.5f}) 가 서울 밖입니다. "
                "좌표계가 EPSG:4326 인지(또는 5174 변환이 맞는지) 확인하세요.")


def normalize_date(v: Any) -> str | None:
    """'2024.3.5' / '2024-03-05' / '20240305' → '2024-03-05'."""
    s = str(v or "").strip()
    if re.fullmatch(r"\d{8}", s):
        s = f"{s[:4]}-{s[4:6]}-{s[6:]}"
    m = _DATE_RE.match(s)
    if not m:
        return None
    y, mo, d = (int(g) for g in m.groups())
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


# ---- 보전구역 (QGIS 수작업 GeoJSON) -----------------------------------------

def _looks_projected(coords: Any) -> bool:
    return any(abs(x) > 180 or abs(y) > 90 for x, y in _iter_coords(coords))


def _crs_name(gj: dict) -> str:
    return str(((gj.get("crs") or {}).get("properties") or {}).get("name") or "")


def load_preservation(gj: dict, *, notice_date: str | None = None,
                      precision: int = 6) -> list[dict]:
    """QGIS 에서 내보낸 GeoJSON → 보전구역 feature.

    - EPSG:4326 권장. crs 가 5174 로 명시된 투영좌표면 변환해 준다.
      crs 없이 투영좌표면 무엇인지 알 수 없으므로 거부.
    - 공고일(notice_date) 필수 — feature 속성(notice_date/공고일) 또는 인자.
    """
    if gj.get("type") != "FeatureCollection":
        raise LayerError("보전구역: FeatureCollection GeoJSON 이 아닙니다.")
    crs = _crs_name(gj)
    default_date = normalize_date(notice_date) if notice_date else None
    if notice_date and not default_date:
        raise LayerError(f"보전구역: 공고일 형식 오류 '{notice_date}' (YYYY-MM-DD)")

    out: list[dict] = []
    for i, f in enumerate(gj.get("features") or []):
        geom = f.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise LayerError(f"보전구역 #{i + 1}: 폴리곤이 아닙니다 ({geom.get('type')}).")
        coords = geom["coordinates"]
        if _looks_projected(coords):
            if "5174" not in crs:
                raise LayerError(
                    f"보전구역 #{i + 1}: 투영좌표(m)인데 좌표계가 5174 로 명시돼 있지 "
                    f"않습니다 (crs='{crs or '없음'}'). QGIS 에서 EPSG:4326 으로 "
                    "다시 내보내세요.")
            coords = _map_coords(coords, lambda x, y: to_wgs84(x, y, precision=precision))
        else:
            coords = _round_coords(coords, precision)
        if geom["type"] == "Polygon":
            coords = [coords]
        assert_in_seoul(coords, f"보전구역 #{i + 1}")

        p = f.get("properties") or {}
        date = normalize_date(p.get("notice_date") or p.get("공고일")) or default_date
        if not date:
            raise LayerError(
                f"보전구역 #{i + 1}: 공고일이 없습니다. 속성 notice_date 를 채우거나 "
                "--notice-date 로 지정하세요.")
        name = _nfc(str(p.get("name") or p.get("구역명") or "")).strip()
        props: dict[str, Any] = {
            "layer": "preservation",
            "name": name or "한옥보전구역",
            "notice_date": date,
        }
        notice_no = str(p.get("notice_no") or p.get("공고번호") or "").strip()
        if notice_no:
            props["notice_no"] = notice_no
        out.append({"type": "Feature", "properties": props,
                    "geometry": {"type": "MultiPolygon", "coordinates": coords}})
    if not out:
        raise LayerError("보전구역: feature 가 0개입니다.")
    return out


# ---- 지구단위계획구역 (OA-21161 SHP) ------------------------------------------

def match_district(attrs: dict[str, str]) -> str | None:
    """한옥 밀집 구역이면 구역명, 아니면 None."""
    names = [attrs.get(k, "") for k in _NAME_FIELDS if attrs.get(k)]
    names += [v for k, v in attrs.items() if k not in _NAME_FIELDS]
    for v in names:
        v = _nfc(str(v)).strip()
        compact = re.sub(r"\s+", "", v)
        if any(k in compact for k in DISTRICT_KEYWORDS):
            return v
    return None


def iter_shapefiles(src: Path) -> Iterator[Path]:
    """.shp 파일 / 폴더 / zip 어느 것이든 .shp 경로를 산출 (zip 은 임시 해제)."""
    if src.suffix.lower() == ".shp":
        yield src
        return
    if src.is_dir():
        yield from sorted(src.rglob("*.shp"))
        return
    if src.suffix.lower() == ".zip":
        tmp = Path(tempfile.mkdtemp(prefix="hanok_shp_"))
        try:
            with zipfile.ZipFile(src) as zf:
                # zip slip 방어 — 아카이브 밖으로 나가는 경로는 무시
                members = [m for m in zf.namelist()
                           if not (m.startswith("/") or ".." in Path(m).parts)]
                zf.extractall(tmp, members=members)
            yield from sorted(tmp.rglob("*.shp"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return
    raise LayerError(f"지구단위계획: SHP/폴더/zip 이 아닙니다 — {src}")


def _drop_deleted(dbf: Path, shapes: list) -> list:
    b = dbf.read_bytes()
    nrec, hlen, rlen = struct.unpack("<IHH", b[4:12])
    deleted = {i for i in range(nrec) if b[hlen + i * rlen:hlen + i * rlen + 1] == b"*"}
    return [s for i, s in enumerate(shapes) if i not in deleted]


def load_districts(src: Path, *, precision: int = 6) -> tuple[list[dict], dict]:
    """OA-21161 SHP → 한옥 밀집 구역 feature. (features, report)."""
    out: list[dict] = []
    total = 0
    tf = lambda x, y: to_wgs84(x, y, precision=precision)  # noqa: E731
    for shp in iter_shapefiles(src):
        # .cpg 없는 배포본이 많다 — 열린데이터광장 SHP 는 cp949 (euc-kr 상위집합).
        attrs_list = read_dbf(shp.with_suffix(".dbf"),
                              encoding=detect_encoding(shp, default="cp949"))
        # 원좌표 — 필터 통과분만 변환(전 구역 변환은 낭비). read_dbf 는 삭제
        # 레코드를 건너뛰므로 도형도 같은 행을 빼야 속성과 짝이 맞는다.
        shapes = _drop_deleted(shp.with_suffix(".dbf"), read_polygons(shp))
        for attrs, rings in zip(attrs_list, shapes):
            total += 1
            name = match_district(attrs)
            if not name or not rings:
                continue
            mp = _map_coords(rings_to_multipolygon(rings), tf)
            assert_in_seoul(mp, f"지구단위계획 '{name}'")
            out.append({
                "type": "Feature",
                "properties": {"layer": "district", "name": name},
                "geometry": {"type": "MultiPolygon", "coordinates": mp},
            })
    return out, {"shp_records": total, "matched": len(out)}


# ---- 등록한옥·지원내역 CSV (OA-15415 외) ---------------------------------------

def read_csv(path: Path) -> list[dict[str, str]]:
    """열린데이터광장 CSV — utf-8(BOM) 또는 cp949."""
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp949"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise LayerError(f"CSV 인코딩을 알 수 없습니다 — {path}")
    rows = list(csv.DictReader(io.StringIO(text)))
    return [{_nfc(k or "").strip(): (v or "").strip() for k, v in r.items()} for r in rows]


def find_column(headers: list[str], *candidates: str) -> str | None:
    """헤더 중 후보 키워드를 포함하는 첫 열 (후보 순서 우선)."""
    for c in candidates:
        for h in headers:
            if c in re.sub(r"\s+", "", h):
                return h
    return None


def _num(v: str) -> float | None:
    try:
        return float(v.replace(",", ""))
    except (AttributeError, ValueError):
        return None


def registry_records(rows: list[dict[str, str]]) -> list[dict]:
    """한옥등록 CSV 행 → {reg_no, addr, land_m2, floor_m2}. 주소 없는 행 제외."""
    if not rows:
        return []
    headers = list(rows[0].keys())
    c_no = find_column(headers, "등록번호")
    c_addr = find_column(headers, "도로명주소", "지번주소", "소재지", "주소")
    c_land = find_column(headers, "대지면적")
    c_floor = find_column(headers, "연면적")
    if not c_addr:
        raise LayerError(f"한옥등록: 주소 열을 찾지 못했습니다 (헤더: {headers})")
    out = []
    for r in rows:
        addr = r.get(c_addr, "")
        if not addr:
            continue
        out.append({
            "reg_no": r.get(c_no, "") if c_no else "",
            "addr": addr,
            "land_m2": _num(r.get(c_land, "")) if c_land else None,
            "floor_m2": _num(r.get(c_floor, "")) if c_floor else None,
        })
    return out


def address_column(rows: list[dict[str, str]]) -> str:
    headers = list(rows[0].keys()) if rows else []
    col = find_column(headers, "도로명주소", "지번주소", "소재지", "주소", "위치")
    if not col:
        raise LayerError(f"주소 열을 찾지 못했습니다 (헤더: {headers})")
    return col


def registry_feature(rec: dict, pt: dict) -> dict:
    props: dict[str, Any] = {
        "layer": "registry",
        "reg_no": rec["reg_no"] or None,
        "addr": rec["addr"],
        "loc_precision": pt.get("precision", "parcel"),
    }
    if rec.get("land_m2"):
        props["land_m2"] = rec["land_m2"]
    if rec.get("floor_m2"):
        props["floor_m2"] = rec["floor_m2"]
    return {"type": "Feature", "properties": props,
            "geometry": {"type": "Point", "coordinates": [pt["lng"], pt["lat"]]}}


# ---- 검증: 점이 보전구역 안에 드는가 --------------------------------------------

def points_vs_zones(points: list[tuple[float, float]], zones: list[dict]) -> dict:
    """지원내역·등록한옥 점으로 수작업 보전구역을 교차 검증.

    지원금은 보전구역 기준이라, 지원 점이 구역 밖에 많으면 폴리곤을 의심한다.
    """
    polys = [z["geometry"]["coordinates"] for z in zones]
    outside = [p for p in points if not any(contains(mp, p[0], p[1]) for mp in polys)]
    return {"total": len(points), "inside": len(points) - len(outside), "outside": outside}


def bbox(features: list[dict]) -> list[float]:
    xs, ys = [], []
    for f in features:
        for x, y in _iter_coords(f["geometry"]["coordinates"]):
            xs.append(x)
            ys.append(y)
    return [min(xs), min(ys), max(xs), max(ys)] if xs else []
