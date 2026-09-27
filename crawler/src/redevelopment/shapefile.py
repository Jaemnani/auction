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


def read_dbf(path: str | Path, encoding: str = "euc-kr") -> list[dict[str, str]]:
    """dBase 레코드 → dict 목록. 삭제 표시(*) 레코드는 건너뛴다.

    encoding 은 같은 폴더의 .cpg 파일을 우선 쓰는 것이 안전하다
    (국토부 배포본은 EUC-KR).
    ⚠️ 건너뛴 만큼 인덱스가 당겨지므로 .shp 도형과 짝지을 때는
    read_dbf_records + drop_deleted 를 쓸 것.
    """
    return [r for r in read_dbf_records(path, encoding) if r is not None]


def read_dbf_records(
    path: str | Path, encoding: str = "euc-kr",
) -> list[dict[str, str] | None]:
    """read_dbf 와 같되 삭제·손상 레코드를 None 으로 남겨 원래 레코드 번호를 보존한다.

    .shp 는 삭제 여부와 무관하게 레코드마다 도형을 하나씩 두므로,
    인덱스로 짝지으려면 이쪽을 써야 한다.
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
        if len(rec) < rlen or rec[:1] == b"*":  # 삭제 표시 — 자리는 지킨다
            rows.append(None)
            continue
        pos = 1
        row: dict[str, str] = {}
        for name, flen in fields:
            row[name] = rec[pos:pos + flen].decode(encoding, "replace").strip()
            pos += flen
        rows.append(row)
    return rows


def detect_encoding(shp_path: str | Path, default: str = "euc-kr") -> str:
    """같은 이름의 .cpg 가 있으면 그 인코딩을 쓴다."""
    cpg = Path(shp_path).with_suffix(".cpg")
    if cpg.exists():
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
        if shape_type == SHAPE_POLYGON:
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


def drop_deleted(
    records: list[dict[str, str] | None], shapes: list[Any],
) -> list[tuple[dict[str, str], Any]]:
    """read_dbf_records 결과와 .shp 도형을 원래 레코드 번호로 짝짓고 삭제 레코드를 뺀다.

    짝 없는 꼬리(한쪽이 더 긴 경우)는 버린다.
    """
    return [
        (rec, shape)
        for rec, shape in zip(records, shapes)
        if rec is not None
    ]


def read_shapefile(
    shp_path: str | Path,
    transform: Callable[[float, float], tuple[float, float]] | None = None,
) -> list[tuple[dict[str, str], list]]:
    """(속성, MultiPolygon coordinates) 목록. 도형 없는 레코드·삭제 레코드는 제외."""
    shp_path = Path(shp_path)
    enc = detect_encoding(shp_path)
    records = read_dbf_records(shp_path.with_suffix(".dbf"), encoding=enc)
    shapes = read_polygons(shp_path, transform=transform)
    out: list[tuple[dict[str, str], list]] = []
    for attrs, rings in drop_deleted(records, shapes):
        if not rings:
            continue
        mp = rings_to_multipolygon(rings)
        if mp:
            out.append((attrs, mp))
    return out
