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
  - 成績頁「每一場都下注」和「只下划算的」表格**每一行都有「看每一注 ▾」**（使用者 2026-10-26 要求）：點開列出那一行算進去的每一注（日期、聯賽、押什麼、比賽、勝率／期望值、賠率（台彩的標估）、輸贏、賺賠），跟篩選一致，先顯示 100 注、可再加 200。資料＝`live.series` 第 [9] 欄（指到 `live.sg`＝[時間, 運動, 聯賽, 客, 主]）、第 [10] 欄＝pick 代碼（網頁轉中文）；狀態 `SD`。
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
| 划算注推播 | **已停用**（使用者 10/13 為了省額度停掉；要恢復就把排程 enabled 打開）。原本每小時 :05 跑 alerts_report.py |
| 更新資金流向看板 | 每小時 :10（台灣），重建並發布看板（看板上「立即更新」按鈕也會觸發） |
| 立即更新賽果 | 只能手動觸發（看板「更新賽果」按鈕）：跑 backfill workflow → 本機 track_models → 重建發布 |
| 台彩截圖需求清單 | 每天 21:03，列出還沒記台彩賠率的比賽 |
| 改押對面策略提醒 | 每週日 20:50，check_flip.py 改過的注滿 100 注就推播一次並自動停用 |
| 職業版網頁更新＋NHL 新注通知 | 每天 11:41、21:41，重建發布職業版網頁；NHL 實戰記錄有新注就推播 |

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
  - **下注規則測試（`pro/rule_search.py`，直接看開盤價下注對收盤的 CLV 是否 > 0）**：**MLB「模型比開盤多看好 ≥15%」練習區 554 注 CLV +1.57%（z 5.3，4 段都正）**——檢查過不是資料錯誤、不是押冷門本身（同價位冷門 −3.8%）；2024–25 參考 +5.5%（ESPN 開盤偏軟）。細節 `docs/data/pro/mlb_rule15.json`。還沒正式考：2026 整季（Retrosheet 年底公布後），之後每天實戰。MLB 開季＋≥10% 也過（+0.9%）。NBA 規則全部 −2～−3%（移動太小贏不過 −110）。
  - **10/13 第三輪**：樹模型（梯度提升）在 MLB 明顯變差，不再試。`pro/combo_eval.py`（開盤＋模型合併 vs 收盤，`combo_report.json`）。**NHL：SBRO 冰球開盤只有 2007–2014 欄位錯位，2014–15 起正常**；`pro/nhl_search.py` 練習區 2014–2022，收盤往模型移（b 0.17–0.26）；規則「≥15%」CLV +0.57%、4 段都正、z 1.62 差一點（門檻 1.64）。
  - **10/13 第四輪（大小分、各聯賽）**：NBA 大小分 −2～−3%；NFL 大小分 +0.4%（差 ≥5 分 +0.8%，拿掉實際天氣也差不多），讓分 −3%；NHL 加賽程特徵還是 +0.6%（4 段正、z 1.66 未過）；足球 `pro/soccer_rules.py` 大小 2.5 −3.6%、亞洲讓分樣本太少。結論：MLB 贏、NHL／NFL 大小分差不多、NBA／足球輸。
  - **NHL 實戰記錄（10/13 上線）**：`.github/workflows/pro_live.yml`（每天台灣 11:17、21:17、03:47）→ `pro/live_data.py nhl`（這一季資料存成 `docs/data/pro/nhl/*_cur.*`，**不 commit**，讀檔時自動合併）→ `pro/live_nhl.py`（規則：模型開盤版 × Pinnacle 當下賠率 − 1 ≥ 15%；每場第一次看到時決定、之後不改；季初已打完的「回補」）。輸出 `docs/data/pro/live/nhl.csv`、`nhl_summary.json`。排程任務「職業版網頁更新＋NHL 新注通知」台灣 11:41、21:41 重建發布職業版網頁、有新注就推播。MLB 等 2027 開季＋Retrosheet 2026 資料再接。
  - **地基檢查（10/15，`pro/audit_calm.py`、`pro/audit_pitcher.py`、`pro/audit_clean.py` → `audit_clean.json`）**：以前規則測試排除「開盤到收盤移動 ≥ 8%」＝偷看未來，**以後規則一律不用 CALM**；改用下注當下可知的條件：開盤兩邊一樣（佔位價）不下、模型多看好 > 30% 不下（EDGE_MAX）、MLB 只算正常輪值先發（模型用實際先發，開盤可能掛別人）。SBRO 開盤有錯價（大移動 MLB 75:1、NHL 31:1、NFL 大小 48:4 往模型），所以同時看「截尾 ±10%」與「保守下限（排除大移動）」。結果：MLB ≥15% 下限 +1.1%／補後 +1.8%（59% 打贏收盤）；NHL ≥15% +0.6%／+0.8%（search_log_nhl #5–7 乾淨版都過，賽程版 4/4 段，實戰仍用 edge_15 不換）；NFL 大小 3–10 分補後 +1.5% 但下限 −0.2%（打平，不夠把握；當天實際天氣是偷看，已拿掉）。NHL 實戰規則加上 ≤30% 上限，結算改成每筆獨立（以前球員資料沒進來的比賽不會結算）。
  - **每日對照表（第 4 階段，10/15）**：職業版網頁「我們開的盤 vs Pinnacle」，NHL 每一場（還沒打的＋最近 2 天），資料來自 live/nhl.csv 的 board。MLB 等 2027；NBA、NFL 沒贏過莊家不放。
  - **NBA 傷兵消息時間點（10/13 起）**：`pro/injury_watch.py nba` 放在常駐工作每 10 分鐘的步驟裡，ESPN 傷兵名單只記變動 → `docs/data/nba/injury_log_YYYY-MM.csv`（狀態存 `docs/data/state/nba_injuries.json`）。以後拿來對 Pinnacle 盤口時間，研究「消息出來後盤口多久、移多少」。
  - **足球資料來源（使用者 10/13 交給 Claude 決定）**：football-data.org 免費版沒有名單、API-Football 要使用者自己註冊、Understat 條款查不到 → 用 **ESPN**（專案本來就在用、hoopR 也是 ESPN；試探結果 `docs/data/pro/probe_espn_soccer.txt`：十個聯賽 2010 起都有先發名單＋換人，一級聯賽有球員射正／進球／助攻，沒有 xG）。下載 `pro/fetch_espn_soccer.py` ＋ `.github/workflows/pro_soccer_espn.yml`（每聯賽一個工作，已抓過的跳過）→ `docs/data/pro/soccer/espn_<聯賽>.csv.gz`。足球第 2 版（10/15，`pro/soccer_player.py`：ESPN 隊名自動對到 98.7%、球員評分線上學習）：開盤版（上一場名單）z 1.74 < 門檻 2.58 沒通過；用今天實際名單的版本（z 5.0）是偷看，標 peek 不算，只證明收盤在名單出來後往名單移。足球結論：沒優勢。第 2 階段：MLB 收盤明顯往模型移（60–63% vs 26–33%），開盤 CLV 約 −1%～+0.5%；NFL、NHL 沒有優勢。四個美國運動都已考過（test_log.json，不能重考）。
