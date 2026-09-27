"""
資金流向抓取主程式（分層頻率版 v2）
============================================
v2 改進：
1. 網址改成已確認的 MLB 版頁面
2. 除了讀網頁文字，另外把網頁背後載入的「原始資料(JSON)」整包存下來。
   這個網站的表格是由背景程式載入資料後才畫出來的，那份原始資料最完整、最精確，
   有了它之後我可以寫出 100% 對得上的解析規則，不用再靠猜網頁排版。
3. 分層頻率：距開賽 >3 小時每 120 分鐘、1~3 小時每 30 分鐘、<1 小時每 12 分鐘
"""

import csv
import json
import os
import re
from datetime import datetime, timezone, timedelta

from playwright.sync_api import sync_playwright

from mlb_common import get_schedule, hours_until, guess_team_abbr

SBD_URL = "https://www.sportsbettingdime.com/mlb/public-betting-trends/"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
RAW_DIR = os.path.join(DATA_DIR, "raw")
STATE_FILE = os.path.join(DATA_DIR, "state", "last_snapshot.json")
HISTORY_CSV = os.path.join(DATA_DIR, "odds_history.csv")

os.makedirs(RAW_DIR, exist_ok=True)
os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)

TEAM_PCT_PATTERN = re.compile(r"([A-Z][A-Za-z.\'\- ]{2,40}?)\s+(\d{1,3})%\s+(\d{1,3})%")


def tier_interval_minutes(hrs_to_game: float) -> int:
    if hrs_to_game > 3:
        return 120
    elif hrs_to_game > 1:
        return 30
    return 12


def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def parse_page_text(text: str):
    """暫時性的通用解析，拿到原始 JSON 後會換成精確版本"""
    rows = []
    for m in TEAM_PCT_PATTERN.finditer(text):
        team, a, b = m.groups()
        team = team.strip()
        if len(team) >= 3:
            rows.append({"team_text": team, "bet_pct": int(a), "money_pct": int(b)})
    return rows


def fetch_page(ts_str: str):
    """打開網頁，同時存下：頁面文字 + 背景載入的所有 JSON 原始資料"""
    captured = []

    def on_response(resp):
        try:
            ctype = resp.headers.get("content-type", "")
            if "json" in ctype and resp.request.resource_type in ("xhr", "fetch"):
                captured.append({"url": resp.url, "body": resp.json()})
        except Exception:
            pass

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 2400})
        page.on("response", on_response)
        page.goto(SBD_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(5000)
        body_text = page.inner_text("body")
        browser.close()

    with open(os.path.join(RAW_DIR, f"{ts_str}.txt"), "w", encoding="utf-8") as f:
        f.write(body_text)
    if captured:
        with open(os.path.join(RAW_DIR, f"{ts_str}_network.json"), "w", encoding="utf-8") as f:
            json.dump(captured, f, ensure_ascii=False, indent=1)

    return body_text, captured


def run():
    now = datetime.now(timezone.utc)
    ts_str = now.strftime("%Y-%m-%dT%H-%M-%SZ")

    games = get_schedule(now.strftime("%Y-%m-%d")) + get_schedule(
        (now + timedelta(days=1)).strftime("%Y-%m-%d")
    )

    upcoming = []
    for g in games:
        h = hours_until(g["game_time_utc"])
        if 0 <= h <= 24:
            g["_hours_until"] = h
            upcoming.append(g)

    if not upcoming:
        print("目前沒有未來 24 小時內的比賽，本次不抓取。")
        return

    state = load_state()
    due_games = []
    for g in upcoming:
        last = state.get(str(g["game_id"]))
        if last is None or (now - datetime.fromisoformat(last)).total_seconds() / 60 >= tier_interval_minutes(g["_hours_until"]):
            due_games.append(g)

    if not due_games:
        print("所有比賽都還沒到下一次該存檔的時間點，本次不抓取。")
        return

    body_text, captured = fetch_page(ts_str)
    print(f"背景原始資料共攔截到 {len(captured)} 份")

    parsed_rows = parse_page_text(body_text)
    if not parsed_rows:
        print("⚠️ 這次沒解析到隊伍數據，但原始資料已存檔於 docs/data/raw/，請交給 Claude 核對。")
        return

    file_exists = os.path.exists(HISTORY_CSV)
    written = 0
    with open(HISTORY_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "timestamp_utc", "game_id", "away_team", "home_team", "game_time_utc",
            "hours_until_game", "team_text", "bet_pct", "money_pct", "gap",
        ])
        if not file_exists:
            writer.writeheader()
        for g in due_games:
            gid = str(g["game_id"])
            abbrs = (guess_team_abbr(g["away_team"]), guess_team_abbr(g["home_team"]))
            matched = False
            for r in parsed_rows:
                ra = guess_team_abbr(r["team_text"])
                if ra is not None and ra in abbrs:
                    writer.writerow({
                        "timestamp_utc": now.isoformat(), "game_id": gid,
                        "away_team": g["away_team"], "home_team": g["home_team"],
                        "game_time_utc": g["game_time_utc"],
                        "hours_until_game": round(g["_hours_until"], 2),
                        "team_text": r["team_text"], "bet_pct": r["bet_pct"],
                        "money_pct": r["money_pct"], "gap": r["money_pct"] - r["bet_pct"],
                    })
                    written += 1
                    matched = True
            if matched:
                state[gid] = now.isoformat()

    save_state(state)
    print(f"寫入 {written} 筆資料，涵蓋 {len(due_games)} 場到期比賽。")


if __name__ == "__main__":
    run()
