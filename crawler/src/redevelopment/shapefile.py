"""최소 shapefile(.shp/.dbf) 리더 — 폴리곤 + 속성만.

pyshp/geopandas 없이 순수 Python (noise 레이어와 같은 무의존성 방침).
국토부 정비구역 SHP(LSMD_CONT_UD602_5174_*)가 유일한 소비처라
Polygon(shapeType 5)과 dBase III 문자/숫자 필드만 지원한다.

포맷 참고: ESRI Shapefile Technical Description
  .shp  100바이트 헤더 + [레코드번호(4,BE) 길이(4,BE) 콘텐츠] 반복
        Polygon = type(4,LE) box(32) numParts(4) numPoints(4)
                  parts(4*n) points(16*n)  — 링은 외곽=시계, 구멍=반시계
  .dbf  32바이트 헤더 + 32바이트*필드 + 0x0D + 레코드(첫 바이트 = 삭제 플래그)
"""
from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Callable

SHAPE_NULL = 0
SHAPE_POLYGON = 5
# PolygonZ/PolygonM — XY 레이아웃이 Polygon 과 같다(뒤에 Z/M 배열이 더 붙을 뿐).
# 지원하지 않으면 레코드가 NULL 로 취급돼 구역이 조용히 빠진다.
POLYGON_TYPES = (SHAPE_POLYGON, 15, 25)


def read_dbf(path: str | Path, encoding: str = "euc-kr") -> list[dict[str, str]]:
    """dBase 레코드 → dict 목록. 삭제 표시(*) 레코드는 건너뛴다.

    ⚠ 삭제 레코드를 빼므로 .shp 도형과 인덱스가 어긋날 수 있다 — 도형과
    짝지을 때는 read_dbf_aligned 를 쓸 것.
    encoding 은 같은 폴더의 .cpg 파일을 우선 쓰는 것이 안전하다
    (국토부 배포본은 EUC-KR).
    """
    return [r for r in read_dbf_aligned(path, encoding) if r is not None]


def read_dbf_aligned(path: str | Path, encoding: str = "euc-kr",
                     ) -> list[dict[str, str] | None]:
    """.shp 레코드와 인덱스가 맞는 dBase 레코드 목록.

    삭제 표시(*)·잘린 레코드는 None 으로 자리를 지킨다. 삭제 레코드를 그냥
    빼면 그 뒤 모든 속성이 한 칸씩 밀려 엉뚱한 폴리곤에 붙는다 (예외 없이).
    """
    b = Path(path).read_bytes()
    nrec, hlen, rlen = struct.unpack("<IHH", b[4:12])

    fields: list[tuple[str, int]] = []
    off = 32
    while off < len(b) and b[off] != 0x0D:
        name = b[off:off + 11].split(b"\0")[0].decode("ascii", "replace")
        flen = b[off + 16]
        fields.append((name, flen))
        off += 32

    rows: list[dict[str, str] | None] = []
    for i in range(nrec):
        start = hlen + i * rlen
        rec = b[start:start + rlen]
        if len(rec) < rlen or rec[:1] == b"*":  # 삭제 표시 — 자리만 지킨다
            rows.append(None)
            continue
        pos = 1
        row: dict[str, str] = {}
        for name, flen in fields:
            row[name] = rec[pos:pos + flen].decode(encoding, "replace").strip()
            pos += flen
        rows.append(row)
    return rows


def find_sidecar(shp_path: str | Path, ext: str) -> Path | None:
    """같은 이름의 짝 파일(.dbf/.cpg)을 확장자 대소문자 무시로 찾는다.

    배포본에 .SHP/.DBF 대문자가 흔하고, Linux 는 대소문자를 구분한다.
    """
    shp_path = Path(shp_path)
    exact = shp_path.with_suffix(ext)
    if exact.exists():
        return exact
    for p in shp_path.parent.iterdir():
        if p.stem == shp_path.stem and p.suffix.lower() == ext.lower():
            return p
    return None


