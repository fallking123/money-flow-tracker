"""
冷門玩法歷史發生機率（使用者 2026-10-27 要求：先統計機率，之後再拿台彩賠率來比）
================================================================
輸出 docs/data/niche_probs.json；用法：python3 niche_stats.py
- 足球五大聯賽（football-data 12 季，含半場比分）：半場勝負、半全場、波膽、總進球單雙、兩隊都進球、半場 0:0；依「全場主隊勝率」分組
- NBA（sbro＋espn 每節比分）：第一節／上半場勝負（含平手）、各節總分單雙、全場單雙；依全場讓分分組
- NHL（每節比分）：每節勝負平、每節進球數、60 分鐘打平（進延長）比例；依全場熱門程度分組
- MLB（每局比分）：第一局有沒有得分、全場單雙；依大小分盤口分組
- 英雄聯盟（Oracle's Elixir 2025）：首殺、首條小龍、首先鋒、首塔、首條大龍——藍方／紅方、Elo 強隊／弱隊
"""
import collections
import csv
import glob
import json
import math
import os

HERE = os.path.dirname(os.path.abspath(__file__))
D = os.path.join(HERE, "docs", "data")


def am(v):
    try:
        a = float(v)
    except (TypeError, ValueError):
        return None
    if abs(a) < 100:
        return None
    return 1 + (a / 100 if a > 0 else 100 / -a)


def fair2(oa, oh):
    if not oa or not oh:
        return None
    s = 1 / oa + 1 / oh
    return (1 / oh) / s if 1.0 <= s <= 1.12 else None


def pct(c, n):
    return round(c / n * 100, 1) if n else None


def table(rows, key, outcomes, groups):
    """rows: [(group, outcome)]，回傳 {group: {n, outcome: %}}"""
    out = {}
    for g in groups + ["全部"]:
        sel = [o for gg, o in rows if g == "全部" or gg == g]
        n = len(sel)
        if not n:
            continue
        c = collections.Counter(sel)
        out[g] = {"n": n, **{k: pct(c[k], n) for k in outcomes}}
    return out


def periods(s):
    try:
        return [int(float(x)) for x in str(s).split("|")] if s not in ("", None) else None
    except ValueError:
        return None


def us_rows(sport, ok):
    for f in sorted(glob.glob(os.path.join(D, sport, "history", "*.csv"))):
        b = os.path.basename(f)
        if not ok(b):
            continue
        for r in csv.DictReader(open(f, encoding="utf-8")):
            yield r


