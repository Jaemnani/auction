#!/usr/bin/env python
"""공항 소음등고선 GeoJSON 생성 → web/public/noise/.

  python scripts/noise_layer.py build        # 6개 공항 수집·변환·저장
  python scripts/noise_layer.py check        # 갱신 여부만 확인 (연 1회면 충분)

한 번 받아 저장하고 재사용한다 — 원 서비스(airportnoise.kr)에 부하를 주지 않기
위해서다. 등고선은 연 단위로만 바뀌므로 check 로 새 YEAR 가 보일 때만 build.

⚠ 출처 표기 의무: 화면에 "자료: 공항소음포털" 상시 노출. 원본 다운로드 제공 금지.
   근거·라이선스 논의는 docs/airport_noise_layer.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from noise.fetch import fetch_contours, latest_years, list_airports  # noqa: E402

OUT_DIR = PROJECT_ROOT / "web" / "public" / "noise"
INDEX = OUT_DIR / "index.json"


def cmd_check(_args: argparse.Namespace) -> None:
    years = latest_years()
    cur = {}
    if INDEX.exists():
        cur = {a["code"]: a["year"] for a in json.loads(INDEX.read_text())["airports"]}
    stale = [c for c, y in years.items() if cur.get(c) != y]
    for code, y in sorted(years.items()):
        mark = "NEW" if cur.get(code) != y else "ok"
        print(f"  {code}  원본 {y}  저장본 {cur.get(code, '-')}  [{mark}]")
    print(f"\n[done] 갱신 필요: {len(stale)}개" + (f" {stale}" if stale else ""))
    sys.exit(1 if stale else 0)


def cmd_build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    airports = {a.code: a for a in list_airports()}
    years = latest_years()
    index = {
        "source": "공항소음포털 (airportnoise.kr)",
        "source_url": "https://www.airportnoise.kr/anps/gis",
        "note": "표시용 사본. 참고용이며 정확한 구역은 관할 지자체 확인 필요.",
        "airports": [],
    }
    total = 0
    for code, ap in sorted(airports.items()):
        year = years.get(code)
        if not year:
            print(f"  {code}: 등고선 없음 — 건너뜀")
            continue
        started = time.monotonic()
        fc = fetch_contours(code, year, precision=args.precision)
        path = OUT_DIR / f"{code}.json"
        path.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
        kb = path.stat().st_size // 1024
        total += kb
        print(f"  {code} {ap.name:6s} {year}  feature={len(fc['features'])}  "
              f"{kb:,}KB  ({time.monotonic() - started:.0f}s)")
        index["airports"].append({
            "code": code, "name": ap.name, "year": year,
            "bbox": ap.bbox, "file": f"/noise/{code}.json",
        })
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"\n[done] {len(index['airports'])}개 공항, 합계 {total:,}KB → {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="공항 소음등고선 GeoJSON 생성")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="수집·변환·저장")
    b.add_argument("--precision", type=int, default=6,
                   help="좌표 소수 자릿수 (기본 6 ≈ 11cm)")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="원본에 새 연도가 있는지 확인 (exit 1=갱신 필요)")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
