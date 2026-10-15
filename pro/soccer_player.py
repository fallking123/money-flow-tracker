"""
職業版・足球第 2 版：用球員名單組出每場的陣容強度（ESPN 先發＋換人）
================================================================
1. 隊名對照：ESPN 的隊名 ↔ football-data 的隊名，靠「同聯賽、日期差 ≤1 天、比分一樣」投票自動對（不用人工）。
2. 球員評分（線上學習，嚴格照時間）：每位球員一個數字 w＝這個人在場時球隊淨勝球多多少。
   一場的「陣容淨勝球」＝ 主隊 Σ w×上場比例 − 客隊 Σ w×上場比例；賽後用誤差微調每個上場球員（有上場分鐘的比例分），
   並往 0 收縮（新球員 = 0）。球員轉隊，評分跟著人走。
3. 兩種版本：
   - actual：用這場「實際」先發＋換人（收盤盤口已經知道，拿來跟開盤比是偷看，只當對照）
   - prev：開盤版，只用該隊上一場的先發＋換人當預計陣容（開盤時還不知道今天誰上）
   另外 dev：陣容跟這隊「平常」陣容的差（缺人的程度）。
輸出：候選特徵給 soccer_search（extra: id(row) → 特徵列表）
"""
import csv
import glob
import gzip
import os
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from pro import soccer_model as SM

SOC = os.path.join(SM.OUT, "soccer")
DIVS = {"eng.1": "E0", "eng.2": "E1", "esp.1": "SP1", "esp.2": "SP2", "ita.1": "I1", "ita.2": "I2",
        "ger.1": "D1", "ger.2": "D2", "fra.1": "F1", "fra.2": "F2"}
LR, SHRINK = 0.02, 0.0005


def load_espn():
    """event → {date, div, home, away, hg, ag, players: {side: [(pid, 上場比例)]}, starters}"""
    ev = {}
    for f in sorted(glob.glob(os.path.join(SOC, "espn_*.csv.gz"))):
        lg = os.path.basename(f)[5:-7]
        with gzip.open(f, "rt", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                e = ev.setdefault(r["event"], {"date": datetime.strptime(r["date"], "%Y-%m-%d"), "div": DIVS[lg], "home": r["home"], "away": r["away"],
                                               "hg": r["hg"], "ag": r["ag"], "pl": {"home": [], "away": []}, "st": {"home": [], "away": []}})
                if r["side"] not in ("home", "away") or not r["player"]:
                    continue
                if r["starter"] == "1":
                    out = float(r["min_out"]) if r["sub_out"] == "1" and r["min_out"] else 90.0
                    frac = min(max(out, 1.0), 95.0) / 90.0
                    e["st"][r["side"]].append(r["player"])
                elif r["sub_in"] == "1":
                    mi = float(r["min_in"]) if r["min_in"] else 60.0
                    frac = max(90.0 - mi, 1.0) / 90.0
                else:
                    continue
                e["pl"][r["side"]].append((r["player"], frac))
    return ev


def team_map(ev, rows):
    """每個聯賽：ESPN 隊名 → football-data 隊名（投票）"""
    idx = defaultdict(list)
    for r in rows:
        idx[(r["div"], r["dt"].date())].append(r)
    votes = defaultdict(Counter)
    for e in ev.values():
        try:
            hg, ag = int(e["hg"]), int(e["ag"])
        except ValueError:
            continue
        c = [r for dd in (-1, 0, 1) for r in idx.get((e["div"], e["date"].date() + timedelta(days=dd)), []) if r["hg"] == hg and r["ag"] == ag]
        if len(c) == 1:
            votes[(e["div"], e["home"])][c[0]["home"]] += 1
            votes[(e["div"], e["away"])][c[0]["away"]] += 1
    return {k: v.most_common(1)[0][0] for k, v in votes.items() if v.most_common(1)[0][1] >= 2}, votes


def link(ev, rows):
    """football-data 的 row → ESPN event（用對照後的隊名＋日期差 ≤1）"""
    tm, _ = team_map(ev, rows)
    idx = defaultdict(list)
    for r in rows:
        idx[(r["div"], r["home"], r["away"])].append(r)
    out, miss = {}, 0
    for eid, e in ev.items():
        h, a = tm.get((e["div"], e["home"])), tm.get((e["div"], e["away"]))
        if not h or not a:
            miss += 1
            continue
        c = [r for r in idx.get((e["div"], h, a), []) if abs((r["dt"].date() - e["date"].date()).days) <= 1]
        if len(c) == 1:
            out[id(c[0])] = eid
        else:
            miss += 1
    return out, miss, tm


def build(rows, ev, links):
    """逐場照時間跑：回傳 {id(row): {'actual':…, 'prev':…, 'dev':…}}"""
    w = defaultdict(float)
    last = {}                                   # 隊 → 上一場 [(pid, frac)]
    usual = defaultdict(lambda: defaultdict(float))   # 隊 → pid → 衰減出場量
    res = {}
    for r in rows:
        eid = links.get(id(r))
        if not eid:
            continue
        e = ev[eid]
        H, A = e["pl"]["home"], e["pl"]["away"]
        if len(e["st"]["home"]) < 9 or len(e["st"]["away"]) < 9:
            continue
        f = {}
        for side, team, P in (("home", r["home"], H), ("away", r["away"], A)):
            act = sum(w[p] * m for p, m in P)
            pv = last.get(team)
            prev = sum(w[p] * m for p, m in pv) if pv else None
            us = usual[team]
            tot = sum(us.values()) or 1.0
            exp_usual = sum(w[p] * v / tot * 11 for p, v in us.items() if v / tot * 11 > 0.3) if us else None
            f[side] = (act, prev, exp_usual, sum(m for p, m in P if p in us and us[p] / tot * 11 > 0.3) if us else 0.0)
        a, p, u = f["home"][0] - f["away"][0], None, None
        if f["home"][1] is not None and f["away"][1] is not None:
            p = f["home"][1] - f["away"][1]
        if f["home"][2] is not None and f["away"][2] is not None:
            u = (f["home"][0] - f["home"][2]) - (f["away"][0] - f["away"][2])
        res[id(r)] = {"actual": a, "prev": p, "dev": u}
        # 賽後更新
        gd = r["hg"] - r["ag"]
        err = gd - (0.25 + a * 1.0)
        for P, s in ((H, 1), (A, -1)):
            for pid, m in P:
                w[pid] += LR * err * s * m - SHRINK * w[pid]
        for side, team, P in (("home", r["home"], H), ("away", r["away"], A)):
            last[team] = P
            us = usual[team]
            for k in list(us):
                us[k] *= 0.95
            for pid, m in P:
                us[pid] += m
    return res


def feature_sets(rows):
    ev = load_espn()
    links, miss, tm = link(ev, rows)
    print(f"ESPN {len(ev)} 場，對到 football-data {len(links)} 場（沒對到 {miss}），隊名對照 {len(tm)} 個", flush=True)
    res = build(rows, ev, links)
    out = {}
    for name in ("actual", "prev", "dev"):
        out[name] = {k: [v[name] if v[name] is not None else 0.0, float(v[name] is None)] for k, v in res.items()}
    return out, {"espn_events": len(ev), "linked": len(links), "team_names": len(tm)}
