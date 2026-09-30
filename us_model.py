"""
美國運動「模型一・實力」：獨贏（誰贏）
==========================================
資料：download_history.py 抓的歷史比賽＋收盤賠率（docs/data/<運動>/history/）
      SBRO 2007-08 ～ 2021-22、ESPN 2022-23 起（2022-23 兩邊都有，用 ESPN 的，SBRO 只拿來對隊名）

特徵（全部是開賽前就知道的）：
- 市場：收盤獨贏去掉抽成 → log(主勝機率 / 客勝機率)
- Elo 強弱分數：每場依比分差更新（贏越多改越多，但強隊大勝打折），換季往平均拉回
- 休息天數、背靠背（前一天有比賽）
驗證方式跟足球一樣：最早一季只暖機；倒數第三季當驗證季挑特徵；最後兩季當測試（模型沒看過）

輸出：docs/data/<運動>/model/report_ml.json（成績單）、params_ml.json（看板算機率用）
用法：python us_model.py nba   或   python us_model.py nhl
"""
import glob
import json
import math
import os
import re
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

BASE = os.path.dirname(os.path.abspath(__file__))
# 每個運動的 Elo 設定（K、主場分、換季拉回比例、比分差的尺度）
ELO = {"nba": {"k": 20, "home": 70, "regress": 0.25, "mov": 1.0},
       "nhl": {"k": 8, "home": 35, "regress": 0.35, "mov": 1.0},
       "nfl": {"k": 20, "home": 48, "regress": 0.33, "mov": 1.0}}
REST_CAP = 4
EDGES = [0.0, 0.02, 0.04]
TW_DISCOUNT = 0.91   # 台彩賠率大約是美國的 9 成（用你記的台彩賠率估的；之後自動更新）

# SBRO 的隊名（沒有空格）→ ESPN 的隊名；搬家、改名的隊接到同一支（Elo 延續）
SBRO_ALIAS = {
    "nba": {"NewJersey": "Brooklyn Nets", "Seattle": "Oklahoma City Thunder", "NewOrleans": "New Orleans Pelicans",
            "Charlotte": "Charlotte Hornets", "LAClippers": "LA Clippers", "LAClipper": "LA Clippers"},
    "nhl": {"Atlanta": "Winnipeg Jets", "Phoenix": "Arizona Coyotes", "Arizona": "Arizona Coyotes", "Arizonas": "Arizona Coyotes"},
}
# ESPN 時代的改名／搬家（接到同一支）
ESPN_ALIAS = {"nhl": {"Utah Hockey Club": "Arizona Coyotes", "Utah Mammoth": "Arizona Coyotes"}}


def squash(s):
    return re.sub(r"[^a-z]", "", str(s).lower())


def devig2(a, h):
    ia, ih = 1 / a, 1 / h
    return ih / (ia + ih)


def am2dec(v):
    v = np.asarray(v, dtype=float)
    with np.errstate(divide="ignore"):
        return np.where(v > 0, 1 + v / 100, 1 + 100 / np.abs(v))


