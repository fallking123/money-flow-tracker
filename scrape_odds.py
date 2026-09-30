"""
資金流向抓取主程式 v4（多運動版）
====================================================
資料來源：SportsBettingDime 背後的 <運動>-odds 原始資料（JSON），
一次執行就依序抓完 MLB、NFL、NCAAF、NBA、NHL、NCAAB，每種運動分開存檔。

每種運動存在 docs/data/<運動>/：
1. odds_history_YYYY-MM.csv —— 每場比賽一列（核心資料）
   三種盤（獨贏 / 讓分 / 大小分）的 bet% 與 money%、
   美國莊家的共識賠率（目前 + 開盤）、讓分與總分線（目前 + 開盤）、去水後隱含機率、
   ESPN 比賽編號（對賽果用）與賽季階段（例行賽 / 季後賽）
2. odds_books_YYYY-MM.csv   —— 每家莊家、每個盤、每一邊的賠率明細（只在賠率有變動時才記）
3. raw/日期.json.gz         —— 每天第一次抓到的原始資料備份

分層頻率：距開賽 >24 小時每 6 小時、3~24 小時每 2 小時、1~3 小時每 30 分、1 小時內每 10 分
（美式足球整週都在下注，所以開賽前 7 天就開始記錄；其他運動 48 小時）

直接讀資料網址，不用開瀏覽器；萬一被擋（HTTP 403），程式結束碼為 3，
排程會自動改用瀏覽器模式重跑（python scrape_odds.py --browser）。
"""

import gzip
import hashlib
import json
import os
import statistics
import sys
from datetime import datetime, timezone, timedelta

import requests

from sports_common import (SPORTS, active_sports, STATE_DIR, UA, append_rows, espn_events, is_college,
                           match_event, monthly_path, parse_time, sbd_full_name, sport_dir)

API_URL = "https://www.sportsbettingdime.com/wp-json/adpt/v1/{sbd}-odds"
BOOKS = "sr:book:17324,sr:book:18149,sr:book:28901,sr:book:32219,sr:book:18186"
PAGE_URL = "https://www.sportsbettingdime.com/nfl/public-betting-trends/"
STATE_FILE = os.path.join(STATE_DIR, "last_snapshot.json")

HISTORY_FIELDS = [
    "timestamp_utc", "sport", "sbd_id", "event_id", "season_type", "game_time_utc", "hours_until_game",
    "away_team", "home_team", "away_abbr", "home_abbr",
    # 獨贏 Moneyline
    "ml_splits_updated", "ml_away_bets_pct", "ml_away_money_pct", "ml_home_bets_pct", "ml_home_money_pct",
    "ml_away_odds", "ml_home_odds", "ml_away_open_odds", "ml_home_open_odds",
    "ml_away_novig_prob", "ml_home_novig_prob",
    # 讓分 Spread（棒球叫 run line、冰球叫 puck line；以客隊角度記錄讓分值）
    "sp_splits_updated", "sp_away_bets_pct", "sp_away_money_pct", "sp_home_bets_pct", "sp_home_money_pct",
    "sp_away_line", "sp_away_open_line", "sp_away_odds", "sp_home_odds",
    # 大小分 Total
    "ou_splits_updated", "ou_over_bets_pct", "ou_over_money_pct", "ou_under_bets_pct", "ou_under_money_pct",
    "ou_line", "ou_open_line", "ou_over_odds", "ou_under_odds",
    "books_count",
]
BOOK_FIELDS = [
    "timestamp_utc", "sport", "sbd_id", "market", "book", "side",
    "odds_american", "open_odds_american", "line", "open_line",
]


class Blocked(Exception):
    pass


# ---------------- 工具函數 ----------------
MISSING_RETRY_MIN = 120
# 手動「馬上更新」：改 force_update.txt（寫運動代碼，例如 mlb）推上去就會觸發，這些運動不管間隔、全部重抓一次
FORCE_SPORTS = {s.strip() for s in os.environ.get("FORCE_SPORTS", "").replace("\n", ",").split(",") if s.strip()}
NOTHING_DUE = ".nothing_due"
SPLIT_KEY = {"ml": "ml_away_bets_pct", "sp": "sp_away_bets_pct", "ou": "ou_over_bets_pct"}


