"""일본 BIT 매물 파생 카테고리 룰 엔진.

기본 분류 (jp_properties.sale_cls / sale_cls_label):
  1=土地 / 2=戸建て / 3=マンション / 4=その他

이 엔진은 그 위에 사용자 정의 카테고리:

코드:
  bessou   別荘·山荘 — 戸建て + 별장 키워드
  akiya    空き家·古民家 — 戸建て + 키워드(空き家/古民家)
  rizoto   リゾート地 — 戸建て + 휴양 prefecture (北海道01·沖縄47)
  tousho   離島 — 沖縄 prefecture (도서지역)

추후 LLM 보강 가능 (Plan 4-6).
"""

from __future__ import annotations

# 휴양·도서 prefecture
VACATION_PREFS: set[str] = {"01", "47"}  # 北海道, 沖縄

# 키워드 (address_text / detail_result 텍스트에서 검색)
VACATION_KW: tuple[str, ...] = ("別荘", "山荘", "リゾート", "別邸", "リゾ")
AKIYA_KW: tuple[str, ...] = ("空き家", "古民家", "あきや", "古い民家")


def derive_categories(prop: dict) -> list[str]:
    """일본 매물 derived_category 코드 리스트.

    Args:
        prop: jp_properties row (sale_cls, address_text, prefecture_code 등).
    """
    cats: list[str] = []
    sale_cls = str(prop.get("sale_cls") or "")
    pref = str(prop.get("prefecture_code") or "")
    addr = (prop.get("address_text") or "")

    # 戸建て (sale_cls=2) — 별장·고민가 후보
    if sale_cls == "2":
        if any(kw in addr for kw in VACATION_KW):
            cats.append("bessou")
        if any(kw in addr for kw in AKIYA_KW):
            cats.append("akiya")
        if pref in VACATION_PREFS:
            cats.append("rizoto")

    # 離島 — 沖縄(47) prefecture (土地·戸建て·マンション 무관)
    if pref == "47":
        cats.append("tousho")

    # 중복 제거 (insertion order 유지)
    seen, out = set(), []
    for c in cats:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


ALL_CATEGORIES: list[dict] = [
    {"code": "bessou",  "label": "別荘・山荘",      "desc": "戸建て + 別荘·山荘·リゾート·別邸 키워드"},
    {"code": "akiya",   "label": "空き家・古民家",  "desc": "戸建て + 空き家·古民家 키워드"},
    {"code": "rizoto",  "label": "リゾート地",      "desc": "戸建て + 北海道(01)·沖縄(47) prefecture"},
    {"code": "tousho",  "label": "離島",            "desc": "沖縄(47) prefecture (모든 sale_cls)"},
]
