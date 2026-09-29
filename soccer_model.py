"""
足球第一層模型：獨贏（主／和／客）
============================================
資料：football-data.co.uk 五大聯賽過去五季＋本季（docs/data/soccer/eu/）
目的：算出每場比賽「本來該怎麼開」的主／和／客機率，之後第二層再用資金流向修正。

做法（每一步都只用「比賽開打前就知道」的資訊，避免偷看答案）：
1. 特徵
   - 市場機率：賽前各家平均賠率（Avg）去掉抽成
   - Elo 強弱分數：每場打完依比分更新，換季時往平均拉回一點；升級隊從較低分開始
   - 近 6 場：場均進球、失球、射正、被射正、積分
   - 休息天數（聯賽內）
2. 按時間切：前四季訓練、最近一季＋本季測試（模型沒看過的比賽）
   挑特徵、挑參數只用「訓練季內部」切出來的驗證季（2024/25），不看測試季，避免對著答案調
   驗證結果：只加 Elo 最好；近況、射正、休息天數加進去反而變差（在背雜訊），所以最終模型＝賠率＋Elo
3. 比較三種方式的準確度（log loss，越低越準）：
   - 只看賠率（市場）
   - 只看球隊數據（不看賠率）
   - 兩個一起（我們的模型）
   另外列出收盤賠率的準確度當「天花板」參考（收盤時的資訊最多，下注時拿不到）
4. 模擬下注：模型機率 × 賠率 > 1 + 門檻才下，看在歐洲平均賠率、估計的台彩賠率下賺賠

輸出：docs/data/soccer/model/report_1x2.json（看板讀）
"""

import glob
import json
import math
import os
import warnings
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

warnings.filterwarnings("ignore", category=pd.errors.PerformanceWarning)

BASE = os.path.dirname(os.path.abspath(__file__))
EU_DIR = os.path.join(BASE, "docs", "data", "soccer", "eu")
OUT_DIR = os.path.join(BASE, "docs", "data", "soccer", "model")
DIV_LEAGUE = {"E0": "epl", "SP1": "laliga", "I1": "seriea", "D1": "bundesliga", "F1": "ligue1"}
TEST_SEASONS = {"2526", "2627"}
FORM_N = 6
ELO_K, ELO_HOME, ELO_START, ELO_PROMOTED, ELO_REGRESS = 20, 60, 1500, 1430, 1 / 3
TW_FACTOR = 0.90          # 台彩賠率大約是歐洲平均的 9 成（之後用你記的台彩足球賠率校正）
EDGES = [0.0, 0.02, 0.05, 0.08]
OUTCOMES = ["H", "D", "A"]


# ---------------- 讀資料 ----------------
def load():
    frames = []
    for path in sorted(glob.glob(os.path.join(EU_DIR, "*.csv"))):
        div, season = os.path.basename(path)[:-4].split("_")
        if div not in DIV_LEAGUE:
            continue
        df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="ignore", on_bad_lines="skip")
        df["div"], df["season"] = div, season
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
    df["date"] = pd.to_datetime(df["Date"], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["date"]).sort_values(["date", "div"]).reset_index(drop=True)
    for c in ["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC"]:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    for c in ["AvgH", "AvgD", "AvgA", "AvgCH", "AvgCD", "AvgCA", "PSCH", "PSCD", "PSCA", "MaxH", "MaxD", "MaxA"]:
        df[c] = pd.to_numeric(df.get(c), errors="coerce")
    return df


def devig(h, d, a):
    inv = np.vstack([1 / h, 1 / d, 1 / a]).T
    return inv / inv.sum(axis=1, keepdims=True)


