"""
足球：資金流向、歐洲賠率、賽果（五大聯賽＋歐冠）
============================================
跟美國四大運動分開一支程式，因為資料來源不同：
- 資金流向（下注人數 % / 金額 %）：Action Network 公開賽程 API（共識盤 book 15）
    玩法：1X2（主／和／客）、讓球、大小、單隊大小
- 歐洲賠率：football-data.co.uk（英國）
    fixtures.csv    即將開賽：Bet365、Betfair 交易所、BetVictor、Betway、Paddy Power、Sky Bet、平均、最高
    本季檔 E0.csv…  已完賽：比分＋開盤／收盤賠率＋射門、角球、xG 等
    過去幾季        一次下載，之後做回測／模型用
- 比分：ESPN（比 football-data 快，完場幾小時內就有）

存檔（docs/data/soccer/）：
- odds_history_YYYY-MM.csv   資金流向快照（跟其他運動一樣，依距離開賽時間決定多久抓一次）
- results.csv                賽果（上下半場比分放在 away_periods / home_periods）
- eu_odds_YYYY-MM.csv        歐洲賠率快照（fixtures.csv，賠率有變才記）
- eu/<聯賽>_<季>.csv         football-data 本季／歷史檔（原檔照存）
"""

import csv
import io
import json
import os
from datetime import datetime, timezone, timedelta

import requests

from sports_common import (ET, STATE_DIR, UA, _norm, append_rows, parse_espn_event, parse_time, read_rows,
                           recent_monthly_files, sport_dir, monthly_path)

SPORT = "soccer"
# an＝Action Network 名稱；espn＝ESPN 路徑；fd＝football-data 聯賽代碼
LEAGUES = {
    "epl":        {"name": "英超", "an": "epl",        "espn": "soccer/eng.1", "fd": "E0"},
    "laliga":     {"name": "西甲", "an": "laliga",     "espn": "soccer/esp.1", "fd": "SP1"},
    "seriea":     {"name": "義甲", "an": "seriea",     "espn": "soccer/ita.1", "fd": "I1"},
    "bundesliga": {"name": "德甲", "an": "bundesliga", "espn": "soccer/ger.1", "fd": "D1"},
    "ligue1":     {"name": "法甲", "an": "ligue1",     "espn": "soccer/fra.1", "fd": "F1"},
    "ucl":        {"name": "歐冠", "an": "champions",  "espn": "soccer/uefa.champions", "fd": None},
}
FD_DIV = {v["fd"]: k for k, v in LEAGUES.items() if v["fd"]}
HORIZON_DAYS = 12         # 開賽前 12 天內開始記錄（國際賽空檔時兩輪之間會隔比較久）
# 歷史賽季：2014/15 起（越多季 Elo 越準、訓練樣本越多）
HISTORY_SEASONS = [f"{y:02d}{y + 1:02d}" for y in range(14, 26)]
# 次級聯賽（英冠、西乙、義乙、德乙、法乙）：只拿來算 Elo，讓升級隊一開始就有合理的強弱分數
SECOND_DIV = ["E1", "SP2", "I2", "D2", "F2"]
AN_URL = "https://api.actionnetwork.com/web/v2/scoreboard/{league}"
FD_BASE = "https://www.football-data.co.uk"
STATE_FILE = os.path.join(STATE_DIR, "soccer_state.json")

