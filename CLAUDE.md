# 給 Claude 的專案說明（每個新對話先讀這份）

## 使用者
- 住台灣，在**台灣運彩（台彩）**下注，用 iPhone／iPad 看看板。不會寫程式，所有修改都由 Claude 做。
- **一律用繁體中文回覆**（就算使用者打簡體字也一樣）。用白話，少用術語；數字用表格，結論放前面。
- 目前**每注固定金額**，等資料累積夠了再考慮凱利。下注會緊張，不要鼓吹多下。
- 誠實優先：到現在**還沒有一注台彩期望值是正的**；樣本少的結果要講清楚「大多是運氣」。
- 看板上新增的功能，舊功能都要保留（使用者明確要求過）。

## 絕對不要做
- **不要抓玩運彩（ToS 不允許）、不要抓台彩官網（Cloudflare）**。台彩賠率只能靠使用者截圖，由 Claude 讀圖後用 `record_tw_odds.py` 記錄。
- 只記台彩的**最終賠率**。
- 不協助在台灣使用國外下注網站、VPN 等（在台灣下國外網站是違法的，使用者知道）。

## 看板（網頁 artifact）
- 網址：https://claude.ai/artifact/7PL5t3Y98XSVwmnQBPaTjU
- 原始碼：`dashboard/page.html`（模板）→ `python3 build_dashboard.py` 產生 `dashboard/index.html`（資料內嵌）＋ `dashboard/data.json`。**只改 page.html，不要手改 index.html。**
- 發布：Artifact 工具 publish，`url` 填上面網址、`file_path` 填 `dashboard/index.html`，不要傳 icon、不要傳 capabilities（沿用：`db` ＋ `mcp`（Claude Code Remote 的 fire_trigger））。
- 發布被拒（排程剛發布過新版本）：讀被存下來的那份 HTML，跟本地 index.html 比對短行（`awk 'length<5000'` 再 diff），差異只有自己的修改和開頭的 wrapper 就重送一次同樣內容即可。
- 頁面（底部導覽）：比賽、選注、準不準（分析）、投注、模型、台彩、計算機、說明。
  - 「模型」頁有分頁：成績／曲線／下多少／賠率區間／每一注／回測，上方「只看哪些聯賽」篩選套用到除了回測以外的分頁。
  - 獲利率顏色維持紅綠，下面小字「還看不出／看得出」（注數 < 30 或離 0 不到 2 倍標準誤＝還看不出）。
- 使用者自己的資料存在 artifact 的 db：`bets`（投注／觀察紀錄）、`settings/bank`（本金設定）。
- 測試：用 playwright（Chromium 已裝好），把 index.html 前面接一段假的 `window.claude`（db 回傳假資料）存成暫存檔打開，檢查沒有 JS 錯誤、手機寬 390px 沒有橫向捲動。

## 資料與程式
- 每個運動一個資料夾 `docs/data/<運動>/`（mlb、nba、nfl、nhl、soccer；ncaaf 暫停）。詳細欄位見 README.md。
- `docs/data/tw_odds.csv`：使用者截圖記錄的台彩實際賠率。
- `docs/data/<運動>/model_picks.csv`：各策略「每一場都下」的實戰記錄（`track_models.py` 產生）。
- 主要程式：
  - `scrape_odds.py`（美國四大資金流向，`--final`＝開賽前 5 分鐘截圖）、`scrape_soccer.py`、`scrape_pinnacle.py`、`scrape_extra.py`、`scrape_context.py`
  - `backfill_results.py` 補賽果；`us_model.py`／`soccer_model.py` 模型一訓練
  - `track_models.py` 策略記錄與結算；`alerts.py`／`alerts_report.py` 划算注；`check_flip.py` 參考策略提醒
  - `build_dashboard.py` 組看板資料（`live_summary()` 給模型頁用）
- **常駐工作（2026-10-12 起，主力）**：`resident.py` ＋ `.github/workflows/resident.yml`。一個工作一直開著自己看時鐘：每 10 分美國四大（scrape_odds＋extra＋pinnacle＋track_models＋alerts）、每小時 :25 足球、每場開賽前 5 分截圖；跑 5h40m 交棒給排隊的下一個。心跳檔 `docs/data/state/resident.json`。舊的 scrape_odds／scrape_soccer／final_snapshot 排程變成備援：排程觸發時先 `python resident.py --alive`，有心跳就跳過。檢查：`python3 check_resident.py <開始時間>`。上線前實測 GitHub 排程每小時只跑 2.6–3.6 次、NHL 開賽前截圖只截到 56%。
- GitHub Actions（UTC，舊排程）：scrape_odds 每 10 分（含 track_models、alerts）、final_snapshot 每 10 分、scrape_soccer 每小時 :25、backfill_results 07:02 與 12:17（台灣 15:02、20:17）、scrape_context 每天 4 次、history（模型一重練）週日 20:30、soccer_model 週一四 22:40。
- Actions 一直在 commit 資料：**commit 前一定 `git pull --rebase`**。model_picks.csv 衝突時，取自己的版本後重跑一次 `track_models.py` 就會補回來。
- commit 訊息用繁體中文，結尾加上系統要求的 Co-Authored-By／Claude-Session 兩行。

