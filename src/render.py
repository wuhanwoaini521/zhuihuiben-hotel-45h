"""生成入住手册卡片：单文件 HTML，手机全屏可读，可打印。

不引任何前端框架、不引 CDN，保证离线打开与评委截图时不会白屏。
"""
from __future__ import annotations

import html
from typing import Any

LEVEL_CLASS = {"OK": "ok", "WARN": "warn", "BLOCK": "block", "UNKNOWN": "pending"}
LEVEL_LABEL = {"OK": "已核实", "WARN": "有风险", "BLOCK": "不可行", "UNKNOWN": "待核"}

CSS = """
:root{--bg:#0f1115;--card:#171a21;--line:#252a33;--fg:#e8ecf1;--dim:#8a93a1;
--ok:#3ddc97;--warn:#ffb020;--block:#ff5c5c;--pending:#6aa8ff;--accent:#f5b949}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
line-height:1.6;-webkit-font-smoothing:antialiased}
.wrap{max-width:720px;margin:0 auto;padding:28px 20px 64px}
.brand{font-size:12px;letter-spacing:.18em;color:var(--accent);text-transform:uppercase}
h1{font-size:26px;margin:6px 0 4px;letter-spacing:-.02em}
.sub{color:var(--dim);font-size:14px}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin:22px 0 8px}
.metric{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 10px;text-align:center}
.metric b{display:block;font-size:20px;line-height:1.2}
.metric span{font-size:11px;color:var(--dim)}
section{margin-top:30px}
h2{font-size:14px;letter-spacing:.08em;color:var(--dim);text-transform:uppercase;
margin:0 0 12px;font-weight:600}
.find{background:var(--card);border:1px solid var(--line);border-left-width:3px;
border-radius:10px;padding:12px 14px;margin-bottom:8px}
.find.block{border-left-color:var(--block)}
.find.warn{border-left-color:var(--warn)}
.find.pending{border-left-color:var(--pending)}
.find.ok{border-left-color:var(--ok)}
.find .head{display:flex;justify-content:space-between;gap:10px;align-items:baseline}
.find .title{font-weight:600;font-size:15px}
.tag{font-size:11px;padding:2px 8px;border-radius:999px;white-space:nowrap}
.tag.block{background:rgba(255,92,92,.14);color:var(--block)}
.tag.warn{background:rgba(255,176,32,.14);color:var(--warn)}
.tag.pending{background:rgba(106,168,255,.14);color:var(--pending)}
.tag.ok{background:rgba(61,220,151,.14);color:var(--ok)}
.find .detail{font-size:13.5px;color:#c3cad6;margin-top:6px}
.ev{font-size:12px;color:var(--dim);margin-top:6px;padding-left:10px;
border-left:2px solid var(--line)}
.slot{display:grid;grid-template-columns:96px 1fr;gap:12px;padding:10px 0;
border-bottom:1px solid var(--line);align-items:start}
.slot .t{font-size:12px;color:var(--dim);font-variant-numeric:tabular-nums;padding-top:2px}
.slot .n{font-size:14.5px}
.slot .note{font-size:12px;color:var(--dim);margin-top:2px}
.dot{display:inline-block;width:6px;height:6px;border-radius:50%;margin-right:6px;vertical-align:middle}
.dot.verified{background:var(--ok)}
.dot.pending{background:var(--pending)}
.dot.idle{background:#3a4150}
.slot.idle .n{color:#8a93a1}
.poi{display:flex;justify-content:space-between;gap:10px;padding:8px 0;
border-bottom:1px solid var(--line);font-size:13.5px}
.poi .m{color:var(--dim);font-size:12px;white-space:nowrap}
.poi.no{color:#6c7482}
footer{margin-top:36px;padding-top:16px;border-top:1px solid var(--line);
font-size:12px;color:var(--dim)}
.kv{font-size:13.5px;color:#c3cad6}
.kv b{color:var(--fg);font-weight:600}
"""


