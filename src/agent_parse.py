"""模型解析 + 规则复核：让模型提议，让确定性解析器投票。

这是本项目"模型不许改算式"的具体实现：

1. 模型读 `title + sellPoint`，输出结构化权益 JSON（消耗 token 的那一步）
2. 正则解析器（`parse_package.py`）独立读同一段文案，输出另一份 JSON
3. 逐字段比对，差异分三类：
   - 一致
   - 模型更保守（模型给 null，规则层有值）→ 无害，记一笔
   - **模型越界**（模型凭空给出规则层没有的值）→ 直接判红，这是幻觉
4. 越界字段一律不进入手册，以规则层为准

用法：
    python -m src.agent_parse --package-keyword 自助晚餐            # 本地 Ollama
    DASHSCOPE_API_KEY=sk-xxx python -m src.agent_parse --provider bailian
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

if __package__ in (None, ""):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from src import llm  # type: ignore
    from src.build_manual import find_package  # type: ignore
    from src.parse_package import parse_package  # type: ignore
else:
    from . import llm
    from .build_manual import find_package
    from .parse_package import parse_package

FIELDS = [
    "nights",
    "breakfast_count",
    "surcharge_days",
    "surcharge_amount",
    "valid_until",
    "child_height_max_m",
    "no_points",
]

SYSTEM_PROMPT = """你是一个酒店套餐条款解析器。只做抽取，不做推断。

规则：
1. 只输出一个 JSON 对象，不要任何解释、不要 markdown 围栏。
2. 文案没写的字段一律填 null。禁止用常识补全（例如"酒店一般含早"这类推断）。
3. 数字必须是原文出现的数字，不要换算、不要估算。
4. 星期用数组表示，0=周一，6=周日。例如"周二至周四"填 [1,3]（区间两端）。
5. 无法确定时填 null，宁可 null 也不要猜。

输出字段：
nights（整数，晚数）、breakfast_count（整数，早餐份数）、
surcharge_days（数组，加价的星期区间两端）、surcharge_amount（数字，加价金额元）、
valid_until（字符串 YYYY-MM-DD）、child_height_max_m（数字，儿童身高上限米）、
no_points（布尔，是否明确不含会员积分房晚）。"""


def ask_model(title: str, sell_point: str, provider: str, model: str | None) -> dict[str, Any]:
    user = f"标题：{title}\n卖点原文：{sell_point or '（空）'}\n\n请输出 JSON。"
    raw = llm.chat(
        [{"role": "system", "content": SYSTEM_PROMPT},
         {"role": "user", "content": user}],
        provider=provider, model=model, temperature=0.0,
    )
    return {"raw": raw, "parsed": llm.extract_json(raw)}


def compare(model_out: dict[str, Any], rule_out: dict[str, Any]) -> list[dict[str, Any]]:
    diffs = []
    for field in FIELDS:
        m = model_out.get(field)
        r = rule_out.get(field)
        if isinstance(r, tuple):
            r = list(r)
        if m == r:
            verdict = "一致"
        elif m is None:
            verdict = "模型更保守"
        elif r is None:
            verdict = "模型越界"
        else:
            verdict = "数值不一致"
        diffs.append({"field": field, "model": m, "rule": r, "verdict": verdict})
    return diffs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="模型解析 vs 规则解析 一致性检查")
    ap.add_argument("--package-keyword", default="自助晚餐")
    ap.add_argument("--provider", default="ollama", choices=list(llm.PRESETS))
    ap.add_argument("--model", default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    item = find_package(args.package_keyword)
    rule_out = parse_package(item)

    print(f"provider : {args.provider}")
    print(f"套餐     : {item.get('title')}")
    print("—" * 60)

    try:
        got = ask_model(item.get("title", ""), item.get("sellPoint") or "",
                        args.provider, args.model)
    except llm.LLMError as exc:
        print(f"[模型调用失败] {exc}")
        return 2

    diffs = compare(got["parsed"], rule_out)
    print(f"{'字段':<20}{'模型':<22}{'规则':<22}判定")
    for d in diffs:
        print(f"{d['field']:<20}{str(d['model']):<22}{str(d['rule']):<22}{d['verdict']}")

    ok = sum(1 for d in diffs if d["verdict"] == "一致")
    over = [d for d in diffs if d["verdict"] == "模型越界"]
    print("—" * 60)
    print(f"一致 {ok}/{len(diffs)}；模型越界 {len(over)} 项"
          f"{'（已拒绝采用，以规则层为准）' if over else ''}")

    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump({"model_raw": got["raw"], "model": got["parsed"],
                       "rule": rule_out, "diffs": diffs}, fh,
                      ensure_ascii=False, indent=2, default=str)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
