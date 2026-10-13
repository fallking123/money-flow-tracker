"""
職業版・NBA／NFL 特徵搜尋（練習區），用「讓分」量：收盤讓分有沒有往模型移（單位：分）
================================================================
- 開盤／收盤讓分＝SBRO 歷史檔（pro/fetch_sbro_open.py）：NBA 2007-08～2022-23、NFL 2007～2021（NFL 練習區 2011–2021：前兩季沒有足夠的訓練資料）。
- 基本模型＝第 2 版（用球員組出球隊）的「開盤版」（只用上一場的名單），第二層跟第 2 版一樣（嶺迴歸預測分差）。
- 成績：用開盤＋b×（模型分差−開盤）預測收盤，誤差少多少（每場配對）。收盤大動（NBA ≥ 3 分、NFL ≥ 2.5 分，
  通常是臨時傷兵）排除。通過標準、門檻跟 MLB 一樣；每次嘗試記在 docs/data/pro/search_log_<運動>.json。
用法：python3 -m pro.spread_search nba <候選…>
"""
import csv
import json
import math
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np

from pro import mlb_search as S

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "data", "pro")
CFG = {
    "nba": {"blocks": [(2011, 2013), (2014, 2016), (2017, 2019), (2020, 2023)], "calm": 3.0, "first": 2010},
    "nfl": {"blocks": [(2011, 2012), (2013, 2015), (2016, 2018), (2019, 2021)], "calm": 2.5, "first": 2006},
}
TZ_NBA = {**{t: -6 for t in ("CHI", "DAL", "HOU", "MEM", "MIL", "MIN", "NO", "NOH", "NOK", "OKC", "SA")},
          **{t: -7 for t in ("DEN", "UTAH", "UTA", "PHX")}, **{t: -8 for t in ("GS", "LAC", "LAL", "POR", "SAC", "SEA")}}
TZ_NFL = {**{t: -6 for t in ("CHI", "DAL", "GB", "HOU", "KC", "MIN", "NO", "TEN")}, **{t: -7 for t in ("DEN", "ARI")},
          **{t: -8 for t in ("LA", "LAC", "LV", "SEA", "SF")}}


def cache_path(sport):
    return os.path.join(os.environ.get("PRO_CACHE", "/tmp"), f"{sport}_base_prev.pkl")


def base(sport):
    p = cache_path(sport)
    if os.path.exists(p):
        return pickle.load(open(p, "rb"))
    R = json.load(open(os.path.join(OUT, "us_report.json"), encoding="utf-8"))[sport + "2"]["chosen"]
    if sport == "nba":
        from pro import nba_player_model as NB
        games = NB.V1.load()
        feats = NB.features(games, NB.load_box(), NB.load_players(), {**R, "lineup": "prev"})
        for f in feats:
            f["hs_"], f["as_"] = f["hs"], f["as"]
    else:
        from pro import nfl_player_model as NF
        games, tg = NF.V1.load()
        feats = NF.features(games, tg, NF.load_extra(), NF.load_players(), {**R, "lineup": "prev"})
        for f in feats:
            f["hs_"], f["as_"] = float(f["home_score"]), float(f["away_score"])
    # 開盤／收盤讓分（日期＋比分對）
    lines = defaultdict(list)
    for r in csv.DictReader(open(os.path.join(OUT, sport, "sbro_lines.csv"), encoding="utf-8")):
        try:
            lines[(r["date"], int(float(r["home_score"])), int(float(r["away_score"])))].append(r)
        except (TypeError, ValueError):
            pass
    n = 0
    for f in feats:
        dt = datetime.strptime(f["date"][:10], "%Y-%m-%d")
        f["so"] = f["sc"] = f["to"] = f["tc"] = None
        for dd in (0, -1, 1):
            c = lines.get(((dt + timedelta(days=dd)).strftime("%Y-%m-%d"), int(f["hs_"]), int(f["as_"])), [])
            if len(c) == 1 and c[0]["spread_open_home"] and c[0]["spread_close_home"]:
                f["so"], f["sc"] = -float(c[0]["spread_open_home"]), -float(c[0]["spread_close_home"])     # 主隊預期贏幾分
                try:
                    f["to"], f["tc"] = float(c[0]["total_open"]), float(c[0]["total_close"])
                except (TypeError, ValueError):
                    f["to"] = f["tc"] = None
                n += 1
                break
    print(f"{sport}：{len(feats)} 場、對到開收盤讓分 {n}", flush=True)
    pickle.dump((games, feats, R), open(p, "wb"))
    return games, feats, R


