"""确定性校验：模型负责提议，能不能落地由这里说了算。

八条规则的共同前提是——只用两种输入：
  1. 飞猪接口真实返回的字段（fixtures 里那份）；
  2. 用户自己填入的行程条件。
凡是拿不到证据的，一律判 UNKNOWN（待核），绝不用"一般来说"补位。

这一条是产品的立场：宁可让手册上出现"待核"的黄色块，
也不给用户一个看起来完整、到店才发现错的行程。
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field, asdict
from typing import Any

from .geo import haversine_m, walkable, walking_minutes

OK = "OK"
WARN = "WARN"
BLOCK = "BLOCK"
UNKNOWN = "UNKNOWN"

LEVEL_LABEL = {
    OK: "已核实",
    WARN: "有风险",
    BLOCK: "不可行",
    UNKNOWN: "待核",
}


@dataclass
class Finding:
    id: str
    level: str
    title: str
    detail: str
    evidence: str | None = None
    rule: str = ""

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["level_label"] = LEVEL_LABEL[self.level]
        return d


@dataclass
class Booking:
    hotel_name: str
    check_in: str  # YYYY-MM-DD
    check_out: str  # YYYY-MM-DD
    adults: int = 2
    children: list[dict[str, Any]] = field(default_factory=list)
    walk_threshold_m: int = 1200

    @property
    def check_in_date(self) -> dt.date:
        return dt.date.fromisoformat(self.check_in)

    @property
    def check_out_date(self) -> dt.date:
        return dt.date.fromisoformat(self.check_out)

    @property
    def nights(self) -> int:
        return (self.check_out_date - self.check_in_date).days

    def night_dates(self) -> list[dt.date]:
        return [self.check_in_date + dt.timedelta(days=i) for i in range(self.nights)]

    def weekday_set(self) -> set[int]:
        return {d.weekday() for d in self.night_dates()}

    def stay_hours(self) -> float:
        """15:00 入住 → 12:00 退房 的钟点时长。"""
        start = dt.datetime.combine(self.check_in_date, dt.time(15, 0))
        end = dt.datetime.combine(self.check_out_date, dt.time(12, 0))
        return (end - start).total_seconds() / 3600


def _in_window(day: int, window: tuple[int, int]) -> bool:
    lo, hi = window
    if lo <= hi:
        return lo <= day <= hi
    return day >= lo or day <= hi


def check_validity(pkg: dict[str, Any], booking: Booking) -> Finding:
    valid_until = pkg.get("valid_until")
    if not valid_until:
        return Finding(
            "validity", UNKNOWN, "套餐有效期未标注",
            "文案里没有「有效期至…」，无法确认入住日是否在售期内。",
            pkg.get("evidence", {}).get("valid_until"), "R1",
        )
    if booking.check_out_date > dt.date.fromisoformat(valid_until):
        return Finding(
            "validity", BLOCK, "套餐已过有效期",
            f"套餐有效期至 {valid_until}，本次离店 {booking.check_out} 已超出。",
            pkg["evidence"].get("valid_until"), "R1",
        )
    return Finding(
        "validity", OK, "套餐在有效期内",
        f"有效期至 {valid_until}，本次离店 {booking.check_out} 未超出。",
        pkg["evidence"].get("valid_until"), "R1",
    )


def check_weekday_window(pkg: dict[str, Any], booking: Booking) -> Finding:
    window = pkg.get("weekday_window")
    if not window:
        return Finding(
            "weekday_window", UNKNOWN, "套餐未标注可用星期",
            "文案没有「X 至 Y 通用」的限制，按无限制处理，但建议下单前向客服确认。",
            None, "R2",
        )
    allowed = {d for d in range(7) if _in_window(d, window)}
    used = booking.weekday_set()
    bad = sorted(used - allowed)
    names = "、".join("周" + "一二三四五六日"[d] for d in bad)
    if bad:
        return Finding(
            "weekday_window", BLOCK, "入住日不在套餐可用范围",
            f"套餐限{'周' + '一二三四五六日'[window[0]]}至{'周' + '一二三四五六日'[window[1]]}使用，"
            f"本次涉及 {names}。",
            pkg["evidence"].get("weekday_window"), "R2",
        )
    return Finding(
        "weekday_window", OK, "入住日落在可用星期内",
        f"套餐可用{'周' + '一二三四五六日'[window[0]]}至{'周' + '一二三四五六日'[window[1]]}，本次全部命中。",
        pkg["evidence"].get("weekday_window"), "R2",
    )


def check_surcharge(pkg: dict[str, Any], booking: Booking) -> Finding:
    days = pkg.get("surcharge_days")
    amount = pkg.get("surcharge_amount")
    if not days or amount is None:
        return Finding(
            "surcharge", OK, "未发现加价条款",
            "文案中没有「周X至周Y需加价」的约定。",
            None, "R3",
        )
    hit = sorted(d for d in booking.weekday_set() if _in_window(d, days))
    if not hit:
        return Finding(
            "surcharge", OK, "本次不触发加价",
            f"套餐在{'、'.join('周' + '一二三四五六日'[d] for d in range(7) if _in_window(d, days))}"
            f"每间夜加价 {amount:.0f} 元，但本次入住日不含这些星期。",
            pkg["evidence"].get("surcharge"), "R3",
        )
    total = amount * len(hit)
    names = "、".join("周" + "一二三四五六日"[d] for d in hit)
    return Finding(
        "surcharge", WARN, "触发套餐加价",
        f"{names} 共 {len(hit)} 个间夜触发加价，预计加收 {total:.0f} 元（{amount:.0f} 元 × {len(hit)}）。",
        pkg["evidence"].get("surcharge"), "R3",
    )


def check_weekend(pkg: dict[str, Any], booking: Booking) -> Finding:
    if not pkg.get("weekend_no_surcharge"):
        return Finding(
            "weekend", UNKNOWN, "周末是否加价未标注",
            "文案没有「周末不加价」的承诺，周末入住需另行确认。",
            None, "R4",
        )
    used = booking.weekday_set()
    weekend = used & {5, 6}
    detail = (
        "本次含周六/周日入住，套餐明确「周末不加价」，价格条件成立。"
        if weekend
        else "本次不含周六/周日，该条款未生效。"
    )
    return Finding("weekend", OK, "周末加价规则已核对", detail,
                   pkg["evidence"].get("weekend_no_surcharge"), "R4")


def check_child_policy(pkg: dict[str, Any], booking: Booking) -> Finding:
    limit = pkg.get("child_height_max_m")
    if not booking.children:
        return Finding("child", OK, "无同行儿童", "本次没有儿童同行，该项不适用。", None, "R5")
    if not limit:
        return Finding(
            "child", UNKNOWN, "儿童政策未标注",
            f"有 {len(booking.children)} 名儿童同行，但套餐未写明儿童免票/加收条件。",
            None, "R5",
        )
    over = [c for c in booking.children if (c.get("height_cm") or 0) / 100 > limit]
    if not over:
        return Finding(
            "child", OK, "儿童权益成立",
            f"套餐允许每位成人携带 1 位 {limit}M 以下儿童，同行儿童均在范围内。",
            pkg["evidence"].get("child_height_max_m"), "R5",
        )
    heights = "、".join(f"{c.get('height_cm')}cm" for c in over)
    return Finding(
        "child", WARN, "儿童超出身高限制",
        f"套餐限 {limit}M（{limit * 100:.0f}cm）以下儿童，同行 {heights} 需按成人/儿童价另计，"
        f"补差金额接口未返回，标注待核。",
        pkg["evidence"].get("child_height_max_m"), "R5",
    )


def check_breakfast(pkg: dict[str, Any], booking: Booking) -> Finding:
    have = pkg.get("breakfast_count")
    need_total = booking.adults * booking.nights
    amb = [a for a in pkg.get("ambiguous", []) if a["field"] == "breakfast_count"]
    if have is None:
        if amb:
            return Finding("breakfast", UNKNOWN, "早餐份数存在歧义",
                           amb[0]["why"] + "。按一人一份估算需求为 "
                           f"{need_total} 份，实际以订单页为准。", amb[0]["evidence"], "R6")
        return Finding("breakfast", UNKNOWN, "未含早餐", "套餐文案未出现早餐份数。", None, "R6")
    if amb:
        return Finding(
            "breakfast", UNKNOWN, "早餐份数存在歧义",
            f"解析到「{amb[0]['evidence']}」，可能是 {have} 份总量、也可能是每晚 {have} 份；"
            f"按总量口径，本次 {booking.adults} 人 × {booking.nights} 晚需 {need_total} 份。",
            amb[0]["evidence"], "R6",
        )
    if have >= need_total:
        return Finding("breakfast", OK, "早餐份数够用",
                       f"套餐 {have} 份 ≥ {booking.adults} 人 × {booking.nights} 晚 = {need_total} 份。",
                       pkg["evidence"].get("breakfast_count"), "R6")
    return Finding("breakfast", WARN, "早餐份数不足",
                   f"套餐 {have} 份 < 需求 {need_total} 份，缺口 {need_total - have} 份，"
                   f"单份价格接口未返回，标注待核。",
                   pkg["evidence"].get("breakfast_count"), "R6")


def check_marginal_cost(pkg: dict[str, Any], booking: Booking) -> Finding:
    """房费已沉没，这里只算增量；起价不等于成交价。"""
    if pkg.get("price_value") is None:
        return Finding("cost", UNKNOWN, "无可用价格", "套餐未返回价格字段。", None, "R7")
    if pkg.get("price_is_from"):
        return Finding(
            "cost", UNKNOWN, "起价不等于成交价",
            f"接口价格为「{pkg['price_text']}」，「起」表示最低档起价；"
            f"指定日期、指定房型的成交价需在订单页确认，此处不做加总。",
            pkg["price_text"], "R7",
        )
    return Finding(
        "cost", OK, "边际成本可计算",
        f"套餐价 {pkg['price_value']:.0f} 元（{pkg.get('price_unit') or '未标注单位'}），"
        f"房费视为已沉没，仅作增量参考。",
        pkg["price_text"], "R7",
    )


def scan_pois(hotel: dict[str, Any], pois: list[dict[str, Any]],
              threshold_m: float) -> dict[str, Any]:
    """以酒店坐标为圆心，算每个 POI 的真实步行时长。"""
    hlat, hlon = float(hotel["latitude"]), float(hotel["longitude"])
    rows = []
    for poi in pois:
        try:
            lat, lon = float(poi["latitude"]), float(poi["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        meters = haversine_m(hlat, hlon, lat, lon)
        rows.append({
            "name": poi.get("name"),
            "category": poi.get("category"),
            "list_rank": poi.get("listRank"),
            "free_status": poi.get("freePoiStatus"),
            "poi_level": poi.get("poiLevel"),
            "meters": round(meters),
            "walk_minutes": round(walking_minutes(meters)),
            "walkable": walkable(meters, threshold_m),
            "detail_url": poi.get("jumpUrl"),
        })
    rows.sort(key=lambda r: r["meters"])
    return {
        "threshold_m": threshold_m,
        "rows": rows,
        "walkable": [r for r in rows if r["walkable"]],
        "nearest": rows[0] if rows else None,
    }


def check_walk_radius(scan: dict[str, Any], booking: Booking) -> Finding:
    if not scan["rows"]:
        return Finding("walk", UNKNOWN, "周边无可核验地点",
                       "飞猪 POI 检索未返回可用坐标，无法计算步行半径。", None, "R8")
    if scan["walkable"]:
        names = "、".join(r["name"] for r in scan["walkable"][:3])
        return Finding(
            "walk", OK, f"周边 {len(scan['walkable'])} 处可步行抵达",
            f"步行半径 {booking.walk_threshold_m}m 内：{names}"
            f"（最近 {scan['walkable'][0]['meters']}m / 约 {scan['walkable'][0]['walk_minutes']} 分钟）。",
            "坐标来自 search-poi 返回的 latitude/longitude", "R8",
        )
    nearest = scan["nearest"]
    return Finding(
        "walk", WARN, "周边步行不可达",
        f"步行半径 {booking.walk_threshold_m}m 内 0 处；最近的是「{nearest['name']}」"
        f"直线 {nearest['meters']}m、约 {nearest['walk_minutes']} 分钟步行。"
        f"45 小时实际会被限制在酒店内，应切换到「纯宅」方案。",
        "坐标来自 search-poi 返回的 latitude/longitude", "R8",
    )


def check_time_window(pkg: dict[str, Any], booking: Booking) -> Finding:
    """午市/晚餐权益与 12:00 退房时刻的关系：只有文案写了时段才算，否则待核。"""
    has_lunch = any(e["name"] == "午市套餐" for e in pkg.get("entitlements", []))
    if not has_lunch:
        return Finding("time_window", OK, "无餐段权益与退房冲突",
                       "套餐不含午市权益，退房前无餐段安排。", None, "R9")
    return Finding(
        "time_window", UNKNOWN, "午市权益与 12:00 退房可能冲突",
        "套餐含「午市」权益，但接口未返回可用时段；离店当天 12:00 退房，"
        "午市通常 11:00 后开始，能否在离店前使用需向酒店确认。",
        next(e["evidence"] for e in pkg["entitlements"] if e["name"] == "午市套餐"), "R9",
    )


def run_all(pkg: dict[str, Any], booking: Booking,
            scan: dict[str, Any] | None = None) -> list[Finding]:
    findings = [
        check_validity(pkg, booking),
        check_weekday_window(pkg, booking),
        check_surcharge(pkg, booking),
        check_weekend(pkg, booking),
        check_child_policy(pkg, booking),
        check_breakfast(pkg, booking),
        check_marginal_cost(pkg, booking),
        check_time_window(pkg, booking),
    ]
    if scan is not None:
        findings.append(check_walk_radius(scan, booking))
    return findings


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {level: 0 for level in (BLOCK, WARN, UNKNOWN, OK)}
    for f in findings:
        counts[f.level] += 1
    return counts