def _e(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def _findings(findings: list[dict[str, Any]]) -> str:
    order = {"BLOCK": 0, "WARN": 1, "UNKNOWN": 2, "OK": 3}
    out = []
    for f in sorted(findings, key=lambda x: order.get(x["level"], 9)):
        cls = LEVEL_CLASS[f["level"]]
        ev = f'<div class="ev">原句：{_e(f["evidence"])}</div>' if f.get("evidence") else ""
        out.append(
            f'<div class="find {cls}"><div class="head">'
            f'<span class="title">{_e(f["title"])}</span>'
            f'<span class="tag {cls}">{_e(LEVEL_LABEL[f["level"]])} · {_e(f["rule"])}</span>'
            f'</div><div class="detail">{_e(f["detail"])}</div>{ev}</div>'
        )
    return "\n".join(out)


def _slots(slots: list[dict[str, Any]]) -> str:
    out = []
    for s in slots:
        cls = {"已核实": "verified", "待核": "pending", "留白": "idle"}.get(s["evidence_level"], "pending")
        row_cls = " idle" if cls == "idle" else ""
        note = f'<div class="note">{_e(s["note"])}</div>' if s.get("note") else ""
        out.append(
            f'<div class="slot{row_cls}"><div class="t">{_e(s["start_label"])}<br>–{_e(s["end_label"])}</div>'
            f'<div><div class="n"><span class="dot {cls}"></span>{_e(s["title"])}</div>{note}</div></div>'
        )
    return "\n".join(out)


def _pois(scan: dict[str, Any]) -> str:
    out = []
    for r in scan["rows"][:8]:
        cls = "" if r["walkable"] else " no"
        out.append(
            f'<div class="poi{cls}"><span>{_e(r["name"])}'
            f'{"　· " + _e(r["list_rank"]) if r.get("list_rank") else ""}</span>'
            f'<span class="m">{r["meters"]}m / 约 {r["walk_minutes"]} 分</span></div>'
        )
    return "\n".join(out)


def page(manual: dict[str, Any]) -> str:
    h = manual["hotel"]
    b = manual["booking"]
    pkg = manual["package"]
    m = manual["timeline"]["metrics"]
    s = manual["summary"]

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>住回本 · {_e(h['name'])} 45 小时入住手册</title>
<style>{CSS}</style></head>
<body><div class="wrap">
<div class="brand">住回本 · 45 小时入住手册</div>
<h1>{_e(h['name'])}</h1>
<div class="sub">{_e(b['check_in'])} 15:00 入住 → {_e(b['check_out'])} 12:00 退房 ·
{b['adults']} 成人{("　·　" + str(len(b['children'])) + " 名儿童") if b['children'] else ""} ·
共 {m['total_hours']} 小时</div>

<div class="metrics">
<div class="metric"><b>{s['BLOCK']}</b><span>不可行</span></div>
<div class="metric"><b>{s['WARN']}</b><span>风险</span></div>
<div class="metric"><b>{s['UNKNOWN']}</b><span>待核</span></div>
<div class="metric"><b>{m['awake_idle_hours']}</b><span>清醒留白(h)</span></div>
</div>

<section><h2>照单核验（{len(manual['findings'])} 项规则）</h2>
{_findings(manual['findings'])}
</section>

<section><h2>45 小时时间轴</h2>
<div class="kv">{m['total_hours']}h = <b>{m['sleep_hours']}h</b> 睡眠 + <b>{m['awake_hours']}h</b> 清醒；
清醒里 <b>{m['verified_hours']}h</b> 已核实 · <b>{m['pending_hours']}h</b> 待核 ·
<b>{m['awake_idle_hours']}h</b> 留白</div>
{_slots(manual['timeline']['slots'])}
</section>

<section><h2>步行半径 {b['walk_threshold_m']}m（{len(manual['scan']['walkable'])} 处可步行）</h2>
{_pois(manual['scan'])}
<div class="ev">坐标来自 search-poi 返回的 latitude / longitude；步行时长 = 直线距离 × 1.3 绕行系数 ÷ 4.5km/h。</div>
</section>

<section><h2>套餐原文</h2>
<div class="kv"><b>{_e(pkg['title'])}</b><br>{_e(pkg['price_text'])}</div>
<div class="ev">{_e(pkg['sell_point'])}</div>
</section>

<footer>
数据来源：飞猪 FlyAI（search-hotel / search-marriott-package / search-poi），
查询时间 2026-11-18，已固化在仓库 fixtures/ 下，离线可复现。<br>
边界：接口不返回房型、设施清单、设施营业时间、押金与退改政策；
POI 开放时间亦未返回，因此时间轴上所有 POI 均标注「待核」。
价格标注「起」时为起价，不是成交价。
</footer>
</div></body></html>
"""