## 排程任務（Claude 的 scheduled tasks）
| 名稱 | 做什麼 |
|---|---|
| 划算注推播 | 每小時 :05（台灣），跑 alerts_report.py，有新的才推播 |
| 更新資金流向看板 | 每小時 :10（台灣），重建並發布看板（看板上「立即更新」按鈕也會觸發） |
| 立即更新賽果 | 只能手動觸發（看板「更新賽果」按鈕）：跑 backfill workflow → 本機 track_models → 重建發布 |
| 台彩截圖需求清單 | 每天 21:03，列出還沒記台彩賠率的比賽 |
| 改押對面策略提醒 | 每週日 20:50，check_flip.py 改過的注滿 100 注就推播一次並自動停用 |

## 職業版（pro/，進行中）
- 照職業團隊做法從頭建的新模型，**跟原本的看板和模型一完全分開，是獨立的成品**：
  - 網頁：https://claude.ai/artifact/2gU7YFcfAW7F5E2EJQr2F5（模板 `pro/page.html` → `python3 -m pro.build_page` → `pro/dist/index.html`，發布到這個網址）
  - 程式只放 `pro/`，輸出只寫 `docs/data/pro/` 和 `pro/dist/`。原本的看板沒有任何職業版的東西；不要改模型一或 model_picks.csv 來配合它。
- **職業版不考慮台彩**（使用者 2026-10-13 指示）：只看能不能贏過國際／美國盤口，不用再提台彩抽成。
- **每做完一個階段就停下來**：跟使用者說明這階段在做什麼、結果如何，等他確認才做下一階段。
- 原則：核心模型不放賠率（自己先開盤再跟莊家比）、嚴格照時間順序、最後兩季留到最後才考、成績單看 log loss vs 收盤／機率校準／CLV／美國或 Pinnacle 賠率獲利＋運氣範圍。不用條款不允許抓取的網站。資料不齊全就從頭重建。
- 階段：0 CLV 追蹤＋資料檢查（`pro/lines.py`、`pro/clv.py`、`pro/datacheck.py`）→ 1 足球比分模型 → 2 NFL、MLB、NHL → 3 NBA → 4 混合＋每日對照表。
- 進度：第 0、1、2 階段使用者已確認。第 3 階段 NBA 第 1 版（`pro/nba_model.py`，球隊效率；資料 `pro/nba_data.py`＝hoopR／sportsdataverse CC BY 4.0，在 `pro_data.yml` 轉檔）最後兩季已考過。第 2 版（`pro/nba_player_model.py`，用球員評分組出球隊：交易跟著球員、新秀用選秀順位、年齡、預計上場分鐘；結果在 us_report.json 的 `nba2`）2026-10-12 完成，等使用者確認：追上收盤 驗證 90%（第 1 版 80%），最後兩季 86%（只當參考，真正考試是 2026–27）；混合後沒有比收盤準。**公平檢查**：模型用「今天誰上場」，跟開盤比是偷看傷兵消息；開盤版（`lineup: prev`＝只用上一場名單）收盤往模型 48% vs 43%、CLV −3.4%，沒優勢。第 1 版的 54% vs 38% 也是同樣原因偏樂觀。設定：`--tune`（12 種）→ `--lineups`（actual／actual10／prev）→ `--reference-test`（已跑過）。
- **各運動第 2 版（2026-10-13，使用者要求「其他運動也改成職業做法」，等使用者確認）**：結果都在 us_report.json 的 `mlb2`／`nfl2`／`nhl2`，參考考試都已跑過（test_log.json）。資料：`pro/fetch_players.py`（GitHub Actions `pro_players.yml`：Retrosheet 每位打者／投手每場、Chadwick 生日、sportsdataverse NHL 球員逐場、MoneyPuck 射門 xG）、`pro/nfl_player_data.py`（nflverse 出場次數、傷兵報告、每週名單、先發四分衛，本機可下載）。
  - MLB（`pro/mlb_player_model.py`）：每位打者×投手勝算比對決、左右投打、棒次、牛棚疲勞。追上收盤 驗證 86%（第 1 版 80%）、參考 82%（67%）。只用上一場打線（開盤版）收盤往模型移 76% vs 16%、CLV +0.8%——但 2024–25 開盤是 ESPN，比 SBRO 軟很多，可能偏樂觀；SBRO 驗證季 −0.8%（看好 ≥10% 時 +0.7%）。**真正考試：2026 球季**（沒用過，docs/data/mlb/history/espn_2026.csv 有開收盤；等 Retrosheet 年底公布 2026 逐打席）。
  - NFL（`pro/nfl_player_model.py`）：先發四分衛跟著人、四分衛換人、七個位置完整度；三種名單 actual／report（傷兵報告＋每週名單）／prev。驗證 91%（79%），參考 67%（68%）；進步幾乎全靠開賽前 90 分鐘的不上場名單（收盤也知道）。
  - NHL（`pro/nhl_player_model.py`）：守門員 GSAx、每位球員每 60 分鐘評分、上場時間加權；開盤版猜守門員。參考 77%（第 1 版 62%），開盤版 71%；混合沒幫助。
  - **MLB 特徵搜尋（2026-10-13 開始）**：`pro/mlb_search.py`（練習區 2012–2021 SBRO 開盤、分 4 段、成績＝用開盤＋模型預測收盤的誤差；門檻依總嘗試次數 Bonferroni）、候選在 `pro/mlb_candidates.py`、「什麼時候下」在 `pro/mlb_segments.py`，**每次嘗試都記在 docs/data/pro/search_log.json，不能刪**。天氣／主審好球帶／捕手／先發休息／新秀投手／連勝／移動（`docs/data/pro/mlb/game_info.csv`、`framing.csv.gz`）。第一輪 10 次只有「4、5 月」通過（CLV 約 −0.1%，打平）。基本特徵快取用環境變數 PRO_CACHE。
  - **特徵搜尋其他運動**：足球 `pro/soccer_search.py`（Pinnacle 賽前 2–3 天 vs 收盤，log `search_log_soccer.json`）；NBA／NFL `pro/spread_search.py nba|nfl`（SBRO 開盤／收盤讓分 `docs/data/pro/<nba|nfl>/sbro_lines.csv`，由 `pro/fetch_sbro_open.py` 在 Actions 下載；log `search_log_<運動>.json`）。NHL 舊開盤壞了不做。到 10/13：共 31 次，通過＝MLB 開季 4–5 月、NBA 開季 10–11 月、NBA 擺爛隊、足球開季 8–9 月；NFL 沒有。效果都太小，還不夠贏抽水。
  - 足球：先發名單的合法來源找不到（FBref、Transfermarkt 條款不允許；Understat 條款不明），**還沒做，等使用者決定**。第 2 階段：MLB 收盤明顯往模型移（60–63% vs 26–33%），開盤 CLV 約 −1%～+0.5%；NFL、NHL 沒有優勢。四個美國運動都已考過（test_log.json，不能重考）。
