"""
看板用：把 Pinnacle 盤口記錄（scrape_pinnacle.py）整理成每場比賽「第一次看到」和「最新」的主盤。
檔案只記有變動的選項 → 每個選項取最早一筆＝開盤、最後一筆＝最新。
"""
from datetime import timedelta

from sports_common import _norm, parse_time, read_rows, recent_monthly_files


def num(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None

TOLERANCE_H = 3


def _snap(vals):
    """vals: {(market, team, side): (line, odds)} → 看板格式（只取全場主盤）"""
    ml = {s: o for (m, _, s), (_, o) in vals.items() if m == "moneyline" and o}
    sp = {s: [ln, o] for (m, _, s), (ln, o) in vals.items() if m == "spread" and o}
    ov, un = vals.get(("total", "", "over")), vals.get(("total", "", "under"))
    out = {}
    if ml:
        out["ml"] = ml
    if sp:
        out["sp"] = sp
    if ov and un:
        out["ou"] = {"line": ov[0], "over": ov[1], "under": un[1]}
    return out


def load(sport, now, recent_days):
    games = {}
    for path in recent_monthly_files(sport, "pinnacle", months=2):
        for r in read_rows(path):
            if r["units"] != "Regular" or r["period"] != "0" or r["market"] not in ("moneyline", "spread", "total"):
                continue
            t = parse_time(r["game_time_utc"])
            if t < now - timedelta(days=recent_days):
                continue
            g = games.setdefault(r["pin_id"], {"league": r["league"], "home": r["home_team"], "away": r["away_team"], "t": t,
                                                "first": {}, "last": {}, "ts": set(), "lim": None})
            k = (r["market"], r["team"], r["side"])
            v = (num(r["line"]), num(r["odds"]))
            g["first"].setdefault(k, v)
            g["last"][k] = v
            g["t"] = t
            g["ts"].add(r["timestamp_utc"][:16])
            if r["market"] == "moneyline" and r.get("limit"):
                g["lim"] = num(r["limit"])
    out = []
    for g in games.values():
        ts = sorted(g["ts"])
        out.append({"league": g["league"], "home": g["home"], "away": g["away"], "t": g["t"],
                    "o": _snap(g["first"]), "l": _snap(g["last"]), "first_ts": ts[0] + "Z", "ts": ts[-1] + "Z",
                    "n": len(ts), "lim": g["lim"]})
    return out


def find(entries, home, away, t, score=None, league=None):
    """US 運動用隊名正規化比對；足球傳入 score 函式（soccer_dashboard.match_score）"""
    best, best_s = None, None
    for e in entries:
        if league and e["league"] != league:
            continue
        if abs((e["t"] - t).total_seconds()) > TOLERANCE_H * 3600:
            continue
        if score:
            sh, sa = score(home, e["home"]), score(away, e["away"])
            if not (sh[0] and sa[0]):
                continue
            s = sh + sa
        else:
            if (_norm(e["home"]), _norm(e["away"])) != (_norm(home), _norm(away)):
                continue
            s = (1,)
        if best_s is None or s > best_s:
            best, best_s = e, s
    if not best:
        return None
    return {k: best[k] for k in ("o", "l", "first_ts", "ts", "n", "lim")}
