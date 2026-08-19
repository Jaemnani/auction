#!/usr/bin/env python
"""정비사업(재개발·재건축) 구역 GeoJSON 생성 → web/public/redev/.

  python scripts/redev_layer.py build         # 수집·조인·저장 (현재 서울)
  python scripts/redev_layer.py check         # 원본 사업장 수 변화 확인

noise_layer.py 와 같은 운영: 한 번 받아 정적 파일로 커밋 = 배포.
단계 변동은 월 단위면 충분 — 월 1회 check 후 변화가 있으면 build + commit.
크론 미편입 (web/public 산출물은 커밋이 배포 수단).

⚠ 출처 표기 의무: 화면에 "자료: 서울시 정비사업 정보몽땅·서울 도시공간포털" 상시
   노출, 참고용 고지. 근거·정찰 기록은 docs/redev_layer_recon.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redevelopment import seoul  # noqa: E402

OUT_DIR = PROJECT_ROOT / "web" / "public" / "redev"
INDEX = OUT_DIR / "index.json"

# 시도코드(법정동 앞 2자리) → (이름, 빌더). 다른 시도는 소스 확보 후 여기 등록.
REGIONS = {
    "11": ("서울", seoul.build_features),
}


def _bbox(fc: dict) -> list[float]:
    xs, ys = [], []
    for f in fc["features"]:
        for poly in f["geometry"]["coordinates"]:
            for ring in poly:
                for x, y in ring:
                    xs.append(x)
                    ys.append(y)
    return [round(min(xs), 6), round(min(ys), 6),
            round(max(xs), 6), round(max(ys), 6)]


def cmd_check(_args: argparse.Namespace) -> None:
    cur = {}
    if INDEX.exists():
        cur = {r["code"]: r["count"] for r in json.loads(INDEX.read_text())["regions"]}
    stale = []
    for code, (name, _) in sorted(REGIONS.items()):
        n = len(seoul.fetch_biz_list()) if code == "11" else 0
        # count 는 "매칭된 feature 수" 라 사업장 수와 다르다 — 사업장 수 변화를
        # 갱신 신호로만 쓴다 (저장본에 biz_total 을 기록해 비교).
        saved = cur.get(code)
        meta_total = None
        if INDEX.exists():
            for r in json.loads(INDEX.read_text())["regions"]:
                if r["code"] == code:
                    meta_total = r.get("biz_total")
        mark = "NEW" if meta_total != n else "ok"
        if meta_total != n:
            stale.append(code)
        print(f"  {code} {name}  원본 사업장 {n}  저장 시점 {meta_total or '-'}"
              f"  (feature {saved or '-'})  [{mark}]")
    print(f"\n[done] 갱신 필요: {len(stale)}개" + (f" {stale}" if stale else ""))
    sys.exit(1 if stale else 0)


def cmd_build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = ([args.sido] if args.sido else list(REGIONS))
    index = {
        "source": "서울시 정비사업 정보몽땅 · 서울 도시공간포털(UPIS)",
        "source_url": "https://cleanup.seoul.go.kr/",
        "note": "표시용 사본. 참고용이며 정확한 구역·단계는 고시 원문 확인 필요.",
        "updated": time.strftime("%Y-%m-%d"),
        "regions": [],
    }
    # 부분 build 시 기존 index 의 다른 지역 항목 보존
    if INDEX.exists() and args.sido:
        old = json.loads(INDEX.read_text())
        index["regions"] = [r for r in old.get("regions", [])
                            if r["code"] not in targets]
    total_kb = 0
    for code in sorted(targets):
        if code not in REGIONS:
            print(f"  {code}: 미지원 시도 — 건너뜀 (지원: {list(REGIONS)})")
            continue
        name, builder = REGIONS[code]
        started = time.monotonic()
        fc, report = builder(precision=args.precision)
        path = OUT_DIR / f"{code}.json"
        path.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
        kb = path.stat().st_size // 1024
        total_kb += kb
        print(f"  {code} {name}  feature={report['features']}  {kb:,}KB  "
              f"({time.monotonic() - started:.0f}s)")
        print(f"     사업장 {report['biz_total']} (지도ID {report['biz_with_map_id']})"
              f" → ID조인 {report['joined_by_id']} + 이름조인 {report['joined_by_name']}"
              f" / 지도ID 미해결 {report['map_id_unmatched']}"
              f" / 도형누락 {report['missing_geometry']}")
        if report["unmapped_stage_values"]:
            print(f"     ⚠ 미매핑 단계(unknown 처리): {report['unmapped_stage_values']}"
                  f" — phases.py 매핑 추가 검토")
        index["regions"].append({
            "code": code, "name": name,
            "bbox": _bbox(fc) if fc["features"] else [126, 37, 128, 38],
            "file": f"/redev/{code}.json",
            "count": report["features"],
            "biz_total": report["biz_total"],
        })
    index["regions"].sort(key=lambda r: r["code"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"\n[done] {len(index['regions'])}개 지역, 합계 {total_kb:,}KB → {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="정비사업 구역 GeoJSON 생성")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="수집·조인·저장")
    b.add_argument("--sido", help="특정 시도만 (예: 11)")
    b.add_argument("--precision", type=int, default=6,
                   help="좌표 소수 자릿수 (기본 6 ≈ 11cm)")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="원본 변화 확인 (exit 1=갱신 필요)")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
