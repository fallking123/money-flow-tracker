"""
共用模組：MLB 官方 Stats API 封裝 + 球場座標表
MLB Stats API 完全免費、不用申請 API key：https://statsapi.mlb.com

這支模組是整套系統的「比賽身分證中心」——所有其他程式(抓資金流向、抓天氣、
抓賽果)都靠這裡拿到的 game_id、開賽時間、球場，才能對得起來、湊成同一場比賽的完整紀錄。
"""

import requests
from datetime import datetime, timezone

MLB_SCHEDULE_URL = "https://statsapi.mlb.com/api/v1/schedule"

# 30 座 MLB 球場的概略座標，給天氣 API 查詢用（不需要到公尺級精準）
BALLPARK_COORDS = {
    "ARI": (33.4455, -112.0667), "ATL": (33.8908, -84.4678), "BAL": (39.2839, -76.6218),
    "BOS": (42.3467, -71.0972), "CHC": (41.9484, -87.6553), "CWS": (41.8299, -87.6338),
    "CIN": (39.0979, -84.5082), "CLE": (41.4962, -81.6852), "COL": (39.7559, -104.9942),
    "DET": (42.3390, -83.0485), "HOU": (29.7573, -95.3555), "KC": (39.0517, -94.4803),
    "LAA": (33.8003, -117.8827), "LAD": (34.0739, -118.2400), "MIA": (25.7781, -80.2196),
    "MIL": (43.0280, -87.9712), "MIN": (44.9817, -93.2776), "NYM": (40.7571, -73.8458),
    "NYY": (40.8296, -73.9262), "OAK": (37.7516, -122.2005), "PHI": (39.9061, -75.1665),
    "PIT": (40.4469, -80.0057), "SD": (32.7073, -117.1566), "SEA": (47.5914, -122.3325),
    "SF": (37.7786, -122.3893), "STL": (38.6226, -90.1928), "TB": (27.7683, -82.6534),
    "TEX": (32.7473, -97.0847), "TOR": (43.6414, -79.3894), "WSH": (38.8730, -77.0074),
}

# 室內/固定圓頂球場：這幾隊的天氣資料意義不大(可以在分析階段直接排除)
DOME_TEAMS = {"TB", "TOR", "MIA", "MIL", "HOU", "SEA", "TEX", "ARI"}  # 後四隊是可開闔式屋頂


def get_schedule(date_str: str) -> list:
    """
    抓某一天(YYYY-MM-DD)的完整 MLB 賽程，含先發投手、球場、開賽時間(UTC)。
    回傳一個 list，每個元素是一場比賽的 dict。
    """
    params = {
        "sportId": 1,
        "date": date_str,
        "hydrate": "probablePitcher,team,venue,linescore",
    }
    resp = requests.get(MLB_SCHEDULE_URL, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()

    games = []
    for date_block in data.get("dates", []):
        for g in date_block.get("games", []):
            away = g["teams"]["away"]
            home = g["teams"]["home"]
            games.append(
                {
                    "game_id": g["gamePk"],
                    "game_time_utc": g["gameDate"],  # ISO8601 UTC
                    "status": g["status"]["detailedState"],
                    "away_team": away["team"]["name"],
                    "home_team": home["team"]["name"],
                    "away_score": away.get("score"),
                    "home_score": home.get("score"),
                    "venue": g.get("venue", {}).get("name"),
                    "away_probable_pitcher": away.get("probablePitcher", {}).get("fullName"),
                    "home_probable_pitcher": home.get("probablePitcher", {}).get("fullName"),
                }
            )
    return games


def hours_until(game_time_utc_str: str) -> float:
    """算現在距離開賽還有幾小時（可能是負數，代表已經開打或已結束）"""
    game_time = datetime.fromisoformat(game_time_utc_str.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return (game_time - now).total_seconds() / 3600.0


# 常見隊名縮寫對照，因為 SportsBettingDime 頁面上顯示的隊名格式，
# 跟 MLB Stats API 回傳的正式全名不一定完全一樣，需要靠這個表做模糊比對的輔助
TEAM_NAME_TO_ABBR = {
    "diamondbacks": "ARI", "braves": "ATL", "orioles": "BAL", "red sox": "BOS",
    "cubs": "CHC", "white sox": "CWS", "reds": "CIN", "guardians": "CLE",
    "rockies": "COL", "tigers": "DET", "astros": "HOU", "royals": "KC",
    "angels": "LAA", "dodgers": "LAD", "marlins": "MIA", "brewers": "MIL",
    "twins": "MIN", "mets": "NYM", "yankees": "NYY", "athletics": "OAK",
    "phillies": "PHI", "pirates": "PIT", "padres": "SD", "mariners": "SEA",
    "giants": "SF", "cardinals": "STL", "rays": "TB", "rangers": "TEX",
    "blue jays": "TOR", "nationals": "WSH",
}


def guess_team_abbr(team_name_text: str) -> str | None:
    """把 SBD 頁面上出現的隊名文字，盡量對應回標準三字縮寫"""
    text = team_name_text.strip().lower()
    for keyword, abbr in TEAM_NAME_TO_ABBR.items():
        if keyword in text:
            return abbr
    return None