- 資料：MLB＝Retrosheet（`pro/fetch_us.py` 在 GitHub Actions `pro_data.yml` 下載整理，網頁要附 Retrosheet 聲明）；NHL＝MoneyPuck；NFL＝nflverse（`pro/nfl_data.py`，工作環境可直接下載）。**ESPN 冰球盤 2022–23、2023–24 的收盤獨贏是壞的（兩邊機率加起來 83%），SBRO 冰球盤也有問題**；原本模型一的冰球訓練用過這些盤口，要修先問使用者。
- 資料：football-data 2025/26 季中起沒有 Pinnacle 收盤 → 最後兩季用 Betfair 交易所收盤（BFEC*）當標準答案。Pinnacle 檔案 period：0＝全場；NHL 的 6＝60 分鐘三選一（有和局賠率）。

## 重要的運彩規則（算錯會差很多）
- 期望值 EV = 勝率 × 賠率 − 1；「划算」門檻 EV ≥ +2%。
- 台彩抽成約 15%（美國約 4.5%）；沒有實際台彩賠率時用「美國賠率 ×（1 + 折扣）」估，折扣由 tw_odds.csv 算（約 −9.5%）。
- **NHL 台彩獨贏＝60 分鐘三選一（客／和／主），打進延長賽＝和局，押隊伍算輸**；大小分也只算 60 分鐘；台彩冰球讓分跟美國 ±1.5 不能比（不算）。美國盤含延長賽。
- 足球台彩讓分是三選一（例如 1:0），我們的足球讓分是美國／亞洲盤，不能直接比。
- 模型一＝每週重練的羅吉斯迴歸，效果約等於市場收盤價；勝率準、但不保證贏抽成。
- 樣本少時不要下結論：每格／每策略幾百注才看得出來。

## 目前的觀察（2026-10-12）
- 10/1 起：模型一・美國賠率 +12.7%（還看不出），同一注改去台彩下約 +0%；模型一・台彩 −11%；都押冷門 −30%（看得出會虧）。
- 足球模型一的獲利大多來自和局（11 注中 5）。
- 長期歷史：台彩每個賠率區間都虧 10–18%，低賠（< 1.3）虧最少、3.0 以上大冷門虧最多。
