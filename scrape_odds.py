"""
資金流向抓取主程式 v3（直接讀網站背後的原始資料）
====================================================
資料來源：SportsBettingDime 頁面背後載入的 mlb-odds 原始資料（JSON），
不再讀網頁畫面文字，數字精確到小數點，不會有辨識錯誤。

每次抓取會存兩份表：
1. docs/data/odds_history.csv  —— 每場比賽一列（核心資料）
   三種盤（獨贏 / 讓分 / 大小分）的 bet% 與 money%、
   六家美國莊家的共識賠率（目前 + 開盤）、讓分與總分線（目前 + 開盤）、
   去水後隱含機率
2. docs/data/odds_books.csv    —— 每家莊家、每個盤、每一邊的賠率明細（盤口移動分析用）

分層頻率：距開賽 >3 小時每 120 分鐘、1~3 小時每 30 分鐘、1 小時內每 10 分鐘
"""

import csv
import gzip
import json
import os
import statistics
from datetime import datetime, timezone, timedelta

import requests
from playwright.sync_api import sync_playwright

from mlb_common import get_schedule, guess_team_abbr

PAGE_URL = "https://www.sportsbettingdime.com/mlb/public-betting-trends/"
API_MARKER = "/wp-json/adpt/v1/mlb-odds"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
STATE_FILE = os.path.join(DATA_DIR, "state", "last_snapshot.json")
HISTORY_CSV = os.path.join(DATA_DIR, "odds_history.csv")
BOOKS_CSV = os.path.join(DATA_DIR, "odds_books.csv")

HISTORY_FIELDS = [
    "timestamp_utc", "sbd_id", "mlb_game_id", "game_time_utc", "hours_until_game",
    "away_team", "home_team", "away_abbr", "home_abbr",
    # 獨贏 Moneyline
    "ml_splits_updated", "ml_away_bets_pct", "ml_away_money_pct", "ml_home_bets_pct", "ml_home_money_pct",
    "ml_away_odds", "ml_home_odds", "ml_away_open_odds", "ml_home_open_odds",
    "ml_away_novig_prob", "ml_home_novig_prob",
    # 讓分 Run line（以客隊角度記錄讓分值）
    "rl_splits_updated", "rl_away_bets_pct", "rl_away_money_pct", "rl_home_bets_pct", "rl_home_money_pct",
    "rl_away_line", "rl_away_open_line", "rl_away_odds", "rl_home_odds",
    # 大小分 Total
    "ou_splits_updated", "ou_over_bets_pct", "ou_over_money_pct", "ou_under_bets_pct", "ou_under_money_pct",
    "ou_line", "ou_open_line", "ou_over_odds", "ou_under_odds",
    "books_count",
]
BOOK_FIELDS = [
    "timestamp_utc", "sbd_id", "market", "book", "side",
    "odds_american", "open_odds_american", "line", "open_line",
]


# ---------------- 工具函數 ----------------
def tier_interval_minutes(hrs: float) -> int:
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


def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default


def append_rows(path, fields, rows):
    if not rows:
        return
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if not exists:
            w.writeheader()
        w.writerows(rows)


