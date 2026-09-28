"""정비구역 SHP 적재의 기하 계층 단위 테스트 (stdlib unittest — pytest 불필요).

실행:
    cd crawler && python -m unittest tests.test_redev_geo -v

여기서 잡으려는 것은 **조용히 틀어지는 좌표**다. 투영/datum 변환이 어긋나도
예외는 나지 않고 폴리곤이 수백 m 밀린 채 지도에 그려져 사람이 보기 전엔 모른다.
특히 EPSG:5174 는 Bessel + 한국측지계1985 라 7-파라미터 Helmert 를 빠뜨리면
전국이 일제히 ~350~400m 밀린다 (그래도 '한국 안'이라 범위 검사로는 못 잡음).
"""

from __future__ import annotations

import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from redevelopment import national  # noqa: E402
from redevelopment.proj5174 import _tm_inverse, to_wgs84  # noqa: E402
from redevelopment.shapefile import (  # noqa: E402
    read_dbf,
    read_dbf_records,
    read_shapefile,
    rings_to_multipolygon,
)


class TestProj5174(unittest.TestCase):
    """EPSG:5174 → WGS84."""

    # 실데이터로 검증된 앵커 — 부산 정비구역 SHP(202608)의 bbox 모서리.
    # 변환 결과가 실제 부산 범위와 일치함을 육안·데이터로 확인한 값이라
    # 이후 수식이 바뀌면 여기서 걸린다. (docs/redev_layer_recon.md)
    ANCHORS = [
        ((378532.0, 175328.0), (128.957824, 35.061200)),   # 부산 남서
        ((407330.0, 205687.0), (129.280922, 35.329124)),   # 부산 북동
        ((200000.0, 500000.0), (127.000784, 38.002746)),   # 투영 원점
    ]

    def test_known_anchors(self):
        for (x, y), (lon, lat) in self.ANCHORS:
            got = to_wgs84(x, y)
            self.assertAlmostEqual(got[0], lon, places=5, msg=f"lon @ ({x},{y})")
            self.assertAlmostEqual(got[1], lat, places=5, msg=f"lat @ ({x},{y})")

    def test_datum_shift_is_applied(self):
        """Helmert(towgs84)를 빠뜨리면 이 테스트가 잡는다.

        한국측지계1985 → WGS84 오프셋은 국내에서 대략 300~450m.
        datum shift 를 생략하면 0m 가 되어 실패한다.
        """
        import math
        for (x, y), _ in self.ANCHORS:
            lon_w, lat_w = to_wgs84(x, y)
            lon_b, lat_b = _tm_inverse(x, y)
            dx = (lon_w - math.degrees(lon_b)) * 88_000
            dy = (lat_w - math.degrees(lat_b)) * 111_000
            shift = math.hypot(dx, dy)
            self.assertGreater(shift, 300, f"datum shift 미적용 의심 @ ({x},{y})")
            self.assertLess(shift, 450, f"datum shift 과대 @ ({x},{y})")

    def test_monotonic(self):
        """동쪽으로 갈수록 경도↑, 북쪽으로 갈수록 위도↑ (축 뒤바뀜 방지)."""
        base = to_wgs84(300000.0, 300000.0)
        east = to_wgs84(310000.0, 300000.0)
        north = to_wgs84(300000.0, 310000.0)
        self.assertGreater(east[0], base[0])
        self.assertAlmostEqual(east[1], base[1], places=2)
        self.assertGreater(north[1], base[1])

    def test_within_korea(self):
        for (x, y), _ in self.ANCHORS:
            lon, lat = to_wgs84(x, y)
            self.assertTrue(124 < lon < 132, f"경도 이상: {lon}")
            self.assertTrue(33 < lat < 39.5, f"위도 이상: {lat}")

    def test_precision_rounding(self):
        self.assertEqual(to_wgs84(378532.0, 175328.0, precision=3), (128.958, 35.061))


