"""공항 소음등고선 WFS 수집 → GeoJSON (EPSG:4326).

출처: 공항소음포털(airportnoise.kr) — /anps/gis/engine, WFS 1.1.0, TL_NS_CTRLN
자세한 정찰 근거는 docs/airport_noise_layer.md.

⚠ 원 자료는 국토교통부 공항소음대책지역 계열이고, 같은 내용을 브이월드가
  CC BY-NC-ND 로 배포한다. 우리는 **표시용 사본**만 두고, 출처를 명시하며,
  원본 다운로드를 제공하지 않는다. 갱신은 연 단위(YEAR)라 재수집도 드물게 한다.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any

from .proj import to_wgs84

BASE = "https://www.airportnoise.kr/anps/gis"
ENGINE = f"{BASE}/engine"

# WECPNL 등급 → 소음대책지역 구분 (공항소음방지법 시행령).
# 등고선 값 자체는 70 부터 있으나 법정 대책지역은 75 이상이다.
WECPNL_ZONE = {
    95: "제1종 구역",
    90: "제2종 구역",
    85: "제3종 가지구",
    80: "제3종 나지구",
    75: "제3종 다지구",
    70: "참고(대책지역 밖)",
}

_GETFEATURE = """<wfs:GetFeature service="WFS" version="1.1.0">
  <wfs:Query typeName="TL_NS_CTRLN" srsName="EPSG:5179">
    <ogc:SrsName>EPSG:5179</ogc:SrsName>
    <ogc:Filter><ogc:And>
      <ogc:PropertyIsEqualTo><ogc:PropertyName>ARP_SE</ogc:PropertyName>
        <ogc:Literal>{arp}</ogc:Literal></ogc:PropertyIsEqualTo>
      <ogc:PropertyIsEqualTo><ogc:PropertyName>YEAR</ogc:PropertyName>
        <ogc:Literal>{year}</ogc:Literal></ogc:PropertyIsEqualTo>
    </ogc:And></ogc:Filter>
  </wfs:Query>
</wfs:GetFeature>"""


@dataclass
class Airport:
    code: str
    name: str
    bbox: list[float]      # [minLng, minLat, maxLng, maxLat]


def _post(url: str, body: bytes, ctype: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, data=body, headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def list_airports() -> list[Airport]:
    raw = _post(f"{BASE}/getAirportPosList", b"{}", "application/json")
    out = []
    for a in json.loads(raw)["data"]:
        bbox = [float(v) for v in str(a["BBOX"]).split(",")]
        out.append(Airport(a["ARP_SE"], a["ARPRT_KOR_NM"], bbox))
    return out


def latest_years() -> dict[str, int]:
    """공항별 최신 등고선 연도. 갱신 감지에도 쓴다."""
    raw = _post(f"{BASE}/getCtrlnList", b"{}", "application/json")
    out: dict[str, int] = {}
    for c in json.loads(raw)["data"]:
        code, yr = c["ARP_SE"], int(c["YEAR"])
        out[code] = max(out.get(code, 0), yr)
    return out


# GML 파싱 — 응답이 단순·고정 구조라 정규식으로 충분 (외부 XML 의존성 회피).
_FEATURE = re.compile(r"<gml:featureMember>(.*?)</gml:featureMember>", re.S)
_WECPNL = re.compile(r"<noisedb:WECPNL>(\d+)</noisedb:WECPNL>")
_POLY = re.compile(r"<gml:(?:Polygon|surfaceMember|polygonMember)\b.*?</gml:"
                   r"(?:Polygon|surfaceMember|polygonMember)>", re.S)
_OUTER = re.compile(r"<gml:(?:exterior|outerBoundaryIs)\b.*?</gml:"
                    r"(?:exterior|outerBoundaryIs)>", re.S)
_INNER = re.compile(r"<gml:(?:interior|innerBoundaryIs)\b.*?</gml:"
                    r"(?:interior|innerBoundaryIs)>", re.S)
_POSLIST = re.compile(r"<gml:posList[^>]*>([^<]+)</gml:posList>")


def _ring(chunk: str, precision: int) -> list[list[float]] | None:
    m = _POSLIST.search(chunk)
    if not m:
        return None
    nums = m.group(1).split()
    ring = []
    for i in range(0, len(nums) - 1, 2):
        lon, lat = to_wgs84(float(nums[i]), float(nums[i + 1]))
        ring.append([round(lon, precision), round(lat, precision)])
    if len(ring) < 4:
        return None
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def fetch_contours(arp: str, year: int, *, precision: int = 6) -> dict[str, Any]:
    """공항 1곳의 등고선 → GeoJSON FeatureCollection (EPSG:4326).

    precision: 좌표 소수 자릿수. 6 이면 약 11cm — 표시용으로 충분하고
    파일 크기를 절반 이하로 줄인다 (기하 단순화가 아니라 반올림이라
    폴리곤 모양은 사실상 보존된다).
    """
    xml = _post(ENGINE, _GETFEATURE.format(arp=arp, year=year).encode(),
                "text/xml").decode("utf-8", "replace")
    feats = []
    for fm in _FEATURE.findall(xml):
        wm = _WECPNL.search(fm)
        if not wm:
            continue
        wec = int(wm.group(1))
        polys = _POLY.findall(fm) or [fm]
        coords = []
        for poly in polys:
            outer = _OUTER.search(poly)
            ring = _ring(outer.group(0) if outer else poly, precision)
            if not ring:
                continue
            rings = [ring]
            for inner in _INNER.findall(poly):
                r = _ring(inner, precision)
                if r:
                    rings.append(r)
            coords.append(rings)
        if not coords:
            continue
        feats.append({
            "type": "Feature",
            "properties": {
                "airport": arp, "year": year, "wecpnl": wec,
                "zone": WECPNL_ZONE.get(wec, f"WECPNL {wec}"),
            },
            "geometry": {"type": "MultiPolygon", "coordinates": coords},
        })
    # 넓은 구역이 좁은 구역을 덮지 않도록 소음도 낮은 것부터 (아래에 깔림)
    feats.sort(key=lambda f: f["properties"]["wecpnl"])
    return {"type": "FeatureCollection", "features": feats}
