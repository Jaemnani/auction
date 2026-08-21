#!/usr/bin/env python
"""정비사업(재개발·재건축) 구역 GeoJSON 생성 → web/public/redev/.

  python scripts/redev_layer.py build [--sido 26]   # 수집·결합·저장
  python scripts/redev_layer.py check               # 원본 사업장 수 변화 확인

지역별 구성:
  서울(11)  정비몽땅 사업장 ↔ 서울 UPIS 폴리곤을 지도ID 로 조인(단계 100%).
            폴리곤 없는 사업장은 대표지번 지오코딩 점.
  부산(26)  국토부 정비구역 SHP 폴리곤 + 부산 API 단계(이름·위치 매칭)
  경기(41)  국토부 정비구역 SHP 폴리곤 + 경기 API 단계(이름·위치 매칭)
  그 외     국토부 SHP 폴리곤만 — 단계 소스가 없어 "단계 미확인"

폴리곤 SHP 는 사람이 브이월드에서 받아 둔 폴더를 읽는다(기본 ~/Downloads/download,
REDEV_SHP_DIR 로 변경). 없으면 SHP 기반 지역은 건너뛴다.

noise_layer.py 와 같은 운영: 정적 파일로 커밋 = 배포. 월 1회 check 후 build.
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

from redevelopment import busan, gyeonggi, national, seoul  # noqa: E402

OUT_DIR = PROJECT_ROOT / "web" / "public" / "redev"
INDEX = OUT_DIR / "index.json"

# 시도코드(법정동 앞 2자리) → 표시명. 개편 전후 코드를 모두 둔다.
# 12 = 전남·광주 통합특별시(신설). 29(광주)·46(전남)은 통합 전 코드.
SIDO_NAMES = {
    "11": "서울", "12": "전남·광주", "26": "부산", "27": "대구", "28": "인천",
    "29": "광주", "30": "대전", "31": "울산", "36": "세종", "41": "경기",
    "42": "강원", "43": "충북", "44": "충남", "45": "전북", "46": "전남",
    "47": "경북", "48": "경남", "50": "제주", "51": "강원", "52": "전북",
}

# 단계(사업 진행) 소스가 있는 시도 → 어댑터 모듈
STAGE_ADAPTERS = {"26": busan, "41": gyeonggi}

# 지오코딩 오매칭 방어용 시도 경계(여유 있게). 주소만 있는 사업장을 좌표로
# 바꿀 때 동명 지명·도로명이 타 시도에 있으면 엉뚱한 곳에 찍힌다
# (실측: 부산 '광안2 재건축'이 세종 좌표로). 폴리곤은 공식 데이터라 대상 아님.
SIDO_POINT_BOX = {
    "11": (126.70, 37.40, 127.20, 37.72),   # 서울
    "26": (128.70, 34.95, 129.35, 35.45),   # 부산
    "41": (126.30, 36.85, 127.95, 38.35),   # 경기
}


def _drop_mislocated_points(fc: dict, box: tuple[float, float, float, float]) -> int:
    """검증 박스 밖 Point 제거 — 오지오코딩은 오정보라 표시하지 않는다."""
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

# 서울은 UPIS 지도ID 조인이 더 정확해 SHP 대신 전용 경로를 쓴다.
SEOUL = "11"


def _bbox(fc: dict) -> list[float]:
    xs: list[float] = []
    ys: list[float] = []
    for f in fc["features"]:
        geom = f["geometry"]
        if geom["type"] == "Point":
            xs.append(geom["coordinates"][0])
            ys.append(geom["coordinates"][1])
        else:
            for poly in geom["coordinates"]:
                for ring in poly:
                    for x, y in ring:
                        xs.append(x)
                        ys.append(y)
    if not xs:
        return [126.0, 34.0, 130.0, 38.5]
    return [round(min(xs), 6), round(min(ys), 6),
            round(max(xs), 6), round(max(ys), 6)]


def cmd_check(_args: argparse.Namespace) -> None:
    saved: dict[str, dict] = {}
    if INDEX.exists():
        saved = {r["code"]: r for r in json.loads(INDEX.read_text())["regions"]}
    stale = []
    sources = {SEOUL: seoul, **STAGE_ADAPTERS}
    for code, mod in sorted(sources.items()):
        name = SIDO_NAMES.get(code, code)
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
    polys = national.load_polygons()
    print(f"\n  SHP 폴리곤: {sum(len(v) for v in polys.values())}건 "
          f"/ {len(polys)}개 시도  ({national.shp_dir()})")
    print(f"[done] 갱신 필요: {len(stale)}개" + (f" {stale}" if stale else ""))
    sys.exit(1 if stale else 0)


def cmd_build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    polys_by_sido = national.load_polygons()
    if not polys_by_sido:
        print(f"  ⚠ SHP 폴리곤 없음 ({national.shp_dir()}) — 서울만 생성됩니다.")

    targets = [args.sido] if args.sido else sorted(
        {SEOUL, *STAGE_ADAPTERS, *polys_by_sido})

    index = {
        "source": "국토교통부 정비구역(브이월드) · 서울 정비사업 정보몽땅"
                  "·도시공간포털 / 부산광역시 / 경기데이터드림",
        "source_url": national.SOURCE_URL,
        "note": "표시용 사본. 참고용이며 정확한 구역·단계는 고시 원문 확인 필요. "
                "점(Point)은 구역 경계가 아니라 주소 기반 대표 위치.",
        "updated": time.strftime("%Y-%m-%d"),
        "regions": [],
    }
    if INDEX.exists() and args.sido:
        old = json.loads(INDEX.read_text())
        index["regions"] = [r for r in old.get("regions", [])
                            if r["code"] not in targets]

    total_kb = 0
    for code in targets:
        name = SIDO_NAMES.get(code, code)
        started = time.monotonic()

        if code == SEOUL:
            fc, report = seoul.build_features(precision=args.precision)
        else:
            polys = polys_by_sido.get(code) or []
            adapter = STAGE_ADAPTERS.get(code)
            if not polys and not adapter:
                continue
            if adapter:
                biz_fc, report = adapter.build_features(precision=args.precision)
                biz = biz_fc["features"]
            else:
                biz, report = [], {"biz_total": 0}
            if polys:
                fc, stat = national.merge(polys, biz)
                report.update(stat)
            else:
                fc = {"type": "FeatureCollection", "features": biz}
                report["features"] = len(biz)
                report["polygons"] = 0

        box = SIDO_POINT_BOX.get(code)
        if box:
            n_drop = _drop_mislocated_points(fc, box)
            if n_drop:
                report["mislocated_dropped"] = n_drop
            report["features"] = len(fc["features"])

        if not fc["features"]:
            print(f"  {code} {name}: feature 0 — 건너뜀")
            continue

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
            "bbox": _bbox(fc),
            "file": f"/redev/{code}.json",
            "count": report["features"],
            "biz_total": report.get("biz_total", 0),
        })

    index["regions"].sort(key=lambda r: r["code"])
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"\n[done] {len(index['regions'])}개 지역, 합계 {total_kb:,}KB → {OUT_DIR}")


def main() -> None:
    ap = argparse.ArgumentParser(description="정비사업 구역 GeoJSON 생성")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="수집·결합·저장")
    b.add_argument("--sido", help="특정 시도만 (예: 26)")
    b.add_argument("--precision", type=int, default=6,
                   help="좌표 소수 자릿수 (기본 6 ≈ 11cm)")
    b.set_defaults(func=cmd_build)
    c = sub.add_parser("check", help="원본 변화 확인 (exit 1=갱신 필요)")
    c.set_defaults(func=cmd_check)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