class TestRingsToMultiPolygon(unittest.TestCase):
    """shapefile 링 → GeoJSON MultiPolygon (외곽=시계, 구멍=반시계)."""

    # 시계방향(부호면적 <= 0) = 외곽
    OUTER = [(0.0, 0.0), (0.0, 10.0), (10.0, 10.0), (10.0, 0.0), (0.0, 0.0)]
    # 반시계 = 구멍
    HOLE = [(2.0, 2.0), (4.0, 2.0), (4.0, 4.0), (2.0, 4.0), (2.0, 2.0)]
    OUTER2 = [(20.0, 0.0), (20.0, 5.0), (25.0, 5.0), (25.0, 0.0), (20.0, 0.0)]

    def test_single_outer(self):
        mp = rings_to_multipolygon([self.OUTER])
        self.assertEqual(len(mp), 1)
        self.assertEqual(len(mp[0]), 1)

    def test_hole_attaches_to_preceding_outer(self):
        mp = rings_to_multipolygon([self.OUTER, self.HOLE])
        self.assertEqual(len(mp), 1, "구멍이 별도 폴리곤이 되면 안 된다")
        self.assertEqual(len(mp[0]), 2, "구멍이 외곽에 붙어야 한다")

    def test_multiple_outers(self):
        mp = rings_to_multipolygon([self.OUTER, self.HOLE, self.OUTER2])
        self.assertEqual(len(mp), 2)
        self.assertEqual(len(mp[0]), 2)   # 첫 외곽 + 구멍
        self.assertEqual(len(mp[1]), 1)   # 두 번째 외곽

    def test_unclosed_ring_is_closed(self):
        mp = rings_to_multipolygon([self.OUTER[:-1]])
        ring = mp[0][0]
        self.assertEqual(ring[0], ring[-1], "링이 자동 폐합되어야 한다")

    def test_degenerate_ring_dropped(self):
        self.assertEqual(rings_to_multipolygon([[(0.0, 0.0), (1.0, 1.0)]]), [])


def _make_dbf(rows: list[dict[str, str]], fields: list[tuple[str, int]],
              deleted: set[int] = frozenset()) -> bytes:
    """테스트용 최소 dBase III 파일 생성."""
    rlen = 1 + sum(fl for _, fl in fields)
    hlen = 32 + 32 * len(fields) + 1
    out = bytearray(b"\x03\x7a\x08\x15")
    out += struct.pack("<IHH", len(rows), hlen, rlen)
    out += b"\x00" * 20
    for name, fl in fields:
        out += name.encode("ascii").ljust(11, b"\0")
        out += b"C" + b"\0" * 4 + bytes([fl]) + b"\0" * 15
    out += b"\x0d"
    for i, r in enumerate(rows):
        out += b"*" if i in deleted else b" "
        for name, fl in fields:
            out += r.get(name, "").encode("euc-kr").ljust(fl, b" ")[:fl]
    return bytes(out)


class TestReadDbf(unittest.TestCase):
    FIELDS = [("ALIAS", 20), ("COL_ADM_SE", 5)]

    def _write(self, data: bytes) -> Path:
        tmp = tempfile.NamedTemporaryFile(suffix=".dbf", delete=False)
        tmp.write(data)
        tmp.close()
        self.addCleanup(lambda: Path(tmp.name).unlink(missing_ok=True))
        return Path(tmp.name)

    def test_reads_korean_and_strips(self):
        p = self._write(_make_dbf(
            [{"ALIAS": "영주1재건축정비구역", "COL_ADM_SE": "26110"}], self.FIELDS))
        rows = read_dbf(p, encoding="euc-kr")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["ALIAS"], "영주1재건축정비구역")
        self.assertEqual(rows[0]["COL_ADM_SE"], "26110")

    def test_skips_deleted_records(self):
        p = self._write(_make_dbf(
            [{"ALIAS": "A", "COL_ADM_SE": "11110"},
             {"ALIAS": "B", "COL_ADM_SE": "11110"}],
            self.FIELDS, deleted={0}))
        rows = read_dbf(p, encoding="euc-kr")
        self.assertEqual([r["ALIAS"] for r in rows], ["B"])


