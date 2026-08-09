"""매각물건명세서 파서 단위 테스트 — 실제 캡처 fixture 기반.

fixture: 2024타경2532 (서울중앙지법) 명세서에서 실제로 뽑은 좌표 텍스트 노드 66개.
이 문서는 전입신고일자 칸이 공란이고 x=501 날짜들은 임대차기간 열이다 —
열을 안 가르면 임대차 시작일을 전입일로 오인해 판정이 뒤집히는 표본이라 회귀 가치가 크다.
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from spec_sheet.parse import SpecSheet, Tenant, parse_spec_sheet  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures_spec_2024ta2532.json"


class TestRealDocument(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.spec = parse_spec_sheet(json.loads(FIXTURE.read_text()))

    def test_lien(self):
        """최선순위 설정일 = 말소기준권리 (문서: 2022.10.11. 근저당)"""
        self.assertEqual(self.spec.lien_date, "2022-10-11")
        self.assertEqual(self.spec.lien_kind, "근저당")

    def test_demand_deadline_with_spaces(self):
        """배당요구종기 — '2024. 8. 1.' 공백 서식도 파싱"""
        self.assertEqual(self.spec.demand_deadline, "2024-08-01")

    def test_tenant_block_detected(self):
        self.assertTrue(self.spec.has_tenant_block)
        self.assertEqual(len(self.spec.tenants), 1)

    def test_dates_go_to_correct_column(self):
        """x=501 날짜는 임대차기간 열 — 전입 열(x≈763)이 아니다.

        이 분리가 깨지면 임대차 시작일(2022-07-10)이 전입일로 오인돼
        '대항력 있음'으로 잘못 뒤집힌다.
        """
        t = self.spec.tenants[0]
        self.assertEqual(t.move_in_dates, [])
        self.assertIn("2022-07-10", t.other_dates)
        self.assertIn("2024-07-09", t.other_dates)

    def test_block_excludes_table_header(self):
        """임차인 블록에 표 머리글이 섞이면 안 된다.

        본문 안내문('…사업자등록신청일자와…')을 블록 시작으로 잡으면 머리글
        줄들이 딸려 들어와 성명이 '점유자성인터코트라주식회사' 로 오염됐다.
        """
        raw = self.spec.tenants[0].raw
        self.assertNotIn("전입신고일자", raw)
        self.assertNotIn("점유정보출처", raw)
        self.assertIn("코트라", raw)

    def test_deposit_not_guessed(self):
        """보증금 공란 — 추정하지 않고 None"""
        self.assertIsNone(self.spec.tenants[0].deposit)
        self.assertTrue(any("보증금 공란" in n for n in self.spec.notes))

    def test_verdict_conservative_risk(self):
        """전입 열을 못 가른 서식 → 모든 날짜를 전입 후보로 보는 보수적 판정.

        임대차기간 2022-07-10 이 최선순위 2022-10-11 보다 빠르므로 risk.
        과다 경고는 원문 확인으로 끝나지만, 과소 경고(none)는 대항력 있는
        임차인을 놓쳐 인수액을 0 으로 믿게 만든다.
        """
        self.assertEqual(self.spec.opposable_risk(), "risk")
        self.assertEqual(self.spec.confidence, "low")


class TestMultiTenant(unittest.TestCase):
    """다중 임차인 실측 문서 (서울동부 2022타경55849, 92 노드).

    임차인 3명이 y 클러스터로 나뉘고, 그중 김승미는 전입 2017 년 <
    최선순위 2019-09-02 이라 대항력이 살아 있는(=인수 위험) 표본이다.
    클러스터를 안 가르면 이름이 '김성철김승미송병규' 로 뭉개진다.
    """

    @classmethod
    def setUpClass(cls):
        f = Path(__file__).parent / "fixtures_spec_2022ta55849.json"
        cls.spec = parse_spec_sheet(json.loads(f.read_text()))

    def test_lien_and_deadline(self):
        self.assertEqual(self.spec.lien_date, "2019-09-02")
        self.assertEqual(self.spec.lien_kind, "가압류")
        self.assertEqual(self.spec.demand_deadline, "2022-12-26")

    def test_three_tenants_split(self):
        names = [t.name for t in self.spec.tenants]
        self.assertEqual(names, ["김성철", "김승미", "송병규"])

    def test_deposit_on_correct_tenant(self):
        """보증금 2.2억은 임차권등기한 김승미의 것 — 다른 임차인엔 없다"""
        by = {t.name: t for t in self.spec.tenants}
        self.assertEqual(by["김승미"].deposit, 220_000_000)
        self.assertIsNone(by["김성철"].deposit)
        self.assertIsNone(by["송병규"].deposit)

    def test_verdict_risk(self):
        """김승미 전입 2017 < 최선순위 2019-09-02 → 인수 위험"""
        self.assertEqual(self.spec.opposable_risk(), "risk")


class TestVerdict(unittest.TestCase):
    """판정 로직 — 합성 입력으로 경계 고정."""

    def test_no_tenant_block(self):
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=False)
        self.assertEqual(s.opposable_risk(), "none")

    def test_move_in_after_lien(self):
        """전입이 최선순위보다 늦음 → 대항력 없음 → 인수 없음"""
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=True)
        s.tenants.append(Tenant(move_in_dates=["2024-07-09"]))
        self.assertEqual(s.opposable_risk(), "none")

    def test_move_in_before_lien(self):
        """전입이 최선순위보다 빠름 → 인수 위험 (금액은 계산하지 않음)"""
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=True)
        s.tenants.append(Tenant(move_in_dates=["2019-03-02"]))
        self.assertEqual(s.opposable_risk(), "risk")

    def test_move_in_column_wins_when_available(self):
        """전입 열을 가른 경우 그 열만 본다 — 임대차기간에 끌려가지 않는다"""
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=True)
        s.tenants.append(Tenant(move_in_dates=["2024-07-09"],
                                other_dates=["2019-01-01"]))
        self.assertEqual(s.opposable_risk(), "none")

    def test_fallback_is_conservative(self):
        """전입 열이 비면 모든 날짜로 보수 판정 (none 이 아니라 risk)"""
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=True)
        s.tenants.append(Tenant(other_dates=["2019-01-01"]))
        self.assertEqual(s.opposable_risk(), "risk")

    def test_no_dates_at_all_is_unknown(self):
        s = SpecSheet(lien_date="2022-10-11", has_tenant_block=True)
        s.tenants.append(Tenant())
        self.assertEqual(s.opposable_risk(), "unknown")

    def test_no_lien_date(self):
        s = SpecSheet(has_tenant_block=True)
        s.tenants.append(Tenant(move_in_dates=["2019-03-02"]))
        self.assertEqual(s.opposable_risk(), "unknown")

    def test_empty_input(self):
        s = parse_spec_sheet([])
        self.assertIsNone(s.lien_date)
        self.assertEqual(s.opposable_risk(), "unknown")


if __name__ == "__main__":
    unittest.main()
