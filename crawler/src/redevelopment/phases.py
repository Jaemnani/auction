"""정비사업 진행단계 공통 enum.

지자체마다 단계 명칭이 다르므로 여기 enum 으로 정규화한다.
웹(web/src/lib/redev-layer.ts)의 PHASE_ORDER/PHASE_LABEL 과 값·순서를 맞출 것.

매핑되지 않는 원 명칭은 unknown 으로 두고 build 가 경고를 출력한다 —
임의 추정 매핑 금지(없으면 "-" 원칙). 원 명칭은 feature 의 phase_raw 로 보존.
"""
from __future__ import annotations

# (enum, 한글 라벨) — 사업 진행 순서대로.
PHASES: list[tuple[str, str]] = [
    ("planned", "계획·준비"),
    ("designated", "구역지정"),
    ("committee", "추진위·조합준비"),
    ("union", "조합설립인가"),
    ("plan_approved", "사업시행인가"),
    ("disposal", "관리처분인가"),
    ("construction", "이주·철거·착공"),
    ("completed", "준공·완료"),
    ("unknown", "단계 미확인"),
]
PHASE_KEYS = [k for k, _ in PHASES]

# 서울 정비몽땅 진행단계 원값 → enum.
# 2026-08 목록 실측 전수(25종) 기준 — docs/redev_layer_recon.md 참조.
SEOUL_STAGE_MAP: dict[str, str] = {
    "정비계획 수립": "planned",
    "안전진단": "planned",
    "안전진단(1차)": "planned",
    "지구단위계획수립/건축심의/교통심의": "planned",
    "도시계획심의": "planned",
    "정비구역지정": "designated",
    "추진위구성": "committee",
    "추진위원회승인": "committee",
    "조합원 모집신고": "committee",
    "조합규약작성": "committee",
    "조합창립총회": "committee",
    "조합설립인가": "union",
    "사업시행인가": "plan_approved",
    "사업계획승인": "plan_approved",
    "관리처분인가": "disposal",
    "이주/철거": "construction",
    "철거": "construction",
    "착공": "construction",
    "철거 및 착공": "construction",
    "분양": "construction",
    "준공인가": "completed",
    "이전고시": "completed",
    "조합해산": "completed",
    "조합청산": "completed",
    "청산 및 조합해산": "completed",
}


def normalize_stage(raw: str, mapping: dict[str, str]) -> str:
    key = (raw or "").strip()
    return mapping.get(key, "unknown")
