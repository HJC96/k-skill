import importlib.util
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "religious-facility-search" / "scripts" / "religious_facility_search.py"
SPEC = importlib.util.spec_from_file_location("religious_facility_search", MODULE_PATH)
religious_facility_search = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(religious_facility_search)


SEARCH_HTML = """
<ul class="list_place">
  <li data-cid="8010608" data-analysis="교회|located_query|강남역||Y|zone_14533">
  <li data-cid="336758453">
  <li data-cid="8010608">
  <li data-cid="14852817">
</ul>
"""

CHURCH_PANEL = {
    "summary": {
        "confirm_id": "8010608",
        "name": "영동중앙교회",
        "category": {
            "name": "교회",
            "name1": "문화,예술",
            "name2": "종교",
            "name3": "기독교",
            "name4": "교회",
        },
        "point": {"lon": 127.03798269392448, "lat": 37.49635271552635},
        "address": {
            "disp": "서울 강남구 논현로75길 9 (역삼동)",
            "road": "서울 강남구 논현로75길 9",
            "jibun": "역삼동 747-11",
        },
        "phone_numbers": [{"tel": "02-555-1234"}, {"tel": "02-555-9999", "type": "FAX"}],
        "homepages": ["http://example-church.or.kr"],
    }
}

CAFE_PANEL = {
    "summary": {
        "confirm_id": "999",
        "name": "교회다방",
        "category": {"name": "카페", "name2": "음식점", "name3": "카페", "name4": "카페"},
        "point": {"lon": 127.0, "lat": 37.5},
        "address": {"disp": "서울 어딘가"},
    }
}

CATHEDRAL_PANEL = {
    "summary": {
        "confirm_id": "10327558",
        "name": "명동대성당",
        "category": {"name": "성당", "name2": "종교", "name3": "천주교", "name4": "성당"},
        "point": {"lon": 126.9873, "lat": 37.5633},
        "address": {"disp": "서울 중구 명동길 74 (명동2가)"},
    }
}


class SearchPlaceIdsTest(unittest.TestCase):
    def test_extracts_ids_in_order_without_duplicates(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value=SEARCH_HTML):
            ids = religious_facility_search.search_place_ids("강남역 교회")

        self.assertEqual(ids, ["8010608", "336758453", "14852817"])

    def test_respects_limit(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value=SEARCH_HTML):
            ids = religious_facility_search.search_place_ids("강남역 교회", limit=2)

        self.assertEqual(ids, ["8010608", "336758453"])

    def test_empty_html_returns_no_ids(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value="<html></html>"):
            self.assertEqual(religious_facility_search.search_place_ids("없는곳"), [])


class FetchPlaceTest(unittest.TestCase):
    def test_maps_summary_fields(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value=CHURCH_PANEL):
            place = religious_facility_search.fetch_place("8010608")

        self.assertEqual(place["name"], "영동중앙교회")
        self.assertEqual(place["category"], "교회")
        self.assertEqual(place["denomination"], "기독교")
        self.assertEqual(place["category_group"], "종교")
        self.assertEqual(place["address"], "서울 강남구 논현로75길 9 (역삼동)")
        self.assertEqual(place["place_url"], "https://place.map.kakao.com/8010608")

    def test_drops_fax_numbers(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value=CHURCH_PANEL):
            place = religious_facility_search.fetch_place("8010608")

        self.assertEqual(place["phone"], "02-555-1234")

    def test_returns_none_when_summary_incomplete(self):
        with mock.patch.object(religious_facility_search, "fetch", return_value={"summary": {"name": "이름만"}}):
            self.assertIsNone(religious_facility_search.fetch_place("1"))

    def test_recoverable_upstream_error_returns_none(self):
        with mock.patch.object(religious_facility_search, "fetch", side_effect=religious_facility_search.LookupError_("HTTP 500")):
            self.assertIsNone(religious_facility_search.fetch_place("1"))


class MatchesTypeTest(unittest.TestCase):
    def test_rejects_non_religion_category_group(self):
        place = {"category_group": "음식점", "category": "카페", "denomination": "카페"}
        self.assertFalse(religious_facility_search.matches_type(place, "교회"))

    def test_accepts_church_for_church_type(self):
        place = {"category_group": "종교", "category": "교회", "denomination": "기독교"}
        self.assertTrue(religious_facility_search.matches_type(place, "교회"))

    def test_rejects_cathedral_for_church_type(self):
        place = {"category_group": "종교", "category": "성당", "denomination": "천주교"}
        self.assertFalse(religious_facility_search.matches_type(place, "교회"))

    def test_temple_aliases_share_results(self):
        place = {"category_group": "종교", "category": "사찰", "denomination": "불교"}
        self.assertTrue(religious_facility_search.matches_type(place, "절"))
        self.assertTrue(religious_facility_search.matches_type(place, "사찰"))

    def test_all_type_accepts_any_religion_facility(self):
        place = {"category_group": "종교", "category": "성당", "denomination": "천주교"}
        self.assertTrue(religious_facility_search.matches_type(place, "전체"))


class HaversineTest(unittest.TestCase):
    def test_same_point_is_zero(self):
        self.assertEqual(round(religious_facility_search.haversine_m(37.5, 127.0, 37.5, 127.0)), 0)

    def test_known_short_distance(self):
        # 위도 0.001도 ≈ 111m
        distance = religious_facility_search.haversine_m(37.500, 127.0, 37.501, 127.0)
        self.assertTrue(105 <= distance <= 116, distance)


