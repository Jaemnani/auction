#!/usr/bin/env python
"""정비사업 데이터 소스 정찰(재현용) — 결과 해석은 docs/redev_layer_recon.md.

  python scripts/probe_redev.py cleanup     # 정비몽땅 목록 구조·단계 값 전수
  python scripts/probe_redev.py upis        # 서울 UPIS ArcGIS 레이어·필드·건수
  python scripts/probe_redev.py join        # 목록 지도ID ↔ UQ181(C/H) 조인 커버리지

read-only 샘플 호출만 한다. 원 서비스 부하 방지를 위해 반복 실행하지 말 것.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redevelopment import seoul  # noqa: E402


def cmd_cleanup(_a: argparse.Namespace) -> None:
    biz = seoul.fetch_biz_list()
    print(f"사업장 {len(biz)}건 / 지도ID {sum(1 for b in biz if b.record_code)}건")
    print("사업구분:", dict(Counter(b.kind for b in biz)))
    print("진행단계 원값 전수:")
    for stage, n in Counter(b.stage_raw for b in biz).most_common():
        print(f"  {n:4d}  {stage or '(빈값)'}")


def cmd_upis(_a: argparse.Namespace) -> None:
    for layer in (seoul.LAYER_CURRENT, seoul.LAYER_HISTORY):
        d = seoul._arcgis_query(layer, {"where": "1=1", "returnCountOnly": "true"})
        print(f"layer {layer}: {d.get('count')}건")
    attrs = seoul.fetch_layer_attrs(seoul.LAYER_CURRENT)
    sample = next(iter(attrs.values()))
    print("C 레이어 속성 필드:", sorted(sample))
    print("LCLAS_CL 분포:",
          Counter(a["LCLAS_CL"] for a in attrs.values()).most_common(10))


def cmd_join(_a: argparse.Namespace) -> None:
    biz = seoul.fetch_biz_list()
    ids = {b.record_code for b in biz if b.record_code}
    c = set(seoul.fetch_layer_attrs(seoul.LAYER_CURRENT))
    h = set(seoul.fetch_layer_attrs(seoul.LAYER_HISTORY))
    print(f"지도ID {len(ids)} → C 매칭 {len(ids & c)} / H 보강 {len((ids - c) & h)}"
          f" / 미해결 {len(ids - c - h)}")
    print("미해결 예시:", sorted(ids - c - h)[:5])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in (("cleanup", cmd_cleanup), ("upis", cmd_upis), ("join", cmd_join)):
        sub.add_parser(name).set_defaults(func=fn)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