def predict(sport, feats, extra, seasons, alpha):
    K = len(next(iter(extra.values()))) if extra else 0
    X = {f["game_id"]: np.array(list(f["x_m"]) + (extra.get(f["game_id"], [0.0] * K) if K else []), float) for f in feats}
    out = []
    for s in range(seasons[0], seasons[1] + 1):
        tr = [f for f in feats if CFG[sport]["first"] <= f["season"] < s]
        te = [f for f in feats if f["season"] == s]
        if len(tr) < 300 or not te:
            continue
        A = np.array([X[f["game_id"]] for f in tr])
        y = np.array([f["margin"] for f in tr], float)
        mu, sd = A.mean(0), A.std(0) + 1e-9
        Z = (A - mu) / sd
        b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
        P = y.mean() + ((np.array([X[f["game_id"]] for f in te]) - mu) / sd) @ b
        for f, pm in zip(te, P):
            out.append({"game_id": f["game_id"], "pm": float(pm), "so": f["so"], "sc": f["sc"], "margin": f["margin"], "f": f})
    return out


def predict_total(sport, feats, seasons, alpha, extra=None):
    """大小分：第 2 版的總分特徵（x_t）＋候選，嶺迴歸預測總分"""
    K = len(next(iter(extra.values()))) if extra else 0
    X = {f["game_id"]: np.array(list(f["x_t"]) + (extra.get(f["game_id"], [0.0] * K) if K else []), float) for f in feats}
    out = []
    for s in range(seasons[0], seasons[1] + 1):
        tr = [f for f in feats if CFG[sport]["first"] <= f["season"] < s]
        te = [f for f in feats if f["season"] == s]
        if len(tr) < 300 or not te:
            continue
        A = np.array([X[f["game_id"]] for f in tr])
        y = np.array([f["total"] for f in tr], float)
        mu, sd = A.mean(0), A.std(0) + 1e-9
        Z = (A - mu) / sd
        b = np.linalg.solve(Z.T @ Z + alpha * np.eye(Z.shape[1]), Z.T @ (y - y.mean()))
        P = y.mean() + ((np.array([X[f["game_id"]] for f in te]) - mu) / sd) @ b
        for f, pt in zip(te, P):
            out.append({"game_id": f["game_id"], "pt": float(pt), "to": f.get("to"), "tc": f.get("tc"), "total": f["total"], "f": f})
    return out


def score(sport, preds):
    rs = [r for r in preds if r["so"] is not None and abs(r["sc"] - r["so"]) < CFG[sport]["calm"]]
    d = np.array([r["pm"] - r["so"] for r in rs])
    m = np.array([r["sc"] - r["so"] for r in rs])
    b = float(d @ m / (d @ d)) if len(rs) else 0.0
    big = [mm * np.sign(dd) for dd, mm in zip(d, m) if abs(dd) >= 2.0]
    return {"ids": [r["game_id"] for r in rs], "err": (m - b * d) ** 2, "b": b, "n": len(rs),
            "clv": (float(np.mean(big)) if big else 0.0, float(np.std(big) / math.sqrt(len(big))) if len(big) > 1 else None, len(big)),
            "ll_each": {r["game_id"]: (r["margin"] - r["pm"]) ** 2 / 100 for r in preds}}


def blocks(sport, feats, extra, alpha):
    return {blk: score(sport, predict(sport, feats, extra, blk, alpha)) for blk in CFG[sport]["blocks"]}


# ─────────── 候選特徵 ───────────
def _team_games(feats):
    tg = defaultdict(list)
    for f in sorted(feats, key=lambda f: f["date"]):
        tg[f["home"]].append(f)
        tg[f["away"]].append(f)
    return tg