def is_shp(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() == ".shp"


def detect_encoding(shp_path: str | Path, default: str = "euc-kr") -> str:
    """같은 이름의 .cpg 가 있으면 그 인코딩을 쓴다."""
    cpg = find_sidecar(shp_path, ".cpg")
    if cpg:
        enc = cpg.read_text(errors="replace").strip()
        if enc:
            return enc
    return default


def read_polygons(
    path: str | Path,
    transform: Callable[[float, float], tuple[float, float]] | None = None,
) -> list[list[list[tuple[float, float]]]]:
    """.shp → 도형별 링 목록. transform 이 있으면 좌표마다 적용(좌표계 변환용).

    반환: shapes[i] = [ring, ...], ring = [(x, y), ...]
          폴리곤이 아닌 레코드는 빈 목록으로 자리를 지켜 .dbf 행과 인덱스가 맞는다.
    """
    b = Path(path).read_bytes()
    out: list[list[list[tuple[float, float]]]] = []
    off = 100
    total = len(b)
    while off + 8 <= total:
        _num, ln = struct.unpack(">ii", b[off:off + 8])
        off += 8
        end = off + ln * 2
        shape_type, = struct.unpack("<i", b[off:off + 4])
        if shape_type in POLYGON_TYPES:
            nparts, npoints = struct.unpack("<ii", b[off + 36:off + 44])
            parts = struct.unpack(f"<{nparts}i", b[off + 44:off + 44 + 4 * nparts])
            pbase = off + 44 + 4 * nparts
            pts = struct.unpack(f"<{2 * npoints}d", b[pbase:pbase + 16 * npoints])
            rings: list[list[tuple[float, float]]] = []
            for i, s in enumerate(parts):
                e = parts[i + 1] if i + 1 < nparts else npoints
                ring = [
                    (transform(pts[2 * j], pts[2 * j + 1]) if transform
                     else (pts[2 * j], pts[2 * j + 1]))
                    for j in range(s, e)
                ]
                rings.append(ring)
            out.append(rings)
        else:  # NULL 등 — 인덱스 정렬 유지
            out.append([])
        off = end
    return out


def rings_to_multipolygon(rings: list[list[tuple[float, float]]]) -> list:
    """shapefile 링 목록 → GeoJSON MultiPolygon coordinates.

    shapefile 규약상 외곽 링은 시계방향(부호 면적 <= 0), 구멍은 반시계.
    구멍은 직전 외곽 링에 붙인다.
    """
    polys: list[list[list[list[float]]]] = []
    for ring in rings:
        if len(ring) < 4:
            continue
        area = 0.0
        for i in range(len(ring) - 1):
            x1, y1 = ring[i]
            x2, y2 = ring[i + 1]
            area += x1 * y2 - x2 * y1
        closed = [[x, y] for x, y in ring]
        if closed[0] != closed[-1]:
            closed.append(closed[0])
        if area <= 0 or not polys:  # 외곽
            polys.append([closed])
        else:  # 구멍
            polys[-1].append(closed)
    return polys


def read_shapefile(
    shp_path: str | Path,
    transform: Callable[[float, float], tuple[float, float]] | None = None,
) -> list[tuple[dict[str, str], list]]:
    """(속성, MultiPolygon coordinates) 목록. 도형 없는·삭제된 레코드는 제외."""
    shp_path = Path(shp_path)
    enc = detect_encoding(shp_path)
    dbf = find_sidecar(shp_path, ".dbf")
    if dbf is None:
        raise FileNotFoundError(f"{shp_path.name} 의 .dbf 가 없습니다")
    attrs = read_dbf_aligned(dbf, encoding=enc)
    shapes = read_polygons(shp_path, transform=transform)
    out: list[tuple[dict[str, str], list]] = []
    for i, rings in enumerate(shapes):
        if i >= len(attrs) or attrs[i] is None or not rings:
            continue
        mp = rings_to_multipolygon(rings)
        if mp:
            out.append((attrs[i], mp))
    return out
