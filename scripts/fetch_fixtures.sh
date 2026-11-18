#!/usr/bin/env bash
# 重新采集 fixtures：需要 `npm i -g @fly-ai/flyai-cli`
# 用法：bash scripts/fetch_fixtures.sh [城市] [入住日] [离店日]
set -euo pipefail

CITY="${1:-杭州}"
CHECKIN="${2:-2026-11-27}"
CHECKOUT="${3:-2026-11-29}"
OUT="$(cd "$(dirname "$0")/.." && pwd)/fixtures"

command -v flyai >/dev/null || { echo "缺少 flyai CLI：npm i -g @fly-ai/flyai-cli"; exit 1; }

echo "→ search-hotel（西湖片区）"
flyai search-hotel --dest-name "$CITY" --poi-name "西湖" \
  --check-in-date "$CHECKIN" --check-out-date "$CHECKOUT" > "$OUT/hotel-$CITY-xihu.json"

echo "→ search-hotel（滨江片区）"
flyai search-hotel --dest-name "$CITY" --key-words "滨江" \
  --check-in-date "$CHECKIN" --check-out-date "$CHECKOUT" > "$OUT/hotel-$CITY-binjiang.json"

echo "→ search-marriott-package"
flyai search-marriott-package --keyword "$CITY" > "$OUT/package-$CITY-marriott.json"

for cat in 公园乐园 博物馆 城市观光 文创街区 市集 温泉; do
  echo "→ search-poi $cat"
  flyai search-poi --city-name "$CITY" --category "$cat" > "$OUT/poi-$cat.json"
done

echo "→ keyword-search"
flyai keyword-search --query "$CITY 温泉 spa 度假" > "$OUT/keyword-$CITY-spa.json"

echo "完成。注意：无 FLYAI_API_KEY 时价格会脱敏为 ¥8xx。"
