"""
比賽背景資料抓取（多運動版）：球場、天氣、先發投手、季後賽標記
============================================
每天跑幾次就夠了（先發投手、天氣預報不會像資金流向那樣分秒在變）。
資料來源都免費、不用申請 key：
- ESPN 賽程：球場、城市、是否室內、中立場地、季後賽說明、MLB 先發投手
- Open-Meteo：天氣預報（只抓戶外運動：MLB、NFL、NCAAF；室內球場跳過）
  球場座標用 Open-Meteo 的地名查詢，查過一次就存起來，不會重複查

每種運動存在 docs/data/<運動>/context.csv，用 event_id 跟 odds_history 對起來。

⚠️ 主審（裁判）的賽前指派名單目前沒有穩定的免費來源，umpire_name 先留空當手動欄位。
"""

import json
import os
from datetime import datetime, timezone, timedelta

import requests

from sports_common import (MLB_ROOF_TEAMS, SPORTS, STATE_DIR, UA, append_rows, espn_events, sport_dir)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
COORDS_FILE = os.path.join(STATE_DIR, "venue_coords.json")
HORIZON_H = 36

CONTEXT_FIELDS = [
    "timestamp_utc", "sport", "event_id", "game_time_utc", "season_type", "series_note",
    "away_team", "home_team", "venue", "city", "region", "indoor", "neutral_site",
    "temp_f", "wind_mph", "wind_dir_deg", "precip_prob_pct",
    "away_probable_pitcher", "home_probable_pitcher", "umpire_name",
]

REGION_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California", "CO": "Colorado",
    "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia",
    "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts",
    "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota",
    "TN": "Tennessee", "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
    "ON": "Ontario", "QC": "Quebec", "BC": "British Columbia", "AB": "Alberta", "MB": "Manitoba",
}


def load_coords():
    if os.path.exists(COORDS_FILE):
        with open(COORDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_coords(coords):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(COORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(coords, f, ensure_ascii=False, indent=1, sort_keys=True)


def geocode(city, region):
    """城市名稱 → 經緯度（Open-Meteo 地名查詢，免費）"""
    if not city:
        return None
    region_full = REGION_NAMES.get(region, region)
    r = requests.get(GEOCODE_URL, params={"name": city, "count": 10, "language": "en"}, timeout=15, headers=UA)
    r.raise_for_status()
    results = r.json().get("results") or []
    for x in results:
        if region_full and x.get("admin1", "").lower() == region_full.lower():
            return [x["latitude"], x["longitude"]]
    for x in results:
        if x.get("country_code") in ("US", "CA"):
            return [x["latitude"], x["longitude"]]
    return None


def get_weather(lat, lon, target_time_utc):
    """Open-Meteo 天氣預報：抓開賽那個小時的預報"""
    params = {
        "latitude": lat, "longitude": lon,
        "hourly": "temperature_2m,windspeed_10m,winddirection_10m,precipitation_probability",
        "temperature_unit": "fahrenheit", "windspeed_unit": "mph", "timezone": "UTC", "forecast_days": 3,
    }
    resp = requests.get(OPEN_METEO_URL, params=params, timeout=15, headers=UA)
    resp.raise_for_status()
    h = resp.json()["hourly"]
    prefix = target_time_utc.strftime("%Y-%m-%dT%H")
    for i, t in enumerate(h["time"]):
        if t.startswith(prefix):
            return {"temp_f": h["temperature_2m"][i], "wind_mph": h["windspeed_10m"][i],
                    "wind_dir_deg": h["winddirection_10m"][i], "precip_prob_pct": h["precipitation_probability"][i]}
    return {}


def run():
    now = datetime.now(timezone.utc)
    coords = load_coords()
    for sport, cfg in SPORTS.items():
        try:
            events = espn_events(sport, now, now + timedelta(hours=HORIZON_H))
        except Exception as e:
            print(f"{cfg['name']}: ESPN 賽程讀取失敗 {e}")
            continue
        rows = []
        for ev in events:
            if ev["state"] != "pre" or not (now <= ev["time"] <= now + timedelta(hours=HORIZON_H)):
                continue
            indoor = bool(ev["indoor"]) or not cfg["outdoor"]
            if sport == "mlb" and ev["home"].get("abbr") in MLB_ROOF_TEAMS:
                indoor = True
            weather = {}
            if not indoor:
                key = ev["venue_id"] or f"{ev['city']}|{ev['region']}"
                try:
                    if key not in coords:
                        coords[key] = geocode(ev["city"], ev["region"])
                    if coords[key]:
                        weather = get_weather(coords[key][0], coords[key][1], ev["time"])
                except Exception as e:
                    print(f"  天氣抓取失敗 ({ev['venue']}): {e}")
            rows.append({
                "timestamp_utc": now.isoformat(), "sport": sport, "event_id": ev["event_id"],
                "game_time_utc": ev["time"].isoformat(), "season_type": ev["season_type"],
                "series_note": ev["series_note"],
                "away_team": ev["away"].get("display"), "home_team": ev["home"].get("display"),
                "venue": ev["venue"], "city": ev["city"], "region": ev["region"],
                "indoor": indoor, "neutral_site": ev["neutral_site"],
                **weather,
                "away_probable_pitcher": ev["away"].get("probable", "") if sport == "mlb" else "",
                "home_probable_pitcher": ev["home"].get("probable", "") if sport == "mlb" else "",
                "umpire_name": "",
            })
        append_rows(os.path.join(sport_dir(sport), "context.csv"), CONTEXT_FIELDS, rows)
        print(f"{cfg['name']}: 寫入 {len(rows)} 場背景資料")
    save_coords(coords)


if __name__ == "__main__":
    run()