def sched(sport, feats):
    """賽程：3 天內第 3 場、6 天內第 4 場、最近 7 天客場幾場、跨時區、到高海拔球場（丹佛、猶他）的背靠背"""
    TZ = TZ_NBA if sport == "nba" else TZ_NFL
    hist = defaultdict(list)
    out = {}
    for f in sorted(feats, key=lambda f: f["date"]):
        dt = datetime.strptime(f["date"][:10], "%Y-%m-%d")
        tz_here = TZ.get(f["home"], -5)
        v = {}
        for side in ("home", "away"):
            h = hist[f[side]]
            last = h[-1] if h else None
            gap = (dt - last[0]).days if last else 7
            in4 = sum(1 for d, _, _ in h if 0 < (dt - d).days <= 3)
            in6 = sum(1 for d, _, _ in h if 0 < (dt - d).days <= 5)
            road7 = sum(1 for d, _, away in h if 0 < (dt - d).days <= 7 and away)
            shift = abs(tz_here - last[1]) if last else 0
            alt = 1.0 if side == "away" and f["home"] in ("DEN", "UTAH", "UTA") and gap <= 1 else 0.0
            v[side] = [float(in4 >= 2), float(in6 >= 3), road7, shift, alt]
        out[f["game_id"]] = [a - b for a, b in zip(v["home"], v["away"])]
        hist[f["home"]].append((dt, tz_here, False))
        hist[f["away"]].append((dt, tz_here, True))
    return out


def turnover_early(sport, feats):
    """開季初（NBA 前 20 場、NFL 前 4 週）：上一場名單裡，去年在別隊的人占幾成（去年的球隊數據不準）"""
    if sport == "nba":
        from pro import nba_player_model as NB
        box = NB.load_box()
        lu = {gid: [(t, p) for (t, p, v) in rows] for gid, rows in box.items()}
    else:
        from pro import nfl_player_model as NF
        snaps = NF.load_extra()[0]
        lu = {gid: [(t, p) for (t, p, g, pct) in rows] for gid, rows in snaps.items()}
    team_season, last, ngames = {}, {}, Counter()
    out = {}
    for f in sorted(feats, key=lambda f: f["date"]):
        s = f["season"]
        v = {}
        for side in ("home", "away"):
            t = f[side]
            early = ngames[(t, s)] < (20 if sport == "nba" else 4)
            ppl = last.get(t, [])
            known = [team_season.get((p, s - 1)) for p in ppl]
            known = [x for x in known if x]
            v[side] = (sum(1 for x in known if x != t) / len(known)) if (known and early) else 0.0
        out[f["game_id"]] = [v["home"] - v["away"]]
        rows = lu.get(f["game_id"], [])
        for t in (f["home"], f["away"]):
            ps = [p for tt, p in rows if tt == t]
            if ps:
                last[t] = ps
            ngames[(t, s)] += 1
        for tt, p in rows:
            team_season[(p, s)] = tt
    return out


def tank(sport, feats):
    """球季後段（NBA 2 月中以後），戰績倒數 8 名的隊（擺爛搶選秀）"""
    rec = defaultdict(lambda: [0, 0])
    out = {}
    for f in sorted(feats, key=lambda f: f["date"]):
        s, dt = f["season"], f["date"][5:10]
        late = dt >= "02-15" and dt < "07-01"
        teams = [(w / n, t) for (t, ss), (w, n) in rec.items() if ss == s and n >= 10]
        bottom = {t for _, t in sorted(teams)[:8]} if late and len(teams) >= 20 else set()
        out[f["game_id"]] = [float(f["home"] in bottom) - float(f["away"] in bottom)]
        hw = int(f["margin"] > 0)
        for t, w in ((f["home"], hw), (f["away"], 1 - hw)):
            r = rec[(t, s)]
            r[0] += w
            r[1] += 1
    return out


