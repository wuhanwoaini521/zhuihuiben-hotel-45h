# 数据边界 · 字段级

> 这份文档是本项目的设计前提，不是免责声明。
> 所有产品决策都是先读接口 schema 再定的，不是先想功能再补数据。

## 1. 三个接口的真实返回（2026-11-18 实测，flyai CLI v1.x）

### `search-hotel`

```
address  brandName  commissionMoneyYuan  decorationTime  detailUrl
interestsPoi  latitude  longitude  mainPic  name  price  rate  shId  star
```

- ✅ 可用：名称、星级档（舒适型/高档型/豪华型）、装修年份、地址、经纬度、详情页、收藏 ID
- ❌ 缺失：**评分、点评、房型、设施、押金、退改、早餐**
- ⚠️ 实测 `rate` 全为 null；无正式 Key 时 `price` 脱敏为 `¥8xx`
- 竞品 [#186](https://github.com/modelstudioai/modelstudioai.github.io/issues/186) 的踩坑记录第 1 条即「search-hotel 无评分」，本项目复现了同一结论

### `search-poi`

```
address  category  description  freePoiStatus  id  jumpUrl  latitude
listRank  longitude  mainPic  name  poiLevel  ticketInfo
```

- ✅ 可用：**经纬度**（步行半径可算）、分类、免费状态、榜单排名（如"浙江城市公园景点榜第1名"）、几百字 `description`、门票信息
- ❌ 缺失：**开放时间**、是否需要预约、实时人流

### `search-marriott-package`

```
benefit  commissionMoneyYuan  detailUrl  itemId  picUrl  price  rate  sellPoint  title
```

- ✅ 可用：`sellPoint` 是唯一有信息量的字段，里面埋着真正会翻车的条件：

```
【核心地段】…，【超值套餐】标准房2晚连住含2早+单人午市套餐+不含积分房晚，
【预订须知】有效期至2027年3月31日，周二至周四需加价200元
```

```
自助餐主题随时令更新，周三至周日通用 周末不加价，星厨团队 数百种美食不限量畅吃，
每位成人可携带一位1.2M以下儿童
```

- ❌ 缺失：结构化字段（全部非结构化，必须 NLP/正则解析）、套餐余量、具体房型面积
- ✅ 额外信号：`commissionMoneyYuan` 说明推广者可挂链，是商业化落点

## 2. 由此产生的三条产品禁令

| 禁令 | 原因 | 替代做法 |
| --- | --- | --- |
| 不做评分排行 / PK | 评分与点评条数拿不到 | 不做排序，改做"住进去之后" |
| 不编造设施与开放时间 | 设施清单与营业时间都不返回 | 时间轴标「待核」+ 指向飞猪详情页 |
| 不给总价 | 价格带"起"、无 Key 时脱敏 | 只给区间、缺口、待核标记 |

## 3. 证据分级（贯穿全项目）

| 等级 | 定义 | 典型来源 |
| --- | --- | --- |
| 已核实 | 接口原文可引用，或用户给定条件 | 套餐 `sellPoint` 原句、15:00/12:00 惯例 |
| 待核 | 有数据但不足以支撑结论 | POI 坐标（距离可算、开放时间未知）、起价 |
| 留白 | 无任何证据支撑 | 时间轴空档 |

模型只在"解读"环节出现（把文案翻成条件、把条件翻成人话），
所有判断数字由 `src/rules.py` 计算，模型不得改写算式。

## 4. 人工核验的入口

`data/manual-notes.json` 是唯一允许人工补录的地方，每条必须带：

```json
{
  "source": "来源名称 + URL",
  "collected_at": "YYYY-MM-DD",
  "verify_status": "待核 | 已核实",
  "note": "为什么采信 / 为什么不敢采信"
}
```

没有 `source` 和 `collected_at` 的条目一律不进入手册。
