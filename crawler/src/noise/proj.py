"""EPSG:5179 (Korea 2000 / Unified CS, UTM-K) → EPSG:4326 역투영.

pyproj 없이 순수 Python. Snyder 의 표준 횡메르카토르 역변환(EPSG 9807).
공항 소음등고선 WFS 가 5179 로 내려주는데 구글 지도는 4326 이라 변환이 필요하다.

EPSG:5179 = +proj=tmerc +lat_0=38 +lon_0=127.5 +k=0.9996
            +x_0=1000000 +y_0=2000000 +ellps=GRS80
"""

from __future__ import annotations

import math

# GRS80
_A = 6378137.0
_F = 1 / 298.257222101
_E2 = _F * (2 - _F)
_EP2 = _E2 / (1 - _E2)

# EPSG:5179 파라미터
_LAT0 = math.radians(38.0)
_LON0 = math.radians(127.5)
_K0 = 0.9996
_X0 = 1_000_000.0
_Y0 = 2_000_000.0


def _meridian_arc(phi: float) -> float:
    """적도에서 위도 phi 까지의 자오선 호장."""
    e2, e4, e6 = _E2, _E2 ** 2, _E2 ** 3
    return _A * (
        (1 - e2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * e2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * math.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * math.sin(4 * phi)
        - (35 * e6 / 3072) * math.sin(6 * phi)
    )


_M0 = _meridian_arc(_LAT0)


def to_wgs84(x: float, y: float) -> tuple[float, float]:
    """(easting, northing) EPSG:5179 → (lon, lat) EPSG:4326."""
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

    sin1, cos1, tan1 = math.sin(phi1), math.cos(phi1), math.tan(phi1)
    c1 = _EP2 * cos1 ** 2
    t1 = tan1 ** 2
    n1 = _A / math.sqrt(1 - _E2 * sin1 ** 2)
    r1 = _A * (1 - _E2) / (1 - _E2 * sin1 ** 2) ** 1.5
    d = (x - _X0) / (n1 * _K0)

    lat = phi1 - (n1 * tan1 / r1) * (
        d ** 2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 ** 2 - 9 * _EP2) * d ** 4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 ** 2 - 252 * _EP2 - 3 * c1 ** 2)
        * d ** 6 / 720
    )
    lon = _LON0 + (
        d
        - (1 + 2 * t1 + c1) * d ** 3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 ** 2 + 8 * _EP2 + 24 * t1 ** 2)
        * d ** 5 / 120
    ) / cos1

    return math.degrees(lon), math.degrees(lat)
