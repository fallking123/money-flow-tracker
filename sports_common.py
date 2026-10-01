"""
共用模組：各運動設定、ESPN 賽程/比分、隊名比對、CSV 工具
============================================================
所有程式（抓資金流向、回填比分、抓背景資料）都靠這裡：
- SPORTS：每種運動的資料來源名稱、資料夾名稱、要追蹤多久以前的比賽
- ESPN 公開賽程 API（免費、不用申請 key）：比賽編號、開賽時間、球場、比分、季後賽標記
- 把 SportsBettingDime 的比賽對應到 ESPN 的比賽（靠隊名 + 開賽時間）

資料夾結構（每種運動分開放）：
docs/data/<運動>/odds_history_YYYY-MM.csv   每場比賽的資金流向快照（按月分檔）
docs/data/<運動>/odds_books_YYYY-MM.csv     各莊家賠率明細（按月分檔，只在賠率有變時才記）
docs/data/<運動>/results.csv                賽果
docs/data/<運動>/context.csv                背景資料（球場、天氣、先發投手）
docs/data/<運動>/raw/日期.json.gz           每天第一次抓到的原始資料備份
"""

import csv
import glob
import os
import re
import unicodedata
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "docs", "data")
STATE_DIR = os.path.join(DATA_DIR, "state")
ET = ZoneInfo("America/New_York")
UA = {"User-Agent": "Mozilla/5.0"}

# key = 資料夾名稱
# sbd = SportsBettingDime 資料名稱；espn = ESPN 路徑
# horizon_h = 開賽前多久開始記錄（美式足球一週一賽，整週都在下注，所以抓 7 天）
# outdoor = 需要抓天氣的運動
# enabled = False 代表暫停記錄（台彩沒有開賣的項目先關掉，要恢復就把 False 刪掉）
SPORTS = {
    "mlb":   {"name": "MLB 美國職棒",     "sbd": "mlb",    "espn": "baseball/mlb",                      "horizon_h": 48,  "outdoor": True,  "params": [{}]},
    "nfl":   {"name": "NFL 美式足球",     "sbd": "nfl",    "espn": "football/nfl",                      "horizon_h": 168, "outdoor": True,  "params": [{}]},
    "ncaaf": {"name": "NCAAF 大學美式足球", "sbd": "ncaafb", "espn": "football/college-football",         "horizon_h": 168, "outdoor": True,  "params": [{"groups": "80"}, {"groups": "81"}], "enabled": False},
    "nba":   {"name": "NBA 美國職籃",     "sbd": "nba",    "espn": "basketball/nba",                    "horizon_h": 48,  "outdoor": False, "params": [{}]},
    "nhl":   {"name": "NHL 美國冰球",     "sbd": "nhl",    "espn": "hockey/nhl",                        "horizon_h": 48,  "outdoor": False, "params": [{}]},
    "ncaab": {"name": "NCAAB 大學籃球",   "sbd": "ncaamb", "espn": "basketball/mens-college-basketball", "horizon_h": 48,  "outdoor": False, "params": [{"groups": "50"}], "enabled": False},
}



def active_sports():
    """目前有在記錄的運動"""
    return {k: v for k, v in SPORTS.items() if v.get("enabled", True)}


SEASON_TYPES = {1: "preseason", 2: "regular", 3: "postseason", 4: "offseason"}

# MLB 室內 / 可開闔屋頂球場（天氣影響小，分析時可排除）
MLB_ROOF_TEAMS = {"TB", "TOR", "MIA", "MIL", "HOU", "SEA", "TEX", "ARI"}


# ---------------- 路徑 / CSV ----------------
def sport_dir(sport):
    d = os.path.join(DATA_DIR, sport)
    os.makedirs(d, exist_ok=True)
    return d


def monthly_path(sport, prefix, when):
    return os.path.join(sport_dir(sport), f"{prefix}_{when.strftime('%Y-%m')}.csv")


def recent_monthly_files(sport, prefix, months=2):
    files = sorted(glob.glob(os.path.join(DATA_DIR, sport, f"{prefix}_*.csv")))
    return files[-months:]


def all_monthly_files(sport, prefix):
    """跟 recent_monthly_files 一樣，但拿全部歷史月份（做長期回測/驗證用，不是只拿最近）"""
    return sorted(glob.glob(os.path.join(DATA_DIR, sport, f"{prefix}_*.csv")))


def append_rows(path, fields, rows):
    if not rows:
        return
    exists = os.path.exists(path)
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        if not exists:
            w.writeheader()
        w.writerows(rows)


