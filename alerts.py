"""
划算的注 → 提醒
================================================================
每次排程抓完資料後跑：對接下來 30 小時內要開打的比賽，每個選項（獨贏／讓分／大小，足球含和局）算兩種期望值：
- 台彩：估計勝率 × 台彩賠率 − 1（你記錄過的實際台彩賠率優先，沒有就用「美國賠率 × 台彩平均折扣」估）
- 美國：估計勝率 × 美國共識賠率 − 1
任一種 ≥ +2% 就記一筆提醒；同一場、同一注、同一種只記一次（期望值之後又變更好也不重複）。

估計勝率跟看板一樣：獨贏用模型一（足球用足球模型），讓分／大小用 Pinnacle 去掉抽水（盤口要一樣）。
只有美國莊家自己的賠率可以用時不算（拿美國賠率跟自己比，一定是負的）。

用法：python alerts.py mlb,nba,nfl,nhl   或   python alerts.py soccer
輸出：docs/data/<運動>/alerts.csv（排程任務 alerts_report.py 讀它推播，看板也會列出來）
"""
import csv
import os
import sys
from datetime import datetime, timedelta, timezone

import build_dashboard as B
from sports_common import parse_time, read_rows, sport_dir
from track_models import discount

EV_MIN = 0.02        # 期望值至少 +2% 才提醒
EV_MAX = 0.30        # 超過 30% 多半是資料有問題（某一邊賠率沒更新），不提醒
HORIZON_H = 30
KELLY_FRAC, KELLY_CAP = 0.25, 0.03
FIELDS = ["created_utc", "sport", "league", "game_id", "game_time_utc", "away_zh", "home_zh", "market", "side", "line",
          "pick_zh", "kind", "odds", "odds_src", "p", "p_src", "ev", "stake_pct"]
MK = {"ml": "獨贏", "sp": "讓分", "ou": "大小"}


def path_for(sport):
    return os.path.join(sport_dir(sport), "alerts.csv")


def us_sides(g, snap, mkt):
    """跟看板 JS 的 sides() 一樣：[(key, 美國賠率, 這一邊的盤口)]"""
    a = snap.get(mkt) or []
    get = lambda i: a[i] if len(a) > i else None
    if g["sport"] == "soccer" and mkt == "ml":
        return [("home", get(6), None), ("draw", get(7), None), ("away", get(8), None)]
    if mkt == "ml":
        return [("away", get(4), None), ("home", get(5), None)]
    if g["sport"] == "soccer" and mkt == "sp":
        ln = get(4)
        return [("home", get(6), None if ln is None else -ln), ("away", get(5), ln)]
    if mkt == "sp":
        ln = get(4)
        return [("away", get(5), ln), ("home", get(6), None if ln is None else -ln)]
    return [("over", get(5), get(4)), ("under", get(6), get(4))]


def pin_prob(g, mkt, key, line):
    snap = ((g.get("pin") or {}).get("l") or {}).get(mkt)
    if not snap:
        return None
    if mkt == "ml":
        odds = {k: v for k, v in snap.items() if v}
        if key not in odds:
            return None
        inv = {k: 1 / v for k, v in odds.items()}
    elif mkt == "sp":
        if any(k not in snap for k in ("away", "home")) or snap[key][0] != line:
            return None
        inv = {k: 1 / snap[k][1] for k in ("away", "home") if snap[k][1]}
    else:
        if snap.get("line") != line or not snap.get("over") or not snap.get("under"):
            return None
        inv = {"over": 1 / snap["over"], "under": 1 / snap["under"]}
    return inv[key] / sum(inv.values()) if key in inv else None


def prob(g, mkt, key, line):
    if mkt == "ml" and g["sport"] == "soccer" and g.get("model"):
        return g["model"]["p"][["home", "draw", "away"].index(key)], "模型一"
    if mkt == "ml" and g["sport"] != "soccer" and g.get("m1"):
        return g["m1"]["p"][0 if key == "away" else 1], "模型一"
    p = pin_prob(g, mkt, key, line)
    return (p, "Pinnacle") if p else (None, None)


