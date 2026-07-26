"""
scorer/rules.py 단위 테스트 (stdlib unittest — pytest 불필요).

실행:
    cd crawler && python -m unittest tests.test_scorer -v
    또는  python tests/test_scorer.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from scorer import FLAG_META, property_nature, score_property  # noqa: E402
from scorer.rules import UNKNOWN_CAP  # noqa: E402


def sc(**kw):
    base = dict(
        risk_flags=[], conv_addr="[집합건물 철근콘크리트 84.9㎡]",
        usage_lcl_cd="20000", usage_nm="아파트", building_year=2015,
        has_detail=True, this_year=2026,
    )
    base.update(kw)
    return score_property(**base)


class TestNature(unittest.TestCase):
    def test_marker_precedence(self):
        # 집합건물이 '건물' 부분문자열을 포함 — 집합건물 먼저 판정돼야
        self.assertEqual(property_nature("[집합건물 ...]", None, None), "collective")
        self.assertEqual(property_nature("[건물 ...]", None, None), "building")
        self.assertEqual(property_nature("[토지 ...]", None, None), "land")

    def test_lcl_fallback(self):
        self.assertEqual(property_nature(None, "20000", None), "building")
        self.assertEqual(property_nature(None, "10000", None), "land")
        self.assertEqual(property_nature(None, "30000", None), "other")
        self.assertEqual(property_nature(None, None, None), "unknown")


class TestScore(unittest.TestCase):
    def test_clean_collective_is_100(self):
        self.assertEqual(sc()["score"], 100)

    def test_high_confidence_clean(self):
        self.assertEqual(sc()["confidence"], "high")

    def test_danger_flag_subtracts(self):
        # yuchi=22 → 100-22=78
        r = sc(risk_flags=["yuchi"])
        self.assertEqual(r["score"], 100 - FLAG_META["yuchi"][2])
        self.assertEqual(r["breakdown"]["legal_penalty"], -FLAG_META["yuchi"][2])

    def test_multiple_flags_sum(self):
        r = sc(risk_flags=["senior_tenant", "yuchi", "claim_90"])
        expect = 100 - sum(FLAG_META[c][2] for c in ("senior_tenant", "yuchi", "claim_90"))
        # building 아님(집합건물)이라 type_adj 0
        self.assertEqual(r["score"], expect)

    def test_unknown_flag_ignored(self):
        self.assertEqual(sc(risk_flags=["not_a_real_flag"])["score"], 100)

    def test_clamp_floor_zero(self):
        # danger 다수 → 0 미만이어도 0으로 클램프
        allflags = list(FLAG_META.keys())
        self.assertEqual(sc(risk_flags=allflags)["score"], 0)

    def test_type_adjustment_land(self):
        # 대지(land) type_adj -5
        r = sc(risk_flags=[], conv_addr="[토지]", usage_lcl_cd="10000",
               usage_nm="대지", building_year=None)
        self.assertEqual(r["score"], 95)
        self.assertEqual(r["breakdown"]["type_adj"], -5)

    def test_age_adjustment_thresholds(self):
        self.assertEqual(sc(building_year=2000)["score"], 100)   # 26년 ≤30 → 0
        self.assertEqual(sc(building_year=1990)["score"], 98)    # 36년 >30 → -2
        self.assertEqual(sc(building_year=1980)["score"], 96)    # 46년 >40 → -4

    def test_age_not_applied_to_land(self):
        r = sc(conv_addr="[토지]", usage_lcl_cd="10000", usage_nm="대지",
               building_year=1900)
        self.assertEqual(r["breakdown"]["age_adj"], 0)

    def test_unknown_cap_when_no_detail(self):
        r = sc(has_detail=False, risk_flags=[])
        self.assertEqual(r["score"], UNKNOWN_CAP)
        self.assertEqual(r["confidence"], "low")

    def test_medium_confidence_building_no_year(self):
        r = sc(conv_addr="[건물]", usage_lcl_cd="20000", usage_nm="단독주택",
               building_year=None)
        self.assertEqual(r["confidence"], "medium")

    def test_top_factors_sorted_desc(self):
        r = sc(risk_flags=["tiny_area", "senior_tenant", "claim_90"])
        pens = [f["penalty"] for f in r["breakdown"]["top_factors"]]
        self.assertEqual(pens, sorted(pens, reverse=True))
        self.assertEqual(r["breakdown"]["top_factors"][0]["label"], "선순위 임차인(대항력)")

    def test_all_25_flags_mapped(self):
        self.assertEqual(len(FLAG_META), 25)


if __name__ == "__main__":
    unittest.main(verbosity=2)
