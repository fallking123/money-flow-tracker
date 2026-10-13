"""
職業版・MLB 特徵搜尋：不是新特徵，而是「什麼時候」基本模型（第 2 版開盤版）比開盤更有用
每一個切法算一次嘗試（記在 search_log.json，一起提高門檻）。成績：模型看好 ≥5% 時用開盤價下注的 CLV，
這一組 vs 其他，差多少（4 段分開看）。
用法：python3 -m pro.mlb_segments early dog
"""
import json
import math
import sys
from datetime import datetime, timezone

import numpy as np

from pro import mlb_search as S

SEG = {
    "early": ("球季前兩個月（4、5 月）", "開季時莊家還靠去年的數據和季前預測，我們的模型會用最新的每個打席", lambda r, f: f["date"][5:7] in ("03", "04", "05")),
    "dog": ("模型看好冷門（開盤勝率 < 45% 的那邊）", "一般人愛押熱門，冷門的價錢可能比較好", None),
}


def bets(preds, feats_by):
    out = []
    for r in preds:
        if not (r["pc"] and r["po"]) or abs(r["pc"] - r["po"]) >= S.CALM:
            continue
        for p, po, pc, o in ((r["p"], r["po"], r["pc"], r["oo_h"]), (1 - r["p"], 1 - r["po"], 1 - r["pc"], r["oo_a"])):
            if p * o - 1 >= 0.05:
                out.append({"clv": pc * o - 1, "po": po, "f": feats_by[r["game_id"]]})
    return out


def main(names):
    games, feats = S.base_features()
    fb = {f["game_id"]: f for f in feats}
    per = {blk: bets(S.predict(feats, {}, blk), fb) for blk in S.BLOCKS}
    log = S.load_log()
    for nm in names:
        label, why, fn = SEG[nm]
        test = fn or (lambda b, f: b["po"] < 0.45)
        res = {"blocks": [], "better_blocks": 0}
        allin, allout = [], []
        for blk in S.BLOCKS:
            ins = [b["clv"] for b in per[blk] if (test(b, b["f"]) if fn is None else fn(b, b["f"]))]
            outs = [b["clv"] for b in per[blk] if not (test(b, b["f"]) if fn is None else fn(b, b["f"]))]
            allin += ins
            allout += outs
            d = np.mean(ins) - np.mean(outs) if ins and outs else 0.0
            res["blocks"].append({"seasons": f"{blk[0]}–{blk[1]}", "n_in": len(ins), "clv_in": round(float(np.mean(ins)), 4) if ins else None,
                                  "n_out": len(outs), "clv_out": round(float(np.mean(outs)), 4) if outs else None})
            res["better_blocks"] += int(d > 0)
        a, b = np.array(allin), np.array(allout)
        se = math.sqrt(a.var() / len(a) + b.var() / len(b))
        res["z"] = round(float((a.mean() - b.mean()) / se), 2)
        res["clv_in_all"] = [round(float(a.mean()), 4), round(float(a.std() / math.sqrt(len(a))), 4), len(a)]
        res["z_ll"] = None
        n = len(log["tries"]) + 1
        thr = S.threshold(n)
        ok = res["z"] >= thr and res["better_blocks"] >= 3
        log["tries"].append({"n": n, "name": "seg_" + nm, "kind": "segment", "label": label, "why": why,
                             "time_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "z_needed": thr, "pass": ok, **res})
        json.dump(log, open(S.LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print(f"#{n} {nm}：z={res['z']}（門檻 {thr}），{res['better_blocks']}/4 段，這一組 CLV {res['clv_in_all']} → {'通過' if ok else '沒通過'}")
        for x in res["blocks"]:
            print("   ", x)


if __name__ == "__main__":
    main(sys.argv[1:])
