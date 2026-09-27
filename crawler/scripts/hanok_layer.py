#!/usr/bin/env python
"""서울 한옥 레이어 GeoJSON 생성 → web/public/hanok/.

  python scripts/hanok_layer.py build [--notice-date 2024-03-05]   # 받아 둔 소스 → 레이어
  python scripts/hanok_layer.py verify --subsidy 지원내역.csv       # 보전구역 교차 검증

레이어 3종 (소스는 사람이 받아 HANOK_SRC_DIR, 기본 ~/Downloads/hanok 에 둔다):
  preservation.geojson  한옥보전구역 공식 경계 — 공고 PDF 를 QGIS 로 직접 딴 것
  district/ 또는 district.zip
                        서울시 지구단위계획구역 SHP (열린데이터광장 OA-21161)
  registry.csv          서울시 한옥등록 정보 (OA-15415) — 주소 지오코딩 점

소스가 없는 레이어는 커밋된 파일·색인을 **그대로 유지**한다 (다른 머신에서
build 해도 공들여 딴 보전구역이 지워지지 않게 — redev_layer 35caa6e 교훈).

redev_layer.py 와 같은 운영: 정적 파일로 커밋 = 배포. 크론 미편입.
필요 env: KAKAO_REST_API_KEY (registry / verify 지오코딩만).

⚠ 라이선스: 서울한옥포털 콘텐츠는 공공누리 제4유형(상업적 이용·변경 금지).
   공고 PDF 가공본을 앱에 싣기 전 서울시 이용 허락을 먼저 확인할 것.
   근거·절차: docs/hanok_layer.md
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

from hanok import layers  # noqa: E402

OUT_DIR = PROJECT_ROOT / "web" / "public" / "hanok"
INDEX = OUT_DIR / "index.json"

DISCLAIMER = "공간정보는 참고용이며 지원 여부는 서울시 심의로 결정됩니다"

LAYER_META = {
    "preservation": {
        "label": "한옥보전구역",
        "source": "서울한옥포털 한옥보전구역 지정 공고",
        "source_url": "https://hanok.seoul.go.kr/",
        "license": "공공누리 제4유형",
    },
    "district": {
        "label": "지구단위계획구역(한옥 밀집)",
        "source": "서울 열린데이터광장 지구단위계획구역 (OA-21161)",
        "source_url": "https://data.seoul.go.kr/dataList/OA-21161/S/1/datasetView.do",
    },
    "registry": {
        "label": "등록한옥",
        "source": "서울 열린데이터광장 한옥등록 정보 (OA-15415)",
        "source_url": "https://data.seoul.go.kr/dataList/OA-15415/S/1/datasetView.do",
    },
}


def src_dir() -> Path:
    return Path(os.environ.get("HANOK_SRC_DIR") or Path.home() / "Downloads" / "hanok")


def _district_src(root: Path) -> Path | None:
    for cand in (root / "district", root / "district.zip"):
        if cand.exists():
            return cand
    return None


def _write(key: str, features: list[dict], extra: dict) -> dict:
    path = OUT_DIR / f"{key}.json"
    fc = {"type": "FeatureCollection", "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False, separators=(",", ":")))
    entry = {
        **LAYER_META[key],
        "file": f"/hanok/{key}.json",
        "count": len(features),
        "bbox": layers.bbox(features),
        "built": time.strftime("%Y-%m-%d"),
        **extra,
    }
    print(f"  {key:<12} feature={len(features):,}  {path.stat().st_size // 1024:,}KB")
    return entry


def _geocode_all(addrs: list[str]) -> list[dict | None]:
    import httpx  # 지오코딩 경로에서만 필요

    from redevelopment import geocode
    out: list[dict | None] = []
    with httpx.Client() as client:
        for a in addrs:
            out.append(geocode.geocode(client, a))
    geocode.save_cache()
    return out


def build_registry(csv_path: Path) -> tuple[list[dict], dict]:
    recs = layers.registry_records(layers.read_csv(csv_path))
    pts = _geocode_all([r["addr"] for r in recs])
    feats, failed, outside = [], 0, 0
    for rec, pt in zip(recs, pts):
        if not pt:
            failed += 1
        elif not layers.in_seoul(pt["lng"], pt["lat"]):
            outside += 1   # 동명 지번 오지오코딩 — 버린다
        else:
            feats.append(layers.registry_feature(rec, pt))
    return feats, {"rows": len(recs), "geocode_failed": failed, "outside_dropped": outside}


def cmd_build(args: argparse.Namespace) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    root = src_dir()
    old = json.loads(INDEX.read_text()) if INDEX.exists() else {}
    entries: dict = dict(old.get("layers") or {})
    print(f"소스 폴더: {root}")

    try:
        pres = Path(args.preservation) if args.preservation else root / "preservation.geojson"
        if pres.exists():
            feats = layers.load_preservation(json.loads(pres.read_text()),
                                             notice_date=args.notice_date,
                                             precision=args.precision)
            dates = sorted({f["properties"]["notice_date"] for f in feats})
            entries["preservation"] = _write("preservation", feats,
                                             {"notice_date": dates[-1]})
        else:
            print(f"  preservation 소스 없음 ({pres}) — 기존 유지")

        dist = Path(args.district) if args.district else _district_src(root)
        if dist and dist.exists():
            feats, rep = layers.load_districts(dist, precision=args.precision)
            print(f"     SHP {rep['shp_records']:,}건 중 한옥 밀집 {rep['matched']}건")
            if feats:
                entries["district"] = _write("district", feats, {})
            else:
                print("     ⚠ 매칭 0건 — 기존 유지 (DISTRICT_KEYWORDS / 필드명 확인)")
        else:
            print(f"  district 소스 없음 ({root / 'district'}[.zip]) — 기존 유지")

        reg = Path(args.registry) if args.registry else root / "registry.csv"
        if reg.exists():
            feats, rep = build_registry(reg)
            print("     " + "  ".join(f"{k}={v}" for k, v in rep.items()))
            if feats:
                entries["registry"] = _write("registry", feats, {})
        else:
            print(f"  registry 소스 없음 ({reg}) — 기존 유지")
    except layers.LayerError as e:
        # 좌표계·공고일 문제는 조용히 넘기면 틀린 경계가 배포된다 — 전부 중단.
        print(f"  ✋ {e}")
        sys.exit(2)

    index = {
        "note": "표시용 사본. 참고용이며 정확한 구역은 공고 원문 확인 필요. "
                "등록한옥 점은 주소 기반 대표 위치.",
        "disclaimer": DISCLAIMER,
        "updated": time.strftime("%Y-%m-%d"),
        "layers": {k: entries[k] for k in LAYER_META if k in entries},
    }
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    print(f"\n[done] 레이어 {len(index['layers'])}종 → {OUT_DIR}")


def cmd_verify(args: argparse.Namespace) -> None:
    """지원내역(실제 지원금이 나간 위치)으로 수작업 보전구역 폴리곤을 검증."""
    pres = OUT_DIR / "preservation.json"
    if not pres.exists():
        print("  보전구역 레이어가 아직 없습니다 — build 먼저.")
        sys.exit(2)
    zones = json.loads(pres.read_text())["features"]
    rows = layers.read_csv(Path(args.subsidy))
    col = layers.address_column(rows)
    addrs = [r[col] for r in rows if r.get(col)]
    pts = [(p["lng"], p["lat"]) for p in _geocode_all(addrs) if p]
    rep = layers.points_vs_zones(pts, zones)
    rate = rep["inside"] / rep["total"] * 100 if rep["total"] else 0
    print(f"  지원내역 {len(addrs):,}건 → 좌표 {rep['total']:,}  "
          f"보전구역 안 {rep['inside']:,} ({rate:.1f}%)  밖 {len(rep['outside']):,}")
    for lng, lat in rep["outside"][:20]:
        print(f"     밖: {lat:.6f},{lng:.6f}")
    if rep["outside"]:
        print("  → 밖에 찍힌 점 주변의 폴리곤 경계를 공고 도면과 다시 대조하세요 "
              "(지원 대상이 보전구역 외 한옥일 수도 있음).")


def main() -> None:
    ap = argparse.ArgumentParser(description="서울 한옥 레이어 GeoJSON 생성")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="받아 둔 소스 → web/public/hanok")
    b.add_argument("--preservation", help="보전구역 GeoJSON (기본 <src>/preservation.geojson)")
    b.add_argument("--notice-date", help="공고일 YYYY-MM-DD (feature 속성에 없을 때)")
    b.add_argument("--district", help="OA-21161 SHP 폴더/zip/.shp (기본 <src>/district[.zip])")
    b.add_argument("--registry", help="OA-15415 CSV (기본 <src>/registry.csv)")
    b.add_argument("--precision", type=int, default=6)
    b.set_defaults(func=cmd_build)
    v = sub.add_parser("verify", help="지원내역 점으로 보전구역 교차 검증")
    v.add_argument("--subsidy", required=True, help="한옥비용지원 내역 CSV")
    v.set_defaults(func=cmd_verify)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