def tier_interval_minutes(hrs: float) -> int:
    if hrs > 24:
        return 360
    if hrs > 3:
        return 120
    if hrs > 1:
        return 30
    return 10


def american_to_decimal(s):
    """美式賠率 → 歐式(小數)賠率，跟台灣運彩同一種格式"""
    try:
        v = float(str(s).replace("+", ""))
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + v / 100, 4) if v > 0 else round(1 + 100 / abs(v), 4)


def median_decimal(values):
    vals = [v for v in values if v]
    return round(statistics.median(vals), 4) if vals else None


def to_float(s):
    try:
        return float(str(s).replace("+", ""))
    except (TypeError, ValueError):
        return None


def mode_value(values):
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return max(set(vals), key=vals.count)


def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        raw = json.load(f)
    # 舊版格式：{id: 時間字串}
    return {k: (v if isinstance(v, dict) else {"t": v}) for k, v in raw.items()}


def save_state(state, now):
    cutoff = now - timedelta(days=10)
    state = {k: v for k, v in state.items() if parse_time(v["t"]) > cutoff}
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


# ---------------- 抓資料 ----------------
def parse_body(status, text, sport):
    if status == 403:
        raise Blocked(f"{sport}: HTTP 403")
    if status != 200:
        print(f"  {sport}: HTTP {status}，略過")
        return []
    try:
        return json.loads(text).get("data", []) or []
    except ValueError:
        # 休賽期網站會回空白頁，不是錯誤
        print(f"  {sport}: 目前沒有資料（可能是休賽期）")
        return []


def fetch_direct(sport):
    r = requests.get(API_URL.format(sbd=SPORTS[sport]["sbd"]),
                     params={"books": BOOKS, "format": "us"}, timeout=30, headers=UA)
    return parse_body(r.status_code, r.text, sport)


class BrowserFetcher:
    """備援：開一次網頁，再用網頁本身去讀各運動資料（被擋時才用）"""

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._p = sync_playwright().start()
        self._b = self._p.chromium.launch(headless=True)
        self._page = self._b.new_page()
        self._page.goto(PAGE_URL, wait_until="domcontentloaded", timeout=60000)
        return self

    def fetch(self, sport):
        url = API_URL.format(sbd=SPORTS[sport]["sbd"]) + "?books=" + requests.utils.quote(BOOKS) + "&format=us"
        res = self._page.evaluate(
            "async (u) => { const r = await fetch(u); return {status: r.status, text: await r.text()}; }", url)
        return parse_body(res["status"], res["text"], sport)

    def __exit__(self, *a):
        self._b.close()
        self._p.stop()


def compact_game(g):
    """原始資料瘦身版（拿掉球隊簡介等用不到的欄位）"""
    c = g.get("competitors", {})
    return {
        "id": g.get("id"), "status": g.get("status"), "scheduled": g.get("scheduled"), "league": g.get("league"),
        "away": {k: c.get("away", {}).get(k) for k in ("name", "abbr", "market")},
        "home": {k: c.get("home", {}).get(k) for k in ("name", "abbr", "market")},
        "markets": g.get("markets"), "bettingSplits": g.get("bettingSplits"),
    }


# ---------------- 解析 ----------------
def split_vals(splits, market, side):
    s = (splits or {}).get(market, {}).get(side, {}) or {}
    return s.get("betsPercentage"), s.get("stakePercentage")


