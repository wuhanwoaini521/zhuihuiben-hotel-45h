"""45 小时时间轴：把"有证据的事"排进格子，排不进去就说排不进去。

时间轴上的每一格都必须带 `evidence_level`：
  已核实  —— 来自套餐原句，或用户给定条件（入住 15:00 / 退房 12:00）
  待核    —— 来自 POI 检索，但接口没有返回开放时间
  留白    —— 没有证据支撑任何安排的空档，显式留白，不硬塞

刻意不做的事：不给 POI 编造开放时间。宁可让用户看到一块"待核"，
也不要他到了门口才发现周一闭馆。

口径：45 小时里约 16 小时是睡眠（两晚 × 8 小时），
真正可安排的是 29 小时清醒时间——这个数字才是产品要交代的对象。
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from .rules import Booking

CORE = "core"
ENTITLEMENT = "entitlement"
POI = "poi"
IDLE = "idle"
SLEEP = "sleep"

LEVEL_VERIFIED = "已核实"
LEVEL_PENDING = "待核"
LEVEL_IDLE = "留白"

SLEEP_HOURS_PER_NIGHT = 8


def _slot(start: dt.datetime, end: dt.datetime, title: str, kind: str,
          evidence_level: str, note: str = "", source: str = "") -> dict[str, Any]:
    return {
        "start": start.isoformat(timespec="minutes"),
        "end": end.isoformat(timespec="minutes"),
        "start_label": start.strftime("%m-%d %H:%M"),
        "end_label": end.strftime("%H:%M"),
        "hours": round((end - start).total_seconds() / 3600, 2),
        "title": title,
        "kind": kind,
        "evidence_level": evidence_level,
        "note": note,
        "source": source,
    }


def _overlaps(a_start: dt.datetime, a_end: dt.datetime,
              b_start: dt.datetime, b_end: dt.datetime) -> bool:
    return a_start < b_end and b_start < a_end


def _gaps(occupied: list[tuple[dt.datetime, dt.datetime]],
          window_start: dt.datetime, window_end: dt.datetime
          ) -> list[tuple[dt.datetime, dt.datetime]]:
    gaps = []
    cursor = window_start
    for s, e in sorted(occupied):
        if s > cursor:
            gaps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < window_end:
        gaps.append((cursor, window_end))
    return gaps


def _place(candidates: list[dict[str, Any]],
           occupied: list[tuple[dt.datetime, dt.datetime]],
           window_start: dt.datetime, window_end: dt.datetime
           ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """贪心落位：优先放首选时间，被占就找最近的可容身空档，放不下就显式拒绝。"""
    placed, rejected = [], []
    for cand in candidates:
        dur = cand["duration"]
        start = max(cand["prefer"], window_start)
        if (start + dur <= window_end
                and not any(_overlaps(start, start + dur, s, e) for s, e in occupied)):
            occupied.append((start, start + dur))
            placed.append({**cand, "start": start, "end": start + dur})
            continue
        for gs, ge in _gaps(occupied, window_start, window_end):
            anchor = max(gs, start)
            if anchor + dur <= ge:
                occupied.append((anchor, anchor + dur))
                placed.append({**cand, "start": anchor, "end": anchor + dur})
                break
        else:
            # 首选之后放不下时，退一步往前找最近的空档（尽量贴近首选时间）。
            # 典型场景：11:00 的午市套餐撞上 11:30 退房 → 提到 10:00–11:00。
            best: tuple[dt.datetime, dt.datetime] | None = None
            for gs, ge in _gaps(occupied, window_start, window_end):
                if (ge - gs) < dur:
                    continue
                cand_end = min(ge, start)
                cand_start = cand_end - dur
                if cand_start < gs:
                    continue
                if best is None or cand_start > best[0]:
                    best = (cand_start, cand_start + dur)
            if best:
                occupied.append(best)
                placed.append({**cand, "start": best[0], "end": best[1],
                               "shifted": True})
            else:
                rejected.append(cand)
    return placed, rejected


def build(booking: Booking, pkg: dict[str, Any],
          scan: dict[str, Any] | None) -> dict[str, Any]:
    d_start = dt.datetime.combine(booking.check_in_date, dt.time(15, 0))
    checkout = dt.datetime.combine(booking.check_out_date, dt.time(12, 0))
    win_start, win_end = d_start, checkout

    occupied: list[tuple[dt.datetime, dt.datetime]] = []
    anchors: list[dict[str, Any]] = []

    # --- 固定锚点：入住 / 睡眠 / 退房 ---
    anchors.append(_slot(win_start, win_start + dt.timedelta(minutes=40),
                         "抵达与入住", CORE, LEVEL_VERIFIED,
                         "入住按行业惯例 15:00，订单页可改", "用户条件"))
    occupied.append((win_start, win_start + dt.timedelta(minutes=40)))

    for i in range(booking.nights):
        night = booking.check_in_date + dt.timedelta(days=i)
        s = dt.datetime.combine(night, dt.time(23, 0))
        e = dt.datetime.combine(night + dt.timedelta(days=1), dt.time(7, 0))
        anchors.append(_slot(s, e, "睡眠", SLEEP, LEVEL_VERIFIED,
                             f"按每晚 {SLEEP_HOURS_PER_NIGHT} 小时计", "生理常量"))
        occupied.append((s, e))

    anchors.append(_slot(checkout - dt.timedelta(minutes=30), checkout, "退房",
                         CORE, LEVEL_VERIFIED, "退房按行业惯例 12:00", "用户条件"))
    occupied.append((checkout - dt.timedelta(minutes=30), checkout))

    # --- 候选：套餐权益（有原句证据）---
    entitlements = {e["name"]: e for e in pkg.get("entitlements", [])}
    candidates: list[dict[str, Any]] = []
    d2 = d_start + dt.timedelta(days=1)

    if "早餐" in entitlements:
        breakfast_days = min(max(pkg.get("breakfast_count") or booking.nights, 1), booking.nights)
        for i in range(breakfast_days):
            day = booking.check_in_date + dt.timedelta(days=i + 1)
            candidates.append({
                "prefer": dt.datetime.combine(day, dt.time(7, 30)),
                "duration": dt.timedelta(hours=1, minutes=30),
                "title": "早餐（套餐权益）", "kind": ENTITLEMENT,
                "evidence_level": LEVEL_PENDING if pkg.get("ambiguous") else LEVEL_VERIFIED,
                "note": "早餐时段接口未返回，按 07:30–09:00 建议值排布；份数见核验项",
                "source": pkg["evidence"].get("breakfast_count", ""),
            })

    if "自助晚餐" in entitlements or "自助餐" in entitlements:
        name = "自助晚餐" if "自助晚餐" in entitlements else "自助餐"
        candidates.append({
            "prefer": d_start + dt.timedelta(hours=3, minutes=30),
            "duration": dt.timedelta(hours=2),
            "title": f"{name}（套餐权益）", "kind": ENTITLEMENT, "evidence_level": LEVEL_VERIFIED,
            "note": "开餐时段接口未返回，按 18:30–20:30 建议值排布",
            "source": entitlements[name]["evidence"],
        })

    if "欢迎饮品" in entitlements:
        candidates.append({
            "prefer": d_start + dt.timedelta(hours=1),
            "duration": dt.timedelta(minutes=45),
            "title": "欢迎饮品（套餐权益）", "kind": ENTITLEMENT, "evidence_level": LEVEL_VERIFIED,
            "note": "咖啡或鸡尾酒二选一；可用时段待核",
            "source": entitlements["欢迎饮品"]["evidence"],
        })

    if "下午茶" in entitlements:
        candidates.append({
            "prefer": dt.datetime.combine(d2.date(), dt.time(15, 0)),
            "duration": dt.timedelta(hours=1, minutes=30),
            "title": "下午茶（套餐权益）", "kind": ENTITLEMENT, "evidence_level": LEVEL_PENDING,
            "note": "可用时段与是否需预约待核", "source": entitlements["下午茶"]["evidence"],
        })

    if "午市套餐" in entitlements:
        candidates.append({
            "prefer": dt.datetime.combine(booking.check_out_date, dt.time(11, 0)),
            "duration": dt.timedelta(minutes=60),
            "title": "午市套餐（套餐权益）", "kind": ENTITLEMENT, "evidence_level": LEVEL_PENDING,
            "note": "与 12:00 退房存在时间冲突，能否离店前使用需酒店确认",
            "source": entitlements["午市套餐"]["evidence"],
        })

    # --- 候选：周边步行可达（坐标真实，开放时间待核）---
    if scan:
        for i, poi in enumerate(scan.get("walkable", [])[:3]):
            day = booking.check_in_date + dt.timedelta(days=1 if i < 2 else 2)
            prefer_hour = 9 if i % 2 == 0 else 14
            candidates.append({
                "prefer": dt.datetime.combine(day, dt.time(prefer_hour, 30)),
                "duration": dt.timedelta(hours=2),
                "title": f"步行 {poi['walk_minutes']} 分钟 · {poi['name']}",
                "kind": POI, "evidence_level": LEVEL_PENDING,
                "note": "开放时间接口未返回，出发前请在飞猪详情页核对",
                "source": poi.get("detail_url") or "",
            })

    placed, rejected = _place(candidates, occupied, win_start, win_end)

    # --- 留白：把剩下的空档显式标出来，而不是留着黑洞 ---
    idles = []
    for gs, ge in _gaps(occupied, win_start, win_end):
        if (ge - gs).total_seconds() >= 3600:
            idles.append(_slot(gs, ge, "留白 / 自由活动", IDLE, LEVEL_IDLE,
                               "没有可核验的安排，留给你自己决定"))

    all_slots = anchors + [
        _slot(p["start"], p["end"], p["title"], p["kind"], p["evidence_level"],
              p["note"], p["source"]) for p in placed
    ] + idles
    all_slots.sort(key=lambda s: s["start"])

    def hours(kind: str | None = None, levels: tuple[str, ...] | None = None,
              exclude_kind: str | None = None) -> float:
        return round(sum(s["hours"] for s in all_slots
                         if (kind is None or s["kind"] == kind)
                         and (exclude_kind is None or s["kind"] != exclude_kind)
                         and (levels is None or s["evidence_level"] in levels)), 2)

    total = round((win_end - win_start).total_seconds() / 3600, 1)
    sleep = hours(kind=SLEEP)
    scheduled = hours(levels=(LEVEL_VERIFIED, LEVEL_PENDING), exclude_kind=SLEEP)

    return {
        "window_start": win_start.isoformat(timespec="minutes"),
        "window_end": win_end.isoformat(timespec="minutes"),
        "slots": all_slots,
        "rejected": [
            {"title": c["title"],
             "why": "窗口内放不下（与已占用时段冲突且无足够空档）",
             "prefer": c["prefer"].strftime("%m-%d %H:%M")}
            for c in rejected
        ],
        "metrics": {
            "total_hours": total,
            "sleep_hours": sleep,
            "awake_hours": round(total - sleep, 1),
            "scheduled_hours": scheduled,
            "verified_hours": hours(levels=(LEVEL_VERIFIED,), exclude_kind=SLEEP),
            "pending_hours": hours(levels=(LEVEL_PENDING,)),
            "idle_hours": hours(kind=IDLE),
            "awake_idle_hours": round(total - sleep - scheduled, 1),
        },
        "unused_entitlements": [
            e["name"] for e in pkg.get("entitlements", [])
            if not any(e["name"] in s["title"] for s in all_slots)
        ],
    }
