"""한옥 레이어 변환 계층 단위 테스트 (stdlib unittest).

실행:
    cd crawler && python -m unittest tests.test_hanok_layer -v

잡으려는 것: 보전구역은 지원금이 걸린 경계라 **조용히 틀어진 좌표**와
**공고일 없는 경계**가 배포되는 것이 제일 나쁘다. 둘 다 build 를 멈춰야 한다.
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from hanok import layers  # noqa: E402
from hanok.layers import LayerError  # noqa: E402
from redevelopment.proj5174 import to_wgs84  # noqa: E402

# 북촌 부근 사각형 (EPSG:4326)
BUKCHON = [[126.985, 37.580], [126.990, 37.580], [126.990, 37.585],
           [126.985, 37.585], [126.985, 37.580]]
# 같은 동네의 EPSG:5174 평면좌표 (m)
BUKCHON_5174 = [[199000, 454000], [199400, 454000], [199400, 454400],
                [199000, 454400], [199000, 454000]]


def _fc(coords, props=None, crs=None, gtype="Polygon"):
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": props or {},
         "geometry": {"type": gtype, "coordinates": [coords]}}]}
    if crs:
        gj["crs"] = {"type": "name", "properties": {"name": crs}}
    return gj


class TestNormalizeDate(unittest.TestCase):
    def test_formats(self):
        for v in ("2024-03-05", "2024.3.5", "20240305", "2024.03.05"):
            self.assertEqual(layers.normalize_date(v), "2024-03-05", v)

    def test_leap_day(self):
        self.assertEqual(layers.normalize_date("2024.2.29"), "2024-02-29")

    def test_invalid(self):
        for v in ("", None, "2024-13-01", "3월 5일", "2024/03",
                  "2024-02-31", "2023-04-31", "2023-02-29", "20240230"):
            self.assertIsNone(layers.normalize_date(v), v)


class TestPreservation(unittest.TestCase):
    def test_wgs84_polygon_becomes_multipolygon(self):
        out = layers.load_preservation(
            _fc(BUKCHON, {"name": "북촌", "notice_date": "2024.3.5", "notice_no": "제2024-1호"}))
        self.assertEqual(len(out), 1)
        f = out[0]
        self.assertEqual(f["geometry"]["type"], "MultiPolygon")
        self.assertEqual(f["geometry"]["coordinates"][0][0][0], [126.985, 37.58])
        self.assertEqual(f["properties"], {
            "layer": "preservation", "name": "북촌",
            "notice_date": "2024-03-05", "notice_no": "제2024-1호"})

    def test_notice_date_required(self):
        with self.assertRaises(LayerError):
            layers.load_preservation(_fc(BUKCHON))

    def test_notice_date_from_arg(self):
        out = layers.load_preservation(_fc(BUKCHON), notice_date="2023-11-20")
        self.assertEqual(out[0]["properties"]["notice_date"], "2023-11-20")
        self.assertEqual(out[0]["properties"]["name"], "한옥보전구역")

    def test_feature_date_beats_arg(self):
        out = layers.load_preservation(_fc(BUKCHON, {"공고일": "20240101"}),
                                       notice_date="2023-11-20")
        self.assertEqual(out[0]["properties"]["notice_date"], "2024-01-01")

    def test_projected_without_crs_rejected(self):
        # QGIS 에서 레이어 좌표계(5174) 그대로 내보낸 실수 — 무엇인지 모르니 거부
        with self.assertRaises(LayerError):
            layers.load_preservation(_fc(BUKCHON_5174), notice_date="2024-01-01")

    def test_projected_5174_is_converted_with_datum_shift(self):
        out = layers.load_preservation(
            _fc(BUKCHON_5174, crs="urn:ogc:def:crs:EPSG::5174"), notice_date="2024-01-01")
        first = out[0]["geometry"]["coordinates"][0][0][0]
        self.assertEqual(first, list(to_wgs84(199000, 454000)))

    def test_outside_seoul_rejected(self):
        swapped = [[lat, lng] for lng, lat in BUKCHON]  # 위경도 뒤바뀜
        with self.assertRaises(LayerError):
            layers.load_preservation(_fc(swapped), notice_date="2024-01-01")

    def test_non_polygon_rejected(self):
        gj = {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {},
             "geometry": {"type": "Point", "coordinates": [126.98, 37.58]}}]}
        with self.assertRaises(LayerError):
            layers.load_preservation(gj, notice_date="2024-01-01")

    def test_empty_rejected(self):
        with self.assertRaises(LayerError):
            layers.load_preservation({"type": "FeatureCollection", "features": []},
                                     notice_date="2024-01-01")


class TestMatchDistrict(unittest.TestCase):
    def test_keywords(self):
        for name in ("북촌 지구단위계획구역", "경복궁 서측 지구단위계획구역",
                     "인사동 지구단위계획", "돈화문로 지구단위계획구역",
                     "익선 지구단위계획구역", "운현궁 주변 지구단위계획구역",
                     "선잠단지 지구단위계획구역", "앵두마을 지구단위계획"):
            self.assertEqual(layers.match_district({"DGM_NM": name}), name)

    def test_non_hanok_ignored(self):
        self.assertIsNone(layers.match_district({"DGM_NM": "여의도 지구단위계획구역"}))
        self.assertIsNone(layers.match_district({}))

    def test_unknown_name_field_still_found(self):
        attrs = {"CODE": "UQ121", "LABEL_TXT": "조계사주변 지구단위계획구역"}
        self.assertEqual(layers.match_district(attrs), "조계사주변 지구단위계획구역")


def _make_shp(polys: list[list[tuple[float, float]]]) -> bytes:
    """테스트용 최소 Polygon .shp (단일 링)."""
    out = bytearray(100)  # 헤더 — 리더가 건너뛴다
    for i, ring in enumerate(polys):
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        body = struct.pack("<i4d", 5, min(xs), min(ys), max(xs), max(ys))
        body += struct.pack("<ii", 1, len(ring)) + struct.pack("<i", 0)
        for x, y in ring:
            body += struct.pack("<2d", x, y)
        out += struct.pack(">ii", i + 1, len(body) // 2) + body
    return bytes(out)


def _make_dbf(names: list[str], deleted: set[int] = frozenset()) -> bytes:
    fl = 40
    out = bytearray(b"\x03\x7a\x08\x15")
    out += struct.pack("<IHH", len(names), 32 + 32 + 1, 1 + fl)
    out += b"\x00" * 20
    out += b"DGM_NM".ljust(11, b"\0") + b"C" + b"\0" * 4 + bytes([fl]) + b"\0" * 15
    out += b"\x0d"
    for i, n in enumerate(names):
        out += b"*" if i in deleted else b" "
        out += n.encode("cp949").ljust(fl, b" ")[:fl]
    return bytes(out)


class TestLoadDistricts(unittest.TestCase):
    def _shp(self, names, deleted=frozenset()):
        d = Path(tempfile.mkdtemp())
        ring = [tuple(p) for p in BUKCHON_5174]
        (d / "UPIS.shp").write_bytes(_make_shp([ring] * len(names)))
        (d / "UPIS.dbf").write_bytes(_make_dbf(names, deleted))
        return d

    def test_filters_and_converts(self):
        d = self._shp(["북촌 지구단위계획구역", "여의도 지구단위계획구역"])
        feats, rep = layers.load_districts(d)
        self.assertEqual(rep, {"shp_records": 2, "matched": 1})
        self.assertEqual(feats[0]["properties"], {"layer": "district", "name": "북촌 지구단위계획구역"})
        first = feats[0]["geometry"]["coordinates"][0][0][0]
        self.assertEqual(first, list(to_wgs84(199000, 454000)))
        # 원본 폴더에 부산물(.cpg 등)을 남기지 않는다
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["UPIS.dbf", "UPIS.shp"])

    def test_deleted_record_keeps_alignment(self):
        # 0번 삭제 → 속성 [인사동] 과 도형 [#1] 이 짝지어져야 한다
        d = Path(tempfile.mkdtemp())
        far = [(150000, 300000), (150100, 300000), (150100, 300100), (150000, 300000)]
        near = [tuple(p) for p in BUKCHON_5174]
        (d / "a.shp").write_bytes(_make_shp([far, near]))
        (d / "a.dbf").write_bytes(_make_dbf(["북촌 삭제됨", "인사동 지구단위계획구역"], {0}))
        feats, _ = layers.load_districts(d)
        self.assertEqual(len(feats), 1)
        self.assertEqual(feats[0]["properties"]["name"], "인사동 지구단위계획구역")

    def test_zip_source(self):
        import zipfile
        d = self._shp(["익선 지구단위계획구역"])
        z = d / "district.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.write(d / "UPIS.shp", "sub/UPIS.shp")
            zf.write(d / "UPIS.dbf", "sub/UPIS.dbf")
        feats, _ = layers.load_districts(z)
        self.assertEqual(len(feats), 1)


class TestRegistryCsv(unittest.TestCase):
    def test_cp949_and_header_variants(self):
        p = Path(tempfile.mkdtemp()) / "r.csv"
        p.write_bytes(("한옥 등록번호,소재지 도로명주소,대지면적(㎡),연면적(㎡)\n"
                       "제2020-1호,서울 종로구 계동길 1,\"1,234.5\",88\n"
                       "제2020-2호,,10,5\n").encode("cp949"))
        recs = layers.registry_records(layers.read_csv(p))
        self.assertEqual(recs, [{"reg_no": "제2020-1호", "addr": "서울 종로구 계동길 1",
                                 "land_m2": 1234.5, "floor_m2": 88.0}])

    def test_missing_address_column(self):
        with self.assertRaises(LayerError):
            layers.registry_records([{"등록번호": "1"}])

    def test_feature(self):
        f = layers.registry_feature(
            {"reg_no": "", "addr": "a", "land_m2": None, "floor_m2": 10.0},
            {"lng": 126.98, "lat": 37.58, "precision": "dong"})
        self.assertEqual(f["properties"], {"layer": "registry", "reg_no": None, "addr": "a",
                                           "loc_precision": "dong", "floor_m2": 10.0})


class TestVerify(unittest.TestCase):
    def test_points_vs_zones(self):
        zones = layers.load_preservation(_fc(BUKCHON), notice_date="2024-01-01")
        rep = layers.points_vs_zones([(126.987, 37.582), (127.05, 37.5)], zones)
        self.assertEqual(rep["total"], 2)
        self.assertEqual(rep["inside"], 1)
        self.assertEqual(rep["outside"], [(127.05, 37.5)])


if __name__ == "__main__":
    unittest.main()
