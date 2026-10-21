"""
看板用：全球足球模型（world_model.py 訓練好的參數）算五大聯賽以外比賽的主／和／客機率
"""
import json
import math
import os
import re
import unicodedata

from soccer_comps import COMPS
from sports_common import sport_dir

_P = None


def params():
    global _P
    if _P is None:
        p = os.path.join(sport_dir("soccer"), "model", "world_params.json")
        _P = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
    return _P


# 隊名比對（Pinnacle／Action Network 的隊名 → ESPN 的隊名）
TR = str.maketrans({"ø": "o", "Ø": "o", "æ": "ae", "Æ": "ae", "å": "a", "ß": "ss", "ł": "l", "Ł": "l", "ı": "i", "đ": "d", "Đ": "d", "ð": "d", "þ": "th"})
STOPW = {"fc", "cf", "ac", "sc", "afc", "if", "bk", "fk", "sk", "club", "de", "da", "do", "del", "al", "the", "sport", "sports", "sfk", "ssv",
         "sv", "vfl", "vfb", "tsg", "ii", "bb", "kv", "krc", "ksv", "as", "us", "ss", "cd", "ca", "sad", "ud", "rc", "fk", "nk", "hnk",
         "gnk", "sk", "aik", "osc", "ogc", "1", "05", "04", "07", "98", "1909", "1913", "1846", "boldklub", "calcio", "spor", "royal", "fodbold", "is", "scr"}
ALIAS = {"inter": "internazionale", "linzer athletik sport klub": "lask linz", "lask": "lask linz", "los angeles fc": "lafc",
         "psg": "paris saint germain", "man utd": "manchester united", "man city": "manchester city", "wolves": "wolverhampton wanderers",
         "spurs": "tottenham hotspur", "athletic bilbao": "athletic club", "sporting lisbon": "sporting cp", "red bull salzburg": "salzburg",
         "grasshopper club zurich": "grasshoppers", "grasshopper": "grasshoppers", "oud heverlee leuven": "oh leuven",
         "union st gilloise": "union saint gilloise", "union stgilloise": "union saint gilloise", "atletico mineiro": "atletico mg",
         "crvena zvezda": "red star belgrade", "ham kam": "hamkam", "al qadisiyah": "al qadsiah", "hearts": "heart midlothian",
         "shenzhen peng city": "shenzhen xinpengcheng", "universitatea craiova": "csu craiova", "athletico paranaense": "athletico pr",
         "austria vienna": "austria wien", "rapid vienna": "rapid wien"}
TOKA = {"dynamo": "dinamo", "copenhagen": "kobenhavn", "rennes": "rennais", "koln": "cologne", "olympiakos": "olympiacos",
        "munchen": "munich", "lillestroem": "lillestrom", "togliatti": "tolyatti", "bulls": "bull"}
EU_OUT = ("arg.", "bra.", "mex.", "usa.", "jpn.", "chn.", "ksa.", "aus.", "kor.")


def _norm(s):
    s = (s or "").translate(TR)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[.'`’]", "", s)
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = ALIAS.get(s, s)
    return " ".join(TOKA.get(t, t) for t in s.split())


def _toks(s):
    t = _norm(s).split()
    core = [x for x in t if x not in STOPW]
    return core or t


def _tok_eq(a, b):
    if a == b:
        return True
    for x in (a, b):
        pass
    sa = a[:-4] if a.endswith("spor") and len(a) > 6 else a      # 土耳其隊名：Amedspor ＝ Amed
    sb = b[:-4] if b.endswith("spor") and len(b) > 6 else b
    if sa == sb and len(sa) >= 4:
        return True
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return len(a) >= 4 and len(b) >= 4 and n >= 5 and min(len(a), len(b)) / max(len(a), len(b)) >= 0.75


def _sim(a, b):
    """相似度：其中一邊的關鍵字全部對到＝1；兩邊都各有對不到的字（例如 Atletico Mineiro vs Atletico Madrid）打五折"""
    if _norm(a) == _norm(b):
        return 2.0, 9, 0
    ta, tb = _toks(a), _toks(b)
    if not ta or not tb:
        return 0.0, 0, 0
    ua = [x for x in ta if not any(_tok_eq(x, y) for y in tb)]
    ub = [y for y in tb if not any(_tok_eq(x, y) for x in ta)]
    ma, mb = len(ta) - len(ua), len(tb) - len(ub)
    if not ma:
        return 0.0, 0, 0
    sc = max(ma / len(ta), mb / len(tb))
    return (sc * 0.5 if ua and ub else sc), ma, -(len(ua) + len(ub))


def match(name, cand, rating=None):
    """回傳最像的候選隊名；太不像（相似度 < 0.5）回傳 None。同分時選分數高（比較有名）的隊"""
    best, bs = None, (0.0, 0, 0, -1e9)
    for c in cand:
        sc = _sim(name, c)
        if sc[0] <= 0:
            continue
        key = (*sc, (rating or {}).get(c, 0))          # 相似度 → 對到幾個字 → 多餘的字越少越好 → 比較有名的隊
        if key > bs:
            best, bs = c, key
    return best if bs[0] >= 0.5 else None


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
    if league in ("libertadores", "sudamericana"):        # 南美盃賽：只找南美洲的球隊（巴西、阿根廷，其他國家的隊沒有聯賽資料）
        return {v["n"]: k for k, v in clubs.items() if v["lg"].startswith(("bra.", "arg.")) or v["lg"] == ""}
    if c.get("group") == "cup":
        pre = c["espn"][0].split(".")[0] + "."            # 國內盃賽：只找同一個國家的球隊
        return {v["n"]: k for k, v in clubs.items() if v["lg"].startswith(pre)}
    if c.get("group") == "euro":                         # 歐洲賽事：不找美洲、亞洲的球隊
        return {v["n"]: k for k, v in clubs.items() if not v["lg"].startswith(EU_OUT)}
    return {v["n"]: k for k, v in clubs.items()}


def predict(league, home, away, odds, neutral=False):
    """odds＝[主, 和, 客] 賠率（Pinnacle 或 Action Network）；回傳跟 soccer_dashboard.predict 一樣的格式"""
    P = params()
    if not P or not odds or any(o is None or o <= 1 for o in odds) or league not in COMPS:
        return None
    cand = _cands(league)
    nat = COMPS[league]["kind"] == "national"
    rat = {n: (P["nations"][n] if nat else P["clubs"][k]["r"]) for n, k in cand.items()}
    th, ta = match(home, cand, rat), match(away, cand, rat)
    if not th or not ta or th == ta:
        return None
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
    # 保險：模型跟市場差超過 15 個百分點，多半是隊名對錯（模型本來就很接近市場），寧可不給
    if max(abs(prob["H"] - ph), abs(prob["D"] - pd_), abs(prob["A"] - pa)) > 0.15:
        return None
    return {"p": [round(prob["H"], 4), round(prob["D"], 4), round(prob["A"], 4)], "v": "world",
            "elo": [round(rh), round(ra)], "mkt": [round(ph, 4), round(pd_, 4), round(pa, 4)], "teams": [th, ta]}