- 資料：MLB＝Retrosheet（`pro/fetch_us.py` 在 GitHub Actions `pro_data.yml` 下載整理，網頁要附 Retrosheet 聲明）；NHL＝MoneyPuck；NFL＝nflverse（`pro/nfl_data.py`，工作環境可直接下載）。**ESPN 冰球盤 2022–23、2023–24 的收盤獨贏是壞的（兩邊機率加起來 83%），SBRO 冰球盤也有問題**；原本模型一的冰球訓練用過這些盤口，要修先問使用者。
- 資料：football-data 2025/26 季中起沒有 Pinnacle 收盤 → 最後兩季用 Betfair 交易所收盤（BFEC*）當標準答案。Pinnacle 檔案 period：0＝全場；NHL 的 6＝60 分鐘三選一（有和局賠率）。

## 五大聯賽以外的足球（2026-10-21）
- 使用者要「歐冠／歐霸／歐協聯、國內盃賽、國家隊、其他國家聯賽全部都要，模型一也要預測」；冷門賽事不收資金流向。
- 賽事清單 `soccer_comps.py`（代號、中文、分組 big5/euro/cup/intl/league、ESPN 路徑、Pinnacle 名稱、Action Network）。
- 資金流向（Action Network）只有五大聯賽＋歐冠、歐霸、美職；其他只有 Pinnacle 盤口：`scrape_pinnacle.py soccer` 每次先問 Pinnacle 現有聯賽、對到清單的都記。看板用 `soccer_dashboard.pin_game()` 做成比賽（id＝pin<編號>、`pin_only`），賽果 `scrape_soccer.backfill_pin_results()` 用 ESPN 補。淘汰賽有延長賽只算 90 分鐘。
- 全球足球模型 `world_model.py`（俱樂部 Elo＝ESPN 47 個賽事 2014 起、`fetch_world_soccer.py` 在 `world_soccer_data.yml` 每天補＋重練；國家隊 Elo＝martj42 CC0）→ `docs/data/soccer/model/world_params.json`；看板 `world_predict.py`（隊名比對＋模型跟市場差 >15 點就不給）。跟模型一一樣「市場賠率＋Elo」，考試季 log loss 1.0018 vs 市場 1.0023（≈市場）。五大聯賽仍用原本 soccer_model.py。韓職 ESPN 沒資料（沒有模型）。