# ---------------- 特徵（只用開賽前的資訊）----------------
def build_features(df):
    elo, hist, last_date, season_teams = {}, {}, {}, {}
    prev_season_teams = {}
    feats = []
    cur_season = {}
    for r in df.itertuples(index=False):
        div, season = r.div, r.season
        # 換季：Elo 往平均拉回；記下上季有哪些隊（沒出現過的＝升級隊）
        if cur_season.get(div) != season:
            if div in cur_season:
                prev_season_teams[div] = season_teams.get(div, set())
                for t in season_teams.get(div, set()):
                    k = (div, t)
                    elo[k] = elo[k] + (ELO_START - elo[k]) * ELO_REGRESS
            cur_season[div] = season
            season_teams[div] = set()
        row = {}
        for side, team in (("h", r.HomeTeam), ("a", r.AwayTeam)):
            k = (div, team)
            if k not in elo:
                promoted = bool(prev_season_teams.get(div)) and team not in prev_season_teams[div]
                elo[k] = ELO_PROMOTED if promoted else ELO_START
            season_teams[div].add(team)
            hs = hist.get(k, [])[-FORM_N:]
            n = len(hs)
            row[f"{side}_elo"] = elo[k]
            row[f"{side}_n"] = n
            for i, nm in enumerate(["gf", "ga", "sotf", "sota", "pts"]):
                vals = [x[i] for x in hs if x[i] == x[i]]
                row[f"{side}_{nm}"] = sum(vals) / len(vals) if vals else np.nan
            ld = last_date.get(k)
            row[f"{side}_rest"] = min((r.date - ld).days, 14) if ld is not None else 14
        feats.append(row)
        # 比賽打完：更新 Elo 和近況
        kh, ka = (div, r.HomeTeam), (div, r.AwayTeam)
        exp_h = 1 / (1 + 10 ** ((elo[ka] - elo[kh] - ELO_HOME) / 400))
        res_h = 1.0 if r.FTR == "H" else 0.5 if r.FTR == "D" else 0.0
        gd = abs(r.FTHG - r.FTAG)
        mult = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        delta = ELO_K * mult * (res_h - exp_h)
        elo[kh] += delta
        elo[ka] -= delta
        ph = 3 if r.FTR == "H" else 1 if r.FTR == "D" else 0
        pa = 3 if r.FTR == "A" else 1 if r.FTR == "D" else 0
        hist.setdefault(kh, []).append((r.FTHG, r.FTAG, r.HST, r.AST, ph))
        hist.setdefault(ka, []).append((r.FTAG, r.FTHG, r.AST, r.HST, pa))
        last_date[kh] = last_date[ka] = r.date
    global LAST_ELO, LAST_SEASON_TEAMS
    LAST_ELO, LAST_SEASON_TEAMS = elo, season_teams
    f = pd.DataFrame(feats)
    out = pd.concat([df.reset_index(drop=True), f], axis=1)
    out["elo_diff"] = out["h_elo"] + ELO_HOME - out["a_elo"]
    for nm in ["gf", "ga", "sotf", "sota", "pts"]:
        out[f"d_{nm}"] = out[f"h_{nm}"] - out[f"a_{nm}"]
    out["d_rest"] = out["h_rest"] - out["a_rest"]
    return out


# ---------------- 評估工具 ----------------
def logloss(p, y):
    idx = np.array([OUTCOMES.index(v) for v in y])
    return float(-np.mean(np.log(np.clip(p[np.arange(len(y)), idx], 1e-12, 1))))


def brier(p, y):
    onehot = np.zeros_like(p)
    onehot[np.arange(len(y)), [OUTCOMES.index(v) for v in y]] = 1
    return float(np.mean(np.sum((p - onehot) ** 2, axis=1)))


def simulate(p, y, odds, edge, close=None):
    """模型機率 × 賠率 > 1 + 門檻就下 1 單位（每場最多下一邊：期望值最高那邊）"""
    ev = p * odds - 1
    best = np.nanargmax(np.where(np.isnan(ev), -9, ev), axis=1)
    bev = ev[np.arange(len(y)), best]
    pick = bev > edge
    n = int(pick.sum())
    if not n:
        return {"n": 0}
    won = np.array([OUTCOMES[b] == v for b, v in zip(best, y)])[pick]
    o = odds[np.arange(len(y)), best][pick]
    pl = np.where(won, o - 1, -1.0)
    res = {"n": n, "win": int(won.sum()), "pl": round(float(pl.sum()), 2), "roi": round(float(pl.mean() * 100), 1),
           "avg_odds": round(float(o.mean()), 2),
           "pick_share": {k: int(((best == i) & pick).sum()) for i, k in enumerate(["home", "draw", "away"])}}
    if close is not None:
        c = close[np.arange(len(y)), best][pick]
        ok = ~np.isnan(c)
        if ok.any():
            res["clv"] = round(float(np.mean(o[ok] / c[ok] - 1) * 100), 2)
    # 運氣範圍：假設模型沒本事（勝率＝收盤去水機率），95% 會落在哪
    return res