# ---------------- 抓資料 ----------------
def fetch_api_data():
    """打開網頁，攔截它背後載入的 mlb-odds 原始資料"""
    captured = {}

    def on_response(resp):
        if API_MARKER in resp.url and "body" not in captured:
            try:
                captured["url"] = resp.url
                captured["body"] = resp.json()
            except Exception:
                pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.on("response", on_response)
        page.goto(PAGE_URL, wait_until="networkidle", timeout=90000)
        page.wait_for_timeout(3000)
        browser.close()

    if "body" in captured:
        return captured["body"]

    # 備援：網頁沒攔到就直接向資料網址要一次
    fallback = ("https://www.sportsbettingdime.com/wp-json/adpt/v1/mlb-odds?books="
                "sr%3Abook%3A17324%2Csr%3Abook%3A18149%2Csr%3Abook%3A27447%2C"
                "sr%3Abook%3A28901%2Csr%3Abook%3A32219%2Csr%3Abook%3A18186&format=us")
    r = requests.get(fallback, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    return r.json()


def compact_game(g):
    """原始資料瘦身版（拿掉球隊簡介等用不到的欄位）"""
    c = g.get("competitors", {})
    return {
        "id": g.get("id"), "status": g.get("status"), "scheduled": g.get("scheduled"),
        "away": {k: c.get("away", {}).get(k) for k in ("name", "abbr", "market")},
        "home": {k: c.get("home", {}).get(k) for k in ("name", "abbr", "market")},
        "markets": g.get("markets"), "bettingSplits": g.get("bettingSplits"),
    }


# ---------------- 解析 ----------------
def split_vals(splits, market, side):
    s = (splits or {}).get(market, {}).get(side, {}) or {}
    return s.get("betsPercentage"), s.get("stakePercentage")


def build_rows(g, now, mlb_game_id):
    c = g["competitors"]
    splits = g.get("bettingSplits") or {}
    markets = g.get("markets") or {}
    ts = now.isoformat()
    sched = datetime.fromisoformat(g["scheduled"].replace("Z", "+00:00"))
    hrs = (sched - now).total_seconds() / 3600

    book_rows = []
    agg = {}  # (market, side) -> list

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
                    "timestamp_utc": ts, "sbd_id": g["id"], "market": market,
                    "book": b.get("name"), "side": side,
                    "odds_american": o.get("odds"), "open_odds_american": o.get("opening_odds"),
                    "line": line, "open_line": open_line,
                })
                add((market, side, "odds"), american_to_decimal(o.get("odds")))
                add((market, side, "open"), american_to_decimal(o.get("opening_odds")))
                add((market, side, "line"), line)
                add((market, side, "open_line"), open_line)

    ml_a, ml_h = median_decimal(agg.get(("moneyline", "away", "odds"), [])), median_decimal(agg.get(("moneyline", "home", "odds"), []))
    novig_a = novig_h = None
    if ml_a and ml_h:
        pa, ph = 1 / ml_a, 1 / ml_h
        novig_a, novig_h = round(pa / (pa + ph), 4), round(ph / (pa + ph), 4)

    mlb_a, mlb_m = split_vals(splits, "moneyline", "away")
    mlh_b, mlh_m = split_vals(splits, "moneyline", "home")
    rla_b, rla_m = split_vals(splits, "spread", "away")
    rlh_b, rlh_m = split_vals(splits, "spread", "home")
    ov_b, ov_m = split_vals(splits, "total", "over")
    un_b, un_m = split_vals(splits, "total", "under")

    row = {
        "timestamp_utc": ts, "sbd_id": g["id"], "mlb_game_id": mlb_game_id or "",
        "game_time_utc": g["scheduled"], "hours_until_game": round(hrs, 2),
        "away_team": c["away"].get("name"), "home_team": c["home"].get("name"),
        "away_abbr": c["away"].get("abbr"), "home_abbr": c["home"].get("abbr"),
        "ml_splits_updated": (splits.get("moneyline") or {}).get("updated", ""),
        "ml_away_bets_pct": mlb_a, "ml_away_money_pct": mlb_m,
        "ml_home_bets_pct": mlh_b, "ml_home_money_pct": mlh_m,
        "ml_away_odds": ml_a, "ml_home_odds": ml_h,
        "ml_away_open_odds": median_decimal(agg.get(("moneyline", "away", "open"), [])),
        "ml_home_open_odds": median_decimal(agg.get(("moneyline", "home", "open"), [])),
        "ml_away_novig_prob": novig_a, "ml_home_novig_prob": novig_h,
        "rl_splits_updated": (splits.get("spread") or {}).get("updated", ""),
        "rl_away_bets_pct": rla_b, "rl_away_money_pct": rla_m,
        "rl_home_bets_pct": rlh_b, "rl_home_money_pct": rlh_m,
        "rl_away_line": mode_value(agg.get(("spread", "away", "line"), [])),
        "rl_away_open_line": mode_value(agg.get(("spread", "away", "open_line"), [])),
        "rl_away_odds": median_decimal(agg.get(("spread", "away", "odds"), [])),
        "rl_home_odds": median_decimal(agg.get(("spread", "home", "odds"), [])),
        "ou_splits_updated": (splits.get("total") or {}).get("updated", ""),
        "ou_over_bets_pct": ov_b, "ou_over_money_pct": ov_m,
        "ou_under_bets_pct": un_b, "ou_under_money_pct": un_m,
        "ou_line": mode_value(agg.get(("total", "over", "line"), [])),
        "ou_open_line": mode_value(agg.get(("total", "over", "open_line"), [])),
        "ou_over_odds": median_decimal(agg.get(("total", "over", "odds"), [])),
        "ou_under_odds": median_decimal(agg.get(("total", "under", "odds"), [])),
        "books_count": len((markets.get("moneyline") or {}).get("books", [])),
    }
    return row, book_rows, hrs