def build_rows(sport, g, now, ev):
    c = g["competitors"]
    splits = g.get("bettingSplits") or {}
    markets = g.get("markets") or {}
    ts = now.isoformat()
    hrs = (parse_time(g["scheduled"]) - now).total_seconds() / 3600

    book_rows = []
    agg = {}

    def add(key, val):
        agg.setdefault(key, []).append(val)

    for market, sides in (("moneyline", ("away", "home")), ("spread", ("away", "home")), ("total", ("over", "under"))):
        for b in (markets.get(market) or {}).get("books", []):
            for side in sides:
                o = b.get(side) or {}
                if market == "total":
                    line, open_line = to_float(b.get("total")), to_float(b.get("opening_total"))
                elif market == "spread":
                    line, open_line = to_float(o.get("spread")), to_float(o.get("opening_spread"))
                else:
                    line = open_line = None
                book_rows.append({
                    "timestamp_utc": ts, "sport": sport, "sbd_id": g["id"], "market": market,
                    "book": b.get("name"), "side": side,
                    "odds_american": o.get("odds"), "open_odds_american": o.get("opening_odds"),
                    "line": line, "open_line": open_line,
                })
                add((market, side, "odds"), american_to_decimal(o.get("odds")))
                add((market, side, "open"), american_to_decimal(o.get("opening_odds")))
                add((market, side, "line"), line)
                add((market, side, "open_line"), open_line)

    ml_a = median_decimal(agg.get(("moneyline", "away", "odds"), []))
    ml_h = median_decimal(agg.get(("moneyline", "home", "odds"), []))
    novig_a = novig_h = None
    if ml_a and ml_h:
        pa, ph = 1 / ml_a, 1 / ml_h
        novig_a, novig_h = round(pa / (pa + ph), 4), round(ph / (pa + ph), 4)

    mla_b, mla_m = split_vals(splits, "moneyline", "away")
    mlh_b, mlh_m = split_vals(splits, "moneyline", "home")
    spa_b, spa_m = split_vals(splits, "spread", "away")
    sph_b, sph_m = split_vals(splits, "spread", "home")
    ov_b, ov_m = split_vals(splits, "total", "over")
    un_b, un_m = split_vals(splits, "total", "under")

    ev = ev or {}
    row = {
        "timestamp_utc": ts, "sport": sport, "sbd_id": g["id"],
        "event_id": ev.get("event_id", ""), "season_type": ev.get("season_type", ""),
        "game_time_utc": g["scheduled"], "hours_until_game": round(hrs, 2),
        "away_team": (ev.get("away") or {}).get("display") or sbd_full_name(c["away"]),
        "home_team": (ev.get("home") or {}).get("display") or sbd_full_name(c["home"]),
        "away_abbr": c["away"].get("abbr") or (ev.get("away") or {}).get("abbr", ""),
        "home_abbr": c["home"].get("abbr") or (ev.get("home") or {}).get("abbr", ""),
        "ml_splits_updated": (splits.get("moneyline") or {}).get("updated", ""),
        "ml_away_bets_pct": mla_b, "ml_away_money_pct": mla_m,
        "ml_home_bets_pct": mlh_b, "ml_home_money_pct": mlh_m,
        "ml_away_odds": ml_a, "ml_home_odds": ml_h,
        "ml_away_open_odds": median_decimal(agg.get(("moneyline", "away", "open"), [])),
        "ml_home_open_odds": median_decimal(agg.get(("moneyline", "home", "open"), [])),
        "ml_away_novig_prob": novig_a, "ml_home_novig_prob": novig_h,
        "sp_splits_updated": (splits.get("spread") or {}).get("updated", ""),
        "sp_away_bets_pct": spa_b, "sp_away_money_pct": spa_m,
        "sp_home_bets_pct": sph_b, "sp_home_money_pct": sph_m,
        "sp_away_line": mode_value(agg.get(("spread", "away", "line"), [])),
        "sp_away_open_line": mode_value(agg.get(("spread", "away", "open_line"), [])),
        "sp_away_odds": median_decimal(agg.get(("spread", "away", "odds"), [])),
        "sp_home_odds": median_decimal(agg.get(("spread", "home", "odds"), [])),
        "ou_splits_updated": (splits.get("total") or {}).get("updated", ""),
        "ou_over_bets_pct": ov_b, "ou_over_money_pct": ov_m,
        "ou_under_bets_pct": un_b, "ou_under_money_pct": un_m,
        "ou_line": mode_value(agg.get(("total", "over", "line"), [])),
        "ou_open_line": mode_value(agg.get(("total", "over", "open_line"), [])),
        "ou_over_odds": median_decimal(agg.get(("total", "over", "odds"), [])),
        "ou_under_odds": median_decimal(agg.get(("total", "under", "odds"), [])),
        "books_count": len((markets.get("moneyline") or {}).get("books", [])),
    }
    return row, book_rows


def books_signature(book_rows):
    key = sorted((r["market"], r["book"], r["side"], str(r["odds_american"]), str(r["line"])) for r in book_rows)
    return hashlib.md5(json.dumps(key).encode()).hexdigest()[:12]


