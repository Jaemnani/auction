"""EPSG:5174 (Korean 1985 / Modified Central Belt, Bessel 1841) → EPSG:4326.

국토부 정비구역 SHP(LSMD_CONT_UD602_5174_*)가 5174 로 배포된다.
noise/proj.py 와 같은 방침으로 pyproj 없이 순수 Python.

5174 는 5179(GRS80/ITRF) 와 달리 **Bessel 1841 + Korean Datum 1985** 라
TM 역투영만으로는 WGS84 가 되지 않는다. 7-파라미터 Helmert(datum shift)를
반드시 거쳐야 하고, 생략하면 수백 m 어긋난다.

  +proj=tmerc +lat_0=38 +lon_0=127.0028902777778 +k=1 +x_0=200000 +y_0=500000
  +ellps=bessel +towgs84=-115.80,474.99,674.11,1.16,-2.31,-1.63,6.43

towgs84 값은 국내 표준(서울 도시공간포털 등 공공 GIS 가 동일 값 사용).
회전각 부호 규약은 Position Vector(EPSG:9606) — proj4 towgs84 와 같다.

검증(2026-08): 부산 정비구역 SHP bbox (378532,175328)~(407330,205687) →
경도 128.958~129.281 / 위도 35.061~35.329 로 실제 부산 범위와 일치.
"""
from __future__ import annotations

import math

# --- Bessel 1841 (원본 좌표계) ---
_A = 6377397.155
_F = 1 / 299.1528128
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)

# --- EPSG:5174 투영 파라미터 ---
_LAT0 = math.radians(38.0)
_LON0 = math.radians(127.0028902777778)
_K0 = 1.0
_X0 = 200000.0
_Y0 = 500000.0

# --- Korean 1985 → WGS84 (Position Vector 7-param) ---
_DX, _DY, _DZ = -115.80, 474.99, 674.11
_RX, _RY, _RZ = (math.radians(v / 3600.0) for v in (1.16, -2.31, -1.63))
_S = 6.43e-6

# --- WGS84 ---
_A_W = 6378137.0
_F_W = 1 / 298.257223563
_E2_W = _F_W * (2 - _F_W)


def _meridian_arc(phi: float) -> float:
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    return _A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


_M0 = _meridian_arc(_LAT0)


def _tm_inverse(x: float, y: float) -> tuple[float, float]:
    """5174 평면좌표 → Bessel 타원체상 (lon, lat) 라디안. Snyder 역변환."""
    m = _M0 + (y - _Y0) / _K0
    mu = m / (_A * (1 - _E2 / 4 - 3 * _E2 ** 2 / 64 - 5 * _E2 ** 3 / 256))
    e1 = (1 - math.sqrt(1 - _E2)) / (1 + math.sqrt(1 - _E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
        + (21 * e1 ** 2 / 16 - 55 * e1 ** 4 / 32) * math.sin(4 * mu)
        + (151 * e1 ** 3 / 96) * math.sin(6 * mu)
        + (1097 * e1 ** 4 / 512) * math.sin(8 * mu)
    )
    s1, c1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c = _EP2 * c1 ** 2
    t = tan1 ** 2
    n = _A / math.sqrt(1 - _E2 * s1 ** 2)
    r = _A * (1 - _E2) / (1 - _E2 * s1 ** 2) ** 1.5
    d = (x - _X0) / (n * _K0)
    lat = phi1 - (n * tan1 / r) * (
        d ** 2 / 2
        - (5 + 3 * t + 10 * c - 4 * c ** 2 - 9 * _EP2) * d ** 4 / 24
        + (61 + 90 * t + 298 * c + 45 * t ** 2 - 252 * _EP2 - 3 * c ** 2) * d ** 6 / 720
    )
    lon = _LON0 + (
        d
        - (1 + 2 * t + c) * d ** 3 / 6
        + (5 - 2 * c + 28 * t - 3 * c ** 2 + 8 * _EP2 + 24 * t ** 2) * d ** 5 / 120
    ) / c1
    return lon, lat


def to_wgs84(x: float, y: float, *, precision: int = 6) -> tuple[float, float]:
    """(easting, northing) EPSG:5174 → (lon, lat) EPSG:4326.

    precision: 소수 자릿수. 6 이면 약 11cm — 표시용으로 충분하고 파일이 작아진다.
    """
    lon, lat = _tm_inverse(x, y)

    # 지리좌표(Bessel) → 지심직교좌표
    sin_lat = math.sin(lat)
    n = _A / math.sqrt(1 - _E2 * sin_lat * sin_lat)
    gx = n * math.cos(lat) * math.cos(lon)
    gy = n * math.cos(lat) * math.sin(lon)
    gz = n * (1 - _E2) * sin_lat

    # Helmert 7-param (Position Vector)
    k = 1 + _S
    gx, gy, gz = (
        _DX + k * (gx - _RZ * gy + _RY * gz),
        _DY + k * (_RZ * gx + gy - _RX * gz),
        _DZ + k * (-_RY * gx + _RX * gy + gz),
    )

    # 지심직교 → 지리좌표(WGS84). Bowring 반복 — 국내 위도에서 3회면 mm 수렴.
    lon_w = math.atan2(gy, gx)
    p = math.hypot(gx, gy)
    lat_w = math.atan2(gz, p * (1 - _E2_W))
    for _ in range(5):
        s = math.sin(lat_w)
        nw = _A_W / math.sqrt(1 - _E2_W * s * s)
        h = p / math.cos(lat_w) - nw
        lat_w = math.atan2(gz, p * (1 - _E2_W * nw / (nw + h)))

    return round(math.degrees(lon_w), precision), round(math.degrees(lat_w), precision)
