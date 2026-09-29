"""
比賽背景資料抓取（多運動版）：球場、天氣、先發投手、季後賽標記
============================================
每天跑幾次就夠了（先發投手、天氣預報不會像資金流向那樣分秒在變）。
資料來源都免費、不用申請 key：
- ESPN 賽程：球場、城市、是否室內、中立場地、季後賽說明、先發投手（MLB）／先發門將（NHL）、戰績
- ESPN 過去幾天賽程：每隊休息幾天、是否背靠背、7 天內出賽數、上一場是否客場（算疲勞、移動）
- ESPN 單場資訊：傷兵名單（Out／存疑）
- Open-Meteo：天氣預報（只抓戶外運動：MLB、NFL、NCAAF；室內球場跳過）
  球場座標用 Open-Meteo 的地名查詢，查過一次就存起來，不會重複查

每種運動存在 docs/data/<運動>/context.csv，用 event_id 跟 odds_history 對起來。

⚠️ 主審（裁判）的賽前指派名單目前沒有穩定的免費來源，umpire_name 先留空當手動欄位。
"""

import csv
import json
import os
from datetime import datetime, timezone, timedelta

import requests

from sports_common import (ET, MLB_ROOF_TEAMS, SPORTS, active_sports, STATE_DIR, UA, append_rows, espn_events, read_rows, sport_dir)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
COORDS_FILE = os.path.join(STATE_DIR, "venue_coords.json")
HORIZON_H = 36

CONTEXT_FIELDS = [
    "timestamp_utc", "sport", "event_id", "game_time_utc", "season_type", "series_note",
    "away_team", "home_team", "venue", "city", "region", "indoor", "neutral_site",
    "temp_f", "wind_mph", "wind_dir_deg", "precip_prob_pct",
    "away_probable_pitcher", "home_probable_pitcher", "umpire_name",
    "away_pitcher_stat", "home_pitcher_stat",
    # 各運動共用：戰績、休息、傷兵（NBA/NHL 背靠背、NFL 短週／bye 很關鍵）
    "away_record", "home_record", "away_road_record", "home_home_record",
    "away_rest_days", "home_rest_days", "away_b2b", "home_b2b", "away_games_7d", "home_games_7d",
    "away_last_away", "home_last_away",
    "away_out_n", "home_out_n", "away_injuries", "home_injuries",
]

PROBABLE_SPORTS = ("mlb", "nhl")  # MLB 先發投手、NHL 先發門將（沿用 *_probable_pitcher 欄位）
REST_LOOKBACK_D = {"nfl": 16}     # 往回找上一場：美式足球一週一場，要找久一點；其他 10 天

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


def migrate(path):
    """舊檔案沒有新欄位（投手成績）的話，先補表頭，不然新資料會對不齊"""
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        header = next(csv.reader(f), [])
    if header != CONTEXT_FIELDS:
        rows = read_rows(path)
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CONTEXT_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)


def team_history(sport, now):
    """過去幾天每隊打過的比賽：{隊伍ID: [(開賽時間, 主客)]}"""
    days = REST_LOOKBACK_D.get(sport, 10)
    hist = {}
    for ev in espn_events(sport, now - timedelta(days=days), now):
        if ev["state"] == "pre":
            continue
        for side in ("away", "home"):
            tid = ev[side].get("id")
            if tid:
                hist.setdefault(tid, []).append((ev["time"], side))
    return hist


def rest_info(hist, tid, game_time):
    """休息天數（用美東日期算，昨天有打＝1＝背靠背）、7 天內場數、上一場是不是客場"""
    prior = [(t, s) for t, s in hist.get(tid, []) if t < game_time - timedelta(hours=2)]
    if not prior:
        return {}
    last_t, last_side = max(prior)
    rest = (game_time.astimezone(ET).date() - last_t.astimezone(ET).date()).days
    return {"rest": rest, "b2b": rest == 1,
            "g7": sum(1 for t, _ in prior if t >= game_time - timedelta(days=7)),
            "last_away": last_side == "away"}


OUT_WORDS = ("out", "reserve", "suspen", "il")


