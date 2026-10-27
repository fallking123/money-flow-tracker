"""
冷門玩法帳本（2026-10-27，使用者：「先把資料記下來，有新想法就不用再等好久驗證」）
================================================================
每一場打完的比賽，把 Pinnacle **所有玩法**的收盤（開賽前最後一筆）跟實際結果記成一行：
  全場／半場／單節／單局、獨贏／讓分／大小／球隊得分、足球角球／黃牌
之後拿到台彩任何冷門玩法的賠率，就能直接用這本帳：
  ① 台彩價 vs Pinnacle 公平機率（每一場都比得到）
  ② 這種玩法長期實際結果（例如「半場和局」實際發生幾成）
輸出：docs/data/niche_ledger_YYYY-MM.csv（照比賽月份分檔；每次整份重算，Pinnacle 有記到的比賽都會進來）
用法：python3 niche_ledger.py

Pinnacle period 代碼：
- 足球：0＝全場 90 分、1＝上半場
- 籃球、美式足球：0＝全場（含延長）、1＝上半場、2＝下半場（含延長）、3–6＝第一～四節
- 冰球：0＝全場（含延長、PK）、1–3＝第一～三節、6＝60 分鐘（正規時間）
- 棒球：0＝全場、1＝前五局；其他代碼先只記盤口、不算結果
結果欄 result：1＝贏、0.5＝贏一半、0＝退錢（平盤）、-0.5＝輸一半、-1＝輸；空白＝算不出來（缺比分）
"""
import csv
import glob
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sports_common import DATA_DIR, _norm, parse_time, read_rows, sport_dir

SPORTS = ["mlb", "nba", "nfl", "nhl", "soccer"]
FIELDS = ["sport", "league", "game_id", "pin_id", "game_time_utc", "home", "away", "units", "period", "market", "team", "side",
          "line", "close_odds", "fair_p", "n_sides", "result", "score_home", "score_away"]
TOL_H = 3