def read_rows(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def parse_time(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00"))


# ---------------- ESPN ----------------
def espn_events(sport, start_utc, end_utc):
    """抓某段時間內的 ESPN 賽程（含比分、季後賽資訊、球場、先發投手）"""
    # 注意：ESPN 不接受日期範圍查詢，要一天一天查（美東日期）；
    # 也不要加瀏覽器標頭（會被擋 403），用 requests 預設的就好
    cfg = SPORTS[sport]
    url = f"https://site.api.espn.com/apis/site/v2/sports/{cfg['espn']}/scoreboard"
    day, last = start_utc.astimezone(ET).date(), end_utc.astimezone(ET).date()
    events, seen = [], set()
    while day <= last:
        for extra in cfg["params"]:  # 大學美式足球要分別查 FBS（80）與 FCS（81）
            params = {"dates": day.strftime("%Y%m%d"), "limit": "300", **extra}
            r = requests.get(url, params=params, timeout=30)
            r.raise_for_status()
            for e in r.json().get("events", []):
                if e.get("id") not in seen:
                    seen.add(e.get("id"))
                    events.append(parse_espn_event(e))
        day += timedelta(days=1)
    return events


def probable_stat(pr):
    """先發投手／門將本季成績，例如「10-5 · ERA 3.21」（ESPN 格式不固定，抓不到就留空）"""
    st = {}
    for x in pr.get("statistics") or []:
        k = (x.get("abbreviation") or x.get("name") or "").upper()
        if k:
            st[k] = x.get("displayValue")
    parts = []
    if st.get("W") is not None and st.get("L") is not None:
        parts.append(f"{st['W']}-{st['L']}")
    if st.get("ERA"):
        parts.append(f"ERA {st['ERA']}")
    # 冰球門將：失分率、擋球率
    if st.get("GAA"):
        parts.append(f"失分率 {st['GAA']}")
    for k in ("SV%", "SVPCT", "SAVEPCT"):
        if st.get(k):
            parts.append(f"擋球率 {st[k]}")
            break
    if not parts and isinstance(pr.get("record"), str):
        parts.append(pr["record"].strip("() "))
    return " · ".join(parts)


def parse_espn_event(e):
    comp = (e.get("competitions") or [{}])[0]
    teams = {}
    for t in comp.get("competitors", []):
        side = t.get("homeAway")
        team = t.get("team", {})
        pr = (t.get("probables") or [{}])[0]
        prob = pr.get("athlete", {}).get("displayName", "")
        prob_id = str(pr.get("playerId") or pr.get("athlete", {}).get("id") or "")
        recs = {}
        for rc in t.get("records") or []:
            ty = (rc.get("type") or rc.get("name") or "").lower()
            if ty in ("total", "overall", "ytd"):
                recs["total"] = rc.get("summary", "")
            elif ty == "home":
                recs["home"] = rc.get("summary", "")
            elif ty in ("road", "away"):
                recs["road"] = rc.get("summary", "")
        teams[side] = {
            "id": str(team.get("id", "")), "records": recs,
            "display": team.get("displayName", ""), "name": team.get("name", ""),
            "short": team.get("shortDisplayName", ""), "location": team.get("location", ""),
            "abbr": team.get("abbreviation", ""), "score": t.get("score"),
            "winner": t.get("winner"), "probable": prob, "probable_id": prob_id, "probable_stat": probable_stat(pr),
            # 每一局（冰球每一節、美式足球/籃球每一節）的得分，算單隊大小、第一局和局用
            "periods": [ls.get("value") for ls in (t.get("linescores") or [])],
        }
    status = (e.get("status") or comp.get("status") or {}).get("type", {})
    notes = "; ".join(n.get("headline", "") for n in comp.get("notes", []) if n.get("headline"))
    series = comp.get("series") or {}
    series_note = " | ".join(x for x in (notes, series.get("summary", "")) if x)
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    return {
        "event_id": str(e.get("id")), "time": parse_time(e.get("date")),
        "season_type": SEASON_TYPES.get((e.get("season") or {}).get("type"), ""),
        "series_note": series_note,
        "state": status.get("state"), "status": status.get("name", ""), "completed": status.get("completed", False),
        "away": teams.get("away", {}), "home": teams.get("home", {}),
        "venue_id": venue.get("id", ""), "venue": venue.get("fullName", ""),
        "city": addr.get("city", ""), "region": addr.get("state", ""), "country": addr.get("country", ""),
        "indoor": venue.get("indoor"), "neutral_site": comp.get("neutralSite"),
    }


# ---------------- 隊名比對 ----------------
def _norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"\bst\b\.?", "state", s)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", s)).strip()


def sbd_full_name(team):
    """SBD 的隊名：職業隊是 market=城市 + name=隊名；NHL 直接是全名"""
    name, market = team.get("name") or "", team.get("market") or ""
    if market and market.lower() not in name.lower():
        return f"{market} {name}"
    return name


def team_match(sbd_team, espn_team, college=False):
    full, nick, market = _norm(sbd_full_name(sbd_team)), _norm(sbd_team.get("name")), _norm(sbd_team.get("market"))
    disp, enick = _norm(espn_team.get("display")), _norm(espn_team.get("name"))
    loc, short = _norm(espn_team.get("location")), _norm(espn_team.get("short"))
    if not full:
        return False
    if full == disp:
        return True
    if not college:
        # 職業隊：同一聯盟裡隊名（Broncos、Yankees）不會重複
        if nick and nick in (enick, disp):
            return True
        return full.split()[-1] == disp.split()[-1] if disp else False
    # 大學隊：學校名稱對上就算（隊名寫法常不同，例如 Fightin' Blue Hens / Blue Hens）
    if full in (short, loc) or (market and market in (loc, short)):
        return True
    # 學校名稱寫法不同（Louisiana-Monroe / UL Monroe、Miami (FL) / Miami）：
    # 隊名要一樣，而且學校名稱至少有一個關鍵字相同
    stop = {"state", "university", "of", "the", "college", "and", "fl", "oh"}
    school = set((market or full).split()) - stop
    return bool(nick) and nick == enick and bool(school & (set(f"{loc} {short}".split()) - stop))


def match_event(sbd_game, events, college=False, max_gap_h=8):
    """找出 SBD 比賽在 ESPN 上對應的那一場（兩隊都要對上，開賽時間最接近）"""
    comp = sbd_game.get("competitors", {})
    sa, sh = comp.get("away", {}), comp.get("home", {})
    sched = parse_time(sbd_game["scheduled"])
    best, best_gap = None, None
    for ev in events:
        ok = team_match(sa, ev["away"], college) and team_match(sh, ev["home"], college)
        if not ok:  # 中立場地偶爾主客顛倒
            ok = team_match(sa, ev["home"], college) and team_match(sh, ev["away"], college)
        if not ok:
            continue
        gap = abs((ev["time"] - sched).total_seconds()) / 3600
        if gap <= max_gap_h and (best_gap is None or gap < best_gap):
            best, best_gap = ev, gap
    return best


def is_college(sport):
    return sport in ("ncaaf", "ncaab")


# ---------------- 冰球：台彩只算 60 分鐘（正規時間），有和局 ----------------
# 用 2007–2026 年 16,177 場 NHL 算的：正規時間打平 k:k 的比例（打平合計約 22.6%）
NHL_TIE_AT = {0: 0.0049, 1: 0.0393, 2: 0.0727, 3: 0.0683, 4: 0.0309, 5: 0.0082, 6: 0.0016}
NHL3_MARGIN = 0.19   # 台彩冰球三選一（客／和／主）抽成；第一次看到 3.00／3.70／1.70 ≈ 19%，記錄夠了再換成實際平均


def nhl_reg3(p_home, total=None):
    """含延長賽的主隊勝率 → 60 分鐘三選一 [客, 和, 主]
    打平機率：總分盤 ≤5.5 約 23.5%，≥6 約 21.4%；實力差很多時打平比較少。
    延長賽誰贏：實力強的稍微佔優（歷史：主隊勝率 70% 時延長賽贏 60%）。"""
    tie = 0.235 if total is None or total <= 5.5 else 0.214
    tie -= 0.5 * max(0.0, abs(p_home - 0.5) - 0.2)
    s = 0.5 + 0.5 * (p_home - 0.5)
    return [round((1 - p_home) - tie * (1 - s), 4), round(tie, 4), round(p_home - tie * s, 4)]


def nhl_reg_over(p_over_full, line):
    """含延長賽的「大」機率 → 只算 60 分鐘的「大」機率。
    差別只在正規時間打平、延長賽多 1 分剛好跨過盤口的情況（例如 3:3 → 7 分，大 6.5 就不一樣）。"""
    if line is None or p_over_full is None or abs(line % 1 - 0.5) > 1e-9:
        return p_over_full
    k = int(line)
    return p_over_full - NHL_TIE_AT.get(k // 2, 0.0) if k % 2 == 0 else p_over_full


def reg_winner(away_periods, home_periods):
    """各節比分（例如 1-0-2-1）→ 60 分鐘結果 away/home/tie；沒有各節比分回傳 None"""
    try:
        a = [float(x) for x in str(away_periods).replace("|", "-").split("-") if x != ""]
        h = [float(x) for x in str(home_periods).replace("|", "-").split("-") if x != ""]
    except ValueError:
        return None
    if len(a) < 3 or len(h) < 3:
        return None
    sa, sh = sum(a[:3]), sum(h[:3])
    return "tie" if sa == sh else ("away" if sa > sh else "home")
