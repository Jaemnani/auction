"""매각물건명세서 파싱 — 좌표 텍스트 노드 → 구조화 필드 (순수 함수).

입력: StreamDocs 뷰어에서 뽑은 [{t, x, y, w, h}] (probe_spec_sheet.py 참조)
출력: SpecSheet — 인수액 판정에 필요한 값만. **계산은 하지 않는다.**
      (인수액 산식은 web/src/lib/assumption.ts 의 simulate() 가 이미 검산 완료.
       여기서 다시 구현하면 두 벌이 어긋나므로, 이 모듈은 사실 추출만 한다.)

설계 원칙 — 금액이 걸린 값이라 **모르면 모른다고 한다**:
  · 확실히 뽑히는 것(최선순위 설정일·배당요구종기·임차인 날짜)만 값으로 낸다.
  · 대항력 판정은 "임차인 날짜 vs 최선순위" 비교로 결정적이다.
  · 보증금은 명세서에 아예 공란인 경우가 흔하다(현황조사 출처 등).
    없으면 None 을 내고 confidence 를 낮춘다. 절대 추정하지 않는다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 최선순위 설정 권리 종류 — 이 중 하나가 말소기준권리가 된다
LIEN_KINDS = ("근저당", "저당", "가압류", "압류", "전세권", "담보가등기", "경매개시결정")

# "2022.10.11." / "2024. 8. 1." / "2022-10-11" 모두 수용
_DATE = re.compile(r"(\d{4})\s*[.\-]\s*(\d{1,2})\s*[.\-]\s*(\d{1,2})\s*\.?")
# 전입신고일자 열 판정 허용오차(px) — 조각 시작 x 가 헤더보다 살짝 왼쪽일 수 있음
_COL_TOL = 30

# 금액 — 1,000,000 형태 (명세서 보증금란). 3자리 구분 없는 값은 면적·번지와 구별이 안 돼 제외.
_MONEY = re.compile(r"(\d{1,3}(?:,\d{3}){2,})")


def _norm_date(m: re.Match[str]) -> str:
    y, mo, d = m.group(1), int(m.group(2)), int(m.group(3))
    return f"{y}-{mo:02d}-{d:02d}"


def _dates(text: str) -> list[str]:
    return [_norm_date(m) for m in _DATE.finditer(text)]


@dataclass
class Tenant:
    """명세서 임차인 행에서 뽑은 값. 없으면 None — 추정하지 않는다.

    ⚠ 날짜를 한 덩어리로 섞으면 안 된다. 임대차기간(점유기간)과 전입신고일자는
    법적 의미가 완전히 다르고, 대항력 판정에 쓰는 건 **전입신고일(사업자등록일)**
    뿐이다. 임대차 시작일을 전입일로 오인하면 인수액 판정이 뒤집힌다.
    → 표 헤더의 x 좌표로 열을 갈라 담는다.
    """
    name: str | None = None
    deposit: int | None = None          # 보증금(원)
    move_in_dates: list[str] = field(default_factory=list)  # 전입신고/사업자등록/확정일자 열
    other_dates: list[str] = field(default_factory=list)    # 임대차기간 등 그 밖의 열
    raw: str = ""

    @property
    def dates(self) -> list[str]:
        """호환용 — 전 열의 날짜. 판정에는 move_in_dates 만 쓸 것."""
        return [*self.move_in_dates, *self.other_dates]


@dataclass
class SpecSheet:
    lien_date: str | None = None        # 최선순위 설정일 = 말소기준권리
    lien_kind: str | None = None
    demand_deadline: str | None = None  # 배당요구종기
    tenants: list[Tenant] = field(default_factory=list)
    has_tenant_block: bool = False      # 임차인 표에 내용이 있었나
    confidence: str = "low"             # high | low
    notes: list[str] = field(default_factory=list)
    raw_text: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "lien_date": self.lien_date,
            "lien_kind": self.lien_kind,
            "demand_deadline": self.demand_deadline,
            "tenants": [
                {"name": t.name, "deposit": t.deposit, "dates": t.dates, "raw": t.raw}
                for t in self.tenants
            ],
            "has_tenant_block": self.has_tenant_block,
            "confidence": self.confidence,
            "notes": self.notes,
        }

    # ---- 인수 위험 판정 (금액 계산 아님 — 판정만) ----

    def opposable_risk(self) -> str:
        """'none' 인수 없음 / 'risk' 인수 가능 / 'unknown' 판단 불가.

        대항력 = 전입신고(다음날 0시) 가 최선순위 설정일보다 빠름.
        **전입신고일자 열의 날짜만** 본다 (임대차기간은 대항력과 무관).

        판정 불가면 'none'(안전해 보이는 답)이 아니라 'unknown' 을 낸다 —
        대항력 있는 임차인을 '없음'으로 잘못 말하면 사용자가 인수액을 0으로
        믿고 입찰한다. 그 손해가 '확인 필요'라고 말하는 번거로움보다 훨씬 크다.
        """
        if not self.lien_date:
            return "unknown"
        if not self.has_tenant_block:
            return "none"          # 임차인 기재 자체가 없음
        move_in = [d for t in self.tenants for d in t.move_in_dates]
        if not move_in:
            return "unknown"       # 임차인은 있는데 전입일을 못 읽음 → 원문 확인
        return "none" if min(move_in) > self.lien_date else "risk"


def parse_spec_sheet(nodes: list[dict[str, Any]]) -> SpecSheet:
    """좌표 텍스트 노드 → SpecSheet."""
    out = SpecSheet()
    if not nodes:
        out.notes.append("빈 입력")
        return out

    # y 오름차순(같은 y 면 x) — 문서 읽기 순서 복원
    ordered = sorted(nodes, key=lambda n: (n["y"], n["x"]))
    lines = [(n["y"], n["x"], str(n["t"]).strip()) for n in ordered if str(n["t"]).strip()]
    out.raw_text = "\n".join(t for _, _, t in lines)

    # ---- 1) 최선순위 설정일 + 배당요구종기 ----
    # 한 줄에 같이 오는 게 표준 서식:
    #   "별지 기재와 같음 2022.10.11. 근저당 배당요구종기 2024. 8. 1."
    for _, _, t in lines:
        if "배당요구종기" in t:
            head, _, tail = t.partition("배당요구종기")
            hd, td = _dates(head), _dates(tail)
            if hd:
                out.lien_date = hd[-1]
                for k in LIEN_KINDS:
                    if k in head:
                        out.lien_kind = k
                        break
            if td:
                out.demand_deadline = td[0]
            break
    # 폴백 — 종기가 별도 줄에 있는 서식
    if out.lien_date is None:
        for _, _, t in lines:
            if any(k in t for k in LIEN_KINDS) and _dates(t):
                out.lien_date = _dates(t)[0]
                for k in LIEN_KINDS:
                    if k in t:
                        out.lien_kind = k
                        break
                out.notes.append("최선순위: 폴백 경로로 추출")
                break

    # ---- 2) 임차인 블록 ----
    # 표 헤더 마지막("(배당요구일자)" 등) 다음 ~ "<비고>" 사이가 임차인 행 영역.
    y_start = None
    y_end = None
    for y, _, t in lines:
        if y_start is None and ("배당요구일자" in t or "신청일자" in t):
            y_start = y
        if "<비고>" in t or t.startswith("비고"):
            y_end = y
            break
    if y_start is not None and y_end is not None and y_end > y_start:
        block = [(y, x, t) for y, x, t in lines if y_start < y < y_end]
        # 안내문(고정 문구)은 임차인 행이 아니다
        block = [(y, x, t) for y, x, t in block
                 if "최선순위 설정일자보다" not in t and "매수인에게 인수" not in t]
        if block:
            out.has_tenant_block = True
            raw = " ".join(t for _, _, t in block)
            tenant = Tenant(raw=raw)
            # 전입신고일자 열의 x 시작점을 헤더에서 찾는다 (없으면 열 분리 불가).
            # ⚠ 본문 안내문에도 "전입신고일자" 가 나온다
            #   ("…그 일자, 전입신고일자 또는 사업자등록신청일자와…", x=262).
            #   그걸 헤더로 잡으면 열 경계가 왼쪽 끝이 돼 모든 날짜가 전입 열로
            #   섞여 들어간다 → 표 머리글 셀(짧은 조각)만 인정한다.
            col_x = None
            for _, x, t in lines:
                if "전입신고일자" in t and len(t) <= 12:
                    col_x = x
                    break
            if col_x is None:
                out.notes.append("전입신고일자 열 위치 미확인 — 날짜 열 분리 불가")
                tenant.other_dates = _dates(raw)
            else:
                for _, x, t in block:
                    ds = _dates(t)
                    if not ds:
                        continue
                    # 조각의 시작 x 가 전입 열 안이면 전입/확정일자로 본다
                    if x >= col_x - _COL_TOL:
                        tenant.move_in_dates.extend(ds)
                    else:
                        tenant.other_dates.extend(ds)
            money = _MONEY.findall(raw)
            if money:
                tenant.deposit = int(money[0].replace(",", ""))
            # 성명 — 가장 왼쪽 열(x 최솟값 근처) 조각들을 이어붙임
            xs = [x for _, x, _ in block]
            left = min(xs)
            name_parts = [t for _, x, t in block if x <= left + 12]
            nm = "".join(p.split()[0] for p in name_parts if p.split())
            tenant.name = nm or None
            out.tenants.append(tenant)

    # ---- 3) 신뢰도 ----
    if out.lien_date and (out.demand_deadline or not out.has_tenant_block):
        out.confidence = "high"
    else:
        out.notes.append("최선순위/배당요구종기 일부 미확보")
    if out.has_tenant_block and out.tenants and not out.tenants[0].move_in_dates:
        out.confidence = "low"
        out.notes.append("임차인 기재는 있으나 전입신고일 미확보 — 원문 확인 필요")
    if out.has_tenant_block and out.tenants and out.tenants[0].deposit is None:
        out.notes.append("보증금 공란 — 명세서에 금액 기재 없음")

    return out
