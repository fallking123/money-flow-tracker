"""
職業版・MLB 特徵搜尋的候選特徵（每一組都要先寫「為什麼莊家可能沒算好」）
每個函式回傳 {game_id: [數字…]}（主隊 − 客隊，或整場的數字）。只能用比賽開始前就知道的資訊。
"""
import csv
import gzip
import os
from collections import Counter, defaultdict
from datetime import datetime

import numpy as np

D = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data", "pro", "mlb")
_cache = {}


def info():
    if "info" not in _cache:
        _cache["info"] = {r["game_id"]: r for r in csv.DictReader(open(os.path.join(D, "game_info.csv"), encoding="utf-8"))}
    return _cache["info"]


def framing_rows():
    if "fr" not in _cache:
        fr = defaultdict(list)
        with gzip.open(os.path.join(D, "framing.csv.gz"), "rt", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                fr[r["game_id"]].append((r["team"], r["pitcher"], r["catcher"], float(r["cs"]), float(r["b"])))
        _cache["fr"] = fr
    return _cache["fr"]


def days(dt):
    return (dt - datetime(2000, 1, 1)).days


class Dec:
    def __init__(self, hl):
        self.hl, self.v = hl, {}

    def get(self, k, now):
        x = self.v.get(k)
        return None if x is None else x[1] * 0.5 ** ((now - x[0]) / self.hl)

    def add(self, k, now, arr):
        c = self.get(k, now)
        self.v[k] = (now, np.array(arr, float) if c is None else c + np.array(arr, float))


def by_day(games):
    d = defaultdict(list)
    for g in games:
        d[g["dt"]].append(g)
    return [(k, d[k]) for k in sorted(d)]

TZ = {**{t: -5 for t in ("ATL", "BAL", "BOS", "CIN", "CLE", "DET", "FLO", "MIA", "NYA", "NYN", "PHI", "PIT", "TBA", "TOR", "WAS", "MON")},
      **{t: -6 for t in ("CHA", "CHN", "HOU", "KCA", "MIL", "MIN", "SLN", "TEX")},
      **{t: -7 for t in ("COL", "ARI")},
      **{t: -8 for t in ("ANA", "LAN", "OAK", "ATH", "SDN", "SEA", "SFN")}}


def _park_tz(games):
    home = defaultdict(Counter)
    for g in games:
        home[g["park"]][g["home"]] += 1
    return {p: TZ.get(c.most_common(1)[0][0], -6) for p, c in home.items()}


def travel(games, feats):
    ptz = _park_tz(games)
    last = {}
    hist = defaultdict(list)
    per = {}
    for g in games:
        tz = ptz.get(g["park"], -6)
        row = {}
        for side, t in (("h", g["home"]), ("a", g["vis"])):
            pv = last.get(t)
            gap = (g["dt"] - pv["dt"]).days if pv else 5
            shift = (tz - pv["tz"]) if pv else 0
            dan = 1.0 if pv and gap <= 1 and pv["dn"] == "N" and g["daynight"] == "D" else 0.0
            n10 = sum(1 for d in hist[t] if 0 < (g["dt"] - d).days <= 10)
            row[side] = [abs(shift), 1.0 if shift > 0 else 0.0, dan, 1.0 if gap >= 2 else 0.0, n10]
        per[g["game_id"]] = [a - b for a, b in zip(row["h"], row["a"])]
        for t in (g["home"], g["vis"]):
            last[t] = {"dt": g["dt"], "tz": tz, "dn": g["daynight"]}
            hist[t] = [d for d in hist[t] if (g["dt"] - d).days <= 10] + [g["dt"]]
    return per


# ─────────── 大小分用（整場的數字）───────────
OUT_DIR = {"tocf": 1.0, "tolf": 0.7, "torf": 0.7, "fromcf": -1.0, "fromlf": -0.7, "fromrf": -0.7, "ltor": 0.0, "rtol": 0.0}


def weather(games, feats):
    """溫度、往外／往內吹的風（乘風速）、室內"""
    I = info()
    out = {}
    for g in games:
        r = I.get(g["game_id"])
        if not r:
            continue
        dome = 1.0 if r["sky"] == "dome" else 0.0
        t = float(r["temp"]) if r["temp"] not in ("", "0") else 72.0
        ws = max(0.0, float(r["windspeed"])) if r["windspeed"] not in ("", "-1") else 0.0
        wo = OUT_DIR.get(r["winddir"], 0.0) * ws * (1 - dome)
        out[g["game_id"]] = [(t - 72) * (1 - dome), wo, dome, max(0.0, ws - 12) * (1 - dome)]
    return out


def ump_zone(games, feats):
    """主審的好球帶大小：他當主審時，打者沒揮棒的球被判好球的比例（比聯盟平均多幾 %），往平均拉"""
    I, FR = info(), framing_rows()
    U, LG = Dec(730.0), Dec(365.0)
    out = {}
    for day, gs in by_day(games):
        now = days(day)
        lg = LG.get("lg", now)
        lr = lg[0] / lg[1] if lg is not None and lg[1] > 0 else 0.32
        for g in gs:
            u = (I.get(g["game_id"]) or {}).get("umphome")
            x = U.get(u, now) if u else None
            z = ((x[0] + lr * 3000) / (x[1] + 3000) - lr) * 100 if x is not None else 0.0
            out[g["game_id"]] = [z]
        for g in gs:
            u = (I.get(g["game_id"]) or {}).get("umphome")
            cs = sum(r[3] for r in FR.get(g["game_id"], []))
            tk = cs + sum(r[4] for r in FR.get(g["game_id"], []))
            if u and tk:
                U.add(u, now, [cs, tk])
                LG.add("lg", now, [cs, tk])
    return out


def ump_runs(games, feats):
    """主審過去的比賽，實際總分比收盤大小線多或少幾分（往 0 拉）"""
    I = info()
    by = {f["game_id"]: f for f in feats}
    U = Dec(730.0)
    out = {}
    for day, gs in by_day(games):
        now = days(day)
        for g in gs:
            u = (I.get(g["game_id"]) or {}).get("umphome")
            x = U.get(u, now) if u else None
            out[g["game_id"]] = [x[0] / (x[1] + 60) if x is not None else 0.0]
        for g in gs:
            u = (I.get(g["game_id"]) or {}).get("umphome")
            f = by.get(g["game_id"])
            if u and f and f.get("total_line"):
                U.add(u, now, [g["hs"] + g["as"] - f["total_line"], 1.0])
    return out


# ─────────── 獨贏用（主隊 − 客隊）───────────
def catcher(games, feats):
    """捕手偷好球：同一批投手，換這個捕手接時多被判幾 % 好球（扣掉投手本身的控球）。
    開盤時不知道誰先發捕手 → 用這隊最近 10 場最常先發的捕手。"""
    I, FR = info(), framing_rows()
    P, C = Dec(730.0), Dec(730.0)
    starts = defaultdict(list)
    out = {}
    for day, gs in by_day(games):
        now = days(day)

        def cval(c):
            x = C.get(c, now)
            return (x[0] / (x[1] + 2000)) * 100 if x is not None else 0.0

        for g in gs:
            v = {}
            for side, t in (("h", g["home"]), ("a", g["vis"])):
                hist = starts[t][-10:]
                c = Counter(hist).most_common(1)[0][0] if hist else None
                v[side] = cval(c) if c else 0.0
            out[g["game_id"]] = [v["h"] - v["a"]]
        for g in gs:
            for (t, p, c, cs, b) in FR.get(g["game_id"], []):
                tk = cs + b
                if not tk or not c:
                    continue
                x = P.get(p, now)
                exp = (x[0] + 0.32 * 300) / (x[1] + 300) if x is not None else 0.32
                C.add(c, now, [cs - exp * tk, tk])
                P.add(p, now, [cs, tk])
            r = I.get(g["game_id"]) or {}
            for t, k in ((g["home"], "home_catcher"), (g["vis"], "vis_catcher")):
                if r.get(k):
                    starts[t] = (starts[t] + [r[k]])[-12:]
    return out


def sp_rest(games, feats):
    """先發投手的休息天數、上一場投幾球（短休、上一場投太多球）"""
    from pro import mlb_player_model as M2
    _, pit = M2.load_lines() if "lines" not in _cache else _cache["lines"]
    last = {}
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            v = {}
            for side, sp in (("h", g["home_sp"]), ("a", g["vis_sp"])):
                x = last.get(sp)
                rest = min((day - x[0]).days, 10) if x else 6
                v[side] = [1.0 if rest <= 4 else 0.0, max(0.0, (x[1] if x else 90) - 100), 1.0 if rest >= 8 else 0.0]
            out[g["game_id"]] = [a - b for a, b in zip(v["h"], v["a"])]
        for g in gs:
            for (t, p, st, npitch, vv, vl) in pit.get(g["game_id"], []):
                if st:
                    last[p] = (day, npitch)
    return out


def streak(games, feats):
    """最近 10 場勝場數、連勝連敗（一般人愛追熱門的隊，開盤可能被拉向熱門，收盤再修正）"""
    res = defaultdict(list)
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            v = {}
            for side, t in (("h", g["home"]), ("a", g["vis"])):
                r = res[t][-10:]
                run = 0
                for w in reversed(res[t]):
                    if w == (res[t][-1] if res[t] else 1):
                        run += 1
                    else:
                        break
                v[side] = [sum(r) - len(r) / 2, (run if res[t] and res[t][-1] else -run) if res[t] else 0]
            out[g["game_id"]] = [a - b for a, b in zip(v["h"], v["a"])]
        for g in gs:
            res[g["home"]] = (res[g["home"]] + [int(g["hs"] > g["as"])])[-30:]
            res[g["vis"]] = (res[g["vis"]] + [int(g["as"] > g["hs"])])[-30:]
    return out


def sp_exp(games, feats):
    """先發投手的經驗（生涯先發場數，取 log）：新秀、剛升上來的投手，市場資訊少，開盤可能比較不準"""
    from pro import mlb_player_model as M2
    _, pit = M2.load_lines()
    n = defaultdict(int)
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            a = np.log1p(min(n[g["home_sp"]], 60))
            b = np.log1p(min(n[g["vis_sp"]], 60))
            out[g["game_id"]] = [a - b, float(n[g["home_sp"]] < 5) - float(n[g["vis_sp"]] < 5)]
        for g in gs:
            for (t, p, st, npitch, vv, vl) in pit.get(g["game_id"], []):
                if st:
                    n[p] += 1
    return out


def _lines():
    if "lines" not in _cache:
        from pro import mlb_player_model as M2
        _cache["lines"] = M2.load_lines()
    return _cache["lines"]


def _season_start(games):
    st = {}
    for g in games:
        st[g["season"]] = min(st.get(g["season"], g["dt"]), g["dt"])
    return st


def turnover_early(games, feats):
    """開季 40 天內：今天（上一場）的打線＋先發投手裡，去年在別隊的人占幾成"""
    bat, pit = _lines()
    st = _season_start(games)
    team_season = {}
    last_lu = {}
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            early = 1.0 if (day - st[g["season"]]).days <= 40 else 0.0
            v = {}
            for side, t, sp in (("h", g["home"], g["home_sp"]), ("a", g["vis"], g["vis_sp"])):
                ppl = last_lu.get(t, []) + [sp]
                prev = [team_season.get((p, g["season"] - 1)) for p in ppl]
                known = [x for x in prev if x]
                v[side] = (sum(1 for x in known if x != t) / len(known)) if known else 0.0
            out[g["game_id"]] = [(v["h"] - v["a"]) * early]
        for g in gs:
            lu = defaultdict(list)
            for (t, b, slot, stt, vv, vl) in bat.get(g["game_id"], []):
                team_season[(b, g["season"])] = t
                if stt:
                    lu[t].append(b)
            for (t, p, stt, n, vv, vl) in pit.get(g["game_id"], []):
                team_season[(p, g["season"])] = t
            for t, l in lu.items():
                last_lu[t] = l
    return out


def pythag_early(games, feats):
    """開季 40 天內：去年「實際勝率 − 得失分應有的勝率」（運氣），一般人看戰績，莊家可能跟著"""
    st = _season_start(games)
    rec = defaultdict(lambda: [0, 0, 0.0, 0.0])
    luck = {}
    out = {}
    seen_season = None
    for day, gs in by_day(games):
        s = gs[0]["season"]
        if s != seen_season:
            for (t, ss), (w, n, rs, ra) in list(rec.items()):
                if ss == s - 1 and n > 50 and rs + ra > 0:
                    luck[t] = w / n - rs ** 1.83 / (rs ** 1.83 + ra ** 1.83)
            seen_season = s
        for g in gs:
            early = 1.0 if (day - st[g["season"]]).days <= 40 else 0.0
            out[g["game_id"]] = [(luck.get(g["home"], 0.0) - luck.get(g["vis"], 0.0)) * early]
        for g in gs:
            for t, rs, ra in ((g["home"], g["hs"], g["as"]), (g["vis"], g["as"], g["hs"])):
                r = rec[(t, g["season"])]
                r[0] += int(rs > ra)
                r[1] += 1
                r[2] += rs
                r[3] += ra
    return out


def opener(games, feats):
    """先發投手平常只投 1–2 局（「開局投手」、牛棚車輪戰）：莊家常照「先發投手」定價，可能不準"""
    bat, pit = _lines()
    bf = defaultdict(list)
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            v = {}
            for side, sp in (("h", g["home_sp"]), ("a", g["vis_sp"])):
                x = bf[sp][-5:]
                v[side] = 1.0 if len(x) >= 2 and np.mean(x) < 12 else 0.0
            out[g["game_id"]] = [v["h"] - v["a"]]
        for g in gs:
            for (t, p, stt, n, vv, vl) in pit.get(g["game_id"], []):
                if stt:
                    bf[p].append(vv[0])
    return out


def closer(games, feats):
    """這隊最常用的兩位後援（最近 30 天出場最多），今天能不能投（昨天投 20 球以上、或連投兩天＝不能）"""
    bat, pit = _lines()
    use = defaultdict(lambda: defaultdict(list))      # 隊 → 投手 → [日]
    recent = defaultdict(list)                        # 投手 → [(日, 球數)]
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            v = {}
            for side, t in (("h", g["home"]), ("a", g["vis"])):
                cnt = {p: sum(1 for d in ds if 0 < (day - d).days <= 30) for p, ds in use[t].items()}
                top = sorted(cnt, key=cnt.get, reverse=True)[:2]
                down = 0
                for p in top:
                    rp = recent[p]
                    y = sum(n for d, n in rp if (day - d).days == 1)
                    two = any((day - d).days == 1 for d, _ in rp) and any((day - d).days == 2 for d, _ in rp)
                    down += int(y >= 20 or two)
                v[side] = down
            out[g["game_id"]] = [v["h"] - v["a"]]
        for g in gs:
            for (t, p, stt, n, vv, vl) in pit.get(g["game_id"], []):
                if not stt:
                    use[t][p] = [d for d in use[t][p] if (day - d).days <= 30] + [day]
                recent[p] = [(d, k) for d, k in recent[p] if (day - d).days <= 3] + [(day, n)]
    return out


def sp_form(games, feats):
    """先發投手最近 3 場被打成怎樣（每個打席的 wOBA）減掉長期：一般人看最近的防禦率，可能反應過度"""
    bat, pit = _lines()
    W = np.array([0.0, 0.70, 2.03, 0.88, 1.25, 1.58, 0.88])
    hist = defaultdict(list)
    out = {}
    for day, gs in by_day(games):
        for g in gs:
            v = {}
            for side, sp in (("h", g["home_sp"]), ("a", g["vis_sp"])):
                h = hist[sp]
                if len(h) >= 8:
                    rec = np.sum(h[-3:], axis=0)
                    lt = np.sum(h[-30:], axis=0)
                    v[side] = float(W @ rec[1:] / rec[0] - W @ lt[1:] / lt[0]) if rec[0] and lt[0] else 0.0
                else:
                    v[side] = 0.0
            out[g["game_id"]] = [v["h"] - v["a"]]
        for g in gs:
            for (t, p, stt, n, vv, vl) in pit.get(g["game_id"], []):
                if stt:
                    hist[p] = (hist[p] + [vv])[-30:]
    return out


CANDIDATES = {
    "travel": {"fn": travel, "label": "移動與賽程疲勞",
               "why": "跨時區（尤其往東飛）、前一天夜場今天日場、最近 10 天打幾場、昨天有沒有休息——身體疲勞，莊家可能只粗略考慮"},
    "catcher": {"fn": catcher, "label": "捕手偷好球",
                "why": "好的捕手能把邊邊的球接成好球，一季差十幾分；這是 2010 年代才被重視的數據，盤口可能沒完全反映"},
    "sp_rest": {"fn": sp_rest, "label": "先發投手休息與上一場用球數",
                "why": "短休或上一場投很多球，這場可能比較差；莊家通常只看投手整體數據"},
    "streak": {"fn": streak, "label": "最近戰績、連勝連敗",
               "why": "一般人愛追最近很熱的隊，開盤可能被拉向熱門；如果收盤會修正回來，模型就該知道"},
    "sp_exp": {"fn": sp_exp, "label": "先發投手經驗（新秀、剛升上來）",
               "why": "新投手的資料少，莊家開盤可能比較不準；我們的模型有「新人平均」可以參考"},
    "turnover_early": {"fn": turnover_early, "label": "開季時換了很多人的隊",
                       "why": "開季時莊家和一般人還靠去年的球隊數據；休賽季大換血的隊，去年的數據不準，我們的模型跟著球員走"},
    "pythag_early": {"fn": pythag_early, "label": "開季時，去年戰績的運氣成分",
                     "why": "去年靠運氣多贏的隊（戰績比得失分應有的好），一般人和開盤可能高估"},
    "opener": {"fn": opener, "label": "開局投手（先發只投 1–2 局）",
               "why": "牛棚車輪戰的比賽，盤口常照掛名的先發投手定價，可能不準"},
    "closer": {"fn": closer, "label": "主力後援今天能不能投",
               "why": "終結者、布局投手前兩天投太多，今天可能不能上；開盤時常常沒算進去"},
    "sp_form": {"fn": sp_form, "label": "先發投手最近 3 場被打爆或很神",
                "why": "一般人看最近防禦率，可能反應過度；我們的模型看長期，兩者不一樣時收盤往哪邊？"},
    "weather": {"fn": weather, "kind": "total", "label": "天氣（大小分）",
                "why": "氣溫高球飛比較遠、風往外吹全壘打多；大小盤可能沒完全算進當天的天氣"},
    "ump_zone": {"fn": ump_zone, "kind": "total", "label": "主審好球帶大小（大小分）",
                 "why": "好球帶大的主審三振多、得分少；主審當天早上才公布，盤口可能來不及調整"},
    "ump_runs": {"fn": ump_runs, "kind": "total", "label": "主審過去比賽比大小線多幾分（大小分）",
                 "why": "同上，直接看結果：這個主審的比賽是不是常常開大或開小"},
}