def calibration(p, y, k=8):
    """把機率分成幾組，看模型說 40% 的時候是不是真的大約 40% 會中（三個結果合在一起看）"""
    probs = p.ravel()
    hits = np.zeros_like(p)
    hits[np.arange(len(y)), [OUTCOMES.index(v) for v in y]] = 1
    hits = hits.ravel()
    edges = np.quantile(probs, np.linspace(0, 1, k + 1))
    out = []
    for i in range(k):
        m = (probs >= edges[i]) & (probs <= edges[i + 1] if i == k - 1 else probs < edges[i + 1])
        if m.sum():
            out.append({"pred": round(float(probs[m].mean()) * 100, 1), "real": round(float(hits[m].mean()) * 100, 1), "n": int(m.sum())})
    return out


# ---------------- 主程式 ----------------
def run():
    df = build_features(load()).copy()
    df = df.dropna(subset=["AvgH", "AvgD", "AvgA"])
    mk = devig(df["AvgH"].values, df["AvgD"].values, df["AvgA"].values)
    df["m_h"], df["m_d"], df["m_a"] = mk[:, 0], mk[:, 1], mk[:, 2]
    df["lm_h"] = np.log(df["m_h"] / df["m_a"])
    df["lm_d"] = np.log(df["m_d"] / df["m_a"])
    # 近況資料不足（開季前幾場、升級隊）先用 0 差距補，並把「場數」當特徵讓模型知道資訊少
    team_cols = ["elo_diff", "d_gf", "d_ga", "d_sotf", "d_sota", "d_pts", "d_rest", "h_n", "a_n"]
    for c in team_cols:
        df[c] = df[c].fillna(0)
    for lg in DIV_LEAGUE:
        df[f"lg_{lg}"] = (df["div"] == lg).astype(float)
    lg_cols = [f"lg_{lg}" for lg in DIV_LEAGUE]

    train = df[~df["season"].isin(TEST_SEASONS) & (df["h_n"] >= 3) & (df["a_n"] >= 3)]
    test = df[df["season"].isin(TEST_SEASONS)]
    ytr, yte = train["FTR"].values, test["FTR"].values

    def fit(cols, C=1.0):
        sc = StandardScaler().fit(train[cols])
        m = LogisticRegression(C=C, max_iter=2000).fit(sc.transform(train[cols]), ytr)
        order = [list(m.classes_).index(o) for o in OUTCOMES]
        return (lambda d: m.predict_proba(sc.transform(d[cols]))[:, order]), m, sc

    p_mkt = test[["m_h", "m_d", "m_a"]].values
    f_team, _, _ = fit(team_cols + lg_cols)
    FINAL = ["lm_h", "lm_d", "elo_diff"]
    f_both, m_both, sc_both = fit(FINAL, C=1.0)
    f_recal, _, _ = fit(["lm_h", "lm_d"], C=1.0)          # 只把莊家賠率重新校正（看莊家本身有沒有系統性偏差）
    f_all, _, _ = fit(["lm_h", "lm_d"] + team_cols + lg_cols, C=1.0)  # 全部特徵（對照用，驗證季比較差）
    p_team, p_both, p_recal, p_all = f_team(test), f_both(test), f_recal(test), f_all(test)

    # 收盤（天花板參考）：優先用 Pinnacle 收盤，沒有就用各家平均收盤
    ch = test["PSCH"].fillna(test["AvgCH"]).values
    cd = test["PSCD"].fillna(test["AvgCD"]).values
    ca = test["PSCA"].fillna(test["AvgCA"]).values
    okc = ~(np.isnan(ch) | np.isnan(cd) | np.isnan(ca))
    p_close = devig(ch[okc], cd[okc], ca[okc])

    res = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "train_games": int(len(train)), "test_games": int(len(test)),
        "train_seasons": sorted(set(train["season"])), "test_seasons": sorted(set(test["season"])),
        "base_rates": {k: round(float((df["FTR"] == k).mean()) * 100, 1) for k in OUTCOMES},
        "base_rates_by_league": {DIV_LEAGUE[d]: {k: round(float((g["FTR"] == k).mean()) * 100, 1) for k in OUTCOMES}
                                 for d, g in df.groupby("div")},
        "accuracy": {
            "market": {"logloss": round(logloss(p_mkt, yte), 4), "brier": round(brier(p_mkt, yte), 4)},
            "team_only": {"logloss": round(logloss(p_team, yte), 4), "brier": round(brier(p_team, yte), 4)},
            "model": {"logloss": round(logloss(p_both, yte), 4), "brier": round(brier(p_both, yte), 4)},
            "market_recal": {"logloss": round(logloss(p_recal, yte), 4), "brier": round(brier(p_recal, yte), 4)},
            "all_features": {"logloss": round(logloss(p_all, yte), 4), "brier": round(brier(p_all, yte), 4)},
            "closing": {"logloss": round(logloss(p_close, yte[okc]), 4), "brier": round(brier(p_close, yte[okc]), 4),
                        "n": int(okc.sum())},
            "uniform": {"logloss": round(math.log(3), 4)},
        },
        "hit_rate": {k: round(float(np.mean(np.array(OUTCOMES)[p.argmax(1)] == yte)) * 100, 1)
                     for k, p in (("market", p_mkt), ("team_only", p_team), ("model", p_both))},
        "calibration": calibration(p_both, yte),
        "features": FINAL,
        "weights": {c: round(float(w), 3) for c, w in zip(FINAL, m_both.coef_[list(m_both.classes_).index("H")])},
    }
    # 模擬下注：歐洲平均賠率、估計台彩賠率、歐洲最高賠率
    avg = test[["AvgH", "AvgD", "AvgA"]].values
    mx = test[["MaxH", "MaxD", "MaxA"]].values
    close = np.vstack([test["AvgCH"].values, test["AvgCD"].values, test["AvgCA"].values]).T
    res["betting"] = {
        "avg": {str(e): simulate(p_both, yte, avg, e, close) for e in EDGES},
        "tw": {str(e): simulate(p_both, yte, avg * TW_FACTOR, e) for e in EDGES},
        "max": {str(e): simulate(p_both, yte, mx, e) for e in EDGES},
        "market_only_avg": simulate(p_mkt, yte, avg, 0.0),
    }
    # 每季、每個聯賽拆開看模型 vs 市場
    res["by_league"] = {}
    for d, idx in test.groupby("div").indices.items():
        res["by_league"][DIV_LEAGUE[d]] = {"n": int(len(idx)), "market": round(logloss(p_mkt[idx], yte[idx]), 4),
                                          "model": round(logloss(p_both[idx], yte[idx]), 4)}
    # 給看板用的模型參數（看板不用裝 sklearn，直接用這些數字算）＋目前每隊的 Elo
    # 看板用「全部已完賽比賽」重新訓練一次（包含測試季），測試季的成績上面已經記下來了
    full = df[(df["h_n"] >= 3) & (df["a_n"] >= 3)]
    sc_f = StandardScaler().fit(full[FINAL])
    m_f = LogisticRegression(C=1.0, max_iter=2000).fit(sc_f.transform(full[FINAL]), full["FTR"].values)
    params = {
        "generated_utc": res["generated_utc"], "features": FINAL, "classes": list(m_f.classes_),
        "mean": sc_f.mean_.round(6).tolist(), "scale": sc_f.scale_.round(6).tolist(),
        "coef": m_f.coef_.round(6).tolist(), "intercept": m_f.intercept_.round(6).tolist(),
        "elo_home": ELO_HOME,
        "elo": {DIV_LEAGUE[d]: {t: round(LAST_ELO[(d, t)], 1) for t in teams} for d, teams in LAST_SEASON_TEAMS.items()},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report_1x2.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "params_1x2.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=1)
    return res


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: r[k] for k in ("train_games", "test_games", "accuracy", "hit_rate", "base_rates")}, ensure_ascii=False, indent=1))
    print(json.dumps(r["betting"], ensure_ascii=False, indent=1))
    print(json.dumps(r["by_league"], ensure_ascii=False))
    print(json.dumps(r["calibration"], ensure_ascii=False))
    print(json.dumps(r["weights"], ensure_ascii=False))
