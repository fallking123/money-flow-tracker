"""
職業版・地基檢查：「平穩篩選」是不是偷看？
================================================================
練習區的下注規則一直排除「開盤到收盤移動 ≥ 8%」的比賽（CALM）。但下注當下不可能知道之後盤口會不會大移動，
等於用「未來」挑比賽。這裡把同一條規則在「不排除」的情況重算一次，看 CLV 還剩多少。
輸出 docs/data/pro/audit_calm.json
用法：python3 -m pro.audit_calm
"""
import json
import math
import os

import numpy as np

from pro import mlb_search as S
from pro import nhl_search as N


def summ(per):
    a = np.array([x for b in per.values() for x in b])
    blocks = [{"seasons": f"{k[0]}–{k[1]}", "n": len(v), "clv": round(float(np.mean(v)), 4) if v else None} for k, v in per.items()]
    return {"n": len(a), "clv": round(float(a.mean()), 4), "se": round(float(a.std() / math.sqrt(len(a))), 4),
            "z": round(float(a.mean() / (a.std() / math.sqrt(len(a)))), 2), "pos_blocks": sum(1 for b in blocks if (b["clv"] or 0) > 0), "blocks": blocks}


def bets(preds_by_blk, edge, calm, cond=lambda r: True):
    out = {}
    for blk, rows in preds_by_blk.items():
        b, big = [], []
        for r in rows:
            if not (r.get("pc") and r.get("po")) or not cond(r):
                continue
            moved = abs(r["pc"] - r["po"]) >= 0.08
            if calm and moved:
                continue
            for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])):
                if p * o - 1 >= edge:
                    b.append(pc * o - 1)
        out[blk] = b
    return out


def main():
    res = {}
    games, feats = S.base_features()
    mp = {blk: S.predict(feats, {}, blk, "lr") for blk in S.BLOCKS}
    for e in (0.10, 0.15):
        res[f"mlb_{int(e * 100)}"] = {"calm": summ(bets(mp, e, True)), "all": summ(bets(mp, e, False))}
    g2, f2 = N.base()
    npred = {blk: N.predict(f2, {}, blk) for blk in N.BLOCKS}
    for e in (0.10, 0.15):
        res[f"nhl_{int(e * 100)}"] = {"calm": summ(bets(npred, e, True)), "all": summ(bets(npred, e, False))}
    # 移動大的比賽，模型押的那邊盤口是往哪邊移？
    for sp, P in (("mlb", mp), ("nhl", npred)):
        tow = awy = 0
        for rows in P.values():
            for r in rows:
                if not (r.get("pc") and r.get("po")) or abs(r["pc"] - r["po"]) < 0.08:
                    continue
                for side, p, o in ((1, r["p"], r["oo_h"]), (-1, 1 - r["p"], r["oo_a"])):
                    if p * o - 1 >= 0.15:
                        if (r["pc"] - r["po"]) * side > 0:
                            tow += 1
                        else:
                            awy += 1
        res[f"{sp}_bigmove_15"] = {"toward_us": tow, "against_us": awy}
    json.dump(res, open(os.path.join(S.OUT, "audit_calm.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for k, v in res.items():
        print(k, {kk: (vv if not isinstance(vv, dict) else {x: vv[x] for x in ("n", "clv", "z", "pos_blocks")}) for kk, vv in v.items()})


if __name__ == "__main__":
    main()
