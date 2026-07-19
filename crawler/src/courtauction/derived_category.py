"""한국 매물 파생 카테고리 룰 엔진.

기본 분류는 properties.usage_nm (사이트의 dspslUsgNm — '아파트'/'단독주택' 등 20종).
이 엔진은 그 위에 사용자 정의 카테고리를 추출:

코드:
  whole_building  통건물 — 비집합 건물 전체(+대지) 일괄 매각. 지분매각 제외.
  country_house   전원주택 — 단독/다가구 + 외곽 sgg (군 단위 또는 키워드)
  townhouse       도심 단독 — 단독/다가구 + 광역시·인구 50만+ 일반시
  farm_house      농가주택 — 단독/다가구 + 농가 키워드 (별도 강조)
  vacation_home   별장·펜션 — 단독/다가구 + 별장/펜션/산장 키워드
  large_land      대형 토지 — 토지(전답/임야/대지) + 면적 1,000㎡+ (추정)
  apartment_old   구축 아파트 — 아파트 + (build_summary에 ‘20세기’ 단서 — 추후)

룰 변경 시 ingest backfill-categories 로 일괄 재계산.
"""

from __future__ import annotations

import re
from typing import Iterable

# 단독·다가구 (dspslUsgNm) — 전원주택/도심단독/농가 후보군
SINGLE_HOUSE_USG_NMS: set[str] = {
    "단독주택",
    "단독주택다가구",
    "다가구주택",
}

# 토지 (전원지 후보군) — 1차는 미사용
LAND_USG_NMS: set[str] = {
    "전답", "임야", "대지", "대지,임야,전답",
}

# 통건물 후보 용도 — 여기 든다고 전부 통건물은 아님. conv_addr의 물건 표기가
# "[집합건물 ...]"이면 구분소유 호수 매각이므로 텍스트 검사로 걸러야 함
# (라이브 실측: 근린시설 764건 중 648건이 집합건물, 단독 계열도 6~16건 섞임).
# 집합건물 한 동 전체(전 호수) 일괄매각 케이스는 현 데이터로 판별 불가 — 미포함.
WHOLE_BUILDING_USG_NMS: set[str] = SINGLE_HOUSE_USG_NMS | {"근린시설"}

# 광역시 sd_code — 도심
URBAN_SD_CODES: set[str] = {
    "11",  # 서울
    "26",  # 부산
    "27",  # 대구
    "28",  # 인천
    "29",  # 광주
    "30",  # 대전
    "31",  # 울산
    "36",  # 세종
}

# 인구 50만+ 일반시 (광역시 제외) — sgg 이름 startswith 매칭
URBAN_SGG_PATTERNS: tuple[str, ...] = (
    "수원시", "성남시", "고양시", "용인시", "부천시", "안양시", "안산시",
    "남양주시", "화성시", "평택시", "의정부시", "시흥시", "파주시",
    "김해시", "전주시", "천안시", "청주시", "포항시", "창원시",
)

# 키워드 (conv_addr + road_addr + building_summary 결합 텍스트에서 검색)
VACATION_KW: tuple[str, ...] = ("별장", "펜션", "산장", "리조트")
COUNTRYSIDE_KW: tuple[str, ...] = ("전원", "전원주택", "농가", "농어촌")
FARM_KW: tuple[str, ...] = ("농가", "축사", "농장", "농어촌")


def _is_urban(sd_code: str | None, sgg_name: str | None) -> bool:
    if sd_code in URBAN_SD_CODES:
        return True
    if sgg_name and any(sgg_name.startswith(p) for p in URBAN_SGG_PATTERNS):
        return True
    return False


def _is_rural(sgg_name: str | None) -> bool:
    """1차 휴리스틱: sgg 이름이 '군'으로 끝나면 외곽."""
    return bool(sgg_name and sgg_name.endswith("군"))


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(kw in text for kw in keywords)


def derive_categories(
    prop: dict,
    sgg_name: str | None = None,
) -> list[str]:
    """매물의 derived_category 코드 리스트 반환.

    Args:
        prop: properties row (usage_nm, sd_code, sgg_code, conv_addr,
              road_addr, building_summary, risk_flags)
        sgg_name: sgg 한글명 (regions_sgg lookup) — 도시/외곽 판단에 필요.
    Returns:
        derived_category 코드 list (중복 없음).
    """
    cats: list[str] = []
    usg = prop.get("usage_nm") or ""
    sd = prop.get("sd_code")
    text = " ".join(filter(None, [
        prop.get("conv_addr"),
        prop.get("road_addr"),
        prop.get("building_summary"),
    ]))

    # 통건물 — 건물 한 채 전체(+대지) 일괄 매각.
    # 포함: conv_addr 물건 표기가 "[건물 ...]" (라이브 실측: 토지/건물 복합 표기는
    #       없고 물건당 하나 — 통건물 매각은 "[건물"로 표기됨).
    # 제외 1: "집합건물" 표기 = 구분소유 호수 매각 (근린시설의 85%가 이 케이스).
    # 제외 2: "[토지 ...]"만 있는 물건 = 같은 사건의 부지/도로 필지 (전체 태깅의
    #         30%가 이 케이스였음 — 건물 없는 매각은 통건물이 아님).
    # 제외 3: 지분매각 — "전체"가 아님. risk_flags(share_sale)는 detail 수집 후에야
    #         붙으므로 conv_addr의 "지분 N분의 M" 표기도 직접 검사
    #         (실측: detail 백필 전 통건물 태깅 → 나중에 지분으로 밝혀진 케이스 2건).
    risk = prop.get("risk_flags") or []
    if (usg in WHOLE_BUILDING_USG_NMS
            and "[건물" in text
            and "집합건물" not in text
            and "share_sale" not in risk
            and "지분" not in text
            and not re.search(r"\d+분의\s*\d+", text)):
        cats.append("whole_building")

    if usg in SINGLE_HOUSE_USG_NMS:
        urban = _is_urban(sd, sgg_name)
        rural = _is_rural(sgg_name)

        # 별장·펜션 — 키워드 우선 매칭 (외곽/도심 무관)
        if _has_any(text, VACATION_KW):
            cats.append("vacation_home")

        # 농가주택 — 농가 키워드 (별장과 중복 가능)
        if _has_any(text, FARM_KW):
            cats.append("farm_house")

        # 전원주택 — 외곽 sgg OR 전원 키워드
        if rural or _has_any(text, COUNTRYSIDE_KW):
            cats.append("country_house")
        # 도심단독 — 광역시/인구 50만+ 일반시
        elif urban:
            cats.append("townhouse")
        # 그 외 (중소도시/시 단위) — 카테고리 미부여 (필요 시 추후 추가)

    # 중복 제거 (insertion order 유지)
    seen = set()
    out: list[str] = []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


# 알려진 모든 derived 카테고리 코드 (UI 토글 옵션·검증용)
ALL_CATEGORIES: list[dict] = [
    {"code": "whole_building", "label": "통건물", "desc": "단독·다가구·근린시설 건물 전체(+대지) 일괄 매각 — 지분매각 제외"},
    {"code": "country_house", "label": "전원주택", "desc": "단독·다가구 + 외곽 sgg(군) 또는 전원/농가 키워드"},
    {"code": "townhouse",     "label": "도심 단독", "desc": "단독·다가구 + 광역시/인구 50만+ 일반시"},
    {"code": "farm_house",    "label": "농가주택",  "desc": "단독·다가구 + 농가/축사 키워드"},
    {"code": "vacation_home", "label": "별장·펜션", "desc": "단독·다가구 + 별장/펜션/산장 키워드"},
]