def num(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def ints(s):
    if not s:
        return None
    try:
        return [int(float(x)) for x in str(s).replace("|", "-").split("-") if x not in ("", "x", "X")]
    except ValueError:
        return None


# ───────── Pinnacle：每場比賽每個選項的收盤 ─────────
def load_closing(sport):
    games = {}
    for path in sorted(glob.glob(os.path.join(sport_dir(sport), "pinnacle_*.csv"))):
        for r in read_rows(path):
            pid = r["pin_id"]
            t = parse_time(r["game_time_utc"])
            g = games.setdefault(pid, {"pid": pid, "league": r["league"], "home": r["home_team"], "away": r["away_team"], "t": t, "close": {}})
            g["t"] = t
            if parse_time(r["timestamp_utc"]) >= t:      # 只要開賽前的
                continue
            k = (r["units"], r["period"], r["market"], r["team"], r["side"])
            g["close"][k] = (num(r["line"]), num(r["odds"]))
    return games


def fair_rows(g):
    """收盤去抽水：同一個玩法、同一條線的兩（三）邊一起算"""
    groups = defaultdict(list)
    for (units, period, market, team, side), (line, odds) in g["close"].items():
        if not odds or odds <= 1:
            continue
        if market == "moneyline":
            gk = (units, period, market, "")
        elif market == "spread":
            gk = (units, period, market, abs(line) if line is not None else None)
        elif market == "total":
            gk = (units, period, market, line)
        elif market == "team_total":
            gk = (units, period, market, team, line)
        else:
            continue
        groups[gk].append({"units": units, "period": period, "market": market, "team": team, "side": side, "line": line, "odds": odds})
    out = []
    for gk, sel in groups.items():
        if gk[2] == "spread":   # 讓分：主隊 −x 和客隊 +x 才是一對
            sides = {x["side"] for x in sel}
            if sides != {"home", "away"} or len(sel) != 2 or (sel[0]["line"] or 0) + (sel[1]["line"] or 0) != 0:
                continue
        need = {"moneyline": None, "spread": 2, "total": 2, "team_total": 2}[gk[2]]
        if need and len(sel) != need:
            continue
        if gk[2] == "moneyline" and len(sel) < 2:
            continue
        inv = sum(1 / x["odds"] for x in sel)
        for x in sel:
            out.append({**x, "fair_p": round((1 / x["odds"]) / inv, 4), "n_sides": len(sel)})
    return out


# ───────── 比賽結果：每一個 period 的比分 ─────────
def period_scores(sport, res, extra):
    """回傳 {period: (主, 客)}；units＝Regular。足球角球、黃牌另外回傳"""
    a, h = num(res.get("away_score")), num(res.get("home_score"))
    pa, ph = ints(res.get("away_periods")), ints(res.get("home_periods"))
    out = {}
    if a is None or h is None:
        return out
    if sport == "soccer":
        out["0"] = (h, a)
        if extra and extra.get("ht_home") not in ("", None):
            out["1"] = (int(extra["ht_home"]), int(extra["ht_away"]))
        return out
    out["0"] = (h, a)
    if not pa or not ph:
        return out
    if sport in ("nba", "nfl"):
        if len(pa) >= 4 and len(ph) >= 4:
            out["1"] = (ph[0] + ph[1], pa[0] + pa[1])
            out["2"] = (sum(ph[2:]), sum(pa[2:]))
            for i in range(4):
                out[str(3 + i)] = (ph[i], pa[i])
    elif sport == "nhl":
        if len(pa) >= 3 and len(ph) >= 3:
            for i in range(3):
                out[str(1 + i)] = (ph[i], pa[i])
            out["6"] = (sum(ph[:3]), sum(pa[:3]))
    elif sport == "mlb":
        if len(pa) >= 5 and len(ph) >= 5:
            out["1"] = (sum(ph[:5]), sum(pa[:5]))
    return out


def settle_line(diff):
    """diff＝（得分 − 盤口）站在下注那一邊；支援四分之一盤（例如 −0.25 拆成 0 和 −0.5）"""
    def one(d):
        return 1.0 if d > 1e-9 else -1.0 if d < -1e-9 else 0.0
    frac = round(abs(diff) % 0.5, 2)
    if frac in (0.25,):
        lo, hi = diff - 0.25, diff + 0.25
        return (one(lo) + one(hi)) / 2
    return one(diff)


def outcome(row, sc, extra):
    units, period, market, team, side, line = row["units"], row["period"], row["market"], row["team"], row["side"], row["line"]
    if units == "Regular":
        if period not in sc:
            return None, None
        h, a = sc[period]
    elif units in ("Corners", "Bookings") and period == "0" and extra:
        col = "corners" if units == "Corners" else "yc"
        try:
            h, a = int(extra[f"{col}_home"]), int(extra[f"{col}_away"])
        except (KeyError, TypeError, ValueError):
            return None, None
    else:
        return None, None
    if market == "moneyline":
        w = "home" if h > a else "away" if a > h else "draw"
        if row["n_sides"] == 2 and w == "draw":
            return 0.0, (h, a)
        return (1.0 if side == w else -1.0), (h, a)
    if line is None:
        return None, None
    if market == "spread":
        d = (h - a if side == "home" else a - h) + line
        return settle_line(d), (h, a)
    if market == "total":
        d = (h + a - line) if side == "over" else (line - h - a)
        return settle_line(d), (h, a)
    if market == "team_total":
        s = h if team == "home" else a
        d = (s - line) if side == "over" else (line - s)
        return settle_line(d), (h, a)
    return None, None


# ───────── 對比賽 ─────────
def find_pin(entries, home, away, t, score=None, league=None):
    best, bs = None, None
    for e in entries:
        if league and e["league"] != league:
            continue
        if abs((e["t"] - t).total_seconds()) > TOL_H * 3600:
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
        if bs is None or s > bs:
            best, bs = e, s
    return best


def build():
    import soccer_dashboard
    rows = []
    for sport in SPORTS:
        games = load_closing(sport)
        if not games:
            continue
        entries = list(games.values())
        first = min(g["t"] for g in entries)
        extra = {}
        if sport == "soccer":
            extra = {r["event_id"]: r for r in read_rows(os.path.join(sport_dir("soccer"), "match_extra.csv"))}
        for res in read_rows(os.path.join(sport_dir(sport), "results.csv")):
            if res.get("status") != "final":
                continue
            t = parse_time(res["game_time_utc"])
            if t < first - timedelta(days=1):
                continue
            if sport == "soccer":
                gid = res["an_id"]
                if gid.startswith("pin"):
                    g = games.get(gid[3:])
                else:
                    g = find_pin(entries, res["home_team"], res["away_team"], t, score=soccer_dashboard.match_score, league=res.get("league"))
            else:
                gid = res["sbd_id"]
                g = find_pin(entries, res["home_team"], res["away_team"], t)
            if not g:
                continue
            ex = extra.get(res.get("event_id")) if sport == "soccer" else None
            sc = period_scores(sport, res, ex)
            for fr in fair_rows(g):
                v, hs = outcome(fr, sc, ex)
                rows.append({"sport": sport, "league": res.get("league") or g["league"] or sport, "game_id": gid, "pin_id": g["pid"],
                             "game_time_utc": res["game_time_utc"], "home": res["home_team"], "away": res["away_team"],
                             "units": fr["units"], "period": fr["period"], "market": fr["market"], "team": fr["team"], "side": fr["side"],
                             "line": "" if fr["line"] is None else fr["line"], "close_odds": fr["odds"], "fair_p": fr["fair_p"],
                             "n_sides": fr["n_sides"], "result": "" if v is None else v,
                             "score_home": "" if hs is None else hs[0], "score_away": "" if hs is None else hs[1]})
    by_month = defaultdict(list)
    for r in rows:
        by_month[r["game_time_utc"][:7]].append(r)
    for m, rs in by_month.items():
        rs.sort(key=lambda r: (r["game_time_utc"], r["sport"], r["game_id"], r["units"], r["period"], r["market"], r["team"], r["side"]))
        with open(os.path.join(DATA_DIR, f"niche_ledger_{m}.csv"), "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            w.writerows(rs)
    n_games = len({(r["sport"], r["game_id"]) for r in rows})
    n_res = sum(1 for r in rows if r["result"] != "")
    print(f"冷門玩法帳本：{n_games} 場、{len(rows)} 個選項（有結果 {n_res}）")
    return rows


if __name__ == "__main__":
    build()
