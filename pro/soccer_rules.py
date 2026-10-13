"""
職業版・足球的大小 2.5、亞洲讓分下注規則（直接看 CLV）
================================================================
- 大小 2.5：模型（第 1 階段比分模型）的大分機率，先用之前的季校準（羅吉斯），跟 Pinnacle 早盤（P>2.5、P<2.5，賽前 2–3 天）比，
  差 ≥ 門檻就用早盤價下，CLV＝收盤（PC>2.5）公平機率 × 早盤賠率 − 1。
- 亞洲讓分：早盤和收盤讓分線一樣的比賽（AHh＝AHCh），模型的過盤機率同樣校準，用 Pinnacle 早盤讓分賠率（PAHH/PAHA）。
- 練習區 2016/17–2024/25，4 段；通過標準跟其他規則一樣，記在 search_log_soccer.json。
用法：python3 -m pro.soccer_rules ou_10 ah_10
"""
import csv
import glob
import gzip
import json
import math
import os
import sys
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression

from pro import mlb_search as S
from pro import soccer_model as SM
from pro import soccer_search as SC


def raw():
    d = {}
    for f in sorted(glob.glob(os.path.join(SM.EU, "*.csv"))):
        div = os.path.basename(f).split("_")[0]
        for r in csv.DictReader(open(f, encoding="latin-1")):
            if not r.get("HomeTeam"):
                continue
            try:
                dt = SM.parse_dt(r["Date"], r.get("Time"))
            except (ValueError, KeyError):
                continue
            d[(div, dt.strftime("%Y-%m-%d %H:%M"), r["HomeTeam"].strip())] = r
    return d


def rows():
    R = raw()
    out = []
    with gzip.open(os.path.join(SM.OUT, "soccer_preds_all.csv.gz"), "rt", encoding="utf-8") as f:
        for p in csv.DictReader(f):
            r = R.get((p["div"], p["date"], p["home"]))
            if not r:
                continue
            dt = datetime.strptime(p["date"], "%Y-%m-%d %H:%M")
            g = lambda k: SM.num(r.get(k))
            out.append({"ss": SC.season_of(dt), "div": p["div"], "hg": int(p["hg"]), "ag": int(p["ag"]),
                        "po": float(p["p_over25"]), "pah": SM.flt(p["p_ah_home"]), "ahc": SM.flt(p["ahc"]),
                        "ou_o": (g("P>2.5"), g("P<2.5")), "ou_c": (g("PC>2.5"), g("PC<2.5")),
                        "ahh": SM.flt(r.get("AHh")), "ah_o": (g("PAHH"), g("PAHA")), "ah_c": (g("PCAHH"), g("PCAHA"))})
    return out


def lg(p):
    p = min(max(p, 1e-4), 1 - 1e-4)
    return math.log(p / (1 - p))


def calib(train, key, ykey):
    m = LogisticRegression(C=10.0).fit([[lg(t[key])] for t in train], [t[ykey] for t in train])
    return lambda p: float(m.predict_proba([[lg(p)]])[0, 1])


def ou_bets(R, edge):
    for r in R:
        r["y_over"] = int(r["hg"] + r["ag"] > 2.5)
    out = {}
    for blk in SC.BLOCKS:
        b = []
        for s in range(int(blk[0]), int(blk[1])):
            tr = [r for r in R if 2015 <= r["ss"] < s]
            te = [r for r in R if r["ss"] == s and all(r["ou_o"]) and all(r["ou_c"])]
            if len(tr) < 2000:
                continue
            cal = calib(tr, "po", "y_over")
            for r in te:
                fo, fc = SM.fair(r["ou_o"]), SM.fair(r["ou_c"])
                if not fo or not fc or abs(fc[0] - fo[0]) >= 0.08:
                    continue
                p = cal(r["po"])
                for q, qc, o in ((p, fc[0], r["ou_o"][0]), (1 - p, fc[1], r["ou_o"][1])):
                    if q * o - 1 >= edge:
                        b.append(qc * o - 1)
        out[blk] = b
    return out


def ah_bets(R, edge):
    for r in R:
        if r["ahc"] is not None:
            m = r["hg"] - r["ag"] + r["ahc"]
            r["y_ah"] = None if m == 0 else int(m > 0)
    out = {}
    for blk in SC.BLOCKS:
        b = []
        for s in range(int(blk[0]), int(blk[1])):
            ok = lambda r: r["pah"] is not None and r["ahc"] is not None and r.get("y_ah") is not None and (r["ahc"] * 4) % 2 == 0
            tr = [r for r in R if 2015 <= r["ss"] < s and ok(r)]
            te = [r for r in R if r["ss"] == s and ok(r) and r["ahh"] == r["ahc"] and all(r["ah_o"]) and all(r["ah_c"])]
            if len(tr) < 2000:
                continue
            cal = calib(tr, "pah", "y_ah")
            for r in te:
                fo, fc = SM.fair(r["ah_o"]), SM.fair(r["ah_c"])
                if not fo or not fc or abs(fc[0] - fo[0]) >= 0.08:
                    continue
                p = cal(r["pah"])
                for q, qc, o in ((p, fc[0], r["ah_o"][0]), (1 - p, fc[1], r["ah_o"][1])):
                    if q * o - 1 >= edge:
                        b.append(qc * o - 1)
        out[blk] = b
    return out


RULES = {
    "ou_5": ("大小 2.5：模型比早盤多看好 ≥ 5%", "大小分市場通常比主和客鬆；比分模型本來就是算進球數的", lambda R: ou_bets(R, 0.05)),
    "ou_10": ("大小 2.5：模型比早盤多看好 ≥ 10%", "同上，只挑差很多的", lambda R: ou_bets(R, 0.10)),
    "ah_10": ("亞洲讓分（早盤和收盤同一條線）：看好 ≥ 10%", "讓分只看兩隊差距，比分模型直接算得出來", lambda R: ah_bets(R, 0.10)),
}


def main(names):
    R = rows()
    print(f"足球：{len(R)} 場", flush=True)
    log = SC.load_log()
    for nm in names:
        label, why, fn = RULES[nm]
        per = fn(R)
        res = {"blocks": [], "better_blocks": 0}
        allb = []
        for blk, b in per.items():
            allb += b
            m = float(np.mean(b)) if b else 0.0
            res["blocks"].append({"seasons": f"{blk[0]}–{int(blk[1]) - 1}", "n": len(b), "clv": round(m, 4)})
            res["better_blocks"] += int(m > 0)
        a = np.array(allb)
        res["z"] = round(float(a.mean() / (a.std() / math.sqrt(len(a)))), 2) if len(a) > 1 else 0.0
        res["clv_all"] = [round(float(a.mean()), 4), round(float(a.std() / math.sqrt(len(a))), 4), len(a)]
        SC.log_try(log, {"name": "rule_" + nm, "kind": "rule", "label": label, "why": why, **res})
        print("    全部：", res["clv_all"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