def tw_odds(g, mkt, key, line, us, tw):
    rec = ((g.get("tw") or {}).get(mkt) or {}).get(key)
    if rec and rec[0] and (mkt == "ml" or rec[1] is None or rec[1] == line):
        return rec[0], "actual"
    return round(us * (1 + discount(tw, g["sport"], mkt) / 100), 2), "est"


def kelly(p, o):
    f = (p * o - 1) / (o - 1) if o > 1 else 0
    return round(min(max(f, 0) * KELLY_FRAC, KELLY_CAP) * 100, 2)


def pick_name(g, mkt, key, line):
    nm = "和局" if key == "draw" else "大" if key == "over" else "小" if key == "under" else (g.get(key + "_zh") or g[key])
    if mkt == "sp":
        return f"{nm} {'+' if line > 0 else ''}{line:g}"
    if mkt == "ou":
        return f"{nm} {line:g}"
    return nm


def find(g, tw):
    """這場比賽所有 ≥ +2% 的選項"""
    snap = next((s for s in reversed(g.get("snaps") or []) if any(s.get(m) for m in ("ml", "sp", "ou"))), None)
    if not snap:
        return []
    out = []
    for mkt in ("ml", "sp", "ou"):
        ss = us_sides(g, snap, mkt)
        if not ss or any(not o or o <= 1 for _, o, _ in ss):
            continue
        for key, us, line in ss:
            if mkt != "ml" and line is None:
                continue
            p, src = prob(g, mkt, key, line)
            if not p or not (0.02 < p < 0.98):
                continue
            two, tsrc = tw_odds(g, mkt, key, line, us, tw)
            for kind, o, osrc in (("tw", two, tsrc), ("us", us, "us")):
                ev = p * o - 1
                if EV_MIN <= ev <= EV_MAX:
                    out.append({"market": mkt, "side": key, "line": "" if line is None else line, "pick_zh": pick_name(g, mkt, key, line),
                                "kind": kind, "odds": o, "odds_src": osrc, "p": round(p, 4), "p_src": src, "ev": round(ev, 4),
                                "stake_pct": kelly(p, o) if kind == "tw" else ""})
    return out


def run(sports, now=None):
    now = now or datetime.now(timezone.utc)
    data = B.build(now)
    tw = data["tw"]
    for sport in sports:
        path = path_for(sport)
        rows = read_rows(path)
        seen = {(r["game_id"], r["market"], r["side"], str(r["line"]), r["kind"]) for r in rows}
        new = []
        for g in data["games"]:
            if g["sport"] != sport or g["status"] != "upcoming":
                continue
            t = parse_time(g["t"])
            if not (now + timedelta(minutes=10) < t <= now + timedelta(hours=HORIZON_H)):
                continue
            for a in find(g, tw):
                k = (g["id"], a["market"], a["side"], str(a["line"]), a["kind"])
                if k in seen:
                    continue
                seen.add(k)
                new.append({"created_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "sport": sport, "league": g.get("league", sport),
                            "game_id": g["id"], "game_time_utc": g["t"], "away_zh": g.get("away_zh") or g["away"],
                            "home_zh": g.get("home_zh") or g["home"], **a})
        if new:
            exists = os.path.exists(path)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "a", newline="", encoding="utf-8") as f:
                w = csv.DictWriter(f, fieldnames=FIELDS)
                if not exists:
                    w.writeheader()
                w.writerows(new)
        print(f"  {sport}：新提醒 {len(new)} 筆" + "".join(f"\n    {r['away_zh']}@{r['home_zh']} {MK[r['market']]} {r['pick_zh']} "
                                                       f"{'台彩' if r['kind'] == 'tw' else '美國'} {r['odds']} 期望值 {r['ev'] * 100:+.1f}%" for r in new))


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "mlb,nba,nfl,nhl"
    run([s for s in arg.split(",") if s])
