"""把酒店套餐的营销文案（sellPoint）解析成结构化权益。

为什么这是核心：`search-marriott-package` 返回的唯一"有信息量"的字段就是
`sellPoint`，而里面埋着真正会让人到店翻车的条件——可用星期、加价日、
有效期、儿童身高、早餐份数。这些条件在标题里看不到，在价格里看不到，
只在文案的【预订须知】段落里。

因此本模块遵守两条硬规矩：
1. 每个抽出来的字段都必须带回原句证据（evidence），没有证据就不算数。
2. 有歧义就不猜，写进 `ambiguous`，交给规则层标记为「待核」。
"""
from __future__ import annotations

import re
from typing import Any

WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_INDEX = {name: i for i, name in enumerate(WEEKDAY_CN)}

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8}

# 权益关键词 → 展示名。命中即记录原句，不做金额推断。
ENTITLEMENT_KEYWORDS = [
    ("早餐", "早餐"),
    ("双早", "早餐"),
    ("迷你吧", "迷你吧"),
    ("咖啡或鸡尾酒", "欢迎饮品"),
    ("饮品二选一", "欢迎饮品"),
    ("午市", "午市套餐"),
    ("自助晚餐", "自助晚餐"),
    ("下午茶", "下午茶"),
    ("自助餐", "自助餐"),
    ("SPA", "SPA"),
    ("温泉", "温泉"),
]


def _sentence_around(text: str, start: int, end: int) -> str:
    """取命中位置所在的分句（按中文标点切），作为原句证据。"""
    left = 0
    for i in range(start - 1, -1, -1):
        if text[i] in "，。；;,【】：":
            left = i + 1
            break
    right = len(text)
    for i in range(end, len(text)):
        if text[i] in "，。；;,【】":
            right = i
            break
    return text[left:right].strip()


def _parse_cn_count(token: str) -> int | None:
    """'2' / '两' / '双' 这类数量词转 int。"""
    if token.isdigit():
        return int(token)
    if token in _CN_NUM:
        return _CN_NUM[token]
    return None


def _find(pattern: str, text: str) -> re.Match | None:
    return re.search(pattern, text)


