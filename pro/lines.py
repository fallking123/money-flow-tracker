"""
職業版・盤口軌跡：Pinnacle 每一個時間點的全場主盤，加上比對我們自己記錄的比賽和賽果
================================================================
Pinnacle 檔案只記「有變動」的選項，所以某個時間點的盤口＝那個時間以前每個選項的最後一筆。
- 「第一次看到」＝我們開始記這場的時候（不一定是真正的開盤）
- 「收盤」＝開賽那一刻以前的最後一筆
只讀資料，不改任何既有檔案。
"""
import glob
import math
import os
from bisect import bisect_right

from sports_common import _norm, parse_time, read_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data")
US = ("mlb", "nba", "nfl", "nhl")
TOL_H = 3


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


class PinGame:
    """一場比賽在 Pinnacle 的全場主盤軌跡"""

    def __init__(self, pid, league, home, away, t):
        self.pid, self.league, self.home, self.away, self.t = pid, league, home, away, t
        self.ev = []          # (時間, (market, side), line, odds)
        self._ts = None

    def _prep(self):
        if self._ts is None:
            self.ev.sort(key=lambda x: x[0])
            self._ts = [e[0] for e in self.ev]

    def state(self, when):
        """when 這個時間點（含）以前的盤口：{(market, side): (line, odds)}"""
        self._prep()
        out = {}
        for _, k, ln, o in self.ev[:bisect_right(self._ts, when)]:
            out[k] = (ln, o)
        return out

    def first_time(self):
        self._prep()
        return self._ts[0] if self._ts else None

    def close(self):
        return self.state(self.t)


def load_pin(sport):
    games = {}
    for path in sorted(glob.glob(os.path.join(DATA, sport, "pinnacle_*.csv"))):
        for r in read_rows(path):
            if r["units"] != "Regular" or r["period"] != "0" or r["market"] not in ("moneyline", "spread", "total"):
                continue
            t = parse_time(r["game_time_utc"])
            g = games.get(r["pin_id"])
            if g is None:
                g = games[r["pin_id"]] = PinGame(r["pin_id"], r["league"], r["home_team"], r["away_team"], t)
            g.t = t       # 開賽時間如果改過，用最新的
            g.ev.append((parse_time(r["timestamp_utc"]), (r["market"], r["side"]), num(r["line"]), num(r["odds"])))
    return list(games.values())


def fair_ml(st, soccer):
    """去掉抽水後的獨贏機率 {side: p}；缺任何一邊就回傳 None"""
    sides = ("home", "draw", "away") if soccer else ("home", "away")
    odds = [(st.get(("moneyline", s)) or (None, None))[1] for s in sides]
    if any(not o or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    return {s: v / sum(inv) for s, v in zip(sides, inv)}


def fair_pair(st, market, a, b):
    """讓分／大小：兩邊同一條線時，去抽水的機率 {a: p, b: p} 和那條線（a 那一邊的線）"""
    x, y = st.get((market, a)), st.get((market, b))
    if not x or not y or not x[1] or not y[1]:
        return None, None
    ia, ib = 1 / x[1], 1 / y[1]
    return {a: ia / (ia + ib), b: ib / (ia + ib)}, x[0]


# ───────── 比對：我們記錄的比賽 ↔ Pinnacle ─────────
def match_us(pins, home, away, t):
    nh, na = _norm(home), _norm(away)
    best = None
    for g in pins:
        if abs((g.t - t).total_seconds()) > TOL_H * 3600:
            continue
        if (_norm(g.home), _norm(g.away)) == (nh, na):
            if best is None or abs((g.t - t).total_seconds()) < abs((best.t - t).total_seconds()):
                best = g
    return best


def match_soccer(pins, league, home, away, t):
    import soccer_dashboard as SD
    best, best_s = None, None
    for g in pins:
        if g.league != league or abs((g.t - t).total_seconds()) > TOL_H * 3600:
            continue
        sh, sa = SD.match_score(home, g.home), SD.match_score(away, g.away)
        if not (sh[0] and sa[0]):
            continue
        s = sh + sa
        if best_s is None or s > best_s:
            best, best_s = g, s
    return best


def results(sport):
    """{比賽代號: {"winner": home/away/tie, "home": 分, "away": 分}}；足球代號前面加 an（跟 model_picks 一樣）"""
    out = {}
    for r in read_rows(os.path.join(DATA, sport, "results.csv")):
        if r.get("status") not in ("final", "", None) or r.get("winner") not in ("home", "away", "tie"):
            continue
        gid = ("an" + r["an_id"]) if sport == "soccer" else r["sbd_id"]
        out[gid] = {"winner": r["winner"], "home": num(r["home_score"]), "away": num(r["away_score"])}
    return out


def our_games(sport):
    """我們自己記錄的每一場（odds_history），每一場的快照依時間排好：{gid: {"meta":..., "rows":[...] }}"""
    games = {}
    for path in sorted(glob.glob(os.path.join(DATA, sport, "odds_history_*.csv"))):
        for r in read_rows(path):
            gid = ("an" + r["an_id"]) if sport == "soccer" else r["sbd_id"]
            g = games.setdefault(gid, {"rows": []})
            g["meta"] = {"home": r["home_team"], "away": r["away_team"], "t": parse_time(r["game_time_utc"]),
                         "league": r.get("league") or sport}
            r["_ts"] = parse_time(r["timestamp_utc"])
            g["rows"].append(r)
    for g in games.values():
        g["rows"].sort(key=lambda r: r["_ts"])
        g["rows"] = [r for r in g["rows"] if r["_ts"] <= g["meta"]["t"]]   # 開賽後的不算
    return {k: v for k, v in games.items() if v["rows"]}


def linked(sport):
    """我們的比賽 + 對到的 Pinnacle 軌跡 + 賽果（沒賽果的也留著，result=None）"""
    pins = load_pin(sport)
    res = results(sport)
    out = []
    for gid, g in our_games(sport).items():
        m = g["meta"]
        pg = match_soccer(pins, m["league"], m["home"], m["away"], m["t"]) if sport == "soccer" else match_us(pins, m["home"], m["away"], m["t"])
        out.append({"gid": gid, "sport": sport, **m, "rows": g["rows"], "pin": pg, "result": res.get(gid)})
    return out
