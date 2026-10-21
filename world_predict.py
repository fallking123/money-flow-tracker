"""
看板用：全球足球模型（world_model.py 訓練好的參數）算五大聯賽以外比賽的主／和／客機率
"""
import json
import math
import os

from soccer_comps import COMPS
from sports_common import sport_dir

_P = None


def params():
    global _P
    if _P is None:
        p = os.path.join(sport_dir("soccer"), "model", "world_params.json")
        _P = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _P


def _cands(league):
    """這個賽事可能出現的隊伍（隊名比對只在這些裡面找，比較不會對錯）"""
    P = params()
    c = COMPS.get(league) or {}
    if c.get("kind") == "national":
        return {n: n for n in P.get("nations", {})}
    clubs = P.get("clubs", {})
    if c.get("group") == "league":
        lgs = set(c["espn"])
        return {v["n"]: k for k, v in clubs.items() if v["lg"] in lgs}
    if c.get("group") == "cup" and not league.startswith(("libertadores", "sudamericana")):
        pre = c["espn"][0].split(".")[0] + "."            # 國內盃賽：只找同一個國家的球隊
        return {v["n"]: k for k, v in clubs.items() if v["lg"].startswith(pre)}
    return {v["n"]: k for k, v in clubs.items()}


def predict(league, home, away, odds, neutral=False):
    """odds＝[主, 和, 客] 賠率（Pinnacle 或 Action Network）；回傳跟 soccer_dashboard.predict 一樣的格式"""
    from soccer_dashboard import best_team
    P = params()
    if not P or not odds or any(o is None or o <= 1 for o in odds) or league not in COMPS:
        return None
    cand = _cands(league)
    th, ta = best_team(home, cand), best_team(away, cand)
    if not th or not ta or th == ta:
        return None
    nat = COMPS[league]["kind"] == "national"
    if nat:
        rh, ra, hfa = P["nations"][th], P["nations"][ta], P["hfa_n"]
    else:
        rh, ra, hfa = P["clubs"][cand[th]]["r"], P["clubs"][cand[ta]]["r"], P["hfa"]
    if league in ("wc", "euro", "copa", "asian") or neutral:
        hfa = 0.0                                       # 大賽大多是中立場地（地主國例外，這裡先不管）
    inv = [1 / o for o in odds]
    s = sum(inv)
    ph, pd_, pa = (x / s for x in inv)
    x = [math.log(ph / pa), math.log(pd_ / pa), (rh + hfa - ra) / 100.0]
    M = P["mix"]
    z = [(v - m) / sc for v, m, sc in zip(x, M["mean"], M["scale"])]
    lg = [sum(w * v for w, v in zip(ws, z)) + b for ws, b in zip(M["coef"], M["intercept"])]
    mx = max(lg)
    ex = [math.exp(v - mx) for v in lg]
    prob = dict(zip(M["classes"], (e / sum(ex) for e in ex)))
    return {"p": [round(prob["H"], 4), round(prob["D"], 4), round(prob["A"], 4)], "v": "world",
            "elo": [round(rh), round(ra)], "mkt": [round(ph, 4), round(pd_, 4), round(pa, 4)], "teams": [th, ta]}
