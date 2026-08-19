#!/usr/bin/env python
"""정비사업(재개발·재건축) 구역 GeoJSON 생성 → web/public/redev/.

  python scripts/redev_layer.py build [--sido 11]   # 수집·조인·저장
  python scripts/redev_layer.py check               # 원본 사업장 수 변화 확인

지원 지역: 서울(11, 폴리곤+점) / 부산(26, 점) / 경기(41, 점).
폴리곤이 있으면 구역 경계, 없으면 주소 지오코딩 대표 위치 점 — 점은 feature 에
loc_precision(parcel/dong)을 남겨 웹이 정밀도를 표시한다.

noise_layer.py 와 같은 운영: 한 번 받아 정적 파일로 커밋 = 배포.
단계 변동은 월 단위면 충분 — 월 1회 check 후 변화가 있으면 build + commit.
크론 미편입 (web/public 산출물은 커밋이 배포 수단).

필요 env: DATA_GO_KR_API_KEY(부산), GG_DATA_API_KEY(경기),
KAKAO_REST_API_KEY(지오코딩). 프로젝트 루트 .env 를 자동 로드한다.

⚠ 출처 표기 의무: 화면에 출처 상시 노출, 참고용 고지.
   근거·정찰 기록은 docs/redev_layer_recon.md.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))


def _load_dotenv() -> None:
    """루트 .env 의 미설정 변수만 채운다 (수동 실행 편의)."""
    env = PROJECT_ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.split(" #")[0].strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


_load_dotenv()

from redevelopment import busan, gyeonggi, seoul  # noqa: E402

OUT_DIR = PROJECT_ROOT / "web" / "public" / "redev"
INDEX = OUT_DIR / "index.json"

# 시도코드(법정동 앞 2자리) → (이름, 빌더 모듈, 좌표 검증 박스).
# 박스는 지오코딩 오매칭(타 지역 동명·도로명) 점을 걸러내는 sanity 경계 —
# 행정 경계보다 약간 여유. 추가 지역은 여기 등록.
REGIONS = {
    "11": ("서울", seoul, (126.70, 37.40, 127.20, 37.72)),
    "26": ("부산", busan, (128.70, 34.95, 129.35, 35.45)),
    "41": ("경기", gyeonggi, (126.30, 36.85, 127.95, 38.35)),
}


def _drop_mislocated_points(fc: dict, box: tuple[float, float, float, float]) -> int:
    """검증 박스 밖 Point feature 제거 (오지오코딩 = 오정보라 표시하지 않는다)."""
    w, s, e, n = box
    kept, dropped = [], 0
    for f in fc["features"]:
        g = f["geometry"]
        if g["type"] == "Point":
            x, y = g["coordinates"]
            if not (w <= x <= e and s <= y <= n):
                dropped += 1
                continue
        kept.append(f)
    fc["features"] = kept
    return dropped


def _bbox(fc: dict) -> list[float]:
    xs, ys = [], []
    for f in fc["features"]:
        geom = f["geometry"]
        if geom["type"] == "Point":
            xs.append(geom["coordinates"][0])
            ys.append(geom["coordinates"][1])
        else:  # MultiPolygon
            for poly in geom["coordinates"]:
                for ring in poly:
                    for x, y in ring:
                        xs.append(x)
                        ys.append(y)
    return [round(min(xs), 6), round(min(ys), 6),
            round(max(xs), 6), round(max(ys), 6)]


def cmd_check(_args: argparse.Namespace) -> None:
    saved: dict[str, dict] = {}
    if INDEX.exists():
        saved = {r["code"]: r for r in json.loads(INDEX.read_text())["regions"]}
    stale = []
    for code, (name, mod, _box) in sorted(REGIONS.items()):
        try:
            n = mod.source_count()
        except Exception as e:  # 소스 한 곳이 죽어도 나머지는 확인
            print(f"  {code} {name}  확인 실패: {e}")
            continue
        meta_total = saved.get(code, {}).get("biz_total")
        mark = "NEW" if meta_total != n else "ok"
        if meta_total != n:
            stale.append(code)
        print(f"  {code} {name}  원본 사업장 {n}  저장 시점 {meta_total or '-'}"
              f"  (feature {saved.get(code, {}).get('count', '-')})  [{mark}]")
    print(f"\n[done] 갱신 필요: {len(stale)}개" + (f" {stale}" if stale else ""))
    sys.exit(1 if stale else 0)


def cmd_build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    targets = ([args.sido] if args.sido else list(REGIONS))
    index = {
        "source": "서울 정비사업 정보몽땅·도시공간포털 / 부산광역시 / 경기데이터드림",
        "source_url": "https://cleanup.seoul.go.kr/",
        "note": "표시용 사본. 참고용이며 정확한 구역·단계는 고시 원문 확인 필요. "
                "점(Point)은 구역 경계가 아니라 주소 기반 대표 위치.",
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
        name, mod, box = REGIONS[code]
        started = time.monotonic()
        fc, report = mod.build_features(precision=args.precision)
        report["mislocated_dropped"] = _drop_mislocated_points(fc, box)
        report["features"] = len(fc["features"])
        path = OUT_DIR / f"{code}.json"
        path.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
        kb = path.stat().st_size // 1024
        total_kb += kb
        print(f"  {code} {name}  feature={report['features']}  {kb:,}KB  "
              f"({time.monotonic() - started:.0f}s)")
        detail = {k: v for k, v in report.items()
                  if k not in ("features", "unmapped_stage_values") and v}
        if detail:
            print("     " + "  ".join(f"{k}={v}" for k, v in detail.items()))
        if report.get("unmapped_stage_values"):
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
