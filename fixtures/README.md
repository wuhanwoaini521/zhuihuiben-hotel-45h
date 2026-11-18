# fixtures · 真实接口返回

本目录是项目的**数据契约**：单测与手册生成全部离线跑在这批文件上，
评委 clone 下来不需要任何 Key 就能验证结论。

## 采集信息

- 采集时间：2026-11-18
- 工具：`@fly-ai/flyai-cli`（`npm i -g @fly-ai/flyai-cli`）
- 账号态：**未配置 FLYAI_API_KEY**（试用态），因此价格被脱敏为 `¥8xx` / `¥6xx`

> 这反而成了产品的压力测试：连价格都不给的情况下，产品还能说出什么？
> 结论是——能说清"这条套餐什么条件下才能用"，而不用假装知道总价。

## 文件清单

| 文件 | 命令 | 用途 |
| --- | --- | --- |
| `hotel-hangzhou-xihu.json` | `search-hotel --dest-name 杭州 --poi-name 西湖` | 民宿类（薇花园等），样例 B |
| `hotel-hangzhou-binjiang.json` | `search-hotel --dest-name 杭州 --key-words 滨江` | 商务酒店（世融艾美等），样例 A |
| `package-hangzhou-marriott.json` | `search-marriott-package --keyword 杭州` | 套餐卖点解析，核心数据 |
| `poi-*.json` | `search-poi --city-name 杭州 --category X` | 周边步行半径（温泉/博物馆/公园乐园/城市观光/市集/文创街区） |
| `keyword-hangzhou-spa.json` | `keyword-search --query "杭州 温泉 spa 度假"` | 关键词检索对比 |

## 重新采集

```bash
bash scripts/fetch_fixtures.sh
```

有正式 Key 时价格不再脱敏，可直接覆盖本目录（注意：单测里
"起价不给总价"的断言仍然成立，因为 `￥xxx起` 的"起"字与脱敏无关）。
