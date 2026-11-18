"""把 fixtures 组装成一份入住手册（离线可复现，不需要任何密钥）。

用法：
  python -m src.build_manual --hotel 杭州滨江世融艾美酒店 \
      --package-keyword 自助晚餐 --check-in 2026-11-27 --check-out 2026-11-29 \
      --child 125 --out web/emei.html
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import render, rules, timeline  # type: ignore
    from src.parse_package import parse_package  # type: ignore
else:
    from . import render, rules, timeline
    from .parse_package import parse_package

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "fixtures")


def _load(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _items(path: str) -> list[dict[str, Any]]:
    return (_load(path).get("data") or {}).get("itemList") or []


def find_hotel(name: str) -> dict[str, Any]:
    for path in glob.glob(os.path.join(FIXTURES, "hotel-*.json")):
        for item in _items(path):
            if name in (item.get("name") or ""):
                return item
    raise SystemExit(f"fixtures 里没有找到酒店：{name}")


def find_package(keyword: str | None) -> dict[str, Any]:
    if keyword and keyword.lower() == "none":
        # 无套餐场景（例如民宿、单体酒店）：只核验酒店与周边
        return {"title": "无套餐（仅房价）", "sellPoint": "", "price": ""}
    path = os.path.join(FIXTURES, "package-hangzhou-marriott.json")
    items = _items(path)
    if not keyword:
        return items[0]
    for item in items:
        if keyword in (item.get("title") or "") or keyword in (item.get("sellPoint") or ""):
            return item
    raise SystemExit(f"fixtures 里没有匹配「{keyword}」的套餐")


def load_pois() -> list[dict[str, Any]]:
    pois: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in sorted(glob.glob(os.path.join(FIXTURES, "poi-*.json"))):
        for item in _items(path):
            key = item.get("id") or item.get("name")
            if key in seen:
                continue
            seen.add(key)
            pois.append(item)
    return pois


def build(hotel_name: str, package_keyword: str | None, check_in: str, check_out: str,
          adults: int, children: list[dict[str, Any]],
          walk_threshold_m: int) -> dict[str, Any]:
    hotel = find_hotel(hotel_name)
    pkg_raw = find_package(package_keyword)
    pkg = parse_package(pkg_raw)
    booking = rules.Booking(
        hotel_name=hotel["name"],
        check_in=check_in,
        check_out=check_out,
        adults=adults,
        children=children,
        walk_threshold_m=walk_threshold_m,
    )
    scan = rules.scan_pois(hotel, load_pois(), walk_threshold_m)
    findings = rules.run_all(pkg, booking, scan)
    plan = timeline.build(booking, pkg, scan)
    return {
        "hotel": {
            "name": hotel.get("name"),
            "star": hotel.get("star"),
            "address": hotel.get("address"),
            "decoration_time": hotel.get("decorationTime"),
            "latitude": hotel.get("latitude"),
            "longitude": hotel.get("longitude"),
            "detail_url": hotel.get("detailUrl"),
            "price_text": hotel.get("price"),
        },
        "package": pkg,
        "booking": {
            "hotel_name": booking.hotel_name,
            "check_in": booking.check_in,
            "check_out": booking.check_out,
            "adults": booking.adults,
            "children": booking.children,
            "nights": booking.nights,
            "stay_hours": booking.stay_hours(),
            "walk_threshold_m": booking.walk_threshold_m,
        },
        "findings": [f.to_dict() for f in findings],
        "summary": rules.summarize(findings),
        "scan": scan,
        "timeline": plan,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="住回本 · 45 小时入住手册生成器")
    ap.add_argument("--hotel", required=True)
    ap.add_argument("--package-keyword", default=None)
    ap.add_argument("--check-in", required=True)
    ap.add_argument("--check-out", required=True)
    ap.add_argument("--adults", type=int, default=2)
    ap.add_argument("--child", type=int, action="append", default=None,
                    help="儿童身高（cm），可重复传多次")
    ap.add_argument("--walk-threshold", type=int, default=1200,
                    help="步行半径阈值（米），默认 1200")
    ap.add_argument("--out", default="web/index.html")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    children = [{"height_cm": h} for h in (args.child or [])]
    manual = build(args.hotel, args.package_keyword, args.check_in, args.check_out,
                   args.adults, children, args.walk_threshold)

    out_path = args.out if os.path.isabs(args.out) else os.path.join(ROOT, args.out)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(render.page(manual))
    if args.json_out:
        json_path = args.json_out if os.path.isabs(args.json_out) else os.path.join(ROOT, args.json_out)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(manual, fh, ensure_ascii=False, indent=2)

    s = manual["summary"]
    m = manual["timeline"]["metrics"]
    print(f"酒店：{manual['hotel']['name']}")
    print(f"套餐：{manual['package']['title']}")
    print(f"结论：{s['BLOCK']} 不可行 / {s['WARN']} 风险 / {s['UNKNOWN']} 待核 / {s['OK']} 已核实")
    print(f"时间轴：{m['total_hours']}h = 睡眠 {m['sleep_hours']}h + 清醒 {m['awake_hours']}h；"
          f"清醒内 已核实 {m['verified_hours']}h / 待核 {m['pending_hours']}h / 留白 {m['awake_idle_hours']}h")
    print(f"输出：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
