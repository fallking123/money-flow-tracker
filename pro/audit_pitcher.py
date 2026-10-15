"""
職業版・地基檢查：MLB 先發投手是不是偷看？
================================================================
模型（開盤版）打線用上一場的，但「先發投手」用的是 Retrosheet 實際先發。開盤時通常已經公布預定先發，
但偶爾臨時換人（受傷、雨延）——那種比賽模型知道真正先發、開盤不知道，等於偷看，
而且剛好會讓「模型跟開盤差很多」的規則挑到它們。
SBRO 盤口有「掛牌先發」（例如 CSABATHIA-L），跟 Retrosheet 實際先發比對（姓前 4 碼＋名字第 1 碼）。
另外，美國盤口照「掛牌先發」結算：掛牌先發沒上場，那注通常退錢（no action），所以這些比賽本來就不該算。
輸出 docs/data/pro/audit_pitcher.json
"""
import csv
import glob
import json
import math
import os
import re
from collections import defaultdict

import numpy as np

from pro import mlb_search as S
from pro import mlb_model as V1


def key(name):
    """SBRO 'CSABATHIA-L' → ('sabat'[:4], 'c')"""
    n = re.sub(r"-[LR]$", "", (name or "").strip().upper())
    n = re.sub(r"[^A-Z]", "", n)
    if len(n) < 3:
        return None
    return n[1:5].lower(), n[0].lower()


def rkey(rid):
    """Retrosheet 'sabac001' → ('saba', 'c')"""
    if not rid or len(rid) < 5:
        return None
    return rid[:4].replace("-", ""), rid[4]


def main():
    games, feats = S.base_features()
    by = {g["game_id"]: g for g in games}
    hist = defaultdict(list)
    for f in sorted(glob.glob(os.path.join(V1.HIST, "sbro_*.csv"))):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            try:
                hist[(r["date"], int(float(r["home_score"])), int(float(r["away_score"])))].append(r)
            except (ValueError, TypeError, KeyError):
                pass
    flag = {}
    for f in feats:
        g = by[f["game_id"]]
        c = hist.get((g["date"], g["hs"], g["as"]), [])
        if len(c) != 1:
            continue
        r = c[0]
        ok = True
        for col, sp in (("home_pitcher", g.get("home_sp")), ("away_pitcher", g.get("vis_sp"))):
            a, b = key(r.get(col)), rkey(sp)
            if not a or not b:
                ok = None
                break
            # 姓的前 4 碼（Retrosheet 姓不足 4 碼會補 -）＋名字第一個字母
            if not (a[0][:len(b[0])] == b[0] and a[1] == b[1]):
                ok = False
        flag[f["game_id"]] = ok
    res = {"checked": sum(1 for v in flag.values() if v is not None), "mismatch": sum(1 for v in flag.values() if v is False)}
    for e in (0.10, 0.15):
        grp = {"match": [], "mismatch": [], "unknown": []}
        for blk in S.BLOCKS:
            for r in S.predict(feats, {}, blk, "lr"):
                if not (r["pc"] and r["po"]):
                    continue
                k = {True: "match", False: "mismatch", None: "unknown"}[flag.get(r["game_id"])]
                for p, pc, o in ((r["p"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["pc"], r["oo_a"])):
                    if p * o - 1 >= e:
                        grp[k].append(pc * o - 1)
        res[f"edge_{int(e * 100)}"] = {k: {"n": len(v), "clv": round(float(np.mean(v)), 4) if v else None,
                                            "se": round(float(np.std(v) / math.sqrt(len(v))), 4) if len(v) > 1 else None} for k, v in grp.items()}
    json.dump(res, open(os.path.join(S.OUT, "audit_pitcher.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