# ---------------- 主流程 ----------------
def process_sport(sport, games, now, state):
    cfg = SPORTS[sport]
    raw_dir = os.path.join(sport_dir(sport), "raw")
    os.makedirs(raw_dir, exist_ok=True)
    raw_path = os.path.join(raw_dir, f"{now.strftime('%Y-%m-%d')}.json.gz")
    if games and not os.path.exists(raw_path):
        with gzip.open(raw_path, "wt", encoding="utf-8") as f:
            json.dump([compact_game(g) for g in games], f, ensure_ascii=False)

    due = []
    for g in games:
        if g.get("status") != "not_started":
            continue
        hrs = (parse_time(g["scheduled"]) - now).total_seconds() / 3600
        if not (0 <= hrs <= cfg["horizon_h"]):
            continue
        st = state.get(g["id"], {})
        last = st.get("t")
        gap = tier_interval_minutes(hrs)
        # 上次記錄時還有盤別沒有下注比例（網站常晚一點才出讓分/大小分）→ 最多隔 2 小時再抓一次，
        # 不用等到下一個 6 小時，這樣比例一出來很快就會記到
        if st.get("miss"):
            gap = min(gap, MISSING_RETRY_MIN)
        # 容許約 1/4 間隔的誤差：GitHub 排程常延遲幾分鐘，避免剛好差一點就跳過一次
        if sport not in FORCE_SPORTS and last and (now - parse_time(last)).total_seconds() / 60 < gap * 0.75:
            continue
        due.append(g)
    if not due:
        print(f"  {cfg['name']}: 共 {len(games)} 場，這次沒有需要記錄的比賽")
        return 0

    events = []
    try:
        events = espn_events(sport, now - timedelta(days=1), now + timedelta(hours=cfg["horizon_h"] + 24))
    except Exception as e:
        print(f"  {cfg['name']}: ESPN 賽程讀取失敗（比賽編號先留空，回填比分時會再補對）: {e}")

    hist_rows, book_out, unmatched = [], [], 0
    for g in due:
        ev = match_event(g, events, college=is_college(sport)) if events else None
        unmatched += ev is None
        row, book_rows = build_rows(sport, g, now, ev)
        hist_rows.append(row)
        sig = books_signature(book_rows)
        if state.get(g["id"], {}).get("sig") != sig:
            book_out.extend(book_rows)
        miss = [m for m in ("ml", "sp", "ou") if row.get(SPLIT_KEY[m]) in (None, "")]
        state[g["id"]] = {"t": now.isoformat(), "sig": sig, "miss": miss}

    append_rows(monthly_path(sport, "odds_history", now), HISTORY_FIELDS, hist_rows)
    append_rows(monthly_path(sport, "odds_books", now), BOOK_FIELDS, book_out)
    note = f"（{unmatched} 場沒對到 ESPN 編號）" if unmatched else ""
    print(f"  {cfg['name']}: 共 {len(games)} 場，寫入 {len(hist_rows)} 場快照、{len(book_out)} 筆莊家賠率變動{note}")
    return len(hist_rows)


def run(use_browser=False):
    now = datetime.now(timezone.utc)
    state = load_state()
    blocked, fetched = [], {}

    if use_browser:
        with BrowserFetcher() as bf:
            for sport in active_sports():
                try:
                    fetched[sport] = bf.fetch(sport)
                except Blocked:
                    blocked.append(sport)
                except Exception as e:
                    print(f"  {sport}: 讀取失敗 {e}")
    else:
        for sport in active_sports():
            try:
                fetched[sport] = fetch_direct(sport)
            except Blocked:
                blocked.append(sport)
            except Exception as e:
                print(f"  {sport}: 讀取失敗 {e}")

    total = 0
    for sport, games in fetched.items():
        try:
            total += process_sport(sport, games, now, state) or 0
        except Exception as e:
            total += 1          # 出錯時照樣跑後面的步驟，不要靜靜跳過
            print(f"  {sport}: 處理失敗 {e}")
    save_state(state, now)
    # 排程每 10 分鐘醒來一次；這次沒有任何比賽到了該記錄的時間 → 留記號，workflow 就跳過後面的步驟
    if total == 0 and not blocked:
        open(NOTHING_DUE, "w").close()

    if blocked:
        print(f"被網站擋下：{', '.join(blocked)}")
        if not use_browser and len(blocked) == len(active_sports()):
            sys.exit(3)


if __name__ == "__main__":
    run(use_browser="--browser" in sys.argv)