# ───────── 足球 ─────────
def soccer():
    LG = {"E0": "英超", "SP1": "西甲", "I1": "義甲", "D1": "德甲", "F1": "法甲"}
    rows = []
    for f in sorted(glob.glob(os.path.join(D, "soccer", "eu", "*.csv"))):
        div = os.path.basename(f).split("_")[0]
        if div not in LG:
            continue
        for r in csv.DictReader(open(f, encoding="utf-8-sig", errors="ignore")):
            try:
                hg, ag, hh, ha = (int(float(r[k])) for k in ("FTHG", "FTAG", "HTHG", "HTAG"))
            except (KeyError, ValueError, TypeError):
                continue
            od = None
            for cols in (("PSCH", "PSCD", "PSCA"), ("AvgCH", "AvgCD", "AvgCA"), ("PSH", "PSD", "PSA"), ("B365H", "B365D", "B365A")):
                try:
                    o = [float(r[c]) for c in cols]
                    if all(x > 1 for x in o):
                        od = o
                        break
                except (KeyError, ValueError, TypeError):
                    pass
            if not od:
                continue
            inv = sum(1 / x for x in od)
            ph = (1 / od[0]) / inv
            g = "主隊大熱門（≥60%）" if ph >= 0.6 else "主隊小熱門（45–60%）" if ph >= 0.45 else "差不多（30–45%）" if ph >= 0.30 else "客隊熱門（主 <30%）"
            rows.append({"lg": LG[div], "g": g, "hg": hg, "ag": ag, "hh": hh, "ha": ha})
    G = ["主隊大熱門（≥60%）", "主隊小熱門（45–60%）", "差不多（30–45%）", "客隊熱門（主 <30%）"]
    res = lambda a, b: "主" if a > b else "和" if a == b else "客"
    out = {"games": len(rows)}
    out["半場勝負"] = table([(x["g"], res(x["hh"], x["ha"])) for x in rows], None, ["主", "和", "客"], G)
    out["全場勝負"] = table([(x["g"], res(x["hg"], x["ag"])) for x in rows], None, ["主", "和", "客"], G)
    combos = [f"{a}/{b}" for a in "主和客" for b in "主和客"]
    out["半全場"] = table([(x["g"], res(x["hh"], x["ha"]) + "/" + res(x["hg"], x["ag"])) for x in rows], None, combos, G)
    out["總進球單雙"] = table([(x["g"], "單" if (x["hg"] + x["ag"]) % 2 else "雙") for x in rows], None, ["單", "雙"], G)
    out["半場總進球單雙"] = table([(x["g"], "單" if (x["hh"] + x["ha"]) % 2 else "雙") for x in rows], None, ["單", "雙"], G)
    out["兩隊都進球"] = table([(x["g"], "是" if x["hg"] and x["ag"] else "否") for x in rows], None, ["是", "否"], G)
    out["總進球數"] = table([(x["g"], str(min(x["hg"] + x["ag"], 6)) if x["hg"] + x["ag"] < 6 else "6+") for x in rows], None, ["0", "1", "2", "3", "4", "5", "6+"], G)
    out["半場總進球數"] = table([(x["g"], str(x["hh"] + x["ha"]) if x["hh"] + x["ha"] < 3 else "3+") for x in rows], None, ["0", "1", "2", "3+"], G)
    sc = collections.Counter(f"{min(x['hg'], 5)}:{min(x['ag'], 5)}" for x in rows)
    out["波膽（全部）"] = {k: pct(v, len(rows)) for k, v in sc.most_common(16)}
    for g in G:
        sel = [x for x in rows if x["g"] == g]
        c = collections.Counter(f"{min(x['hg'], 5)}:{min(x['ag'], 5)}" for x in sel)
        out[f"波膽（{g}）"] = {"n": len(sel), **{k: pct(v, len(sel)) for k, v in c.most_common(12)}}
    out["各聯賽"] = {lg: {"n": len(s), "半場和局": pct(sum(1 for x in s if x["hh"] == x["ha"]), len(s)),
                         "全場和局": pct(sum(1 for x in s if x["hg"] == x["ag"]), len(s)),
                         "總進球單": pct(sum(1 for x in s if (x["hg"] + x["ag"]) % 2), len(s)),
                         "兩隊都進球": pct(sum(1 for x in s if x["hg"] and x["ag"]), len(s)),
                         "半場0:0": pct(sum(1 for x in s if x["hh"] == 0 and x["ha"] == 0), len(s))}
                    for lg in LG.values() for s in [[x for x in rows if x["lg"] == lg]]}
    return out