HISTORY_FIELDS = [
    "timestamp_utc", "sport", "league", "an_id", "game_time_utc", "hours_until_game",
    "home_team", "away_team", "home_abbr", "away_abbr", "home_color", "away_color", "num_bets",
    "ml_home_odds", "ml_draw_odds", "ml_away_odds",
    "ml_home_bets_pct", "ml_home_money_pct", "ml_draw_bets_pct", "ml_draw_money_pct", "ml_away_bets_pct", "ml_away_money_pct",
    "sp_home_line", "sp_home_odds", "sp_away_odds",
    "sp_home_bets_pct", "sp_home_money_pct", "sp_away_bets_pct", "sp_away_money_pct",
    "ou_line", "ou_over_odds", "ou_under_odds",
    "ou_over_bets_pct", "ou_over_money_pct", "ou_under_bets_pct", "ou_under_money_pct",
    "tt_home_line", "tt_home_over_odds", "tt_home_under_odds", "tt_home_over_bets_pct", "tt_home_over_money_pct",
    "tt_home_under_bets_pct", "tt_home_under_money_pct",
    "tt_away_line", "tt_away_over_odds", "tt_away_under_odds", "tt_away_over_bets_pct", "tt_away_over_money_pct",
    "tt_away_under_bets_pct", "tt_away_under_money_pct",
]
RESULT_FIELDS = [
    "sport", "league", "an_id", "event_id", "game_time_utc", "home_team", "away_team",
    "away_score", "home_score", "winner", "margin", "total_points", "status", "away_periods", "home_periods",
]
EU_FIELDS = [
    "timestamp_utc", "league", "div", "date", "time", "home_team", "away_team",
    "avg_h", "avg_d", "avg_a", "max_h", "max_d", "max_a", "b365_h", "b365_d", "b365_a", "bfe_h", "bfe_d", "bfe_a",
    "avg_over25", "avg_under25", "max_over25", "max_under25",
    "ah_line", "avg_ah_home", "avg_ah_away", "max_ah_home", "max_ah_away",
]


# ---------------- 小工具 ----------------
def american_to_decimal(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return None
    return round(1 + (v / 100 if v > 0 else 100 / -v), 4)


def interval_minutes(hrs):
    """離開賽越近抓越密（跟美國運動一樣的規則）"""
    if hrs > 24:
        return 360
    if hrs > 3:
        return 120
    if hrs > 1:
        return 30
    return 10


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state, now):
    cutoff = now - timedelta(days=14)
    state = {k: v for k, v in state.items() if k.startswith("_") or parse_time(v.get("t", "2000-01-01T00:00:00+00:00")) > cutoff}
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)