def mlb_id_lookup(now):
    """用 MLB 官方賽程，把每場比賽對應到官方 game_id（之後對賽果用）"""
    lookup = []
    for d in range(-1, 3):
        try:
            for g in get_schedule((now + timedelta(days=d)).strftime("%Y-%m-%d")):
                lookup.append(g)
        except Exception as e:
            print(f"MLB 賽程讀取失敗: {e}")
    return lookup


def match_mlb_id(g, lookup):
    a = guess_team_abbr(g["competitors"]["away"].get("name", ""))
    h = guess_team_abbr(g["competitors"]["home"].get("name", ""))
    sched = datetime.fromisoformat(g["scheduled"].replace("Z", "+00:00"))
    best, best_gap = None, None
    for m in lookup:
        if guess_team_abbr(m["away_team"]) == a and guess_team_abbr(m["home_team"]) == h:
            gap = abs((datetime.fromisoformat(m["game_time_utc"].replace("Z", "+00:00")) - sched).total_seconds())
            if gap < 12 * 3600 and (best_gap is None or gap < best_gap):
                best, best_gap = m["game_id"], gap
    return best


# ---------------- 主流程 ----------------
def run():
    now = datetime.now(timezone.utc)
    os.makedirs(RAW_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

    body = fetch_api_data()
    games = body.get("data", [])
    print(f"原始資料共 {len(games)} 場比賽")

    # 每天第一次抓取存一份瘦身原始檔（稽核/除錯用，壓縮後很小）
    raw_path = os.path.join(RAW_DIR, f"{now.strftime('%Y-%m-%d')}.json.gz")
    if not os.path.exists(raw_path):
        with gzip.open(raw_path, "wt", encoding="utf-8") as f:
            json.dump([compact_game(g) for g in games], f, ensure_ascii=False)

    state = load_json(STATE_FILE, {})
    lookup = None
    hist_rows, all_book_rows = [], []

    for g in games:
        if g.get("status") != "not_started":
            continue
        sched = datetime.fromisoformat(g["scheduled"].replace("Z", "+00:00"))
        hrs = (sched - now).total_seconds() / 3600
        if not (0 <= hrs <= 24):
            continue
        last = state.get(g["id"])
        # 容許約 1/4 間隔的誤差：GitHub 排程常延遲幾分鐘，避免剛好差一點就跳過一次
        interval = tier_interval_minutes(hrs)
        if last and (now - datetime.fromisoformat(last)).total_seconds() / 60 < interval * 0.75:
            continue
        if lookup is None:
            lookup = mlb_id_lookup(now)
        row, book_rows, _ = build_rows(g, now, match_mlb_id(g, lookup))
        hist_rows.append(row)
        all_book_rows.extend(book_rows)
        state[g["id"]] = now.isoformat()

    append_rows(HISTORY_CSV, HISTORY_FIELDS, hist_rows)
    append_rows(BOOKS_CSV, BOOK_FIELDS, all_book_rows)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1)

    print(f"本次寫入 {len(hist_rows)} 場比賽快照、{len(all_book_rows)} 筆莊家賠率明細")


if __name__ == "__main__":
    run()