class AnchorScoreTest(unittest.TestCase):
    def test_prefers_exact_then_prefix_then_contains(self):
        exact = religious_facility_search.anchor_score({"name": "강남역"}, "강남역")
        prefix = religious_facility_search.anchor_score({"name": "강남역사거리"}, "강남역")
        contains = religious_facility_search.anchor_score({"name": "놀숲 강남역점"}, "강남역")
        unrelated = religious_facility_search.anchor_score({"name": "교보문고 광화문점"}, "강남역")

        self.assertLess(exact, prefix)
        self.assertLess(prefix, contains)
        self.assertLess(contains, unrelated)

    def test_ignores_spacing(self):
        self.assertEqual(religious_facility_search.anchor_score({"name": "강남 역"}, "강남역"), 0)


class ResolveAnchorTest(unittest.TestCase):
    def test_picks_closest_name_match_over_search_order(self):
        panels = {
            "1": {"summary": {"name": "놀숲 강남역점", "category": {"name2": "여가시설"},
                              "point": {"lat": 37.50098, "lon": 127.02797}, "address": {"disp": "a"}}},
            "2": {"summary": {"name": "강남역사거리", "category": {"name2": "도로시설"},
                              "point": {"lat": 37.49795, "lon": 127.02764}, "address": {"disp": "b"}}},
        }
        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=["1", "2"]), \
                mock.patch.object(religious_facility_search, "fetch", side_effect=lambda url, *a, **k: panels[url.rsplit("/", 1)[1]]):
            anchor = religious_facility_search.resolve_anchor("강남역")

        self.assertEqual(anchor["name"], "강남역사거리")

    def test_returns_none_when_nothing_resolves(self):
        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=[]):
            self.assertIsNone(religious_facility_search.resolve_anchor("없는동네"))


class CollectTest(unittest.TestCase):
    def test_filters_non_religion_and_sorts_by_distance(self):
        anchor = {"name": "강남역사거리", "lat": 37.49795, "lon": 127.02764}
        panels = {"a": CHURCH_PANEL, "b": CAFE_PANEL, "c": CATHEDRAL_PANEL}

        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=["a", "b", "c"]), \
                mock.patch.object(religious_facility_search, "fetch", side_effect=lambda url, *ar, **kw: panels[url.rsplit("/", 1)[1]]):
            scanned, matched, places = religious_facility_search.collect("강남역 교회", "전체", anchor, None, 5)

        self.assertEqual(scanned, 3)
        self.assertEqual(matched, 2)
        self.assertEqual([p["name"] for p in places], ["영동중앙교회", "명동대성당"])
        self.assertLess(places[0]["distance_m"], places[1]["distance_m"])

    def test_radius_filter_drops_far_results(self):
        anchor = {"name": "강남역사거리", "lat": 37.49795, "lon": 127.02764}
        panels = {"a": CHURCH_PANEL, "c": CATHEDRAL_PANEL}

        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=["a", "c"]), \
                mock.patch.object(religious_facility_search, "fetch", side_effect=lambda url, *ar, **kw: panels[url.rsplit("/", 1)[1]]):
            _, _, places = religious_facility_search.collect("강남역 교회", "전체", anchor, 1000, 5)

        self.assertEqual([p["name"] for p in places], ["영동중앙교회"])

    def test_empty_search_raises_explicit_failure(self):
        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=[]):
            with self.assertRaises(religious_facility_search.LookupError_):
                religious_facility_search.collect("없는곳 교회", "교회", None, None, 5)


class MatchedCountTest(unittest.TestCase):
    def test_collect_reports_matched_count_not_displayed_count(self):
        anchor = {"name": "강남역사거리", "lat": 37.49795, "lon": 127.02764}
        panels = {"a": CHURCH_PANEL, "c": CATHEDRAL_PANEL}

        with mock.patch.object(religious_facility_search, "search_place_ids", return_value=["a", "c"]), \
                mock.patch.object(religious_facility_search, "fetch", side_effect=lambda url, *ar, **kw: panels[url.rsplit("/", 1)[1]]):
            _, matched, places = religious_facility_search.collect("강남역 교회", "전체", anchor, None, 1)

        self.assertEqual(matched, 2, "필터를 통과한 수는 표시 수에 잘리면 안 된다")
        self.assertEqual(len(places), 1)

    def test_report_shows_both_matched_and_displayed(self):
        places = [{"name": "영동중앙교회", "category": "교회", "denomination": "기독교",
                   "address": "서울 강남구", "distance_m": 320, "phone": None, "homepage": None,
                   "place_url": "https://place.map.kakao.com/1"}]

        report = religious_facility_search.format_report("강남역 교회", None, 15, 9, places, "교회")

        self.assertIn("종교시설 9건", report)
        self.assertIn("가까운 1건 표시", report)


class FormatReportTest(unittest.TestCase):
    def test_reports_anchor_and_worship_time_caveat(self):
        anchor = {"name": "강남역사거리", "lat": 37.49795, "lon": 127.02764}
        places = [{
            "name": "영동중앙교회", "category": "교회", "denomination": "기독교",
            "address": "서울 강남구 논현로75길 9", "distance_m": 320,
            "phone": "02-555-1234", "homepage": "http://example-church.or.kr",
            "place_url": "https://place.map.kakao.com/8010608",
        }]

        report = religious_facility_search.format_report("강남역 교회", anchor, 15, 1, places, "교회")

        self.assertIn("강남역사거리", report)
        self.assertIn("영동중앙교회", report)
        self.assertIn("약 320m", report)
        self.assertIn("예배", report)

    def test_reports_empty_result_without_inventing_places(self):
        report = religious_facility_search.format_report("없는곳 교회", None, 15, 0, [], "교회")

        self.assertIn("찾지 못했다", report)
        self.assertIn("--radius 는 결과를 좁히는 옵션", report)
        self.assertNotIn("지도 https://", report)


if __name__ == "__main__":
    unittest.main()
