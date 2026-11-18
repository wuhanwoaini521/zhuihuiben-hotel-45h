# 住回本 · 酒店 45 小时体验编排官

> 房费不可退，时间更不可退。酒店不是落脚点，是这趟旅行的目的地本身。

「住回本」解决的不是"选哪家酒店"，而是**已经定了这家酒店之后，入住 15:00 到退房 12:00 的这段 45 小时怎么过**。

它做三件事：

1. **把套餐文案拆成条件**——可用星期、加价日、有效期、儿童身高、早餐份数，全部从 `sellPoint` 原文里解析出来，并保留原句证据
2. **排一条带证据等级的时间轴**——每一格标「已核实 / 待核 / 留白」，不给 POI 编造开放时间
3. **照单核验，算给你看**——9 条确定性规则，把"到店才发现"的坑提前暴露

## 不是什么

- 不做酒店排序（那是 [住哪好 #186](https://github.com/modelstudioai/modelstudioai.github.io/issues/186) 做的事）
- 不算是多少钱（那是 [纯过日子 #179](https://github.com/modelstudioai/modelstudioai.github.io/issues/179) 做的事）
- 不做预算筛选（那是 [狗拿主意 #217](https://github.com/modelstudioai/modelstudioai.github.io/issues/217) 做的事）

我们只做决策链的最后一格：**住进去之后**。

## 45 小时怎么算

```
2026-11-27 15:00 入住 → 2026-11-29 12:00 退房 = 45.0 小时
  其中 16.0 小时是睡眠（两晚 × 8h）
  真正可安排的是 29.0 小时清醒时间 ← 产品要交代的就是这 29 小时
```

## 两份真实样例（离线可复现，不需要 Key）

**样例 A：杭州滨江世融艾美酒店 + 自助晚餐套餐 + 1.25m 儿童**

- 结果：`0 不可行 / 2 风险 / 3 待核 / 4 已核实`
- 风险一：套餐限 1.2M 以下儿童，同行 1.25m → 免票不成立，补差金额接口未返回，标待核
- 风险二：步行半径 1200m 内 **0 处**，最近的是虎跑公园，直线 2722m、约 47 分钟步行
- 时间轴：29 小时清醒里只有 3.2 小时有证据支撑，25.8 小时留白
- **结论：这家酒店在数据上给不出任何可核验的周边体验，不值得为 staycation 住两晚**

**样例 B：杭州薇花园民宿（西湖店，满觉陇）+ 无套餐**

- 结果：`0 不可行 / 0 风险 / 5 待核 / 4 已核实`
- 步行 1200m 内 3 处：少年儿童公园 196m（约 3 分钟）、虎跑公园 1136m、太子湾公园 1181m
- 时间轴：29 小时清醒里 1.2 小时已核实 + 6.0 小时待核（3 个 POI 各 2 小时）
- **结论：这是一家真正"住进去就能玩"的酒店，但 POI 开放时间接口不返回，因此全部标待核**

> A 和 B 的差别不是"推荐谁"，而是**同一套规则给出的两种事实**。
> 产品最锋利的能力是否证，不是安排。

## 快速开始

```bash
git clone https://github.com/wuhanwoaini521/zhuihuiben-hotel-45h
cd zhuihuiben-hotel-45h

# 1. 跑单测（30 例，全程不触网）
python -m unittest discover -s tests

# 2. 生成样例 A 的手册
python src/build_manual.py --hotel "杭州滨江世融艾美酒店" \
  --package-keyword "自助晚餐" --check-in 2026-11-27 --check-out 2026-11-29 \
  --child 125 --out web/emei.html

# 3. 生成样例 B 的手册
python src/build_manual.py --hotel "杭州薇花园民宿" --package-keyword none \
  --check-in 2026-11-27 --check-out 2026-11-29 --out web/xihu-bnb.html

# 4. 重新抓 fixtures（需要 flyai CLI，可选 Key）
bash scripts/fetch_fixtures.sh
```

仅依赖 Python 3.10+ 标准库，无第三方包。

## 目录

```
src/parse_package.py   sellPoint → 结构化权益 + 原句证据 + 歧义清单
src/rules.py           9 条确定性校验（R1–R9）
src/timeline.py        45 小时时间轴（贪心落位 + 显式留白）
src/render.py          单文件 HTML 入住手册
src/geo.py             haversine / 步行时长
fixtures/              真实 API 返回，锁死数据契约（离线可测）
prompts/agent-system.md  百炼智能体系统提示词
data/manual-notes.json   人工核验资料（带来源 + 日期 + 待核标记）
docs/data-boundary.md    字段级「能拿到 / 拿不到」
```

## 数据边界（写在最前面，因为它是设计前提）

飞猪 FlyAI 接口**不返回**：

- 房型、设施清单、设施营业时间
- 押金、退改政策、早餐单价
- POI 的开放时间
- `search-hotel` 的评分与点评（实测全为 null）

因此本项目**不做评分排行、不编造设施、不编造开放时间**。
拿不到的一律进「待核」，详见 [docs/data-boundary.md](docs/data-boundary.md)。

## 判定等级

| 等级 | 含义 | 用户要做什么 |
| --- | --- | --- |
| `BLOCK` 不可行 | 规则判定当前方案走不通 | 换日期 / 换套餐 |
| `WARN` 有风险 | 条件成立但有缺口或加价 | 到店前补差或调整 |
| `UNKNOWN` 待核 | 证据不足，产品拒绝下结论 | 打酒店电话 / 看订单页 |
| `OK` 已核实 | 有原句证据支撑 | 按单执行 |

## 状态

- [x] 套餐文案解析（含歧义标注）
- [x] 9 条确定性规则 + 30 例离线单测
- [x] 45 小时时间轴（贪心落位 + 留白）
- [x] 单文件 HTML 入住手册
- [ ] 百炼 Managed Agent 接入（运行时链路）
- [ ] GitHub Pages 上线手册 demo
- [ ] 多城市 fixtures（杭州已完成，待补上海 / 三亚 / 成都）