def injuries(sport, event_id):
    """ESPN 單場資訊的傷兵名單：{隊伍ID: (確定缺陣人數, 文字)}"""
    url = f"https://site.api.espn.com/apis/site/v2/sports/{SPORTS[sport]['espn']}/summary"
    r = requests.get(url, params={"event": event_id}, timeout=30)
    r.raise_for_status()
    out = {}
    for blk in r.json().get("injuries") or []:
        tid = str((blk.get("team") or {}).get("id", ""))
        outs, maybe = [], []
        for inj in blk.get("injuries") or []:
            st = (inj.get("status") or (inj.get("type") or {}).get("description") or "").strip()
            ath = inj.get("athlete") or {}
            nm = ath.get("shortName") or ath.get("displayName") or ""
            pos = (ath.get("position") or {}).get("abbreviation") or ""
            who = f"{nm}({pos})" if pos else nm
            if not nm:
                continue
            (outs if any(w in st.lower() for w in OUT_WORDS) else maybe).append(who)
        txt = []
        if outs:
            txt.append("缺陣：" + "、".join(outs[:8]))
        if maybe:
            txt.append("存疑：" + "、".join(maybe[:6]))
        out[tid] = (len(outs), "｜".join(txt))
    return out


def run():
    now = datetime.now(timezone.utc)
    coords = load_coords()
    for sport, cfg in active_sports().items():
        try:
            events = espn_events(sport, now, now + timedelta(hours=HORIZON_H))
        except Exception as e:
            print(f"{cfg['name']}: ESPN 賽程讀取失敗 {e}")
            continue
        try:
            hist = team_history(sport, now)
        except Exception as e:
            print(f"  {cfg['name']}: 過去賽程讀取失敗（休息天數先留空）: {e}")
            hist = {}
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
            extra = {}
            for side in ("away", "home"):
                t = ev[side]
                rec = t.get("records") or {}
                extra[f"{side}_record"] = rec.get("total", "")
                ri = rest_info(hist, t.get("id"), ev["time"])
                if ri:
                    extra.update({f"{side}_rest_days": ri["rest"], f"{side}_b2b": ri["b2b"],
                                  f"{side}_games_7d": ri["g7"], f"{side}_last_away": ri["last_away"]})
            extra["away_road_record"] = (ev["away"].get("records") or {}).get("road", "")
            extra["home_home_record"] = (ev["home"].get("records") or {}).get("home", "")
            try:
                inj = injuries(sport, ev["event_id"])
                for side in ("away", "home"):
                    n, txt = inj.get(ev[side].get("id"), (0, ""))
                    extra[f"{side}_out_n"], extra[f"{side}_injuries"] = n, txt
            except Exception as e:
                print(f"  傷兵名單抓取失敗 ({ev['away'].get('abbr')}@{ev['home'].get('abbr')}): {e}")
            prob = sport in PROBABLE_SPORTS
            rows.append({
                **extra,
                "timestamp_utc": now.isoformat(), "sport": sport, "event_id": ev["event_id"],
                "game_time_utc": ev["time"].isoformat(), "season_type": ev["season_type"],
                "series_note": ev["series_note"],
                "away_team": ev["away"].get("display"), "home_team": ev["home"].get("display"),
                "venue": ev["venue"], "city": ev["city"], "region": ev["region"],
                "indoor": indoor, "neutral_site": ev["neutral_site"],
                **weather,
                "away_probable_pitcher": ev["away"].get("probable", "") if prob else "",
                "home_probable_pitcher": ev["home"].get("probable", "") if prob else "",
                "umpire_name": "",
                "away_pitcher_stat": ev["away"].get("probable_stat", "") if prob else "",
                "home_pitcher_stat": ev["home"].get("probable_stat", "") if prob else "",
            })
        path = os.path.join(sport_dir(sport), "context.csv")
        migrate(path)
        append_rows(path, CONTEXT_FIELDS, rows)
        print(f"{cfg['name']}: 寫入 {len(rows)} 場背景資料")
    save_coords(coords)


if __name__ == "__main__":
    run()
