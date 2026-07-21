"""한국 매물 파생 카테고리 룰 엔진.

기본 분류는 properties.usage_nm (사이트의 dspslUsgNm — '아파트'/'단독주택' 등 20종).
이 엔진은 그 위에 사용자 정의 카테고리를 추출:

코드:
  whole_building  통건물 — 비집합 건물 전체(+대지) 일괄 매각. 지분매각 제외.
  country_house   전원주택 — 단독/다가구 + 군(郡) 또는 읍·면 소재 또는 전원 키워드
  townhouse       시가지 단독 — 단독/다가구 + 그 외 전부 (시·광역시 동 지역)
  farm_house      농가주택 — 단독/다가구 + 농가 키워드 (별도 강조)
  vacation_home   별장·펜션 — 단독/다가구 + 별장/펜션/산장 키워드

위치성 카테고리(전원/시가지/농가/별장)는 country_house | townhouse 둘 중 하나가
반드시 붙는 전량 커버 구조 — 단, 토지-only·지분 물건은 주택이 아니므로 제외
(location_excluded). 룰 변경 시 ingest backfill-categories --force 로 일괄 재계산.
"""

from __future__ import annotations

import re
from typing import Iterable

# 단독·다가구 (dspslUsgNm) — 전원주택/시가지단독/농가 후보군
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

# 키워드 (conv_addr + road_addr + building_summary 결합 텍스트에서 검색)
VACATION_KW: tuple[str, ...] = ("별장", "펜션", "산장", "리조트")
COUNTRYSIDE_KW: tuple[str, ...] = ("전원", "전원주택", "농가", "농어촌")
FARM_KW: tuple[str, ...] = ("농가", "축사", "농장", "농어촌")

# 주소 텍스트에서 읍·면 소재 검출 — "애월읍", "가창면" 같은 행정구역 토큰.
# 토큰 뒤 공백/쉼표/끝 경계를 요구해 "삼면길" 같은 도로명 오탐을 막는다.
_EUP_MYEON_RE = re.compile(r"(?:^|[\s,(])[가-힣]{1,10}[읍면](?=[\s,)]|$)")


def _share_sale_text(text: str, risk_flags: list) -> bool:
    """지분매각 신호 — risk_flags 또는 물건 표기 텍스트."""
    return (
        "share_sale" in risk_flags
        or "지분" in text
        or bool(re.search(r"\d+분의\s*\d+", text))
    )


def _land_only_text(text: str) -> bool:
    """건물 없는 토지 필지 물건 — "[토지 ...]" 표기만 있고 "[건물" 없음."""
    return "[토지" in text and "[건물" not in text


def location_excluded(prop: dict) -> bool:
    """위치성 주택 카테고리(전원/시가지/농가/별장) 부여 금지 물건인가.

    단독주택 '사건'에 딸린 토지 필지·지분 물건은 usage_nm이 주택이어도
    주택 매각이 아니다 (라이브 실측: 전원주택 태깅의 32%가 토지-only,
    17%가 지분 — 묘지 지분까지 전원주택으로 노출됐음).

    ingest의 --force LLM-보존 로직과 LLM 보강 트리거도 이 판정을 존중해야
    함 — 아니면 룰이 지운 태그를 보존/재부여해 되살린다.
    """
    text = " ".join(filter(None, [
        prop.get("conv_addr"),
        prop.get("building_summary"),
    ]))
    risk = prop.get("risk_flags") or []
    return _share_sale_text(text, risk) or _land_only_text(text)


def _is_rural(
    sgg_name: str | None, addr_text: str, emd_name: str | None = None,
) -> bool:
    """외곽 판정: 군(郡) 단위 sgg, 읍·면동명(detail의 adongEmdNm — 최우선),
    또는 주소 텍스트의 읍·면 토큰(detail 미수집 신규 행 fallback)."""
    if emd_name and emd_name.endswith(("읍", "면")):
        return True
    if sgg_name and sgg_name.endswith("군"):
        return True
    return bool(_EUP_MYEON_RE.search(addr_text))


def _has_any(text: str, keywords: Iterable[str]) -> bool:
    return any(kw in text for kw in keywords)


def derive_categories(
    prop: dict,
    sgg_name: str | None = None,
) -> list[str]:
    """매물의 derived_category 코드 리스트 반환.

    Args:
        prop: properties row (usage_nm, sd_code, sgg_code, conv_addr,
              road_addr, lot_addr, building_summary, risk_flags, 그리고
              선택적으로 emd_nm — detail_result의 adongEmdNm jsonb 추출값)
        sgg_name: sgg 한글명 (regions_sgg lookup) — 군(郡) 판정에 사용.
    Returns:
        derived_category 코드 list (중복 없음).
    """
    cats: list[str] = []
    usg = prop.get("usage_nm") or ""
    text = " ".join(filter(None, [
        prop.get("conv_addr"),
        prop.get("road_addr"),
        prop.get("building_summary"),
    ]))
    # 읍·면 검출은 주소 필드만 — building_summary의 자재/구조 서술 오탐 방지.
    addr_text = " ".join(filter(None, [
        prop.get("road_addr"),
        prop.get("lot_addr"),
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
            and not _share_sale_text(text, risk)):
        cats.append("whole_building")

    # 위치성 주택 카테고리 — 토지-only/지분 물건은 주택이 아니므로 전부 제외.
    if usg in SINGLE_HOUSE_USG_NMS and not location_excluded(prop):
        # 별장·펜션 — 키워드 우선 매칭 (외곽/시가지 무관)
        if _has_any(text, VACATION_KW):
            cats.append("vacation_home")

        # 농가주택 — 농가 키워드 (별장과 중복 가능)
        if _has_any(text, FARM_KW):
            cats.append("farm_house")

        # 전원주택 — 군(郡) sgg, 읍·면 소재, 또는 전원 키워드.
        # 그 외 전부 시가지 단독 — 중소도시 동(洞) 지역 포함 전량 커버
        # (구 룰은 광역시/50만+ 시만 townhouse → 제주시 등 중소도시 단독 21%가
        #  어느 필터에도 안 잡혔음).
        if (_is_rural(sgg_name, addr_text, prop.get("emd_nm"))
                or _has_any(text, COUNTRYSIDE_KW)):
            cats.append("country_house")
        else:
            cats.append("townhouse")

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
    {"code": "country_house", "label": "전원주택", "desc": "단독·다가구 + 군(郡)/읍·면 소재 또는 전원 키워드 — 토지-only·지분 제외"},
    {"code": "townhouse",     "label": "시가지 단독", "desc": "단독·다가구 + 시·광역시 동(洞) 지역 — 토지-only·지분 제외"},
    {"code": "farm_house",    "label": "농가주택",  "desc": "단독·다가구 + 농가/축사 키워드"},
    {"code": "vacation_home", "label": "별장·펜션", "desc": "단독·다가구 + 별장/펜션/산장 키워드"},
]
