"""
한국 경매 매물 위험 플래그 분석.

detail_result jsonb + properties 컬럼을 종합해 25 키워드 플래그를 산출.
출력 plain text[] 코드 — supabase risk_flags 컬럼에 그대로 저장.

플래그 코드:
  share_sale       지분 매각
  maeng_ji         맹지
  yuchi            유치권
  legal_ground     법정지상권
  senior_tenant    선순위 임차인 (+ 대항력)
  rent_unknown     임대관계/점유관계 미상
  illegal_bld      위반건축물
  reserve_forest   보전산지
  forestry_land    임업용 산지
  agri_zone        농림지역
  nat_protect      자연보전권역
  private_road     사도 (사도법상)
  pollak           포락지
  pamyo            파묘
  power_line       송전선 / 구분지상권
  show_only        제시외 물건
  many_fails       유찰 5회 이상
  special_20       특별 보증금 20%
  claim_90         청구금액이 감정가의 90% 이상
  stopped          정지/연기/취하
  new_villa        신축 빌라 (5년 이내) — 빌라/다세대/도생주
  farm_land        농지
  forest_only      임야 단독
  tiny_area        초소형 (30㎡ 이하)
  share_maeng      지분+맹지 조합 (가장 위험)
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any


# 검색 텍스트 수집 — detail_result의 비고·감정평가 요항 모두 합쳐 검색
def _collect_text(detail: dict[str, Any]) -> str:
    parts: list[str] = []
    dxdy = (detail.get("dspslGdsDxdyInfo") or {}) if isinstance(detail.get("dspslGdsDxdyInfo"), dict) else {}
    for k in ("dspslGdsRmk", "gdsSpcfcRmk"):
        v = dxdy.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v)
    for item in detail.get("aeeWevlMnpntLst") or []:
        if isinstance(item, dict):
            v = item.get("aeeWevlMnpntCtt")
            if isinstance(v, str) and v.strip():
                parts.append(v)
    cs = detail.get("csBaseInfo") or {}
    if isinstance(cs, dict):
        for k in ("rmk", "topRmk"):
            v = cs.get(k)
            if isinstance(v, str) and v.strip():
                parts.append(v)
    return "\n".join(parts)


_AREA_RE = re.compile(r"([\d.]+)\s*㎡")


def _min_area_m2(area_summary: str | None) -> float | None:
    """area_summary 텍스트에서 ㎡ 숫자들을 추출해 최솟값 반환."""
    if not area_summary:
        return None
    matches = _AREA_RE.findall(area_summary)
    nums: list[float] = []
    for m in matches:
        try:
            nums.append(float(m))
        except ValueError:
            pass
    return min(nums) if nums else None


def _parse_yyyymmdd(s: Any) -> date | None:
    if not isinstance(s, str):
        return None
    try:
        if len(s) == 8 and s.isdigit():
            return datetime.strptime(s, "%Y%m%d").date()
        # 'YYYY-MM-DD'
        return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def compute_risk_flags(
    *,
    detail_result: dict[str, Any] | None,
    appraisal_amount: int | float | None,
    fail_count: int | None,
    usage_lcl_cd: str | None,
    usage_mcl_cd: str | None,
    area_summary: str | None,
    building_summary: str | None,
) -> list[str]:
    """매물 정보 → 위험 플래그 코드 리스트.

    아무 위험 없으면 빈 list. 신규 키워드 추가 시 여기에 분기 추가.
    """
    flags: set[str] = set()
    detail = detail_result or {}
    text = _collect_text(detail)

    # ===== 텍스트 키워드 매칭 =====
    if any(p in text for p in ("지분", "지분매각")) or re.search(r"\d+분의\s*\d+", text):
        flags.add("share_sale")
    if "맹지" in text:
        flags.add("maeng_ji")
    if "유치권" in text:
        flags.add("yuchi")
    if re.search(r"법정\s*지상권", text):
        flags.add("legal_ground")
    if re.search(r"선순위.{0,8}임차", text) or "대항력" in text:
        flags.add("senior_tenant")
    if re.search(r"(임대관계|점유관계).{0,6}미상", text):
        flags.add("rent_unknown")
    if "위반건축물" in text or "위반 건축물" in text:
        flags.add("illegal_bld")
    if "보전산지" in text:
        flags.add("reserve_forest")
    if "임업용" in text:
        flags.add("forestry_land")
    if "농림지역" in text:
        flags.add("agri_zone")
    if "자연보전권역" in text:
        flags.add("nat_protect")
    # 사도 — "사도법" 또는 단독 "사도" (도로법상 사도)
    if "사도법" in text or re.search(r"(^|[\s,(])사도($|[\s,)])", text):
        flags.add("private_road")
    if "포락" in text:
        flags.add("pollak")
    if "파묘" in text or "분묘" in text:
        flags.add("pamyo")
    if "송전선" in text or "구분지상권" in text:
        flags.add("power_line")
    if "제시외" in text:
        flags.add("show_only")

    # ===== 수치·상태 매칭 =====
    if isinstance(fail_count, int) and fail_count >= 5:
        flags.add("many_fails")

    # 특별 보증금 20% — dspslGdsDxdyInfo의 보증금 정보
    dxdy = detail.get("dspslGdsDxdyInfo") or {}
    if isinstance(dxdy, dict):
        # 매각 구분 코드 또는 보증금율 텍스트에서 "20%" 검출
        dxdy_text = " ".join(str(v) for v in dxdy.values() if isinstance(v, str))
        if "특별매각" in dxdy_text or re.search(r"보증금.{0,4}20\s*%", dxdy_text):
            flags.add("special_20")

    # 청구금액 90% 이상
    cs = detail.get("csBaseInfo") or {}
    clm = cs.get("clmAmt") if isinstance(cs, dict) else None
    try:
        clm_n = int(clm) if clm not in (None, "") else None
    except (TypeError, ValueError):
        clm_n = None
    if clm_n and appraisal_amount and float(appraisal_amount) > 0:
        if clm_n / float(appraisal_amount) >= 0.9:
            flags.add("claim_90")

    # 정지/연기/취하 — csBaseInfo.csProgStatCd 또는 ultmtDvsCd
    if isinstance(cs, dict):
        prog = str(cs.get("csProgStatCd") or "")
        ultmt = str(cs.get("ultmtDvsCd") or "")
        # courtauction 상태 코드: 022(정지), 023(연기), 030(취하) 등. 정확 매핑은 코드 표 필요.
        # 보수적으로 텍스트에서 "정지", "연기", "취하" 검출도 병행.
        cs_text = " ".join(str(v) for v in cs.values() if isinstance(v, str))
        if any(k in cs_text for k in ("정지", "연기", "취하", "중지")):
            flags.add("stopped")
        # 코드 매칭 (확실한 것만): 022/023/030
        if prog in {"022", "023", "030"} or ultmt in {"022", "023", "030"}:
            flags.add("stopped")

    # 농지 — 용도 코드 (대분류 농지 = 농지·전·답)
    # 코드는 한국 courtauction의 용도 카테고리. 대략: 농지 mcl="20100" (논), "20200" (밭), "20300" (과수원) 등 20000대.
    if usage_lcl_cd and usage_lcl_cd.startswith("20"):
        flags.add("farm_land")
    # 임야 단독 (mcl 임야)
    if usage_mcl_cd and ("30" in usage_mcl_cd[:4]):  # 임야 분류 30000대 가정
        # 추가 검증: building_summary가 비어있어야 단독 임야
        if not building_summary or not building_summary.strip():
            flags.add("forest_only")

    # 초소형 (30㎡ 이하)
    min_area = _min_area_m2(area_summary)
    if min_area is not None and min_area <= 30.0:
        flags.add("tiny_area")

    # 신축 빌라 — building_summary에 "신축" 또는 detail의 건축 연도가 5년 이내
    bs = building_summary or ""
    is_residential = (
        usage_mcl_cd in {"10101", "10102", "10103", "10104", "10105"}  # 다세대/연립/오피스텔 등 가정
        or any(k in bs for k in ("빌라", "다세대", "연립"))
    )
    if is_residential:
        # 건축연도 YYYY 추출 — building_summary "2022년" 등 또는 detail.gdsDspslObjctLst[0].bldDtlDts 등
        years: list[int] = []
        for m in re.finditer(r"(19[6-9]\d|20\d{2})\s*년", bs):
            try:
                years.append(int(m.group(1)))
            except ValueError:
                pass
        for obj in detail.get("gdsDspslObjctLst") or []:
            if isinstance(obj, dict):
                v = obj.get("bldDtlDts")
                if isinstance(v, str):
                    for m in re.finditer(r"(19[6-9]\d|20\d{2})", v):
                        try:
                            years.append(int(m.group(1)))
                        except ValueError:
                            pass
        if years:
            this_year = date.today().year
            newest = max(years)
            if newest >= this_year - 5:
                flags.add("new_villa")

    # 조합 플래그
    if "share_sale" in flags and "maeng_ji" in flags:
        flags.add("share_maeng")

    return sorted(flags)
