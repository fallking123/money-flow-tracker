"""
職業版・資料檢查：每一份要拿來訓練或當標準答案的資料，齊不齊全
================================================================
- 足球歷史（football-data 原檔，docs/data/soccer/eu/）：每季每個聯賽的場數、賽果、Pinnacle 收盤、Betfair 交易所收盤、射門數
- 美國四大歷史（docs/data/<運動>/history/）：每季場數、比分、開盤／收盤賠率
- 我們自己記的盤口（9/27 起）：場數、對到 Pinnacle 的、有賽果的
只讀，不改檔案。用法：python3 -m pro.datacheck
"""
import csv
import glob
import json
import os
from collections import defaultdict

from pro import lines as L

DIVS = {"E0": "英超", "SP1": "西甲", "I1": "義甲", "D1": "德甲", "F1": "法甲",
        "E1": "英冠", "SP2": "西乙", "I2": "義乙", "D2": "德乙", "F2": "法乙"}
# 正常一季幾場（法甲／法乙 2023/24 起 18 隊；法國 2019/20 疫情提前結束；義乙 2018/19 有球隊被除名）
EXPECT = {"E0": 380, "SP1": 380, "I1": 380, "D1": 306, "F1": 380, "E1": 552, "SP2": 462, "I2": 380, "D2": 306, "F2": 380}
KNOWN = {("F1", "1920"): "疫情提前結束", ("F2", "1920"): "疫情提前結束", ("I2", "1819"): "有球隊被除名",
         ("F1", "2324"): "改成 18 隊", ("F1", "2425"): "改成 18 隊", ("F1", "2526"): "改成 18 隊", ("F1", "2627"): "改成 18 隊",
         ("F2", "2425"): "改成 18 隊", ("F2", "2526"): "改成 18 隊", ("F2", "2627"): "改成 18 隊"}


def soccer():
    per = defaultdict(lambda: {"n": 0, "res": 0, "psc": 0, "bfc": 0, "avgc": 0, "bench": 0, "shots": 0, "divs": set()})
    odd = []
    for f in sorted(glob.glob(os.path.join(L.DATA, "soccer", "eu", "*.csv"))):
        div, ss = os.path.basename(f)[:-4].split("_")
        n = res = 0
        with open(f, encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                if not r.get("HomeTeam"):
                    continue
                s = per[ss]
                s["divs"].add(div)
                s["n"] += 1
                n += 1
                ok = r.get("FTR") in ("H", "D", "A")
                s["res"] += ok
                res += ok
                s["psc"] += bool(r.get("PSCH"))
                s["bfc"] += bool(r.get("BFECH"))
                s["avgc"] += bool(r.get("AvgCH"))
                s["bench"] += bool(r.get("PSCH")) or bool(r.get("BFECH"))
                s["shots"] += bool(r.get("HS")) and bool(r.get("HST"))
        if res < n or (n < EXPECT[div] * 0.97 and (div, ss) not in KNOWN and ss != max(os.path.basename(x)[:-4].split("_")[1] for x in glob.glob(os.path.join(L.DATA, "soccer", "eu", div + "_*.csv")))):
            odd.append({"div": DIVS[div], "season": f"20{ss[:2]}/{ss[2:]}", "n": n, "res": res, "expect": EXPECT[div]})
    seasons = [{"season": f"20{k[:2]}/{k[2:]}", "leagues": len(v["divs"]), "n": v["n"], "res": v["res"],
                "psc": v["psc"], "bfc": v["bfc"], "avgc": v["avgc"], "bench": v["bench"], "shots": v["shots"]} for k, v in sorted(per.items())]
    return {"seasons": seasons, "odd": odd, "known": [{"div": DIVS[d], "season": s, "why": w} for (d, s), w in KNOWN.items()]}


def us():
    out = {}
    for sp in ("nfl", "mlb", "nhl", "nba"):
        per = defaultdict(lambda: {"n": 0, "score": 0, "close": 0, "open": 0})
        for f in glob.glob(os.path.join(L.DATA, sp, "history", "*.csv")):
            with open(f) as fh:
                for r in csv.DictReader(fh):
                    if "home_score" not in r:
                        break
                    s = per[r.get("season", "?")]
                    s["n"] += 1
                    s["score"] += L.num(r.get("home_score")) is not None
                    s["close"] += L.num(r.get("ml_close_home")) is not None
                    s["open"] += L.num(r.get("ml_open_home")) is not None
        if per:
            ks = sorted(per)
            tot = {k: sum(v[k] for v in per.values()) for k in ("n", "score", "close", "open")}
            out[sp] = {"from": ks[0], "to": ks[-1], "seasons": len(ks), **tot}
    return out


def main():
    return {"soccer": soccer(), "us": us()}


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1)[:3000])