## 重要的運彩規則（算錯會差很多）
- 期望值 EV = 勝率 × 賠率 − 1；「划算」門檻 EV ≥ +2%。
- 台彩抽成約 15%（美國約 4.5%）；沒有實際台彩賠率時用「美國賠率 ×（1 + 折扣）」估。
- **台彩估計（2026-10-26 起，使用者發現高賠抽很多）**：
  - **獨贏（含和局）＝機率加固定值**：台彩 ≈ 1 ÷（1 ÷ 美國或 Pinnacle 賠率 + k）。使用者三場義甲截圖對 Pinnacle：每個選項機率都多 4–7 點、跟賠率高低無關（10.28 → 6.25、−39%）；比「照比例打折」準（≥3.5 平均誤差 6.4% → 4.4%）。k：主客隊約 0.060（分運動、往全部平均靠 10 筆：MLB 0.057、NBA 0.064、足球 0.059），和局約 0.046（3 筆，往主客隊靠 5 筆）。台彩足球獨贏三項合計抽約 20%（Pinnacle 3.5%）。`record_tw_odds.add_table()`／`est_ml()`；冰球不用（60 分鐘另算）。
  - **基準賠率＝Pinnacle＋bet365（使用者 2026-10-26 指定）**：`base_odds.py`。兩家都有取機率平均，一家就用一家，都沒有才用美國共識盤。估台彩賠率、校正 k／級距都對基準（98 筆截圖全部對得到）。bet365＝SportsBettingDime 的 Bet365.US.NJ（美國四大，每 10 分）；**足球目前只有 Pinnacle**（football-data 的 bet365 一週更新兩次太舊；Action Network 共識盤＝美國各家平均，冷門／和局比較低又改得慢）。g["b365"]、已完賽比賽也接 pin／b365（只給程式用，寫檔前 `strip_closed_base` 拿掉）。看板 Pinnacle 那行顯示賠率數字＋bet365；足球歐洲賠率表加 Pinnacle（現在）。**「美國賠率」策略照舊用美國共識盤結算**。以基準算 k：主客隊 0.064（NBA 0.068、MLB 0.059、足球 0.060）、和局 0.048。
  - **模型一 vs 模型三（使用者 2026-10-26 19:01 重新指定，取代傍晚的 model1_old／model1_new）**：兩個都用模型一的勝率、都用「比較準的台彩賠率」（實際截圖或新估法）結算賺賠，只差在**挑邊**：
    - `model1`（模型一・台彩）＝照**舊估法**挑邊：美國共識盤 ×（1 + 該運動平均折扣）（`old_discount()`／`old_est()`），`est_old` 欄＝挑邊時估的賠率。因為所有選項打同一個折，挑的邊幾乎都跟「模型一・美國賠率」一樣（差在冰球 60 分鐘、有實際截圖的）。過去的注本來就是舊估法挑的（新估法 17:42–19:xx 期間沒有比賽開賽），不用改。
    - `model3`（模型三・台彩）＝照**新估法**（Pinnacle＋bet365、機率加固定值）挑邊；過去比賽由 `backfill_model3()` 用 favorite／underdog／draw 三個選項回頭補（和局勝率＝1 − 主 − 客；冰球估法沒變 → 模型三＝模型一）。
    - **模型三也有三條（使用者 19:18 指定，對應模型一的三條）**：`model3`（台彩）、`model3_pin`（**只用 Pinnacle 一家**的開賽前最新獨贏挑邊＋結算，含延長賽；`pin_options()`，settle 照 `_us` 規則、src＝pin）、`model3_pin_tw`（Pinnacle 選邊・台彩下，跟 model3_pin 押同一邊、台彩賠率結算、冰球 60 分鐘）。過去比賽 `backfill_pin()`：勝率＝model1_us 那筆（另一邊 1 − p）／足球用熱門冷門＋和局，Pinnacle 收盤＝已完賽比賽接的 pin。10/26 當時：model3_pin 652 注 +9.3%（±9.2，剛好在運氣邊緣；NBA 40 注 +39%、足球 +15%），model3_pin_tw −5.2%。「模型一・美國賠率」＝美國 5 家（DK、FD、MGM、Caesars、bet365 NJ）**中位數**，足球＝Action Network 共識盤。
    - 「模型一・美國賠率」「美國選邊・台彩下」照舊。看板：成績頁兩行＋「模型一 vs 模型三：押不一樣的那幾場」（`live.est_cmp`，鍵名 old＝模型一、new＝模型三）；每一注→獨贏有 [模型一][模型三] 切換（`MT.m`，store `mmod`），「接下來怎麼押」改成直接讀記錄（`tw_bets`／`m3_bets`／`us_bets`，`gid`、`eo`＝est_old）；曲線、下多少、賠率區間都加模型三；us_model 回測 `every_tw.model1` 改成照美國賠率挑邊＋新估法結算、另加 `model3`（週日重練生效）。10/26 當時 669 注：模型一 −10.8%、模型三 −12.9%；押不同邊 138 場（模型一 −9.4k、模型三 −23.2k；模型三比較好 70 場、模型一 46 場）。
  - **讓分／大小分＝賠率級距**：`record_tw_odds.band_table()`（1.4／1.7／2.0／2.5／3.0／4.0／5.0 分界，每級記錄平均、筆數少往 ln 趨勢線靠 5 筆）。
  - 資料＝tw_odds.csv ＋ `docs/data/tw_ref_examples.csv`（使用者口頭或截圖給的「Pinnacle vs 台彩」例子，含 side＝side/draw；**還沒開賽的台彩截圖不進 tw_odds.csv（只記最終賠率），拿來校正就記這裡**）。
  - `track_models.reprice_est()` 每次執行都把估的注照最新估法重算（押哪邊不變、實際截圖不動、冰球不動）。10/1 起重算結果：模型一・台彩 −9.8%（舊）→ −11.0%、都押冷門 −18% → −25%、足球押和局 −17% → −20%。us_model 回測也改（`tw_method: add`，週日重練生效）。