def http_get(url, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    return r


# ---------------- 1. 資金流向（Action Network）----------------
def an_games(league_an, day):
    url = AN_URL.format(league=league_an)
    data = http_get(url, params={"bookIds": "15", "date": day.strftime("%Y%m%d")}).json()
    return data.get("games") or []


def pick(outcomes, **cond):
    """從同一種玩法的選項裡挑出主盤（不是替代盤）且符合條件的那一個"""
    for o in outcomes:
        if o.get("is_alt_market"):
            continue
        if all(o.get(k) == v for k, v in cond.items()):
            return o
    return None


def pct(o, kind):
    """人數（tickets）或金額（money）%；沒有任何下注（兩個都 0）視為沒資料"""
    if not o:
        return None
    bi = o.get("bet_info") or {}
    t, m = (bi.get("tickets") or {}).get("percent"), (bi.get("money") or {}).get("percent")
    if not t and not m:
        return None
    return (bi.get(kind) or {}).get("percent")


def both_pct(a, b, kind):
    """兩邊都 0 才算沒資料（其中一邊 0% 是正常的）"""
    va, vb = pct(a, "tickets"), pct(b, "tickets")
    ma, mb = pct(a, "money"), pct(b, "money")
    if not any([va, vb, ma, mb]):
        return None, None
    get = lambda o: ((o or {}).get("bet_info") or {}).get(kind, {}).get("percent")
    return get(a), get(b)


def build_row(league, g, now):
    teams = {t["id"]: t for t in g.get("teams") or []}
    home, away = teams.get(g["home_team_id"], {}), teams.get(g["away_team_id"], {})
    ev = ((g.get("markets") or {}).get("15") or {}).get("event") or {}
    t = parse_time(g["start_time"])
    row = {
        "timestamp_utc": now.isoformat(), "sport": SPORT, "league": league, "an_id": g["id"],
        "game_time_utc": t.isoformat(), "hours_until_game": round((t - now).total_seconds() / 3600, 2),
        "home_team": home.get("full_name", ""), "away_team": away.get("full_name", ""),
        "home_abbr": home.get("abbr", ""), "away_abbr": away.get("abbr", ""),
        "home_color": home.get("primary_color", ""), "away_color": away.get("primary_color", ""),
        "num_bets": g.get("num_bets"),
    }
    # 1X2：三個選項一起判斷有沒有資料
    ml = ev.get("moneyline") or []
    oh, od, oa = pick(ml, side="home"), pick(ml, side="draw"), pick(ml, side="away")
    has = any(pct(o, "tickets") or pct(o, "money") for o in (oh, od, oa))
    for nm, o in (("home", oh), ("draw", od), ("away", oa)):
        row[f"ml_{nm}_odds"] = american_to_decimal((o or {}).get("odds"))
        if has:
            row[f"ml_{nm}_bets_pct"] = ((o or {}).get("bet_info") or {}).get("tickets", {}).get("percent")
            row[f"ml_{nm}_money_pct"] = ((o or {}).get("bet_info") or {}).get("money", {}).get("percent")
    # 讓球（主隊讓分）
    sp = ev.get("spread") or []
    sh, sa = pick(sp, side="home"), pick(sp, side="away")
    row["sp_home_line"] = (sh or {}).get("value")
    row["sp_home_odds"], row["sp_away_odds"] = american_to_decimal((sh or {}).get("odds")), american_to_decimal((sa or {}).get("odds"))
    row["sp_home_bets_pct"], row["sp_away_bets_pct"] = both_pct(sh, sa, "tickets")
    row["sp_home_money_pct"], row["sp_away_money_pct"] = both_pct(sh, sa, "money")
    # 大小
    tot = ev.get("total") or []
    over, under = pick(tot, side="over"), pick(tot, side="under")
    row["ou_line"] = (over or under or {}).get("value")
    row["ou_over_odds"], row["ou_under_odds"] = american_to_decimal((over or {}).get("odds")), american_to_decimal((under or {}).get("odds"))
    row["ou_over_bets_pct"], row["ou_under_bets_pct"] = both_pct(over, under, "tickets")
    row["ou_over_money_pct"], row["ou_under_money_pct"] = both_pct(over, under, "money")
    # 單隊大小
    tt = ev.get("core_bet_type_6_team_score") or []
    for nm, tid in (("home", g["home_team_id"]), ("away", g["away_team_id"])):
        o_, u_ = pick(tt, side="over", team_id=tid), pick(tt, side="under", team_id=tid)
        row[f"tt_{nm}_line"] = (o_ or u_ or {}).get("value")
        row[f"tt_{nm}_over_odds"], row[f"tt_{nm}_under_odds"] = american_to_decimal((o_ or {}).get("odds")), american_to_decimal((u_ or {}).get("odds"))
        row[f"tt_{nm}_over_bets_pct"], row[f"tt_{nm}_under_bets_pct"] = both_pct(o_, u_, "tickets")
        row[f"tt_{nm}_over_money_pct"], row[f"tt_{nm}_under_money_pct"] = both_pct(o_, u_, "money")
    return row


def collect_money_flow(now, state):
    rows = []
    for key, cfg in LEAGUES.items():
        n_games = 0
        for i in range(HORIZON_DAYS + 1):
            day = (now.astimezone(ET) + timedelta(days=i)).date()
            try:
                games = an_games(cfg["an"], day)
            except Exception as e:
                print(f"  {cfg['name']} {day}: 讀取失敗 {e}")
                continue
            for g in games:
                if g.get("status") not in ("scheduled", "delayed") or not g.get("start_time"):
                    continue
                t = parse_time(g["start_time"])
                hrs = (t - now).total_seconds() / 3600
                if not (0 <= hrs <= HORIZON_DAYS * 24):
                    continue
                n_games += 1
                sid = f"an{g['id']}"
                last = state.get(sid, {}).get("t")
                if last and (now - parse_time(last)).total_seconds() / 60 < interval_minutes(hrs) * 0.75:
                    continue
                rows.append(build_row(key, g, now))
                state[sid] = {"t": now.isoformat()}
        print(f"  {cfg['name']}: 未來 {HORIZON_DAYS} 天 {n_games} 場")
    append_rows(monthly_path(SPORT, "odds_history", now), HISTORY_FIELDS, rows)
    print(f"足球資金流向：寫入 {len(rows)} 筆快照")


# ---------------- 2. 賽果（ESPN）----------------
def espn_day(league_path, day):
    url = f"https://site.api.espn.com/apis/site/v2/sports/{league_path}/scoreboard"
    r = requests.get(url, params={"dates": day.strftime("%Y%m%d"), "limit": "300"}, timeout=30)
    r.raise_for_status()
    return [parse_espn_event(e) for e in r.json().get("events", [])]


def same_team(a, espn_team):
    na = set(_norm(a).split()) - {"fc", "cf", "ac", "sc", "afc", "ssc", "as", "rc", "sv", "club", "de", "1"}
    cands = " ".join(_norm(espn_team.get(k, "")) for k in ("display", "name", "short", "location", "abbr"))
    return bool(na & set(cands.split()))


def backfill_results(now):
    path = os.path.join(sport_dir(SPORT), "results.csv")
    done = {r["an_id"] for r in read_rows(path)}
    games = {}
    for p in recent_monthly_files(SPORT, "odds_history"):
        for r in read_rows(p):
            if r["an_id"] in done:
                continue
            t = parse_time(r["game_time_utc"])
            if now - timedelta(days=7) <= t <= now - timedelta(hours=2, minutes=30):
                games[r["an_id"]] = r
    if not games:
        print("足球賽果：沒有要回填的比賽")
        return
    cache, out = {}, []
    for aid, g in games.items():
        t = parse_time(g["game_time_utc"])
        lg = LEAGUES[g["league"]]
        evs = []
        for day in {t.astimezone(ET).date(), (t.astimezone(ET) - timedelta(days=1)).date()}:
            k = (lg["espn"], day)
            if k not in cache:
                try:
                    cache[k] = espn_day(lg["espn"], datetime.combine(day, datetime.min.time()))
                except Exception as e:
                    print(f"  ESPN {lg['name']} {day} 讀取失敗 {e}")
                    cache[k] = []
            evs += cache[k]
        ev = next((e for e in evs if abs((e["time"] - t).total_seconds()) <= 5400
                   and same_team(g["home_team"], e["home"]) and same_team(g["away_team"], e["away"])), None)
        if ev is None:
            ev = next((e for e in evs if abs((e["time"] - t).total_seconds()) <= 5400
                       and (same_team(g["home_team"], e["home"]) or same_team(g["away_team"], e["away"]))), None)
        if ev is None or not ev["completed"]:
            continue
        try:
            a, h = int(float(ev["away"]["score"])), int(float(ev["home"]["score"]))
        except (TypeError, ValueError):
            continue
        per = lambda s: "-".join(str(int(float(v))) for v in (ev[s].get("periods") or []) if v is not None)
        out.append({"sport": SPORT, "league": g["league"], "an_id": aid, "event_id": ev["event_id"],
                    "game_time_utc": g["game_time_utc"], "home_team": g["home_team"], "away_team": g["away_team"],
                    "away_score": a, "home_score": h, "winner": "home" if h > a else "away" if a > h else "tie",
                    "margin": h - a, "total_points": a + h, "status": "final",
                    "away_periods": per("away"), "home_periods": per("home")})
    append_rows(path, RESULT_FIELDS, out)
    print(f"足球賽果：回填 {len(out)} 場")


# ---------------- 3. 歐洲賠率（football-data.co.uk）----------------
def fd_csv(path):
    text = http_get(f"{FD_BASE}/{path}").content.decode("utf-8-sig", errors="ignore")
    return list(csv.DictReader(io.StringIO(text)))


def collect_eu_odds(now, state):
    try:
        rows = fd_csv("fixtures.csv")
    except Exception as e:
        print(f"歐洲賠率：fixtures.csv 讀取失敗 {e}")
        return
    sig = state.setdefault("_eu_sig", {})
    out = []
    g = lambda r, k: r.get(k) or ""
    for r in rows:
        div = r.get("Div")
        if div not in FD_DIV:
            continue
        key = f"{div}|{r.get('Date')}|{r.get('HomeTeam')}|{r.get('AwayTeam')}"
        row = {"timestamp_utc": now.isoformat(), "league": FD_DIV[div], "div": div, "date": g(r, "Date"), "time": g(r, "Time"),
               "home_team": g(r, "HomeTeam"), "away_team": g(r, "AwayTeam"),
               "avg_h": g(r, "AvgH"), "avg_d": g(r, "AvgD"), "avg_a": g(r, "AvgA"),
               "max_h": g(r, "MaxH"), "max_d": g(r, "MaxD"), "max_a": g(r, "MaxA"),
               "b365_h": g(r, "B365H"), "b365_d": g(r, "B365D"), "b365_a": g(r, "B365A"),
               "bfe_h": g(r, "BFEH"), "bfe_d": g(r, "BFED"), "bfe_a": g(r, "BFEA"),
               "avg_over25": g(r, "Avg>2.5"), "avg_under25": g(r, "Avg<2.5"),
               "max_over25": g(r, "Max>2.5"), "max_under25": g(r, "Max<2.5"),
               "ah_line": g(r, "AHh"), "avg_ah_home": g(r, "AvgAHH"), "avg_ah_away": g(r, "AvgAHA"),
               "max_ah_home": g(r, "MaxAHH"), "max_ah_away": g(r, "MaxAHA")}
        s = "|".join(str(row[k]) for k in EU_FIELDS[7:])
        if sig.get(key) == s:
            continue
        sig[key] = s
        out.append(row)
    if len(sig) > 3000:  # 只留最近的，避免狀態檔越來越大
        state["_eu_sig"] = dict(list(sig.items())[-1500:])
    append_rows(monthly_path(SPORT, "eu_odds", now), EU_FIELDS, out)
    print(f"歐洲賠率：fixtures 有 {sum(1 for r in rows if r.get('Div') in FD_DIV)} 場五大聯賽，寫入 {len(out)} 筆變動")


def season_code(now):
    y = now.year % 100
    return f"{y:02d}{(y + 1) % 100:02d}" if now.month >= 7 else f"{(y - 1) % 100:02d}{y:02d}"


def download_seasons(now, state):
    """本季檔每天更新一次（比分＋收盤賠率）；過去幾季只下載一次"""
    eu_dir = os.path.join(sport_dir(SPORT), "eu")
    os.makedirs(eu_dir, exist_ok=True)
    cur = season_code(now)
    today = now.strftime("%Y-%m-%d")
    n = 0
    for div in list(FD_DIV) + SECOND_DIV:
        for season in HISTORY_SEASONS + [cur]:
            path = os.path.join(eu_dir, f"{div}_{season}.csv")
            if season != cur and os.path.exists(path):
                continue
            if season == cur and state.get("_season_day", {}).get(div) == today and os.path.exists(path):
                continue
            try:
                content = http_get(f"{FD_BASE}/mmz4281/{season}/{div}.csv").content
            except Exception as e:
                print(f"  football-data {div} {season} 下載失敗 {e}")
                continue
            if len(content) < 200:
                continue
            with open(path, "wb") as f:
                f.write(content)
            n += 1
            if season == cur:
                state.setdefault("_season_day", {})[div] = today
    print(f"歐洲賠率：更新 {n} 個季度檔")


def run():
    now = datetime.now(timezone.utc)
    state = load_state()
    collect_money_flow(now, state)
    backfill_results(now)
    collect_eu_odds(now, state)
    download_seasons(now, state)
    save_state(state, now)


if __name__ == "__main__":
    run()
