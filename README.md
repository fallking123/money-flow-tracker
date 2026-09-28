# money-flow-tracker

美國運彩資金流向追蹤（個人、低頻使用）。

## 追蹤的運動

| 資料夾 | 運動 | 開賽前多久開始記錄 |
|---|---|---|
| `mlb` | MLB 美國職棒 | 48 小時 |
| `nfl` | NFL 美式足球 | 7 天 |
| `ncaaf` | NCAAF 大學美式足球（暫停：台彩沒有開賣） | 7 天 |
| `nba` | NBA 美國職籃 | 48 小時 |
| `nhl` | NHL 美國冰球 | 48 小時 |
| `ncaab` | NCAAB 大學籃球（暫停：台彩沒有開賣） | 48 小時 |

休賽期的運動會自動略過，開季後自動開始記錄。
暫停的項目在 `sports_common.py` 的 `SPORTS` 設定裡標記 `"enabled": False`，要恢復記錄把它刪掉即可。

## 資料放在哪裡

每種運動一個資料夾：`docs/data/<運動>/`

| 檔案 | 內容 |
|---|---|
| `odds_history_YYYY-MM.csv` | 每場比賽的資金流向快照：三種盤（獨贏 `ml_`、讓分 `sp_`、大小分 `ou_`）的 bet%、money%、共識賠率（目前＋開盤）、盤口線、去水機率。按月分檔 |
| `odds_books_YYYY-MM.csv` | 各家莊家的賠率明細，只在賠率有變動時才記。按月分檔 |
| `results.csv` | 賽果：比分、勝方、讓分差（`margin`）、總分（`total_points`）、賽季階段 |
| `context.csv` | 背景資料：球場、城市、是否室內、天氣、MLB 先發投手 |
| `raw/日期.json.gz` | 每天第一次抓到的原始資料備份 |

檔案之間怎麼對起來：
- `odds_history` ↔ `results`：用 `sbd_id`
- `odds_history` ↔ `context`：用 `event_id`（ESPN 比賽編號）

`season_type` 欄位：`preseason` 季前賽 / `regular` 例行賽 / `postseason` 季後賽。
季後賽的系列賽說明在 `series_note`（例如「ALDS - Game 3」）。

## 程式與排程

| 程式 | 排程檔 | 做什麼 | 頻率 |
|---|---|---|---|
| `scrape_odds.py` | `scrape_odds.yml` | 抓全部運動的資金流向與賠率 | 美國比賽時段密集、其他時段稀疏 |
| `backfill_results.py` | `backfill_results.yml` | 到 ESPN 查比分回填 | 每天台灣時間 20:17 |
| `scrape_context.py` | `scrape_context.yml` | 球場、天氣、先發投手 | 每天 4 次 |
| `sports_common.py` | — | 共用設定：運動清單、ESPN 賽程、隊名比對 | — |

資料來源：SportsBettingDime（資金流向與賠率）、ESPN（賽程、比分）、Open-Meteo（天氣）。