# ---------------- 讀資料 ----------------
def load(sport):
    d = os.path.join(BASE, "docs", "data", sport, "history")
    frames = []
    for p in sorted(glob.glob(os.path.join(d, "*.csv"))):
        df = pd.read_csv(p, dtype={"season": str})
        if len(df):
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    espn_seasons = set(df.loc[df["source"] == "espn", "season"])
    # 隊名對照：用兩邊都有的季（同一天、同樣比分）自動配對 SBRO 名 → ESPN 名
    name_map = dict(SBRO_ALIAS.get(sport, {}))
    both = df[df["season"].isin(espn_seasons)]
    sb, es = both[both["source"] == "sbro"], both[both["source"] == "espn"]
    key = lambda r: (r["date"], int(r["away_score"]), int(r["home_score"]))
    es_idx = {key(r): r for _, r in es.dropna(subset=["away_score", "home_score"]).iterrows()}
    for _, r in sb.dropna(subset=["away_score", "home_score"]).iterrows():
        e = es_idx.get(key(r))
        if e is not None:
            name_map.setdefault(r["away"], e["away"])
            name_map.setdefault(r["home"], e["home"])
    # 沒配到的 SBRO 名：拿 ESPN 名去掉空白後比對城市（例如 GoldenState → Golden State Warriors）
    espn_names = sorted(set(es["away"]) | set(es["home"]))
    for n in set(df.loc[df["source"] == "sbro", "away"]) | set(df.loc[df["source"] == "sbro", "home"]):
        if n in name_map:
            continue
        hits = [e for e in espn_names if squash(e).startswith(squash(n))]
        if len(hits) == 1:
            name_map[n] = hits[0]
    # 同一季兩個來源都有 → 用 ESPN
    df = df[~((df["source"] == "sbro") & df["season"].isin(espn_seasons))].copy()
    sb_mask = df["source"] == "sbro"
    df.loc[sb_mask, "away"] = df.loc[sb_mask, "away"].map(lambda n: name_map.get(n, n))
    df.loc[sb_mask, "home"] = df.loc[sb_mask, "home"].map(lambda n: name_map.get(n, n))
    alias = ESPN_ALIAS.get(sport, {})
    df["away"] = df["away"].map(lambda n: alias.get(n, n))
    df["home"] = df["home"].map(lambda n: alias.get(n, n))
    df = df.dropna(subset=["away_score", "home_score"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["date"]).reset_index(drop=True)
    unmapped = sorted({n for n in set(df["away"]) | set(df["home"]) if n not in espn_names})
    return df, unmapped


# ---------------- 特徵 ----------------
def build_features(df, sport):
    cfg = ELO[sport]
    elo, last_game, cur_season = {}, {}, None
    rows = []
    for r in df.itertuples(index=False):
        if r.season != cur_season:
            if cur_season is not None:
                for t in elo:
                    elo[t] += (1500 - elo[t]) * cfg["regress"]
            cur_season = r.season
        a, h = r.away, r.home
        ea, eh = elo.get(a, 1500.0), elo.get(h, 1500.0)
        home_adv = 0 if r.neutral in (True, "True") else cfg["home"]
        ra = (r.date - last_game[a]).days if a in last_game else REST_CAP
        rh = (r.date - last_game[h]).days if h in last_game else REST_CAP
        rows.append({"elo_away": ea, "elo_home": eh, "elo_diff": eh + home_adv - ea,
                     "rest_away": min(ra, REST_CAP), "rest_home": min(rh, REST_CAP),
                     "b2b_away": float(ra == 1), "b2b_home": float(rh == 1)})
        # 賽後更新 Elo（比分差乘數：538 的作法，強隊大勝打折）
        diff = r.home_score - r.away_score
        exp_h = 1 / (1 + 10 ** (-(eh + home_adv - ea) / 400))
        res = 1.0 if diff > 0 else 0.0 if diff < 0 else 0.5
        elo_gap = (eh + home_adv - ea) * (1 if diff > 0 else -1)
        mult = math.log(abs(diff) + 1) * (2.2 / (elo_gap * 0.001 + 2.2)) if diff else 1.0
        delta = cfg["k"] * mult * (res - exp_h)
        elo[h] = eh + delta
        elo[a] = ea - delta
        last_game[a] = last_game[h] = r.date
    f = pd.DataFrame(rows)
    out = pd.concat([df.reset_index(drop=True), f], axis=1)
    out["rest_diff"] = out["rest_home"] - out["rest_away"]
    out["b2b_diff"] = out["b2b_home"] - out["b2b_away"]
    ok = out["ml_close_away"].notna() & out["ml_close_home"].notna() & (out["ml_close_away"] != 0) & (out["ml_close_home"] != 0)
    ca, ch = am2dec(out["ml_close_away"].fillna(100)), am2dec(out["ml_close_home"].fillna(100))
    out["dec_close_away"], out["dec_close_home"] = np.where(ok, ca, np.nan), np.where(ok, ch, np.nan)
    out["p_mkt"] = devig2(out["dec_close_away"], out["dec_close_home"])
    out["lm"] = np.log(out["p_mkt"] / (1 - out["p_mkt"]))
    oo = out["ml_open_away"].notna() & out["ml_open_home"].notna()
    out["dec_open_away"] = np.where(oo, am2dec(out["ml_open_away"].fillna(100)), np.nan)
    out["dec_open_home"] = np.where(oo, am2dec(out["ml_open_home"].fillna(100)), np.nan)
    out["y"] = (out["home_score"] > out["away_score"]).astype(int)
    out = out[out["home_score"] != out["away_score"]]
    return out, elo


# ---------------- 評估 ----------------
def logloss(p, y):
    p = np.clip(p, 1e-9, 1 - 1e-9)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def brier(p, y):
    return float(np.mean((p - y) ** 2))


def calibration(p, y, k=8):
    probs = np.concatenate([p, 1 - p]); hits = np.concatenate([y, 1 - y])
    edges = np.quantile(probs, np.linspace(0, 1, k + 1))
    out = []
    for i in range(k):
        m = (probs >= edges[i]) & ((probs <= edges[i + 1]) if i == k - 1 else (probs < edges[i + 1]))
        if m.sum():
            out.append({"pred": round(float(probs[m].mean()) * 100, 1), "real": round(float(hits[m].mean()) * 100, 1), "n": int(m.sum())})
    return out


def simulate(p, y, dec_a, dec_h, edge):
    """模型機率 × 賠率 > 1 + 門檻就下 1 單位（每場最多一邊）"""
    ev_h, ev_a = p * dec_h - 1, (1 - p) * dec_a - 1
    pick_h = (ev_h >= ev_a) & (ev_h > edge)
    pick_a = (ev_a > ev_h) & (ev_a > edge)
    pl = np.where(pick_h, np.where(y == 1, dec_h - 1, -1.0), 0) + np.where(pick_a, np.where(y == 0, dec_a - 1, -1.0), 0)
    n = int(pick_h.sum() + pick_a.sum())
    if not n:
        return {"n": 0}
    bet = pl[pick_h | pick_a]
    return {"n": n, "roi": round(float(bet.mean() * 100), 1), "se": round(float(bet.std(ddof=1) / math.sqrt(n) * 100), 1) if n > 1 else None,
            "win": int((bet > 0).sum())}


def fitter(tr, cols, C=1.0):
    tr = tr.dropna(subset=cols + ["y"])
    sc = StandardScaler().fit(tr[cols])
    m = LogisticRegression(C=C, max_iter=3000).fit(sc.transform(tr[cols]), tr["y"])
    return (lambda d: m.predict_proba(sc.transform(d[cols]))[:, 1]), m, sc


CANDIDATES = {
    "市場重新校正": ["lm"],
    "市場＋Elo": ["lm", "elo_diff"],
    "市場＋Elo＋休息": ["lm", "elo_diff", "rest_diff", "b2b_home", "b2b_away"],
    "市場＋休息": ["lm", "rest_diff", "b2b_home", "b2b_away"],
}


def run(sport):
    raw, unmapped = load(sport)
    df, elo = build_features(raw, sport)
    seasons = sorted(df["season"].unique())
    warm, test_seasons, val_season = seasons[0], seasons[-2:], seasons[-3]
    usable = df[df["p_mkt"].notna() & (df["season"] != warm)]
    train_v = usable[usable["season"] < val_season]
    val = usable[usable["season"] == val_season]
    # 1) 在驗證季挑特徵
    val_scores = {}
    for name, cols in CANDIDATES.items():
        f, _, _ = fitter(train_v, cols)
        val_scores[name] = round(logloss(f(val), val["y"].values), 5)
    best = min(val_scores, key=val_scores.get)
    cols = CANDIDATES[best]
    # 2) 用驗證季以前＋驗證季重練，測試季只拿來打分
    train = usable[~usable["season"].isin(test_seasons)]
    test = usable[usable["season"].isin(test_seasons)]
    f_best, m_best, _ = fitter(train, cols)
    f_team, _, _ = fitter(train, ["elo_diff", "rest_diff", "b2b_home", "b2b_away"])
    y = test["y"].values
    p_mkt, p_model, p_team = test["p_mkt"].values, f_best(test), f_team(test)
    U = math.log(2)
    acc = {"market": {"logloss": round(logloss(p_mkt, y), 4), "brier": round(brier(p_mkt, y), 4)},
           "model": {"logloss": round(logloss(p_model, y), 4), "brier": round(brier(p_model, y), 4)},
           "team_only": {"logloss": round(logloss(p_team, y), 4), "brier": round(brier(p_team, y), 4)},
           "uniform": {"logloss": round(U, 4)}}
    # 開盤賠率時代能不能賺（模擬在開盤下注，看收盤前有沒有搶到價）
    has_open = test["dec_open_home"].notna().values
    bet = {"close": {str(e): simulate(p_model, y, test["dec_close_away"].values, test["dec_close_home"].values, e) for e in EDGES},
           "tw": {str(e): simulate(p_model, y, test["dec_close_away"].values * TW_DISCOUNT, test["dec_close_home"].values * TW_DISCOUNT, e) for e in EDGES}}
    if has_open.sum() > 200:
        # 在開盤就下注：模型只能看到開盤賠率（不能偷看收盤），用開盤賠率算特徵再比開盤賠率
        t2 = test[has_open].copy()
        po = devig2(t2["dec_open_away"], t2["dec_open_home"])
        t2["lm"] = np.log(po / (1 - po))
        bet["open"] = {str(e): simulate(f_best(t2), t2["y"].values, t2["dec_open_away"].values, t2["dec_open_home"].values, e) for e in EDGES}
        # 開盤到收盤：收盤往哪邊動（參考：市場在開盤後還會修正多少）
        res_extra = {"open_logloss": round(logloss(po.values, t2["y"].values), 4),
                     "close_logloss_same_games": round(logloss(t2["p_mkt"].values, t2["y"].values), 4), "n": int(len(t2))}
    else:
        res_extra = None
    res = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "sport": sport,
        "seasons": [seasons[0], seasons[-1]], "warmup": warm, "validation_season": val_season, "test_seasons": test_seasons,
        "train_games": int(len(train)), "test_games": int(len(test)), "all_games": int(len(df)),
        "validation": val_scores, "chosen": best, "features": cols,
        "weights": {c: round(float(w), 3) for c, w in zip(cols, m_best.coef_[0])},
        "accuracy": acc,
        "hit_rate": {"market": round(float(np.mean((p_mkt > .5) == y)) * 100, 1), "model": round(float(np.mean((p_model > .5) == y)) * 100, 1)},
        "calibration": calibration(p_model, y), "betting": bet, "open_vs_close": res_extra,
        "home_win_rate": round(float(df["y"].mean()) * 100, 1),
        "unmapped_teams": unmapped[:30],
        "by_season": {s: {"n": int((test["season"] == s).sum()),
                          "market": round(logloss(p_mkt[test["season"].values == s], y[test["season"].values == s]), 4),
                          "model": round(logloss(p_model[test["season"].values == s], y[test["season"].values == s]), 4)}
                      for s in test_seasons},
    }
    # 3) 給看板用：全部資料重練
    full = usable
    _, m_f, sc_f = fitter(full, cols)
    last_season = seasons[-1]
    active = set(df.loc[df["season"] == last_season, "home"]) | set(df.loc[df["season"] == last_season, "away"])
    params = {"generated_utc": res["generated_utc"], "sport": sport, "features": cols,
              "mean": sc_f.mean_.round(6).tolist(), "scale": sc_f.scale_.round(6).tolist(),
              "coef": m_f.coef_[0].round(6).tolist(), "intercept": round(float(m_f.intercept_[0]), 6),
              "elo_home": ELO[sport]["home"], "elo_regress": ELO[sport]["regress"], "rest_cap": REST_CAP,
              # 下一季開始前還會往平均拉回一次；看板在新季第一場前自動套用
              "elo": {t: round(v, 1) for t, v in elo.items() if t in active}, "last_season": last_season}
    od = os.path.join(BASE, "docs", "data", sport, "model")
    os.makedirs(od, exist_ok=True)
    json.dump(res, open(os.path.join(od, "report_ml.json"), "w"), ensure_ascii=False, indent=1)
    json.dump(params, open(os.path.join(od, "params_ml.json"), "w"), ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    for sp in (sys.argv[1] if len(sys.argv) > 1 else "nba,nhl").split(","):
        r = run(sp)
        print(json.dumps({k: r[k] for k in ("sport", "seasons", "train_games", "test_games", "validation", "chosen", "weights",
                                            "accuracy", "hit_rate", "betting", "open_vs_close", "by_season", "unmapped_teams")}, ensure_ascii=False, indent=1))