def parse_package(item: dict[str, Any]) -> dict[str, Any]:
    """解析一条 search-marriott-package 返回项。"""
    title = (item.get("title") or "").strip()
    sell_point = (item.get("sellPoint") or "").strip()
    blob = f"{title}。{sell_point}" if sell_point else title

    evidence: dict[str, str] = {}
    ambiguous: list[dict[str, str]] = []

    # --- 价格 ---
    price_text = (item.get("price") or "").strip()
    price_value = None
    price_is_from = "起" in price_text
    m = re.search(r"(\d+(?:\.\d+)?)", price_text.replace(",", ""))
    if m:
        price_value = float(m.group(1))
    price_unit = price_text.split("/", 1)[1] if "/" in price_text else None

    # --- 晚数 ---
    nights = None
    m = _find(r"(\d+|[一两二三四五六七])\s*晚", blob)
    if m:
        nights = _parse_cn_count(m.group(1))
        evidence["nights"] = _sentence_around(blob, m.start(), m.end())

    # --- 早餐份数 ---
    breakfast_count = None
    m = _find(r"含\s*(双|(\d+|[一两二三四五六七]))\s*早", blob)
    if m:
        token = m.group(1)
        breakfast_count = 2 if token == "双" else _parse_cn_count(token)
        evidence["breakfast_count"] = _sentence_around(blob, m.start(), m.end())
        # 多晚套餐里「含2早」既可能是总量也可能是每晚，必须标歧义。
        if nights and nights > 1:
            ambiguous.append(
                {
                    "field": "breakfast_count",
                    "why": f"套餐为 {nights} 晚，「{m.group(0)}」未说明是总量还是每晚份数",
                    "evidence": evidence["breakfast_count"],
                }
            )
    elif "含早" in blob:
        breakfast_count = None
        ambiguous.append(
            {
                "field": "breakfast_count",
                "why": "文案只写了「含早」，份数未知",
                "evidence": _sentence_around(blob, blob.index("含早"), blob.index("含早") + 2),
            }
        )

    # --- 可用星期窗口 ---
    weekday_window = None
    m = _find(r"(周[一二三四五六日])\s*至\s*(周[一二三四五六日])\s*(通用|可用)", blob)
    if m:
        weekday_window = (WEEKDAY_INDEX[m.group(1)], WEEKDAY_INDEX[m.group(2)])
        evidence["weekday_window"] = _sentence_around(blob, m.start(), m.end())

    # --- 加价日与金额 ---
    surcharge_days = None
    surcharge_amount = None
    m = _find(
        r"(周[一二三四五六日])\s*至\s*(周[一二三四五六日])\s*(?:需|要)?加价\s*(\d+(?:\.\d+)?)\s*元",
        blob,
    )
    if m:
        surcharge_days = (WEEKDAY_INDEX[m.group(1)], WEEKDAY_INDEX[m.group(2)])
        surcharge_amount = float(m.group(3))
        evidence["surcharge"] = _sentence_around(blob, m.start(), m.end())

    # --- 周末不加价 ---
    weekend_no_surcharge = True if "周末不加价" in blob else None
    if weekend_no_surcharge:
        idx = blob.index("周末不加价")
        evidence["weekend_no_surcharge"] = _sentence_around(blob, idx, idx + 5)

    # --- 有效期 ---
    valid_until = None
    m = _find(r"有效期至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", blob)
    if m:
        valid_until = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        evidence["valid_until"] = _sentence_around(blob, m.start(), m.end())

    # --- 儿童身高 ---
    child_height_max_m = None
    m = _find(r"(\d(?:\.\d+)?)\s*M\s*以下", blob)
    if m:
        child_height_max_m = float(m.group(1))
        evidence["child_height_max_m"] = _sentence_around(blob, m.start(), m.end())

    # --- 会员积分房晚 ---
    no_points = "不含积分房晚" in blob or "不含万豪积分房晚" in blob
    if no_points:
        idx = blob.index("不含")
        evidence["no_points"] = _sentence_around(blob, idx, idx + 6)

    # --- 权益清单 ---
    entitlements: list[dict[str, str]] = []
    seen: set[str] = set()
    for kw, display in ENTITLEMENT_KEYWORDS:
        if kw in blob and display not in seen:
            idx = blob.index(kw)
            entitlements.append(
                {
                    "name": display,
                    "keyword": kw,
                    "evidence": _sentence_around(blob, idx, idx + len(kw)),
                }
            )
            seen.add(display)

    # 「含早 / 含2早 / 含双早」不会命中关键词「早餐」，单独补一条权益。
    if "早餐" not in seen and ("含早" in blob or breakfast_count is not None):
        ev = evidence.get("breakfast_count") or _sentence_around(
            blob, blob.index("含早"), blob.index("含早") + 2)
        entitlements.append({"name": "早餐", "keyword": "含早", "evidence": ev})
        seen.add("早餐")

    return {
        "title": title,
        "item_id": item.get("itemId"),
        "detail_url": item.get("detailUrl"),
        "sell_point": sell_point,
        "price_text": price_text,
        "price_value": price_value,
        "price_is_from": price_is_from,
        "price_unit": price_unit,
        "nights": nights,
        "breakfast_count": breakfast_count,
        "weekday_window": weekday_window,
        "surcharge_days": surcharge_days,
        "surcharge_amount": surcharge_amount,
        "weekend_no_surcharge": weekend_no_surcharge,
        "valid_until": valid_until,
        "child_height_max_m": child_height_max_m,
        "no_points": no_points,
        "entitlements": entitlements,
        "ambiguous": ambiguous,
        "evidence": evidence,
        # 解析层从不假装完整：哪些关键字段没解析出来，明确列出来。
        "missing": [
            f
            for f, v in (
                ("nights", nights),
                ("breakfast_count", breakfast_count),
                ("valid_until", valid_until),
            )
            if v is None
        ],
    }