CANDIDATES = {
    "sched": {"fn": sched, "label": "賽程疲勞（密集賽程、客場連戰、跨時區、高海拔）",
              "why": "連續比賽、長途客場、到丹佛猶他高海拔的背靠背，體力差；開盤可能只粗略算"},
    "turnover_early": {"fn": turnover_early, "label": "開季時換了很多人的隊",
                       "why": "跟 MLB、足球一樣：開季時莊家還靠去年的球隊數據，我們的模型跟著球員走"},
    "tank": {"fn": tank, "label": "球季後段擺爛的隊", "why": "戰績差的隊後段會讓年輕球員多打、輸球搶選秀順位；開盤可能沒算夠"},
}
SEG = {
    "early": ("開季初（NBA 10–11 月、NFL 前 4 週）", "開季時莊家資料最少",
              lambda r, sp: (r["f"]["date"][5:7] in ("10", "11")) if sp == "nba" else (str(r["f"].get("week", "99")).isdigit() and int(r["f"]["week"]) <= 4)),
    "late": ("球季最後階段（NBA 3–4 月、NFL 第 15 週以後）", "戰意不同（擺爛、休兵、搶季後賽），開盤可能沒算夠",
             lambda r, sp: (r["f"]["date"][5:7] in ("03", "04")) if sp == "nba" else (str(r["f"].get("week", "0")).isdigit() and int(r["f"]["week"]) >= 15)),
    "div": ("同分區對戰（NFL）", "同分區的隊一年碰兩次、彼此熟悉，一般人常說「分區戰難打」，盤口可能被拉偏",
            lambda r, sp: str(r["f"].get("div_game", "0")) in ("1", "True")),
}


def seg_eval(sport, base_rows, fn):
    res = {"blocks": [], "better_blocks": 0}
    ai, ao = [], []
    for blk, rows in base_rows.items():
        ins, outs = [], []
        for r in rows:
            if r["so"] is None or abs(r["sc"] - r["so"]) >= CFG[sport]["calm"]:
                continue
            d = r["pm"] - r["so"]
            if abs(d) >= 2.0:
                (ins if fn(r, sport) else outs).append((r["sc"] - r["so"]) * np.sign(d))
        ai += ins
        ao += outs
        res["blocks"].append({"seasons": f"{blk[0]}–{blk[1]}", "n_in": len(ins), "move_in": round(float(np.mean(ins)), 3) if ins else None,
                              "n_out": len(outs), "move_out": round(float(np.mean(outs)), 3) if outs else None})
        res["better_blocks"] += int(bool(ins and outs) and np.mean(ins) > np.mean(outs))
    a, b = np.array(ai), np.array(ao)
    res["z"] = round(float((a.mean() - b.mean()) / math.sqrt(a.var() / len(a) + b.var() / len(b))), 2) if len(a) > 1 else 0.0
    res["move_in_all"] = [round(float(a.mean()), 3), round(float(a.std() / math.sqrt(len(a))), 3), len(a)] if len(a) else None
    res["move_out_all"] = [round(float(b.mean()), 3), len(b)]
    return res


def main(sport, names):
    games, feats, R = base(sport)
    log_path = os.path.join(OUT, f"search_log_{sport}.json")
    log = json.load(open(log_path, encoding="utf-8")) if os.path.exists(log_path) else {"sport": sport, "tries": []}
    alpha = R.get("alpha", 5.0)
    blks = CFG[sport]["blocks"]
    base_rows = {blk: predict(sport, feats, {}, blk, alpha) for blk in blks}
    b0 = {blk: score(sport, v) for blk, v in base_rows.items()}
    if "--base" in names:
        for k, v in b0.items():
            print(k, v["n"], round(v["b"], 3), v["clv"])
        return
    for nm in names:
        if nm.startswith("seg_"):
            label, why, fn = SEG[nm[4:]]
            entry = {"name": nm, "kind": "segment", "label": label, "why": why, **seg_eval(sport, base_rows, fn)}
        else:
            c = CANDIDATES[nm]
            extra = c["fn"](sport, feats)
            entry = {"name": nm, "kind": "spread", "label": c["label"], "why": c["why"], **S.compare(b0, blocks(sport, feats, extra, alpha), blks)}
        n = len(log["tries"]) + 1
        thr = S.threshold(n)
        ok = entry["z"] >= thr and entry["better_blocks"] >= 3
        log["tries"].append({"n": n, "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "z_needed": thr, "pass": ok, **entry})
        json.dump(log, open(log_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"#{n} {nm}：z={entry['z']}（門檻 {thr}），{entry['better_blocks']}/4 段 → {'通過' if ok else '沒通過'}", flush=True)
        for b in entry["blocks"]:
            print("   ", b, flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
