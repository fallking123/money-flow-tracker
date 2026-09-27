"""
比賽背景資料抓取（先發投手 + 天氣）
============================================
這支跑得比 scrape_odds.py 少很多次就夠了（建議每 60 分鐘一次），
因為先發投手名單、天氣預報不會像資金流向那樣分秒在變。

⚠️ 誠實說明一個限制：主審(裁判)的「賽前指派名單」，我沒能找到一個
可以穩定、免費抓取的公開來源 —— umpscorecards.com 提供的是「賽後」
好球帶準確率分析，不是賽前指派名單。目前這欄位先留空、當手動輸入欄位，
你如果找到穩定的指派名單來源(例如某個固定會公布的網站)，
再貼給我，我幫你把抓取邏輯補上去。
"""

import csv
import os
from datetime import datetime, timezone, timedelta

import requests

from mlb_common import get_schedule, BALLPARK_COORDS, DOME_TEAMS, guess_team_abbr

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
CONTEXT_CSV = os.path.join(DATA_DIR, "context.csv")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def get_weather(lat: float, lon: float, target_time_utc: datetime) -> dict:
    """
    Open-Meteo 免費天氣 API，不用申請 key。
    抓目標時間點最接近的那一個小時的預報。
    """
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "temperature_2m,windspeed_10m,winddirection_10m,precipitation_probability",
        "temperature_unit": "fahrenheit",
        "windspeed_unit": "mph",
        "timezone": "UTC",
        "forecast_days": 3,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    times = data["hourly"]["time"]
    target_str_prefix = target_time_utc.strftime("%Y-%m-%dT%H")
    for i, t in enumerate(times):
        if t.startswith(target_str_prefix):
            return {
                "temp_f": data["hourly"]["temperature_2m"][i],
                "wind_mph": data["hourly"]["windspeed_10m"][i],
                "wind_dir_deg": data["hourly"]["winddirection_10m"][i],
                "precip_prob_pct": data["hourly"]["precipitation_probability"][i],
            }
    return {"temp_f": None, "wind_mph": None, "wind_dir_deg": None, "precip_prob_pct": None}


def run():
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%Y-%m-%d")
    tomorrow_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    games = get_schedule(today_str) + get_schedule(tomorrow_str)

    file_exists = os.path.exists(CONTEXT_CSV)
    rows_written = 0

    with open(CONTEXT_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp_utc", "game_id", "away_team", "home_team", "venue",
                "away_probable_pitcher", "home_probable_pitcher",
                "is_dome", "temp_f", "wind_mph", "wind_dir_deg", "precip_prob_pct",
                "umpire_name",  # 手動欄位，暫無自動來源
            ],
        )
        if not file_exists:
            writer.writeheader()

        for g in games:
            home_abbr = guess_team_abbr(g["home_team"])
            is_dome = home_abbr in DOME_TEAMS if home_abbr else None

            weather = {"temp_f": None, "wind_mph": None, "wind_dir_deg": None, "precip_prob_pct": None}
            if home_abbr and home_abbr in BALLPARK_COORDS and not is_dome:
                lat, lon = BALLPARK_COORDS[home_abbr]
                game_time = datetime.fromisoformat(g["game_time_utc"].replace("Z", "+00:00"))
                try:
                    weather = get_weather(lat, lon, game_time)
                except Exception as e:
                    print(f"天氣抓取失敗 ({g['home_team']}): {e}")

            writer.writerow(
                {
                    "timestamp_utc": now.isoformat(),
                    "game_id": g["game_id"],
                    "away_team": g["away_team"],
                    "home_team": g["home_team"],
                    "venue": g["venue"],
                    "away_probable_pitcher": g["away_probable_pitcher"],
                    "home_probable_pitcher": g["home_probable_pitcher"],
                    "is_dome": is_dome,
                    "temp_f": weather["temp_f"],
                    "wind_mph": weather["wind_mph"],
                    "wind_dir_deg": weather["wind_dir_deg"],
                    "precip_prob_pct": weather["precip_prob_pct"],
                    "umpire_name": "",  # 留給你手動填，或之後找到來源再自動化
                }
            )
            rows_written += 1

    print(f"寫入 {rows_written} 場比賽的背景資料。")


if __name__ == "__main__":
    run()
