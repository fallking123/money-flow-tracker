"""
職業版・地基檢查：用「下注當下就能知道」的條件，重算 MLB／NHL「看好 ≥ 15%」規則
================================================================
發現的問題：
1. 以前排除「開盤到收盤移動 ≥ 8%」的比賽——這用到了未來（下注時不知道會不會大移動）。
2. 但不排除的話，大移動的比賽幾乎都往模型那邊移（MLB 75:1、NHL 31:1），一看就是 SBRO 開盤資料有錯
   （例如 1.08／9.10、兩邊對調、或還沒正式開盤的 1.91／1.91 佔位價），那種價錢實際上下不到。
3. MLB 模型用的是「實際」先發投手；開盤時如果掛的是另一位預定先發（後來換人），模型等於偷看。
這裡只用下注當下就知道的條件過濾：
- sym：開盤兩邊賠率一模一樣（佔位價），不算
- cap：模型比開盤多看好超過 30%（一看就像資料錯，實際上也不會去下）不算
- rot（只有 MLB）：只算「先發是正常輪值」的比賽——這位投手在這隊最近 6 場先發裡出現過、而且休息 ≥ 4 天
輸出 docs/data/pro/audit_clean.json
"""
import json
import math
import os
from collections import defaultdict
from datetime import datetime

import numpy as np

from pro import mlb_search as S
from pro import nhl_search as N


def stats(v):
    a = np.array(v)
    if len(a) < 2:
        return {"n": len(a)}
    return {"n": len(a), "clv": round(float(a.mean()), 4), "se": round(float(a.std() / math.sqrt(len(a))), 4),
            "z": round(float(a.mean() / (a.std() / math.sqrt(len(a)))), 2)}


def rotation_ok(games):
    hist = defaultdict(list)          # team → [(date, sp)]
    ok = {}
    for g in sorted(games, key=lambda g: (g["date"], g["game_id"])):
        d = datetime.strptime(g["date"], "%Y-%m-%d")
        good = True
        for team, sp in ((g["home"], g.get("home_sp")), (g["vis"], g.get("vis_sp"))):
            h = hist[team][-6:]
            last = [x for x, p in h if p == sp]
            if not sp or not last or (d - last[-1]).days < 4:
                good = False
        ok[g["game_id"]] = good
        for team, sp in ((g["home"], g.get("home_sp")), (g["vis"], g.get("vis_sp"))):
            hist[team].append((d, sp))
    return ok


def run(preds_by_blk, extra_ok=None, edge=0.15):
    cfgs = {"舊做法（排除大移動＝偷看）": dict(calm=True, sym=False, cap=False, rot=False),
            "什麼都不排除": dict(calm=False, sym=False, cap=False, rot=False),
            "排除佔位價": dict(calm=False, sym=True, cap=False, rot=False),
            "排除佔位價＋差太多": dict(calm=False, sym=True, cap=True, rot=False)}
    if extra_ok is not None:
        cfgs["排除佔位價＋差太多＋正常輪值"] = dict(calm=False, sym=True, cap=True, rot=True)
    out = {}
    for name, c in cfgs.items():
        allv, blocks = [], []
        for blk, rows in preds_by_blk.items():
            v = []
            for r in rows:
                if not (r.get("pc") and r.get("po")):
                    continue
                if c["calm"] and abs(r["pc"] - r["po"]) >= 0.08:
                    continue
                if c["sym"] and abs(r["oo_h"] - r["oo_a"]) < 1e-9:
                    continue
                if c["rot"] and not extra_ok.get(r["game_id"], False):
                    continue
                for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])):
                    e = p * o - 1
                    if e >= edge and not (c["cap"] and e > 0.30):
                        v.append(pc * o - 1)
            allv += v
            blocks.append(round(float(np.mean(v)), 4) if v else None)
        out[name] = {**stats(allv), "blocks": blocks}
    return out


def main():
    res = {}
    games, feats = S.base_features()
    mp = {blk: S.predict(feats, {}, blk, "lr") for blk in S.BLOCKS}
    rot = rotation_ok(games)
    res["mlb_rotation_share"] = round(sum(rot.values()) / len(rot), 3)
    res["mlb_15"] = run(mp, rot, 0.15)
    res["mlb_10"] = run(mp, rot, 0.10)
    g2, f2 = N.base()
    npred = {blk: N.predict(f2, {}, blk) for blk in N.BLOCKS}
    res["nhl_15"] = run(npred, None, 0.15)
    res["nhl_10"] = run(npred, None, 0.10)
    json.dump(res, open(os.path.join(S.OUT, "audit_clean.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
