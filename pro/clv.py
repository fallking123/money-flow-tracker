"""
職業版・第 0 階段：CLV（搶到的價錢比收盤好多少）
================================================================
CLV 是職業團隊最看重的成績單：下注那一刻的賠率，跟「收盤」比好還是壞。
收盤（尤其 Pinnacle 收盤）是全世界最準的價錢，所以：
- 下注時賠率 × 收盤的公平勝率 − 1 ＝ 「用收盤當標準答案」算出來的期望值（clv）
- 收盤公平勝率 − 下注當時公平勝率 ＝ 盤口往你這邊移了多少（dp，跟賠率高低、抽成無關，純看「你有沒有比市場早知道」）
雜訊比輸贏小很多：幾百注就看得出有沒有本事；輸贏要幾千注。

這一版做三件事（只讀資料，輸出到 docs/data/pro/）：
A. 市場本身：收盤比「第一次看到的盤」準多少（我們自己的記錄＋歷史幾萬場）→ 證明收盤是好的標準答案
B. 資金流向「錢比人多」訊號：訊號第一次出現就下，CLV 是多少（分門檻、分離開賽多久）
C. 模型一・美國賠率：每一注的 CLV（跟 Pinnacle 收盤比）

用法：python3 -m pro.clv
輸出：docs/data/pro/clv_report.json（看板「職業版」分頁用）、docs/data/pro/clv_signals.csv（每一個訊號，查帳用）
"""
import csv
import glob
import json
import math
import os
import statistics
from datetime import datetime, timezone

from pro import lines as L
from sports_common import read_rows

OUT = os.path.join(L.DATA, "pro")
SPORTS = ("nfl", "nhl", "mlb", "nba", "soccer")
THRESH = (10, 15, 20, 25, 30)
HBUCKETS = [(24, 1e9, "24 小時以上"), (6, 24, "6–24 小時"), (1, 6, "1–6 小時"), (0, 1, "1 小時內")]


def mean_se(xs):
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if not n:
        return {"n": 0}
    m = sum(xs) / n
    se = statistics.stdev(xs) / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean": round(m, 5), "se": round(se, 5) if se is not None else None}


def first_fair(pg, soccer):
    """第一次看到完整獨贏盤的時間和公平機率"""
    pg._prep()
    seen = set()
    for ts, k, _, _ in pg.ev:
        seen.add(k)
        if k[0] == "moneyline":
            f = L.fair_ml(pg.state(ts), soccer)
            if f:
                return ts, f
    return None, None


def logloss(p):
    return -math.log(max(p, 1e-6))


# ───────── A. 市場本身：收盤比第一次看到的準多少 ─────────
def market_live(games):
    out = {}
    for sp in SPORTS:
        gs = [g for g in games if g["sport"] == sp and g["pin"] and g["result"]]
        o_ll, c_ll, moves, hrs = [], [], [], []
        for g in gs:
            soccer = sp == "soccer"
            w = g["result"]["winner"]
            if not soccer and w == "tie":
                continue
            key = {"tie": "draw"}.get(w, w)
            t0, f0 = first_fair(g["pin"], soccer)
            fc = L.fair_ml(g["pin"].close(), soccer)
            if not f0 or not fc:
                continue
            o_ll.append(logloss(f0[key]))
            c_ll.append(logloss(fc[key]))
            moves.append(abs(fc["home"] - f0["home"]))
            hrs.append((g["pin"].t - t0).total_seconds() / 3600)
        if o_ll:
            out[sp] = {"n": len(o_ll), "ll_first": round(sum(o_ll) / len(o_ll), 4), "ll_close": round(sum(c_ll) / len(c_ll), 4),
                       "move": round(sum(moves) / len(moves), 4), "first_h": round(statistics.median(hrs), 1)}
    return out