- **NHL 台彩獨贏＝60 分鐘三選一（客／和／主），打進延長賽＝和局，押隊伍算輸**；大小分也只算 60 分鐘；台彩冰球讓分跟美國 ±1.5 不能比（不算）。美國盤含延長賽。
- 足球台彩讓分是三選一（例如 1:0），我們的足球讓分是美國／亞洲盤，不能直接比。
- 模型一＝每週重練的羅吉斯迴歸，效果約等於市場收盤價；勝率準、但不保證贏抽成。
- 樣本少時不要下結論：每格／每策略幾百注才看得出來。

## 目前的觀察（2026-10-12）
- 10/1 起：模型一・美國賠率 +12.7%（還看不出），同一注改去台彩下約 +0%；模型一・台彩 −11%；都押冷門 −30%（看得出會虧）。
- 足球模型一的獲利大多來自和局（11 注中 5）。
- 長期歷史：台彩每個賠率區間都虧 10–18%，低賠（< 1.3）虧最少、3.0 以上大冷門虧最多。

## 目前的觀察（2026-10-25 更新）
- 模型一 10/1–10/24 共 529 注：獨贏・美國 +1.0%、同注去台彩 −9.5%；讓分・美國 +7.3%（±11.9，還看不出）；大小分 −6.1%；都押和局 −12%／台彩 −18%。沒有哪個賠率區間或聯賽看得出差別。
- 台彩抽水（跟公平機率比）：美國賠率 < 1.5 約 −7%、1.5–3.5 約 −10%、≥ 3.5 約 −27.5%；讓分／大小分約 −9.5%。記過的 293 個台彩價格**沒有一個是正的**（最好 −2.3%）。
- 已跟使用者講清楚：每注都下＝虧抽水；挑最不負的只是虧得慢；只有 EV > 0 才下（台彩慢改盤、開錯、活動加碼），不然當娛樂、固定預算、不串關。
- 看板新增：模型頁日期篩選、賠率區間自己調（MOD）、每一注分獨贏／讓分／大小分；五大以外足球（國際盤，中文隊名）。

## 電競（英雄聯盟首殺，2026-10-25）
- 使用者觀察：台彩 LoL 首殺「高賠方抽水少、低賠方抽得多」。資料用 Oracle's Elixir 2025（使用者把 Google Drive 檔案複製到自己雲端分享；官網 403 不繞過）：`fetch_lol.py`＋`.github/workflows/fetch_lol.yml` → `docs/data/esports/lol_teams_2025.csv.gz`（10,044 場）。
- 結果（Elo K=24）：弱隊拿首殺約 47–48%，大冷門約 39%。台彩首殺兩邊合計抽約 17.7%，大多放在強隊那邊（例：HLE −21%、iG −8%）。弱隊首殺要 ≥ 2.15（大冷門 ≥ 2.6）才划算。只看過很少場，要使用者再截 30–50 場（獨贏＋首殺）確認。首條大龍數字不準（沒殺龍的場兩邊都算 0）。
