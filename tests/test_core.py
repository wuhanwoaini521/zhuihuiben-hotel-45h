"""离线单测：全部用 fixtures 里的真实返回，不触网、不需要任何密钥。

运行：python -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src import rules, timeline                      # noqa: E402
from src.geo import haversine_m, walkable, walking_minutes  # noqa: E402
from src.parse_package import parse_package          # noqa: E402

FIXTURES = os.path.join(ROOT, "fixtures")


def items(name: str) -> list[dict]:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as fh:
        return (json.load(fh).get("data") or {}).get("itemList") or []


def pkg_2nights() -> dict:
    """杭州滨江AC欧轩 2 晚连住含 2 早 + 单人午市 + 周二至周四加价 200。"""
    for it in items("package-hangzhou-marriott.json"):
        if "2晚" in (it.get("title") or ""):
            return parse_package(it)
    raise AssertionError("fixture 里没有 2 晚套餐")


def pkg_dinner() -> dict:
    for it in items("package-hangzhou-marriott.json"):
        if "自助晚餐" in (it.get("title") or ""):
            return parse_package(it)
    raise AssertionError("fixture 里没有自助晚餐套餐")


class TestGeo(unittest.TestCase):
    def test_haversine_known_distance(self):
        # 世融艾美 → 虎跑公园，直测约 2.7km
        m = haversine_m(30.187956, 120.146016, 30.2036, 120.1247)
        self.assertAlmostEqual(m, 2700, delta=120)

    def test_walking_minutes_uses_detour(self):
        # 1200m 直线 × 1.3 绕行 ÷ 4.5km/h ≈ 20.8 分钟
        self.assertAlmostEqual(walking_minutes(1200), 20.8, delta=0.3)

    def test_walkable_threshold(self):
        self.assertTrue(walkable(1199, 1200))
        self.assertFalse(walkable(1201, 1200))


class TestParsePackage(unittest.TestCase):
    def setUp(self):
        self.p = pkg_2nights()

    def test_nights_and_breakfast(self):
        self.assertEqual(self.p["nights"], 2)
        self.assertEqual(self.p["breakfast_count"], 2)

    def test_breakfast_ambiguity_flagged(self):
        fields = [a["field"] for a in self.p["ambiguous"]]
        self.assertIn("breakfast_count", fields)

    def test_surcharge_days_and_amount(self):
        self.assertEqual(self.p["surcharge_days"], (1, 3))  # 周二、周四
        self.assertEqual(self.p["surcharge_amount"], 200.0)
        self.assertIn("加价", self.p["evidence"]["surcharge"])

    def test_validity(self):
        self.assertEqual(self.p["valid_until"], "2027-03-31")

    def test_no_points(self):
        self.assertTrue(self.p["no_points"])

    def test_price_is_from(self):
        self.assertTrue(self.p["price_is_from"])
        self.assertEqual(self.p["price_value"], 998.0)

    def test_entitlements_have_evidence(self):
        names = [e["name"] for e in self.p["entitlements"]]
        self.assertIn("早餐", names)
        self.assertIn("午市套餐", names)
        for e in self.p["entitlements"]:
            self.assertTrue(e["evidence"], f"{e['name']} 缺少原句证据")

    def test_child_height(self):
        self.assertEqual(pkg_dinner()["child_height_max_m"], 1.2)
        self.assertIsNone(self.p["child_height_max_m"])


def booking(check_in="2026-11-27", check_out="2026-11-29", children=None,**kw):
    return rules.Booking(
        hotel_name="杭州滨江AC欧轩",
        check_in=check_in,
        check_out=check_out,
        children=children or [],
        **kw,
    )


class TestRules(unittest.TestCase):
    def setUp(self):
        self.p = pkg_2nights()

    def find(self, findings, rule_id):
        return next(f for f in findings if f.rule == rule_id)

    def test_validity_ok(self):
        f = self.find(rules.run_all(self.p, booking()), "R1")
        self.assertEqual(f.level, rules.OK)

    def test_validity_block_when_expired(self):
        f = self.find(rules.run_all(self.p, booking("2027-05-01", "2027-05-03")), "R1")
        self.assertEqual(f.level, rules.BLOCK)

    def test_surcharge_not_triggered_on_friday(self):
        # 2026-11-27 是周五，不在「周二至周四」内
        f = self.find(rules.run_all(self.p, booking()), "R3")
        self.assertEqual(f.level, rules.OK)
        self.assertIn("不触发", f.title)

    def test_surcharge_triggered_on_tuesday(self):
        # 2026-11-24 是周二
        f = self.find(rules.run_all(self.p, booking("2026-11-24", "2026-11-26")), "R3")
        self.assertEqual(f.level, rules.WARN)
        self.assertIn("200", f.detail)

    def test_child_over_height(self):
        p = pkg_dinner()
        f = self.find(rules.run_all(p, booking(children=[{"height_cm": 125}])), "R5")
        self.assertEqual(f.level, rules.WARN)

    def test_child_policy_missing_is_pending(self):
        # 2 晚套餐没有写儿童条款，只能标待核，不能替它猜
        f = self.find(rules.run_all(self.p, booking(children=[{"height_cm": 125}])), "R5")
        self.assertEqual(f.level, rules.UNKNOWN)

    def test_child_under_height_ok(self):
        p = pkg_dinner()
        f = self.find(rules.run_all(p, booking(children=[{"height_cm": 110}])), "R5")
        self.assertEqual(f.level, rules.OK)

    def test_breakfast_ambiguous_is_pending(self):
        f = self.find(rules.run_all(self.p, booking()), "R6")
        self.assertEqual(f.level, rules.UNKNOWN)
        self.assertIn("歧义", f.title)

    def test_cost_is_from_price(self):
        f = self.find(rules.run_all(self.p, booking()), "R7")
        self.assertEqual(f.level, rules.UNKNOWN)
        self.assertIn("起价", f.detail)

    def test_stay_hours_is_45(self):
        self.assertAlmostEqual(booking().stay_hours(), 45.0)

    def test_walk_radius_zero_when_business_hotel(self):
        hotel = {"latitude": "30.187956", "longitude": "120.146016"}
        pois = [{"name": "远处景点", "latitude": "30.21776", "longitude": "120.13372"}]
        scan = rules.scan_pois(hotel, pois, 1200)
        f = self.find(rules.run_all(self.p, booking(), scan), "R8")
        self.assertEqual(f.level, rules.WARN)
        self.assertIn("步行不可达", f.title)

    def test_walk_radius_positive_case(self):
        hotel = {"latitude": "30.21776", "longitude": "120.13372"}
        pois = [{"name": "近处公园", "latitude": "30.2175", "longitude": "120.1340"}]
        scan = rules.scan_pois(hotel, pois, 1200)
        f = self.find(rules.run_all(self.p, booking(), scan), "R8")
        self.assertEqual(f.level, rules.OK)


class TestTimeline(unittest.TestCase):
    def setUp(self):
        self.p = pkg_2nights()
        self.b = booking()
        hotel = {"latitude": "30.187956", "longitude": "120.146016"}
        self.scan = rules.scan_pois(hotel, [], 1200)
        self.plan = timeline.build(self.b, self.p, self.scan)

    def test_45_hour_window(self):
        self.assertEqual(self.plan["metrics"]["total_hours"], 45.0)

    def test_sleep_is_16_hours(self):
        self.assertEqual(self.plan["metrics"]["sleep_hours"], 16.0)

    def test_no_overlapping_slots(self):
        slots = sorted(self.plan["slots"], key=lambda s: s["start"])
        for a, b in zip(slots, slots[1:]):
            self.assertLessEqual(a["end"], b["start"], f"{a['title']} 与 {b['title']} 重叠")

    def test_all_slots_inside_window(self):
        for s in self.plan["slots"]:
            self.assertGreaterEqual(s["start"], self.plan["window_start"])
            self.assertLessEqual(s["end"], self.plan["window_end"])

    def test_checkout_is_last(self):
        last = self.plan["slots"][-1]
        self.assertEqual(last["title"], "退房")
        self.assertEqual(last["end"], "2026-11-29T12:00")

    def test_verified_hours_exclude_sleep(self):
        m = self.plan["metrics"]
        self.assertLess(m["verified_hours"], 4)
        self.assertGreater(m["verified_hours"], 0)

    def test_entitlements_all_scheduled_or_reported(self):
        titles = " ".join(s["title"] for s in self.plan["slots"])
        for name in ("早餐", "午市套餐"):
            self.assertTrue(name in titles or name in self.plan["unused_entitlements"],
                            f"{name} 既没排上也没被报告为未使用")


class TestModelVsRule(unittest.TestCase):
    """模型的输出必须被规则层复核，越界的一律不采用。"""

    def test_compare_marks_agreement(self):
        from src.agent_parse import compare
        rule = {"nights": 2, "breakfast_count": 2, "surcharge_days": (1, 3),
                "surcharge_amount": 200.0, "valid_until": "2027-03-31",
                "child_height_max_m": None, "no_points": True}
        model = {"nights": 2, "breakfast_count": 2, "surcharge_days": [1, 3],
                 "surcharge_amount": 200, "valid_until": "2027-03-31",
                 "child_height_max_m": None, "no_points": True}
        verdicts = {d["field"]: d["verdict"] for d in compare(model, rule)}
        self.assertTrue(all(v == "一致" for v in verdicts.values()), verdicts)

    def test_compare_flags_hallucination(self):
        from src.agent_parse import compare
        rule = {"nights": 2, "valid_until": None}
        model = {"nights": 3, "valid_until": "2027-01-01"}
        verdicts = {d["field"]: d["verdict"] for d in compare(model, rule)}
        self.assertEqual(verdicts["nights"], "数值不一致")
        self.assertEqual(verdicts["valid_until"], "模型越界")

    def test_compare_accepts_conservative_model(self):
        from src.agent_parse import compare
        rule = {"child_height_max_m": 1.2}
        verdicts = {d["field"]: d["verdict"]
                    for d in compare({"child_height_max_m": None}, rule)}
        self.assertEqual(verdicts["child_height_max_m"], "模型更保守")


if __name__ == "__main__":
    unittest.main()