# ───────── NBA ─────────
def nba():
    ok = lambda b: (b.startswith("sbro_") and int(b[5:9]) <= 2021) or b.startswith("espn_")
    rows = []
    for r in us_rows("nba", ok):
        pa, ph = periods(r.get("periods_away")), periods(r.get("periods_home"))
        if not pa or not ph or len(pa) < 4 or len(ph) < 4:
            continue
        try:
            sp = float(r["spread_close_home"])
        except (ValueError, TypeError):
            sp = None
        if sp is None:
            continue
        g = "主隊讓 ≥7.5" if sp <= -7.5 else "主隊讓 2.5–7" if sp <= -2.5 else "差不多（±2）" if sp < 2.5 else "客隊讓 2.5–7" if sp < 7.5 else "客隊讓 ≥7.5"
        rows.append({"g": g, "pa": pa, "ph": ph, "fav_home": sp < 0})
    G = ["主隊讓 ≥7.5", "主隊讓 2.5–7", "差不多（±2）", "客隊讓 2.5–7", "客隊讓 ≥7.5"]
    res = lambda a, h: "主" if h > a else "平" if h == a else "客"
    out = {"games": len(rows)}
    out["第一節勝負"] = table([(x["g"], res(x["pa"][0], x["ph"][0])) for x in rows], None, ["主", "平", "客"], G)
    out["上半場勝負"] = table([(x["g"], res(sum(x["pa"][:2]), sum(x["ph"][:2]))) for x in rows], None, ["主", "平", "客"], G)
    out["第四節勝負"] = table([(x["g"], res(x["pa"][3], x["ph"][3])) for x in rows], None, ["主", "平", "客"], G)
    out["全場總分單雙"] = table([(x["g"], "單" if (sum(x["pa"]) + sum(x["ph"])) % 2 else "雙") for x in rows], None, ["單", "雙"], G)
    out["第一節總分單雙"] = table([(x["g"], "單" if (x["pa"][0] + x["ph"][0]) % 2 else "雙") for x in rows], None, ["單", "雙"], G)
    fq = [x for x in rows if x["g"] != "差不多（±2）"]
    both = collections.Counter()
    for x in fq:
        fav = "ph" if x["fav_home"] else "pa"
        dog = "pa" if x["fav_home"] else "ph"
        q1 = "熱門贏" if x[fav][0] > x[dog][0] else "平" if x[fav][0] == x[dog][0] else "冷門贏"
        full = "熱門贏" if sum(x[fav]) > sum(x[dog]) else "冷門贏"
        both[(q1, full)] += 1
    n = len(fq)
    out["第一節 vs 全場（全場有熱門的比賽）"] = {"n": n, **{f"第一節{a}・全場{b}": pct(c, n) for (a, b), c in both.most_common()}}
    return out


# ───────── NHL ─────────
def nhl():
    ok = lambda b: (b.startswith("sbro_") and b[5:9].isdigit() and int(b[5:9]) >= 2014 and "-" in b) or b.startswith("espn_2024") or b.startswith("espn_2025")
    rows = []
    for r in us_rows("nhl", ok):
        pa, ph = periods(r.get("periods_away")), periods(r.get("periods_home"))
        if not pa or not ph or len(pa) < 3 or len(ph) < 3:
            continue
        p = fair2(am(r.get("ml_close_away")), am(r.get("ml_close_home")))
        if p is None:
            continue
        g = "主隊大熱門（≥65%）" if p >= 0.65 else "主隊熱門（55–65%）" if p >= 0.55 else "差不多（45–55%）" if p >= 0.45 else "客隊熱門"
        rows.append({"g": g, "pa": pa[:3], "ph": ph[:3]})
    G = ["主隊大熱門（≥65%）", "主隊熱門（55–65%）", "差不多（45–55%）", "客隊熱門"]
    res = lambda a, h: "主" if h > a else "平" if h == a else "客"
    out = {"games": len(rows)}
    out["60 分鐘勝負平"] = table([(x["g"], res(sum(x["pa"]), sum(x["ph"]))) for x in rows], None, ["主", "平", "客"], G)
    for i, nm in enumerate(["第一節", "第二節", "第三節"]):
        out[f"{nm}勝負平"] = table([(x["g"], res(x["pa"][i], x["ph"][i])) for x in rows], None, ["主", "平", "客"], G)
        out[f"{nm}進球數"] = table([(x["g"], str(min(x["pa"][i] + x["ph"][i], 3)) if x["pa"][i] + x["ph"][i] < 3 else "3+") for x in rows], None, ["0", "1", "2", "3+"], G)
    out["60 分鐘總進球單雙"] = table([(x["g"], "單" if (sum(x["pa"]) + sum(x["ph"])) % 2 else "雙") for x in rows], None, ["單", "雙"], G)
    return out


