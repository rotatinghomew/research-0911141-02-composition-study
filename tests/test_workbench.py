from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen
import json
import unittest

from composition_study.composition import benjamini_hochberg, compare, options, t_cdf, t_ppf
from composition_study.domain import explore, validate
from composition_study.service import Workbench
from composition_study.server import make_server
from composition_study.storage import fingerprint


ROOT = Path(__file__).resolve().parents[1]


class DomainTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "fixtures" / "data.json").read_text())
        self.selection = json.loads((ROOT / "product.json").read_text())["selection"]

    def test_fixture_is_valid_and_serializable(self):
        validate(self.data)
        view = explore(self.data, self.selection)
        self.assertTrue(view["rows"])
        self.assertTrue(view["notes"])
        json.dumps(view, allow_nan=False)

    def test_exploration_does_not_mutate_inputs(self):
        before = deepcopy(self.data)
        explore(self.data, self.selection)
        self.assertEqual(before, self.data)

    def test_missing_table_is_not_silently_accepted(self):
        with self.assertRaises(ValueError):
            validate({})

    def test_unknown_is_not_zero(self):
        view = explore(self.data, self.selection)
        self.assertGreater(view["summary"]["未定量单元格"], 0)
        self.assertLess(next(row for row in view["rows"] if row["component"] == "E")["quantified_n"], len(self.data["samples"]))

    def test_dilution_restores_concentration(self):
        sample = self.data["samples"][1]
        readings = [row for row in self.data["readings"] if row["sample_id"] == sample["sample_id"] and row["state"] == "measured"]
        before = explore(self.data, {"group": sample["group"]})
        sample["dilution"] *= 2
        for reading in readings:
            reading["value"] /= 2
        after = explore(self.data, {"group": sample["group"]})
        self.assertEqual(before, after)

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workbench = Workbench(ROOT, self.temporary.name)

    def test_content_addressed_import_is_idempotent(self):
        data = self.workbench.store.dataset(self.workbench.default_revision)
        uploaded = self.workbench.upload({"label": "再次导入", "data": data})
        self.assertEqual(uploaded["revision"], self.workbench.default_revision)
        self.assertEqual(len(self.workbench.store.datasets()), 1)

    def test_browser_numeric_roundtrip_preserves_fingerprint(self):
        self.assertEqual(fingerprint({"values": [1.0, 2, -0.0]}), fingerprint({"values": [1, 2.0, 0]}))

    def test_saved_description_keeps_original_dataset(self):
        saved = self.workbench.save({"title": "会议记录"})
        original = deepcopy(saved)
        data = self.workbench.store.dataset(self.workbench.default_revision)
        data["context_note"] = "新资料"
        newer = self.workbench.upload({"label": "新数据", "data": data})
        self.assertNotEqual(newer["revision"], saved["revision"])
        reopened = self.workbench.store.notebook(saved["id"])
        self.assertEqual(reopened, original)
        self.assertEqual(fingerprint(reopened["dataset"]), saved["revision"])

    def test_invalid_upload_leaves_no_dataset(self):
        with self.assertRaises(ValueError):
            self.workbench.upload({"label": "坏数据", "data": {}})
        self.assertEqual(len(self.workbench.store.datasets()), 1)

    def test_unknown_version_cannot_fall_back(self):
        with self.assertRaises(LookupError):
            self.workbench.inspect({"revision": "missing"})

    def test_blank_title_rejected(self):
        with self.assertRaises(ValueError):
            self.workbench.save({"title": " "})

    def test_saved_view_is_reproducible_after_restart(self):
        saved = self.workbench.save({"title": "重启核对"})
        restarted = Workbench(ROOT, self.temporary.name)
        self.assertEqual(saved, restarted.store.notebook(saved["id"]))


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.server = make_server(ROOT, self.temporary.name, port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temporary.cleanup()

    def test_http_explore_save_and_read(self):
        with urlopen(self.base + "/health") as response:
            self.assertEqual(json.load(response)["status"], "ok")
        request = Request(self.base + "/api/notebooks", data=json.dumps({"title": "页面保存"}).encode(),
                          headers={"Content-Type": "application/json"})
        with urlopen(request) as response:
            saved = json.load(response)
            self.assertEqual(response.status, 201)
        with urlopen(self.base + "/api/notebooks/" + str(saved["id"])) as response:
            self.assertEqual(saved, json.load(response))

    def test_bad_data_returns_client_error(self):
        request = Request(self.base + "/api/datasets", data=b'{"label":"bad","data":{}}',
                          headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError) as caught:
            urlopen(request)
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_unknown_route_is_not_static_file_access(self):
        with self.assertRaises(HTTPError) as caught:
            urlopen(self.base + "/../product.json")
        self.assertEqual(caught.exception.code, 404)
        caught.exception.close()


def synthetic(groups, with_total=True):
    """构造两成分合成数据：groups = {组名: [(x, y), ...]}，稀释倍数 1，全部定量。"""
    data = {"components": ["X", "Y"], "samples": [], "readings": [],
            "component_groups": {"pair": ["X", "Y"]}}
    for group, points in groups.items():
        for index, (x, y) in enumerate(points):
            sample_id = f"{group}_{index}"
            data["samples"].append({"sample_id": sample_id, "group": group,
                                    "batch": group + "_batch", "dilution": 1,
                                    "total": x + y if with_total else None})
            for component, value in (("X", x), ("Y", y)):
                data["readings"].append({"sample_id": sample_id, "component": component,
                                         "value": value, "state": "measured", "limit": 0})
    return data


class StatisticsTests(unittest.TestCase):
    def test_t_distribution_against_known_quantiles(self):
        self.assertAlmostEqual(t_cdf(2.228, 10), 0.975, places=3)
        self.assertAlmostEqual(t_cdf(1.96, 1000000), 0.975, places=3)
        self.assertAlmostEqual(t_ppf(0.975, 10), 2.228, places=2)

    def test_bh_controls_familywise_order(self):
        qvalues = benjamini_hochberg([0.01, 0.04, 0.5])
        self.assertAlmostEqual(qvalues[0], 0.03)
        self.assertAlmostEqual(qvalues[1], 0.06)
        self.assertAlmostEqual(qvalues[2], 0.5)


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.data = json.loads((ROOT / "fixtures" / "data.json").read_text())
        self.scheme = {"group_a": "base", "group_b": "revised",
                       "components": ["A", "B", "C", "D", "E"], "below_limit": "pairwise"}

    def test_fixture_compare_is_serializable_and_structural(self):
        view = compare(self.data, self.scheme)
        json.dumps(view, allow_nan=False)
        structural = {item["component"] for item in view["structural"]}
        self.assertIn("E", structural)
        self.assertNotIn("E", [row["component"] for row in view["contrasts"]])
        self.assertTrue(view["limitations"])
        self.assertTrue(view["notes"])

    def test_overall_change_does_not_fabricate_composition_differences(self):
        data = synthetic({"g1": [(10, 20), (11, 19), (9, 21)],
                          "g2": [(20, 40), (22, 38), (18, 42)]})
        view = compare(data, {"group_a": "g1", "group_b": "g2", "components": ["X", "Y"]})
        level = next(row for row in view["level"] if row["kind"] == "independent_total")
        self.assertAlmostEqual(level["fold"], 0.5, places=6)  # 基准组总量为对比组的一半
        for row in view["contrasts"]:
            self.assertAlmostEqual(row["effect_log"], 0.0, places=9)
            self.assertGreater(row["q"], 0.05)

    def test_composition_change_does_not_fabricate_level_difference(self):
        data = synthetic({"g1": [(10, 20), (11, 19), (9, 21)],
                          "g2": [(20, 10), (19, 11), (21, 9)]})
        view = compare(data, {"group_a": "g1", "group_b": "g2", "components": ["X", "Y"]})
        level = next(row for row in view["level"] if row["kind"] == "independent_total")
        self.assertAlmostEqual(level["effect_log"], 0.0, places=9)
        row = next(row for row in view["contrasts"] if row["component"] == "X")
        self.assertAlmostEqual(row["fold"], 0.5, delta=0.01)  # X 相对份额减半
        self.assertLess(row["q"], 0.05)

    def test_below_limit_scenarios_change_comparability(self):
        scheme = {"group_a": "base", "group_b": "pilot",
                  "components": ["A", "B", "C", "D", "E"], "below_limit": "pairwise"}
        pairwise = compare(self.data, scheme)
        half = compare(self.data, {**scheme, "below_limit": "half_limit"})
        a_pairwise = next(row for row in pairwise["contrasts"] if row["component"] == "A")
        a_half = next(row for row in half["contrasts"] if row["component"] == "A")
        self.assertLess(a_pairwise["n_b"], a_half["n_b"])
        sensitivity = {row["target"]: row for row in pairwise["sensitivity"]}
        self.assertIn("假设", sensitivity["成分:A"]["stability"])

    def test_effect_is_antisymmetric_in_group_order(self):
        forward = compare(self.data, self.scheme)
        backward = compare(self.data, {**self.scheme, "group_a": "revised", "group_b": "base"})
        for left, right in zip(forward["contrasts"], backward["contrasts"]):
            self.assertAlmostEqual(left["effect_log"], -right["effect_log"], places=9)

    def test_scheme_validation_rejects_bad_input(self):
        with self.assertRaises(ValueError):
            compare(self.data, {"group_a": "base", "group_b": "base", "components": ["A", "B"]})
        with self.assertRaises(ValueError):
            compare(self.data, {"group_a": "base", "group_b": "revised", "components": ["A"]})
        with self.assertRaises(ValueError):
            compare(self.data, {"group_a": "base", "group_b": "revised", "components": ["A", "ZZ"]})
        with self.assertRaises(ValueError):
            compare(self.data, {"group_a": "base", "group_b": "revised",
                                "components": ["A", "B"], "below_limit": "fill_zero"})

    def test_compare_does_not_mutate_inputs(self):
        before = deepcopy(self.data)
        compare(self.data, self.scheme)
        self.assertEqual(before, self.data)

    def test_options_reflect_dataset(self):
        found = options(self.data)
        self.assertIn("pilot", found["groups"])
        self.assertEqual(found["components"], ["A", "B", "C", "D", "E"])
        self.assertIn("pairwise", found["scenarios"])


class ComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workbench = Workbench(ROOT, self.temporary.name)
        self.scheme = {"group_a": "base", "group_b": "revised",
                       "components": ["A", "B", "C", "D", "E"], "below_limit": "pairwise"}

    def test_saved_comparison_explains_scheme_and_survives_restart(self):
        saved = self.workbench.save_comparison({"title": "基线对比", "scheme": self.scheme})
        self.assertEqual(saved["scheme"], self.scheme)
        for key in ["limitations", "notes", "contrasts", "sensitivity"]:
            self.assertIn(key, saved["result"]["view"])
        restarted = Workbench(ROOT, self.temporary.name)
        self.assertEqual(saved, restarted.store.comparison(saved["id"]))

    def test_rerun_on_new_data_keeps_saved_result(self):
        saved = self.workbench.save_comparison({"title": "留档对比", "scheme": self.scheme})
        data = deepcopy(self.workbench.store.dataset(self.workbench.default_revision))
        data["samples"][0]["dilution"] = 2.0
        newer = self.workbench.upload({"label": "新数据", "data": data})["revision"]
        rerun = self.workbench.compare({"revision": newer, "scheme": saved["scheme"]})
        self.assertEqual(rerun["revision"], newer)
        self.assertNotEqual(rerun["data_sha256"], saved["result"]["data_sha256"])
        self.assertEqual(self.workbench.store.comparison(saved["id"]), saved)

    def test_blank_comparison_title_rejected(self):
        with self.assertRaises(ValueError):
            self.workbench.save_comparison({"title": " ", "scheme": self.scheme})

    def test_unknown_revision_cannot_compare(self):
        with self.assertRaises(LookupError):
            self.workbench.compare({"revision": "missing", "scheme": self.scheme})


class ComparisonHttpTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.server = make_server(ROOT, self.temporary.name, port=0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.scheme = {"group_a": "base", "group_b": "revised",
                       "components": ["A", "B", "C", "D", "E"], "below_limit": "pairwise"}

    def tearDown(self):
        self.server.shutdown()
        self.thread.join()
        self.server.server_close()
        self.temporary.cleanup()

    def post(self, path, payload):
        request = Request(self.base + path, data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json"})
        return urlopen(request)

    def test_compare_options_and_run(self):
        with urlopen(self.base + "/api/compare/options") as response:
            found = json.load(response)
            self.assertIn("pilot", found["groups"])
        with self.post("/api/compare", {"scheme": self.scheme}) as response:
            result = json.load(response)
            self.assertEqual(result["scheme"], self.scheme)
            self.assertTrue(result["view"]["contrasts"])

    def test_bad_scheme_returns_client_error(self):
        with self.assertRaises(HTTPError) as caught:
            self.post("/api/compare", {"scheme": {"group_a": "base", "group_b": "base",
                                                  "components": ["A", "B"]}})
        self.assertEqual(caught.exception.code, 400)
        caught.exception.close()

    def test_save_and_read_comparison(self):
        with self.post("/api/comparisons", {"title": "页面比较", "scheme": self.scheme}) as response:
            saved = json.load(response)
            self.assertEqual(response.status, 201)
        with urlopen(self.base + "/api/comparisons") as response:
            self.assertEqual(json.load(response)[0]["id"], saved["id"])
        with urlopen(self.base + "/api/comparisons/" + str(saved["id"])) as response:
            self.assertEqual(json.load(response), saved)


if __name__ == "__main__":
    unittest.main()
