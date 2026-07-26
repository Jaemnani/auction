"""
매수 안전도 점수 (가격 제외) — 규칙 기반, 순수 함수(I/O 없음).

100점에서 위험 신호별 감점 + 물건유형/연식 보정. 가격(감정가 대비 최저가,
유찰에 따른 할인)은 예상낙찰가 모델(property_estimates)이 별도 담당하므로 제외.
가중치 성향: '균형' — 권리 하자(danger)에 큰 감점, 호재 가산은 Phase 2에서 추가.

주 입력은 crawler risk_flags(0011) 25종. 코드→(라벨, tier, 감점)은 FLAG_META.
웹(web/src/lib/risk-flags.ts)에 라벨/티어 사본이 있으니 코드 추가 시 함께 갱신.
"""

from __future__ import annotations

from datetime import date

VERSION = "score-v1"

# detail 미동기(위험 미상) 매물 점수 상한 — "정보부족"을 안전으로 오인 방지
UNKNOWN_CAP = 65

# risk_flags 코드 → (한글 라벨, tier, 감점). tier 는 UI 색/설명용.
FLAG_META: dict[str, tuple[str, str, int]] = {
    # ── danger: 권리·절차 하자 (인수·무효·사용불가 위험) ──
    "senior_tenant": ("선순위 임차인(대항력)", "danger", 25),
    "yuchi":         ("유치권", "danger", 22),
    "legal_ground":  ("법정지상권", "danger", 22),
    "stopped":       ("정지/연기/취하", "danger", 20),
    "share_sale":    ("지분 매각", "danger", 18),
    "maeng_ji":      ("맹지", "danger", 18),
    "illegal_bld":   ("위반건축물", "danger", 16),
    "share_maeng":   ("지분+맹지 조합", "danger", 12),  # share_sale+maeng_ji 위 조합 가중
    # ── warn: 실현·활용 리스크 ──
    "rent_unknown":  ("점유관계 미상", "warn", 10),
    "reserve_forest": ("보전산지", "warn", 9),
    "pollak":        ("포락지", "warn", 9),
    "private_road":  ("사도", "warn", 8),
    "claim_90":      ("청구액 감정가 90%+", "warn", 8),
    "power_line":    ("송전선/구분지상권", "warn", 7),
    "special_20":    ("특별매각 보증금 20%", "warn", 6),
    "many_fails":    ("유찰 5회+", "warn", 6),
    # ── info: 성격·소폭 하자 ──
    "pamyo":         ("분묘/파묘", "info", 6),
    "forest_only":   ("임야 단독", "info", 5),
    "agri_zone":     ("농림지역", "info", 5),
    "nat_protect":   ("자연보전권역", "info", 5),
    "show_only":     ("제시외 물건", "info", 5),
    "forestry_land": ("임업용 산지", "info", 4),
    "farm_land":     ("농지", "info", 4),
    "tiny_area":     ("초소형(30㎡ 이하)", "info", 3),
    "new_villa":     ("신축 빌라", "info", 3),
}

# 물건 유형별 보정 — 권리 단순성/환금성. flags(농지·임야 등)와 이중감점 안 되게 소폭.
_TYPE_ADJ = {
    "collective": 0,    # 집합건물(아파트/오피스텔/다세대) — 권리 단순, 환금성↑ = 기준
    "building": -3,     # 일반 건물(단독/다가구/상가)
    "land": -5,         # 토지(대지) — 개발/활용 변수
    "other": -6,        # 차량·기타
    "unknown": -2,
}


def property_nature(
    conv_addr: str | None, usage_lcl_cd: str | None, usage_nm: str | None
) -> str:
    """물건 성격 판정. conv_addr 의 [집합건물/[건물/[토지 마커가 진실(memo.txt).
    없으면 usage_lcl_cd 폴백."""
    s = conv_addr or ""
    if "집합건물" in s:
        return "collective"
    if "건물" in s:
        return "building"
    if "토지" in s:
        return "land"
    # 폴백 — 대분류 코드
    if usage_lcl_cd == "20000":
        return "building"
    if usage_lcl_cd == "10000":
        return "land"
    if usage_lcl_cd in ("30000", "40000"):
        return "other"
    return "unknown"


def _age_adj(nature: str, building_year: int | None, this_year: int) -> int:
    """건물 노후 보정 — 건물류만. 토지엔 미적용.
    노후 집합건물은 재건축 호재일 수 있으나 zoning 데이터(Phase 2) 전까지는 소폭 감점."""
    if nature not in ("collective", "building") or not building_year:
        return 0
    age = this_year - building_year
    if age > 40:
        return -4
    if age > 30:
        return -2
    return 0


def score_property(
    *,
    risk_flags: list[str] | None,
    conv_addr: str | None,
    usage_lcl_cd: str | None,
    usage_nm: str | None,
    building_year: int | None,
    has_detail: bool,
    this_year: int | None = None,
) -> dict:
    """매물 → {score, confidence, breakdown}. 순수 계산(I/O 없음).

    has_detail=False 면 risk_flags 가 신뢰 불가(미산출) → 신뢰도 low + 상한 UNKNOWN_CAP.
    """
    yr = this_year or date.today().year
    flags = risk_flags or []

    factors: list[tuple[str, int, str]] = []  # (label, penalty, tier)
    legal_pen = 0
    for code in flags:
        meta = FLAG_META.get(code)
        if meta is None:
            continue
        label, tier, pen = meta
        legal_pen += pen
        factors.append((label, pen, tier))

    nature = property_nature(conv_addr, usage_lcl_cd, usage_nm)
    type_adj = _TYPE_ADJ.get(nature, 0)
    age_adj = _age_adj(nature, building_year, yr)

    raw = 100 - legal_pen + type_adj + age_adj
    score = max(0, min(100, raw))

    if not has_detail:
        # 위험을 알 수 없음 — 안전으로 오인 금지
        score = min(score, UNKNOWN_CAP)
        confidence = "low"
    elif nature in ("collective", "building") and not building_year:
        confidence = "medium"
    else:
        confidence = "high"

    factors.sort(key=lambda x: -x[1])
    breakdown = {
        "base": 100,
        "legal_penalty": -legal_pen,
        "type_adj": type_adj,
        "age_adj": age_adj,
        "nature": nature,
        "flag_count": len(factors),
        "top_factors": [
            {"label": lbl, "penalty": pen, "tier": tier}
            for lbl, pen, tier in factors[:6]
        ],
    }
    return {"score": int(score), "confidence": confidence, "breakdown": breakdown}