def market_hist():
    """歷史：足球 football-data（Pinnacle 賽前 vs Pinnacle 收盤）、美國 SBRO/ESPN（開盤 vs 收盤）"""
    out = {}
    # 足球：PSH/PSD/PSA（大約賽前兩三天抓的）vs PSCH/PSCD/PSCA（收盤）
    o_ll, c_ll, mv = [], [], []
    for f in glob.glob(os.path.join(L.DATA, "soccer", "eu", "*.csv")):
        with open(f, encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                if r.get("FTR") not in ("H", "D", "A"):
                    continue
                po = [L.num(r.get(k)) for k in ("PSH", "PSD", "PSA")]
                pc = [L.num(r.get(k)) for k in ("PSCH", "PSCD", "PSCA")]
                if any(not x or x <= 1 for x in po + pc):
                    continue
                fo = [1 / x for x in po]
                fo = [x / sum(fo) for x in fo]
                fc = [1 / x for x in pc]
                fc = [x / sum(fc) for x in fc]
                i = "HDA".index(r["FTR"])
                o_ll.append(logloss(fo[i]))
                c_ll.append(logloss(fc[i]))
                mv.append(abs(fc[0] - fo[0]))
    if o_ll:
        out["soccer"] = {"n": len(o_ll), "ll_first": round(sum(o_ll) / len(o_ll), 4), "ll_close": round(sum(c_ll) / len(c_ll), 4),
                         "move": round(sum(mv) / len(mv), 4), "what": "Pinnacle 賽前 2–3 天 vs Pinnacle 收盤"}
    dec = lambda a: (1 + a / 100 if a > 0 else 1 + 100 / -a) if a and abs(a) >= 100 else None
    for sp in ("nhl", "mlb", "nba"):
        o_ll, c_ll, mv = [], [], []
        for f in glob.glob(os.path.join(L.DATA, sp, "history", "*.csv")):
            with open(f) as fh:
                for r in csv.DictReader(fh):
                    if "ml_open_home" not in r:
                        break
                    oh, oa, ch, ca = (dec(L.num(r.get(k))) for k in ("ml_open_home", "ml_open_away", "ml_close_home", "ml_close_away"))
                    hs, as_ = L.num(r.get("home_score")), L.num(r.get("away_score"))
                    if not all((oh, oa, ch, ca)) or hs is None or as_ is None or hs == as_:
                        continue
                    po = (1 / oh) / (1 / oh + 1 / oa)
                    pc = (1 / ch) / (1 / ch + 1 / ca)
                    hw = hs > as_
                    o_ll.append(logloss(po if hw else 1 - po))
                    c_ll.append(logloss(pc if hw else 1 - pc))
                    mv.append(abs(pc - po))
        if o_ll:
            out[sp] = {"n": len(o_ll), "ll_first": round(sum(o_ll) / len(o_ll), 4), "ll_close": round(sum(c_ll) / len(c_ll), 4),
                       "move": round(sum(mv) / len(mv), 4), "what": "美國開盤 vs 美國收盤"}
    return out


# ───────── B. 資金流向訊號 ─────────
def sides_of(sport, mkt):
    if mkt == "ml":
        return ("home", "draw", "away") if sport == "soccer" else ("away", "home")
    if mkt == "sp":
        return ("home", "away") if sport == "soccer" else ("away", "home")
    return ("over", "under")


def signals(games):
    rows = []
    for g in games:
        pg = g["pin"]
        if not pg:
            continue
        sp, soccer = g["sport"], g["sport"] == "soccer"
        close = pg.close()
        fc_ml = L.fair_ml(close, soccer)
        for mkt in ("ml", "sp", "ou"):
            for side in sides_of(sp, mkt):
                b, m = f"{mkt}_{side}_bets_pct", f"{mkt}_{side}_money_pct"
                done = set()
                for r in g["rows"]:
                    bp, mp = L.num(r.get(b)), L.num(r.get(m))
                    if bp is None or mp is None:
                        continue
                    diff = mp - bp
                    for T in THRESH:
                        if T in done or diff < T:
                            continue
                        done.add(T)
                        st = pg.state(r["_ts"])
                        h = (g["t"] - r["_ts"]).total_seconds() / 3600
                        rec = {"sport": sp, "league": g["league"], "gid": g["gid"], "t": g["t"].strftime("%Y-%m-%dT%H:%MZ"),
                               "home": g["home"], "away": g["away"], "mkt": mkt, "side": side, "thr": T, "diff": round(diff, 1),
                               "hours": round(h, 2), "dp": None, "clv_us": None, "clv_pin": None, "gain_pts": None, "result": None}
                        if mkt == "ml":
                            f0 = L.fair_ml(st, soccer)
                            us = L.num(r.get(f"ml_{side}_odds"))
                            pin_o = (st.get(("moneyline", side)) or (None, None))[1]
                            if f0 and fc_ml:
                                rec["dp"] = round(fc_ml[side] - f0[side], 5)
                                if us and us > 1:
                                    rec["clv_us"] = round(us * fc_ml[side] - 1, 5)
                                    base = [L.num(r.get(f"ml_{s}_odds")) * fc_ml[s] - 1 for s in sides_of(sp, "ml") if L.num(r.get(f"ml_{s}_odds"))]
                                    rec["clv_base"] = round(sum(base) / len(base), 5) if base else None
                                if pin_o:
                                    rec["clv_pin"] = round(pin_o * fc_ml[side] - 1, 5)
                            if g["result"]:
                                w = {"tie": "draw"}.get(g["result"]["winner"], g["result"]["winner"])
                                rec["result"] = "push" if (not soccer and w == "draw") else ("win" if w == side else "loss")
                                rec["us_odds"] = us
                        else:
                            market = "spread" if mkt == "sp" else "total"
                            a = (st.get((market, side)) or (None, None))[0]
                            c = (close.get((market, side)) or (None, None))[0]
                            if a is not None and c is not None:
                                # 讓分：這一邊的讓分數字越大越好（+3 比 +2.5 好、−2.5 比 −3 好）
                                # 大小：大分希望線越低、小分希望線越高
                                rec["gain_pts"] = round((a - c) if mkt == "sp" else ((c - a) if side == "over" else (a - c)), 2)
                        rows.append(rec)
    return rows


def summarize_signals(rows):
    out = {}
    for mkt in ("ml", "sp", "ou"):
        for T in THRESH:
            rs = [r for r in rows if r["mkt"] == mkt and r["thr"] == T]
            if not rs:
                continue
            item = {"all": _sum(rs, mkt)}
            item["by_h"] = [{"label": lab, **_sum([r for r in rs if lo <= r["hours"] < hi], mkt)} for lo, hi, lab in HBUCKETS]
            item["by_sport"] = {sp: _sum([r for r in rs if r["sport"] == sp], mkt) for sp in sorted({r["sport"] for r in rs})}
            out[f"{mkt}_{T}"] = item
    return out


def _sum(rs, mkt):
    if mkt == "ml":
        d = mean_se([r["dp"] for r in rs])
        cu = mean_se([r["clv_us"] for r in rs])
        cb = mean_se([r.get("clv_base") for r in rs if r["clv_us"] is not None])
        cp = mean_se([r["clv_pin"] for r in rs])
        tw = [r for r in rs if r["dp"] is not None]
        toward = sum(1 for r in tw if r["dp"] > 0.002) / len(tw) if tw else None
        away = sum(1 for r in tw if r["dp"] < -0.002) / len(tw) if tw else None
        done = [r for r in rs if r["result"] in ("win", "loss") and r.get("us_odds")]
        roi = sum((r["us_odds"] - 1) if r["result"] == "win" else -1 for r in done) / len(done) if done else None
        return {"n": len(rs), "dp": d, "clv_us": cu, "clv_base": cb, "clv_pin": cp,
                "toward": round(toward, 3) if toward is not None else None, "away": round(away, 3) if away is not None else None,
                "n_done": len(done), "roi_us": round(roi, 4) if roi is not None else None}
    gs = [r["gain_pts"] for r in rs if r["gain_pts"] is not None]
    return {"n": len(rs), "gain": mean_se(gs),
            "toward": round(sum(1 for x in gs if x > 0) / len(gs), 3) if gs else None,
            "away": round(sum(1 for x in gs if x < 0) / len(gs), 3) if gs else None}


# ───────── C. 模型一・美國賠率每一注的 CLV ─────────
def model1_clv(games):
    """每一注：用美國賠率下 × Pinnacle 收盤公平勝率 − 1；另外算「同一時間兩邊隨便押」的平均當基準，
    以及從記錄那一刻到收盤，盤口往模型押的那邊移了多少（dp）"""
    from sports_common import parse_time
    by = {g["gid"]: g for g in games}
    out = {}
    for sp in SPORTS:
        path = os.path.join(L.DATA, sp, "model_picks.csv")
        if not os.path.exists(path):
            continue
        cl, base, dps = [], [], []
        for r in read_rows(path):
            if r["strategy"] != "model1_us":
                continue
            g = by.get(r["game_id"])
            us = L.num(r["us_odds"])
            if not g or not g["pin"] or not us:
                continue
            soccer = sp == "soccer"
            fc = L.fair_ml(g["pin"].close(), soccer)
            if not fc or r["pick"] not in fc:
                continue
            cl.append(us * fc[r["pick"]] - 1)
            # 基準：記錄那一刻，我們的美國賠率每一邊都押的平均
            try:
                t = parse_time(r["updated_utc"].replace("Z", ":00+00:00") if r["updated_utc"].count(":") == 1 else r["updated_utc"])
            except Exception:
                t = None
            row = None
            if t:
                for x in g["rows"]:
                    if x["_ts"] <= t:
                        row = x
            if row:
                bs = [L.num(row.get(f"ml_{s}_odds")) * fc[s] - 1 for s in fc if L.num(row.get(f"ml_{s}_odds"))]
                if bs:
                    base.append(sum(bs) / len(bs))
                f0 = L.fair_ml(g["pin"].state(t), soccer)
                if f0:
                    dps.append(fc[r["pick"]] - f0[r["pick"]])
        if cl:
            out[sp] = {**mean_se(cl), "pos": round(sum(1 for x in cl if x > 0) / len(cl), 3),
                       "base": mean_se(base), "dp": mean_se(dps)}
    vs = list(out.values())
    if vs:
        n = sum(v["n"] for v in vs)
        nb = sum(v["base"]["n"] for v in vs)
        out["all"] = {"n": n, "mean": round(sum(v["mean"] * v["n"] for v in vs) / n, 5),
                      "base": round(sum(v["base"]["mean"] * v["base"]["n"] for v in vs if v["base"]["n"]) / nb, 5) if nb else None}
    return out


def main():
    games = []
    for sp in SPORTS:
        try:
            games += L.linked(sp)
        except FileNotFoundError:
            continue
    sig = signals(games)
    rep = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "coverage": {sp: {"games": sum(1 for g in games if g["sport"] == sp),
                          "pin": sum(1 for g in games if g["sport"] == sp and g["pin"]),
                          "done": sum(1 for g in games if g["sport"] == sp and g["pin"] and g["result"])}
                     for sp in SPORTS if any(g["sport"] == sp for g in games)},
        "market_live": market_live(games),
        "market_hist": market_hist(),
        "signals": summarize_signals(sig),
        "model1_us": model1_clv(games),
    }
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "clv_report.json"), "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    keys = ["sport", "league", "gid", "t", "home", "away", "mkt", "side", "thr", "diff", "hours", "dp", "clv_us", "clv_pin", "gain_pts", "result", "us_odds"]
    with open(os.path.join(OUT, "clv_signals.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(sig)
    print(f"CLV：{len(games)} 場、{len(sig)} 個訊號 → docs/data/pro/clv_report.json")
    return rep


if __name__ == "__main__":
    main()
