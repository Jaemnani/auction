"""
data.go.kr OpenAPI 클라이언트 — 국토부 실거래가(RTMSDataSvc) + 건축HUB 표제부.

웹 프록시(web/src/app/api/molit-deals/route.ts, building-register/route.ts)의
호출·정규화 규칙을 그대로 포팅:
  - ServiceKey 는 이미 URL-encoded 형태 → raw concat (재인코딩하면 깨짐)
  - _type=json 으로 JSON 강제 (기본 XML)
  - normalizeDeal: 유형별 영문 필드 차이를 폴백 체인으로 흡수
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# 실거래가 유형 → 엔드포인트 (웹 route.ts ENDPOINTS 와 동일 키)
DEAL_ENDPOINTS: dict[str, str] = {
    "apt":  "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade",
    "rh":   "https://apis.data.go.kr/1613000/RTMSDataSvcRHTrade/getRTMSDataSvcRHTrade",
    "sh":   "https://apis.data.go.kr/1613000/RTMSDataSvcSHTrade/getRTMSDataSvcSHTrade",
    "offi": "https://apis.data.go.kr/1613000/RTMSDataSvcOffiTrade/getRTMSDataSvcOffiTrade",
    "land": "https://apis.data.go.kr/1613000/RTMSDataSvcLandTrade/getRTMSDataSvcLandTrade",
    "nrg":  "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
    "indu": "https://apis.data.go.kr/1613000/RTMSDataSvcInduTrade/getRTMSDataSvcInduTrade",
}

BR_TITLE_ENDPOINT = (
    "https://apis.data.go.kr/1613000/BldRgstHubService/getBrTitleInfo"
)


class MolitError(RuntimeError):
    pass


def _s(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _num(v: Any) -> float | None:
    s = _s(v).replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _int(v: Any) -> int | None:
    f = _num(v)
    return int(f) if f is not None else None


def normalize_deal(d: dict[str, Any]) -> dict[str, Any]:
    """RTMSDataSvc row → molit_deals 컬럼 형태. (웹 normalizeDeal 포팅 + built_year/deal_date)"""
    year = _s(d.get("dealYear"))
    month = _s(d.get("dealMonth"))
    day = _s(d.get("dealDay"))
    deal_date = None
    if year.isdigit() and month.isdigit() and day.isdigit():
        deal_date = f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return {
        "name": (_s(d.get("aptNm")) or _s(d.get("offiNm")) or _s(d.get("mhouseNm"))
                 or _s(d.get("houseType")) or _s(d.get("buildingType"))
                 or _s(d.get("umdNm"))) or None,
        "umd_nm": _s(d.get("umdNm")) or None,
        "jibun": _s(d.get("jibun")) or None,
        "area_m2": (_num(d.get("excluUseAr")) or _num(d.get("dealArea"))
                    or _num(d.get("totalFloorAr")) or _num(d.get("buildingAr"))
                    or _num(d.get("landAr"))),
        "floor": _int(d.get("floor")),
        "built_year": _int(d.get("buildYear")),
        "amount_manwon": _num(d.get("dealAmount")),
        "deal_date": deal_date,
        "raw": d,
    }


def _ymd_to_date(s: str) -> str | None:
    s = _s(s)
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return None


def normalize_br_title(d: dict[str, Any]) -> dict[str, Any]:
    """건축HUB 표제부 row → property_building_register 컬럼 형태."""
    return {
        "use_approval_day": _ymd_to_date(d.get("useAprDay")),
        "structure": _s(d.get("strctCdNm")) or None,
        "main_purpose": _s(d.get("mainPurpsCdNm")) or None,
        "total_area": _num(d.get("totArea")),
        "arch_area": _num(d.get("archArea")),
        "plat_area": _num(d.get("platArea")),
        "ground_floors": _int(d.get("grndFlrCnt")),
        "underground_floors": _int(d.get("ugrndFlrCnt")),
        "households": _int(d.get("hhldCnt")),
        "height": _num(d.get("heit")),
        "raw": d,
    }


class MolitClient:
    """동기 httpx 클라이언트. 호출 간 최소 간격으로 data.go.kr 부하 완화."""

    def __init__(self, api_key: str | None = None, min_interval_s: float = 0.2) -> None:
        self.api_key = api_key or os.environ.get("DATA_GO_KR_API_KEY")
        if not self.api_key:
            raise MolitError("DATA_GO_KR_API_KEY env required")
        self.min_interval_s = min_interval_s
        self._last_call = 0.0
        self._http = httpx.Client(timeout=30.0, headers={"Accept": "application/json"})
        self.calls = 0  # 예산 계정 — 실제 HTTP 호출 수

    def close(self) -> None:
        self._http.close()

    def _get_json(self, url: str) -> dict[str, Any]:
        wait = self.min_interval_s - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()
        self.calls += 1
        r = self._http.get(url)
        r.raise_for_status()
        try:
            return r.json()
        except ValueError as e:
            # 키 오류/쿼터 초과 시 XML 에러 응답이 옴 — 본문 앞부분을 에러에 포함
            raise MolitError(f"non-JSON response: {r.text[:300]}") from e

    @staticmethod
    def _items(body: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """OpenAPI 표준 응답 { response: { header, body: { items, totalCount } } } 해체.
        header.resultCode != 00 이면 에러 (쿼터 초과 22 등)."""
        resp = (body or {}).get("response") or {}
        header = resp.get("header") or {}
        code = _s(header.get("resultCode"))
        if code and code not in ("00", "0"):
            raise MolitError(
                f"API error {code}: {_s(header.get('resultMsg'))}")
        b = resp.get("body") or {}
        raw = (b.get("items") or {})
        items = raw.get("item") if isinstance(raw, dict) else None
        if items is None:
            items = []
        if isinstance(items, dict):
            items = [items]
        total = _int(b.get("totalCount")) or 0
        return items, total

    def fetch_deals(self, deal_type: str, lawd_cd: str, deal_ymd: str,
                    rows_per_page: int = 1000) -> list[dict[str, Any]]:
        """(유형, 시군구, 월) 조합의 전체 거래 — totalCount 넘으면 페이징."""
        endpoint = DEAL_ENDPOINTS.get(deal_type)
        if not endpoint:
            raise MolitError(f"unknown deal_type: {deal_type}")
        out: list[dict[str, Any]] = []
        page = 1
        while True:
            url = (f"{endpoint}?serviceKey={self.api_key}"
                   f"&pageNo={page}&numOfRows={rows_per_page}"
                   f"&LAWD_CD={lawd_cd}&DEAL_YMD={deal_ymd}&_type=json")
            items, total = self._items(self._get_json(url))
            out.extend(normalize_deal(i) for i in items)
            if len(out) >= total or not items:
                return out
            page += 1

    def fetch_br_title(self, sigungu_cd: str, bjdong_cd: str, bun: str, ji: str,
                       plat_gb_cd: str = "0") -> list[dict[str, Any]]:
        """건축물대장 표제부 — 지번 하나에 복수 동(棟)이 올 수 있음."""
        url = (f"{BR_TITLE_ENDPOINT}?serviceKey={self.api_key}"
               f"&sigunguCd={sigungu_cd}&bjdongCd={bjdong_cd}"
               f"&platGbCd={plat_gb_cd}&bun={bun}&ji={ji}"
               f"&numOfRows=20&pageNo=1&_type=json")
        items, _total = self._items(self._get_json(url))
        return [normalize_br_title(i) for i in items]