# ───────── MLB ─────────
def mlb():
    ok = lambda b: (b.startswith("sbro_") and int(b[5:9]) <= 2020) or b.startswith("espn_")
    rows = []
    for r in us_rows("mlb", ok):
        pa, ph = periods(r.get("periods_away")), periods(r.get("periods_home"))
        if not pa or not ph:
            continue
        try:
            tot = float(r["total_close"])
        except (ValueError, TypeError):
            tot = None
        g = "大小 ≤7.5" if tot is not None and tot <= 7.5 else "大小 8–8.5" if tot is not None and tot <= 8.5 else "大小 ≥9" if tot is not None else "沒有盤口"
        try:
            ta = float(r["away_score"]) + float(r["home_score"])
        except (ValueError, TypeError):
            continue
        rows.append({"g": g, "f1": pa[0] + ph[0] > 0, "f1a": pa[0] > 0, "f1h": ph[0] > 0, "odd": int(ta) % 2 == 1})
    G = ["大小 ≤7.5", "大小 8–8.5", "大小 ≥9"]
    out = {"games": len(rows)}
    out["第一局有得分"] = table([(x["g"], "有" if x["f1"] else "沒有") for x in rows], None, ["有", "沒有"], G)
    out["第一局客隊得分"] = table([(x["g"], "有" if x["f1a"] else "沒有") for x in rows], None, ["有", "沒有"], G)
    out["第一局主隊得分"] = table([(x["g"], "有" if x["f1h"] else "沒有") for x in rows], None, ["有", "沒有"], G)
    out["全場總分單雙"] = table([(x["g"], "單" if x["odd"] else "雙") for x in rows], None, ["單", "雙"], G)
    return out


# ───────── 英雄聯盟 ─────────
def lol():
    import pandas as pd
    d = pd.read_csv(os.path.join(D, "esports", "lol_teams_2025.csv.gz")).sort_values(["date", "gameid"])
    elo = collections.defaultdict(lambda: 1500.0)
    K = 24
    obj = ["firstblood", "firstdragon", "firstherald", "firsttower", "firstbaron"]
    NM = {"firstblood": "首殺", "firstdragon": "首條小龍", "firstherald": "首先鋒", "firsttower": "首塔", "firstbaron": "首條大龍"}
    side = collections.defaultdict(lambda: [0, 0])
    fav = collections.defaultdict(lambda: collections.defaultdict(lambda: [0, 0]))
    win = collections.defaultdict(lambda: [0, 0])
    for gid, g in d.groupby("gameid", sort=False):
        if len(g) != 2:
            continue
        a, b = g.iloc[0], g.iloc[1]
        ea, eb = elo[a["teamname"]], elo[b["teamname"]]
        pa = 1 / (1 + 10 ** ((eb - ea) / 400))
        strong, weak, ps = (a, b, pa) if pa >= 0.5 else (b, a, 1 - pa)
        band = "勢均力敵（50–60%）" if ps < 0.6 else "強隊明顯（60–75%）" if ps < 0.75 else "強隊大熱門（≥75%）"
        for o in obj:
            vs, vw = strong.get(o), weak.get(o)
            if pd.isna(vs) or pd.isna(vw) or vs + vw != 1:
                continue
            fav[band][o][0] += int(vs)
            fav[band][o][1] += 1
            blue = a if a["side"] == "Blue" else b
            side[o][0] += int(blue[o])
            side[o][1] += 1
        win[band][0] += int(strong["result"])
        win[band][1] += 1
        ra = float(a["result"])
        ea2 = ea + K * (ra - pa)
        eb2 = eb + K * ((1 - ra) - (1 - pa))
        elo[a["teamname"]], elo[b["teamname"]] = ea2, eb2
    out = {"games": int(sum(v[1] for v in win.values()))}
    out["藍方拿到"] = {NM[o]: {"n": side[o][1], "藍方": pct(*side[o])} for o in obj if side[o][1]}
    for band in ["勢均力敵（50–60%）", "強隊明顯（60–75%）", "強隊大熱門（≥75%）"]:
        if not win[band][1]:
            continue
        out[f"強隊拿到（{band}）"] = {"n": win[band][1], "強隊贏整場": pct(*win[band]), **{NM[o]: pct(*fav[band][o]) for o in obj if fav[band][o][1]}}
    return out


if __name__ == "__main__":
    res = {"note": "歷史發生機率（%）。n＝場數。用來跟台彩賠率比：台彩賠率 × 機率 > 1 才划算。",
           "soccer": soccer(), "nba": nba(), "nhl": nhl(), "mlb": mlb(), "lol": lol()}
    p = os.path.join(D, "niche_probs.json")
    json.dump(res, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(res, ensure_ascii=False, indent=1))