def _make_shp(polys: list[list[tuple[float, float]]]) -> bytes:
    """테스트용 최소 Polygon .shp 생성 — 도형마다 단일 링."""
    body = bytearray()
    for n, ring in enumerate(polys, start=1):
        xs = [x for x, _ in ring]
        ys = [y for _, y in ring]
        content = struct.pack("<i4d", 5, min(xs), min(ys), max(xs), max(ys))
        content += struct.pack("<iii", 1, len(ring), 0)  # 1 part, 시작 인덱스 0
        for x, y in ring:
            content += struct.pack("<2d", x, y)
        body += struct.pack(">ii", n, len(content) // 2) + content
    header = struct.pack(">i5ii", 9994, 0, 0, 0, 0, 0, (100 + len(body)) // 2)
    header += struct.pack("<ii4d4d", 1000, 5, 0, 0, 0, 0, 0, 0, 0, 0)
    return header + bytes(body)


def _square(x0: float) -> list[tuple[float, float]]:
    # 외곽 링은 시계방향
    return [(x0, 0.0), (x0, 1.0), (x0 + 1, 1.0), (x0 + 1, 0.0), (x0, 0.0)]


class TestReadShapefile(unittest.TestCase):
    FIELDS = [("ALIAS", 20), ("COL_ADM_SE", 5)]

    def _write_pair(self, shp: bytes, dbf: bytes) -> Path:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name)
        (d / "zone.shp").write_bytes(shp)
        (d / "zone.dbf").write_bytes(dbf)
        return d / "zone.shp"

    def test_deleted_dbf_record_keeps_shape_pairing(self):
        # 레코드 0 이 삭제 → B 의 속성은 반드시 도형 #1(x0=10)과 짝지어져야 한다
        shp = self._write_pair(
            _make_shp([_square(0.0), _square(10.0), _square(20.0)]),
            _make_dbf(
                [{"ALIAS": "A", "COL_ADM_SE": "11110"},
                 {"ALIAS": "B", "COL_ADM_SE": "26110"},
                 {"ALIAS": "C", "COL_ADM_SE": "41110"}],
                self.FIELDS, deleted={0}),
        )
        got = [(a["ALIAS"], a["COL_ADM_SE"], mp[0][0][0][0])
               for a, mp in read_shapefile(shp)]
        self.assertEqual(got, [("B", "26110", 10.0), ("C", "41110", 20.0)])

    def test_no_deletions_pairs_in_order(self):
        shp = self._write_pair(
            _make_shp([_square(0.0), _square(10.0)]),
            _make_dbf(
                [{"ALIAS": "A", "COL_ADM_SE": "11110"},
                 {"ALIAS": "B", "COL_ADM_SE": "26110"}],
                self.FIELDS),
        )
        got = [(a["ALIAS"], mp[0][0][0][0]) for a, mp in read_shapefile(shp)]
        self.assertEqual(got, [("A", 0.0), ("B", 10.0)])

def _make_shp_typed(polys: list[list[tuple[float, float]] | None], shape_type: int = 5) -> bytes:
    """테스트용 최소 .shp — 단일 링 폴리곤, None = NULL shape.

    shape_type 15(PolygonZ) 면 XY 뒤에 Z 범위·배열을 붙인다 (실제 레이아웃).
    """
    out = bytearray(100)  # 헤더 — 리더가 건너뛴다
    for i, ring in enumerate(polys):
        if ring is None:
            out += struct.pack(">ii", i + 1, 2) + struct.pack("<i", 0)
            continue
        xs, ys = [p[0] for p in ring], [p[1] for p in ring]
        body = struct.pack("<i4d", shape_type, min(xs), min(ys), max(xs), max(ys))
        body += struct.pack("<ii", 1, len(ring)) + struct.pack("<i", 0)
        for x, y in ring:
            body += struct.pack("<2d", x, y)
        if shape_type == 15:
            body += struct.pack("<2d", 0.0, 0.0) + struct.pack(f"<{len(ring)}d", *[0.0] * len(ring))
        out += struct.pack(">ii", i + 1, len(body) // 2) + body
    return bytes(out)


# 부산 정비구역 bbox 안의 작은 사각형 두 개 (EPSG:5174)
RING_A = [(380000.0, 180000.0), (380100.0, 180000.0), (380100.0, 180100.0),
          (380000.0, 180100.0), (380000.0, 180000.0)]
RING_B = [(390000.0, 190000.0), (390100.0, 190000.0), (390100.0, 190100.0),
          (390000.0, 190100.0), (390000.0, 190000.0)]


class TestShapefileAlignment(unittest.TestCase):
    """삭제된 DBF 레코드가 속성↔도형 짝을 밀어내지 않는가.

    예전 read_shapefile 은 삭제 레코드를 뺀 속성 목록과 전체 도형 목록을
    인덱스로 짝지어, 삭제 1건 뒤의 모든 구역 이름·코드가 옆 폴리곤에 붙었다.
    """
    FIELDS = [("ALIAS", 20), ("COL_ADM_SE", 5), ("MNUM", 10)]

    def _dir(self) -> Path:
        d = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(d, ignore_errors=True))
        return d

    def test_aligned_keeps_slots(self):
        d = self._dir()
        (d / "a.dbf").write_bytes(_make_dbf(
            [{"ALIAS": "A"}, {"ALIAS": "B"}, {"ALIAS": "C"}], self.FIELDS, deleted={1}))
        rows = read_dbf_records(d / "a.dbf")
        self.assertEqual([r and r["ALIAS"] for r in rows], ["A", None, "C"])

    def test_deleted_record_does_not_shift_attributes(self):
        d = self._dir()
        (d / "z.shp").write_bytes(_make_shp_typed([RING_A, RING_B]))
        (d / "z.dbf").write_bytes(_make_dbf(
            [{"ALIAS": "삭제된구역"}, {"ALIAS": "B구역"}], self.FIELDS, deleted={0}))
        out = read_shapefile(d / "z.shp")
        self.assertEqual(len(out), 1)
        attrs, mp = out[0]
        self.assertEqual(attrs["ALIAS"], "B구역")
        self.assertEqual(mp[0][0][0], [390000.0, 190000.0])  # B 의 도형이어야 한다

    def test_uppercase_extensions(self):
        d = self._dir()
        (d / "Z.SHP").write_bytes(_make_shp_typed([RING_A]))
        (d / "Z.DBF").write_bytes(_make_dbf([{"ALIAS": "A구역"}], self.FIELDS))
        out = read_shapefile(d / "Z.SHP")
        self.assertEqual([a["ALIAS"] for a, _ in out], ["A구역"])

    def test_polygon_z_is_read(self):
        d = self._dir()
        (d / "z.shp").write_bytes(_make_shp_typed([RING_A, RING_B], shape_type=15))
        (d / "z.dbf").write_bytes(_make_dbf([{"ALIAS": "A"}, {"ALIAS": "B"}], self.FIELDS))
        out = read_shapefile(d / "z.shp")
        self.assertEqual([a["ALIAS"] for a, _ in out], ["A", "B"])
        self.assertEqual(out[1][1][0][0][0], [390000.0, 190000.0])

    def test_missing_dbf_raises(self):
        d = self._dir()
        (d / "z.shp").write_bytes(_make_shp_typed([RING_A]))
        with self.assertRaises(FileNotFoundError):
            read_shapefile(d / "z.shp")

    def test_load_polygons_end_to_end(self):
        """national.load_polygons: 대문자 배포본 폴더 + 삭제 레코드 → 올바른 시도·이름."""
        root = self._dir()
        folder = root / "LSMD_CONT_UD602_5174_부산"
        folder.mkdir()
        (folder / "X.SHP").write_bytes(_make_shp_typed([RING_A, RING_B]))
        (folder / "X.DBF").write_bytes(_make_dbf(
            [{"ALIAS": "지워진구역", "COL_ADM_SE": "11110", "MNUM": "M1"},
             {"ALIAS": "광안2재건축", "COL_ADM_SE": "26500", "MNUM": "M2"}],
            self.FIELDS, deleted={0}))
        out = national.load_polygons(root)
        self.assertEqual(list(out), ["26"])            # 삭제된 서울(11) 행이 새지 않는다
        z = out["26"][0]
        self.assertEqual((z["alias"], z["mnum"]), ("광안2재건축", "M2"))
        lon, lat = z["coordinates"][0][0][0]
        self.assertEqual([lon, lat], list(to_wgs84(390000.0, 190000.0)))


class TestPointInPolygon(unittest.TestCase):
    SQUARE = [[[[0.0, 0.0], [0.0, 10.0], [10.0, 10.0], [10.0, 0.0], [0.0, 0.0]],
               [[2.0, 2.0], [4.0, 2.0], [4.0, 4.0], [2.0, 4.0], [2.0, 2.0]]]]

    def test_inside(self):
        self.assertTrue(national.contains(self.SQUARE, 8.0, 8.0))

    def test_outside(self):
        self.assertFalse(national.contains(self.SQUARE, 20.0, 20.0))

    def test_hole_is_not_inside(self):
        self.assertFalse(national.contains(self.SQUARE, 3.0, 3.0),
                         "구멍 안의 점은 포함이 아니다")


class TestCanonName(unittest.TestCase):
    def test_strips_suffixes(self):
        # 실제 매칭된 사례 (부산·경기)
        pairs = [
            ("영주1재건축정비구역", "영주1 재건축"),
            ("수진1 재개발 정비구역", "수진1"),
            ("호원2구역 재개발정비구역", "호원2구역"),
            ("범일2재개발구역", "범일2 재개발"),
        ]
        for a, b in pairs:
            self.assertEqual(national.canon_name(a), national.canon_name(b),
                             f"{a} ↔ {b} 매칭 실패")

    def test_distinct_zones_stay_distinct(self):
        self.assertNotEqual(national.canon_name("수진1 재개발 정비구역"),
                            national.canon_name("수진2 재개발 정비구역"))


class TestMerge(unittest.TestCase):
    def _poly(self, alias, x0=0.0):
        ring = [[x0, 0.0], [x0, 10.0], [x0 + 10, 10.0], [x0 + 10, 0.0], [x0, 0.0]]
        return {"alias": alias, "ntfdate": "20250101", "sggcd": "26110",
                "mnum": f"M{alias}", "coordinates": [[ring]]}

    def _biz(self, name, x, y, phase="union"):
        return {"type": "Feature",
                "properties": {"name": name, "kind": "재개발", "phase": phase,
                               "phase_raw": "조합설립인가", "sigungu": "부산진구",
                               "jibun": "어딘가 1", "area_m2": 1000,
                               "record_code": None, "loc_precision": "parcel"},
                "geometry": {"type": "Point", "coordinates": [x, y]}}

    def test_name_match_wins_and_stage_attaches(self):
        polys = [self._poly("범일2재개발구역")]
        # 점은 폴리곤 밖이지만 이름이 맞으므로 매칭돼야 한다
        fc, stat = national.merge(polys, [self._biz("범일2 재개발", 99.0, 99.0)])
        self.assertEqual(stat["by_name"], 1)
        self.assertEqual(stat["leftover_points"], 0)
        self.assertEqual(len(fc["features"]), 1)
        props = fc["features"][0]["properties"]
        self.assertEqual(props["phase"], "union")
        self.assertEqual(props["boundary_source"], "molit")
        self.assertEqual(fc["features"][0]["geometry"]["type"], "MultiPolygon")

    def test_point_in_polygon_fallback(self):
        polys = [self._poly("이름없음")]
        polys[0]["alias"] = None
        fc, stat = national.merge(polys, [self._biz("전혀 다른 이름", 5.0, 5.0)])
        self.assertEqual(stat["by_point"], 1)
        self.assertEqual(fc["features"][0]["properties"]["phase"], "union")

    def test_unmatched_polygon_is_unknown_not_guessed(self):
        fc, stat = national.merge([self._poly("어떤구역")], [])
        props = fc["features"][0]["properties"]
        self.assertEqual(props["phase"], "unknown", "단계를 추정하면 안 된다")
        self.assertIsNone(props["phase_raw"])
        self.assertEqual(props["name"], "어떤구역")

    def test_unmatched_biz_stays_a_point(self):
        """폴리곤에 못 붙은 사업장은 단계 정보를 잃지 않도록 점으로 남는다."""
        fc, stat = national.merge([self._poly("A구역")],
                                  [self._biz("전혀 다른 곳", 99.0, 99.0)])
        self.assertEqual(stat["leftover_points"], 1)
        kinds = [f["geometry"]["type"] for f in fc["features"]]
        self.assertEqual(sorted(kinds), ["MultiPolygon", "Point"])

    def test_one_polygon_takes_only_one_biz(self):
        """단계 충돌 방지 — 같은 폴리곤에 둘째 사업장은 점으로 남는다."""
        polys = [self._poly("공유구역")]
        biz = [self._biz("첫째", 5.0, 5.0, phase="union"),
               self._biz("둘째", 6.0, 6.0, phase="completed")]
        fc, stat = national.merge(polys, biz)
        self.assertEqual(stat["by_point"], 1)
        self.assertEqual(stat["leftover_points"], 1)
        poly_feats = [f for f in fc["features"]
                      if f["geometry"]["type"] == "MultiPolygon"]
        self.assertEqual(len(poly_feats), 1)
        self.assertEqual(poly_feats[0]["properties"]["phase"], "union")


if __name__ == "__main__":
    unittest.main()
