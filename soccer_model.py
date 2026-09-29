"""
足球第一層模型：獨贏（主／和／客）
============================================
資料：football-data.co.uk 五大聯賽＋各國次級聯賽，2014/15 季到本季（docs/data/soccer/eu/）

做法（每一步都只用「比賽開打前就知道」的資訊，避免偷看答案）：
1. 特徵
   - 市場機率：賠率去掉抽成
   - Elo 強弱分數：每場打完依比分更新；換季時往該級聯賽平均拉回一點
     次級聯賽（英冠、西乙…）一起算，而且同一國家的頂級＋次級放在同一個分數池
     → 升級隊帶著它在次級聯賽的分數上來，不用一律從固定低分開始
   - pi-rating（Constantinou 2013）：每隊一個主場分、一個客場分，單位是「淨勝球」，
     比分差越出乎意料、分數改越多。跟 Elo 看的角度不同（Elo 看勝負、pi 看淨勝球）
   - 近 6 場進失球、射正、積分、休息天數（只給「全部特徵」對照組用；驗證季上加進去反而變差）
2. 兩個模型，差在「餵進去的賠率是什麼時候的」：
   - 賽前版：用 football-data 的賽前平均賠率（週二／週五抓，大約開賽前 1–3 天）訓練
     → 看板在歐洲賠率出來、離開賽還久的時候用
   - 臨場版：用收盤賠率（開賽那一刻）訓練
     → 看板在開賽前 3 小時內，用 Action Network 即時共識賠率代入
   越接近開賽的賠率越準（傷兵、先發名單都已經反映），這是最大的準度來源
3. 按時間切：2014/15–2018/19 只拿來暖機（算 Elo／pi）；2019/20 起訓練；2024/25 當驗證季挑特徵、挑參數；
   2025/26＋本季當測試（模型沒看過的比賽），測試季不拿來調任何東西
4. 模擬下注：模型機率 × 賠率 > 1 + 門檻才下，看在歐洲平均賠率、估計的台彩賠率下賺賠

輸出：docs/data/soccer/model/report_1x2.json（看板成績單）、params_1x2.json（看板算機率用）
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
SECOND_DIV = {"E1": "E0", "SP2": "SP1", "I2": "I1", "D2": "D1", "F2": "F1"}   # 次級 → 同國頂級
COUNTRY = {d: d[:-1] for d in list(DIV_LEAGUE) + list(SECOND_DIV)}              # E0/E1 → E
VAL_SEASON = "2425"
# 訓練只用 2019/20 起：football-data 從這季開始改用現在這套「各家平均」賠率；
# 更早的是另一個來源（Betbrain），驗證季上拿來訓練反而變差。更早的比賽只拿來算 Elo／pi
TRAIN_FROM = "1920"
TEST_SEASONS = {"2526", "2627"}
FORM_N = 6
ELO_K, ELO_HOME, ELO_START, ELO_REGRESS = 20, 60, 1500, 1 / 3
ELO_GAP = 100            # 第一季暖機時，次級聯賽比頂級低幾分（之後由升降級自然調整）
ELO_NEW = 50             # 從更低級聯賽升上來、第一次出現的隊：比該級平均低幾分
PI_LAMBDA, PI_GAMMA = 0.035, 0.7
PI_GAP, PI_NEW = 0.4, 0.15
TW_FACTOR = 0.90          # 台彩賠率大約是歐洲平均的 9 成（之後用你記的台彩足球賠率校正）
EDGES = [0.0, 0.02, 0.05, 0.08]
OUTCOMES = ["H", "D", "A"]
# 2019/20 以前的欄位名稱（Betbrain）→ 新名稱
OLD_COLS = {"BbAvH": "AvgH", "BbAvD": "AvgD", "BbAvA": "AvgA", "BbMxH": "MaxH", "BbMxD": "MaxD", "BbMxA": "MaxA",
            "BbAv>2.5": "Avg>2.5", "BbAv<2.5": "Avg<2.5", "BbAHh": "AHh", "BbAvAHH": "AvgAHH", "BbAvAHA": "AvgAHA"}
NUM_COLS = ["FTHG", "FTAG", "HS", "AS", "HST", "AST", "HC", "AC", "AvgH", "AvgD", "AvgA", "MaxH", "MaxD", "MaxA",
            "AvgCH", "AvgCD", "AvgCA", "PSCH", "PSCD", "PSCA", "PSH", "PSD", "PSA", "BFEH", "BFED", "BFEA"]
PRE_FEATURES = ["lm_h", "lm_d", "elo_diff", "pi_diff"]
CLOSE_FEATURES = ["lc_h", "lc_d", "elo_diff", "pi_diff"]


# ---------------- 讀資料 ----------------
def load():
    frames = []
    for path in sorted(glob.glob(os.path.join(EU_DIR, "*.csv"))):
        div, season = os.path.basename(path)[:-4].split("_")
        if div not in COUNTRY:
            continue
        df = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="ignore", on_bad_lines="skip")
        df = df.dropna(subset=["HomeTeam", "AwayTeam", "FTR", "FTHG", "FTAG"])
        if df.empty:
            continue
        for old, new in OLD_COLS.items():
            if old in df.columns:
                df[new] = df[new].fillna(df[old]) if new in df.columns else df[old]
        # 各季日期格式不同（dd/mm/yy、dd/mm/yyyy），每個檔案自己解析
        df["date"] = pd.to_datetime(df["Date"], dayfirst=True, format="mixed", errors="coerce")
        df["div"], df["season"], df["top"] = div, season, div in DIV_LEAGUE
        frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    df = df.dropna(subset=["date"]).sort_values(["date", "div"]).reset_index(drop=True)
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce") if c in df.columns else np.nan
    # 收盤：2019/20 起有各家平均收盤；更早只有 Pinnacle 收盤
    for s in "HDA":
        df[f"C{s}"] = df[f"AvgC{s}"].fillna(df[f"PSC{s}"])
    return df


def devig(h, d, a):
    inv = np.vstack([1 / h, 1 / d, 1 / a]).T
    return inv / inv.sum(axis=1, keepdims=True)


def pi_expected(r):
    """pi 分數 → 預期淨勝球"""
    return (10 ** (abs(r) / 3) - 1) * (1 if r >= 0 else -1)


# ---------------- 特徵（只用開賽前的資訊）----------------
def build_features(df):
    """Elo 和 pi-rating：同一國家的頂級＋次級聯賽放在同一個分數池"""
    elo, pi, hist, last_date = {}, {}, {}, {}
    team_div = {}                 # 每隊最近一次踢的是哪個級別
    last_seen = {}                # 每隊最近一次出賽是哪一季
    cur_season, prev_season = {}, {}   # 每個國家目前是哪一季、上一季
    div_start = {}                # 每個級別資料從哪一季開始
    feats = []

    def div_mean(table, div, default, idx=None):
        """某級別的平均分：只算最近兩季有出賽的隊（掉到第三級以下、不再出現的隊不算）"""
        c = COUNTRY[div]
        ok = (cur_season.get(c), prev_season.get(c))
        vals = [(v if idx is None else v[idx]) for k, v in table.items()
                if team_div.get(k) == div and last_seen.get(k) in ok]
        return sum(vals) / len(vals) if vals else default

    for r in df.itertuples(index=False):
        div, season, c = r.div, r.season, COUNTRY[r.div]
        top_div = div if div in DIV_LEAGUE else SECOND_DIV[div]
        # 換季：Elo 往各隊「上季所在級別」的平均拉回
        if cur_season.get(c) != season:
            if c in cur_season:
                means = {d: div_mean(elo, d, ELO_START) for d in COUNTRY if COUNTRY[d] == c}
                for k in [k for k in elo if k[0] == c]:
                    m = means.get(team_div.get(k), ELO_START)
                    elo[k] += (m - elo[k]) * ELO_REGRESS
                prev_season[c] = cur_season[c]
            cur_season[c] = season
        row = {}
        for side, team in (("h", r.HomeTeam), ("a", r.AwayTeam)):
            k = (c, team)
            if k not in elo:
                base_e = ELO_START if div == top_div else ELO_START - ELO_GAP
                base_p = 0.0 if div == top_div else -PI_GAP
                seen = div_start.setdefault(div, season) != season   # 這個級別第一季（暖機）大家都是新隊，不扣分
                elo[k] = div_mean(elo, div, base_e) - (ELO_NEW if seen else 0)
                pm = (div_mean(pi, div, base_p, 0), div_mean(pi, div, base_p, 1))
                pi[k] = [pm[0] - (PI_NEW if seen else 0), pm[1] - (PI_NEW if seen else 0)]
            team_div[k], last_seen[k] = div, season
            hs = hist.get(k, [])[-FORM_N:]
            n = len(hs)
            row[f"{side}_elo"] = elo[k]
            row[f"{side}_n"] = n
            for i, nm in enumerate(["gf", "ga", "sotf", "sota", "pts"]):
                vals = [x[i] for x in hs if x[i] == x[i]]
                row[f"{side}_{nm}"] = sum(vals) / len(vals) if vals else np.nan
            ld = last_date.get(k)
            row[f"{side}_rest"] = min((r.date - ld).days, 14) if ld is not None else 14
        kh, ka = (c, r.HomeTeam), (c, r.AwayTeam)
        row["pi_h"], row["pi_a"] = pi[kh][0], pi[ka][1]
        feats.append(row)
        # 比賽打完：更新 Elo
        exp_h = 1 / (1 + 10 ** ((elo[ka] - elo[kh] - ELO_HOME) / 400))
        res_h = 1.0 if r.FTR == "H" else 0.5 if r.FTR == "D" else 0.0
        gd = abs(r.FTHG - r.FTAG)
        mult = 1 if gd <= 1 else 1.5 if gd == 2 else (11 + gd) / 8
        delta = ELO_K * mult * (res_h - exp_h)
        elo[kh] += delta
        elo[ka] -= delta
        # 更新 pi-rating（主隊的主場分、客隊的客場分直接改，另一個分數跟著改一部分）
        pred = pi_expected(pi[kh][0]) - pi_expected(pi[ka][1])
        obs = r.FTHG - r.FTAG
        psi = 3 * math.log10(1 + abs(obs - pred))
        ph = psi if obs > pred else -psi
        dh, da = ph * PI_LAMBDA, -ph * PI_LAMBDA
        pi[kh][0] += dh
        pi[kh][1] += dh * PI_GAMMA
        pi[ka][1] += da
        pi[ka][0] += da * PI_GAMMA
        # 近況
        p_h = 3 if r.FTR == "H" else 1 if r.FTR == "D" else 0
        p_a = 3 if r.FTR == "A" else 1 if r.FTR == "D" else 0
        hist.setdefault(kh, []).append((r.FTHG, r.FTAG, r.HST, r.AST, p_h))
        hist.setdefault(ka, []).append((r.FTAG, r.FTHG, r.AST, r.HST, p_a))
        last_date[kh] = last_date[ka] = r.date
    global LAST_ELO, LAST_PI, LAST_TEAM_DIV, LAST_SEEN
    LAST_ELO, LAST_PI, LAST_TEAM_DIV, LAST_SEEN = elo, pi, team_div, last_seen
    f = pd.DataFrame(feats)
    out = pd.concat([df.reset_index(drop=True), f], axis=1)
    out["elo_diff"] = out["h_elo"] + ELO_HOME - out["a_elo"]
    out["pi_diff"] = out["pi_h"] - out["pi_a"]
    for nm in ["gf", "ga", "sotf", "sota", "pts"]:
        out[f"d_{nm}"] = out[f"h_{nm}"] - out[f"a_{nm}"]
    out["d_rest"] = out["h_rest"] - out["a_rest"]
    return out


def add_market(df):
    mk = devig(df["AvgH"].values, df["AvgD"].values, df["AvgA"].values)
    df["m_h"], df["m_d"], df["m_a"] = mk[:, 0], mk[:, 1], mk[:, 2]
    df["lm_h"] = np.log(df["m_h"] / df["m_a"])
    df["lm_d"] = np.log(df["m_d"] / df["m_a"])
    ck = devig(df["CH"].values, df["CD"].values, df["CA"].values)
    df["c_h"], df["c_d"], df["c_a"] = ck[:, 0], ck[:, 1], ck[:, 2]
    df["lc_h"] = np.log(df["c_h"] / df["c_a"])
    df["lc_d"] = np.log(df["c_d"] / df["c_a"])
    return df


def prepare():
    df = add_market(build_features(load()))
    team_cols = ["elo_diff", "pi_diff", "d_gf", "d_ga", "d_sotf", "d_sota", "d_pts", "d_rest", "h_n", "a_n"]
    for c in team_cols:
        df[c] = df[c].fillna(0)
    for lg in DIV_LEAGUE:
        df[f"lg_{lg}"] = (df["div"] == lg).astype(float)
    first = df["season"].min()
    # 只用頂級聯賽的比賽訓練／測試；最早一季只拿來暖機
    df = df[df["top"] & (df["season"] != first)].copy()
    return df, team_cols, [f"lg_{lg}" for lg in DIV_LEAGUE]


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
           # 運氣範圍：投報率的標準誤（±2 倍以內都可能只是運氣）
           "se": round(float(pl.std(ddof=1) / math.sqrt(n) * 100), 1) if n > 1 else None,
           "avg_odds": round(float(o.mean()), 2),
           "pick_share": {k: int(((best == i) & pick).sum()) for i, k in enumerate(["home", "draw", "away"])}}
    if close is not None:
        c = close[np.arange(len(y)), best][pick]
        ok = ~np.isnan(c)
        if ok.any():
            res["clv"] = round(float(np.mean(o[ok] / c[ok] - 1) * 100), 2)
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


def fitter(train, cols, C=1.0):
    tr = train.dropna(subset=cols)
    sc = StandardScaler().fit(tr[cols])
    m = LogisticRegression(C=C, max_iter=3000).fit(sc.transform(tr[cols]), tr["FTR"].values)
    order = [list(m.classes_).index(o) for o in OUTCOMES]
    return (lambda d: m.predict_proba(sc.transform(d[cols]))[:, order]), m, sc


def export(m, sc, cols):
    return {"features": cols, "classes": list(m.classes_), "mean": sc.mean_.round(6).tolist(),
            "scale": sc.scale_.round(6).tolist(), "coef": m.coef_.round(6).tolist(), "intercept": m.intercept_.round(6).tolist()}


def acc(p, y):
    return {"logloss": round(logloss(p, y), 4), "brier": round(brier(p, y), 4)}


# ---------------- 主程式 ----------------
def run():
    df, team_cols, lg_cols = prepare()
    enough = (df["h_n"] >= 3) & (df["a_n"] >= 3)
    recent = df["season"] >= TRAIN_FROM
    train = df[~df["season"].isin(TEST_SEASONS) & enough & recent]
    test = df[df["season"].isin(TEST_SEASONS)].dropna(subset=["m_h"])
    yte = test["FTR"].values

    p_mkt = test[["m_h", "m_d", "m_a"]].values
    f_team, _, _ = fitter(train.dropna(subset=["m_h"]), team_cols + lg_cols)
    f_pre, m_pre, _ = fitter(train, PRE_FEATURES)
    f_old, _, _ = fitter(train, ["lm_h", "lm_d", "elo_diff"])         # 上一版（只有 Elo）對照
    f_recal, _, _ = fitter(train, ["lm_h", "lm_d"])                   # 只把莊家賠率重新校正
    f_all, _, _ = fitter(train, ["lm_h", "lm_d"] + team_cols + lg_cols)
    p_team, p_pre, p_old, p_recal, p_all = f_team(test), f_pre(test), f_old(test), f_recal(test), f_all(test)

    # 臨場版：收盤賠率＋Elo＋pi（跟收盤賠率本身比）
    tc = test.dropna(subset=["c_h"])
    f_close, m_close, _ = fitter(train.dropna(subset=["c_h"]), CLOSE_FEATURES)
    p_close_mkt = tc[["c_h", "c_d", "c_a"]].values
    p_close_model = f_close(tc)
    yc = tc["FTR"].values

    res = {
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "train_games": int(len(train)), "test_games": int(len(test)),
        "train_seasons": sorted(set(train["season"])), "test_seasons": sorted(set(test["season"])),
        "base_rates": {k: round(float((df["FTR"] == k).mean()) * 100, 1) for k in OUTCOMES},
        "base_rates_by_league": {DIV_LEAGUE[d]: {k: round(float((g["FTR"] == k).mean()) * 100, 1) for k in OUTCOMES}
                                 for d, g in df.groupby("div")},
        "accuracy": {
            "market": acc(p_mkt, yte),
            "team_only": acc(p_team, yte),
            "model": acc(p_pre, yte),
            "model_v1": acc(p_old, yte),
            "market_recal": acc(p_recal, yte),
            "all_features": acc(p_all, yte),
            "closing": {**acc(p_close_mkt, yc), "n": int(len(tc))},
            "model_close": {**acc(p_close_model, yc), "n": int(len(tc))},
            "uniform": {"logloss": round(math.log(3), 4)},
        },
        "hit_rate": {k: round(float(np.mean(np.array(OUTCOMES)[p.argmax(1)] == yte)) * 100, 1)
                     for k, p in (("market", p_mkt), ("team_only", p_team), ("model", p_pre))},
        "calibration": calibration(p_pre, yte),
        "calibration_close": calibration(p_close_model, yc),
        "features": PRE_FEATURES, "features_close": CLOSE_FEATURES,
        "weights": {c: round(float(w), 3) for c, w in zip(PRE_FEATURES, m_pre.coef_[list(m_pre.classes_).index("H")])},
        "settings": {"elo_k": ELO_K, "elo_home": ELO_HOME, "elo_regress": round(ELO_REGRESS, 3), "elo_gap": ELO_GAP,
                     "history_from": sorted(set(load_seasons()))[0], "second_divisions": sorted(SECOND_DIV)},
    }
    avg = test[["AvgH", "AvgD", "AvgA"]].values
    mx = test[["MaxH", "MaxD", "MaxA"]].values
    close = np.vstack([test["AvgCH"].values, test["AvgCD"].values, test["AvgCA"].values]).T
    res["betting"] = {
        "avg": {str(e): simulate(p_pre, yte, avg, e, close) for e in EDGES},
        "tw": {str(e): simulate(p_pre, yte, avg * TW_FACTOR, e) for e in EDGES},
        "max": {str(e): simulate(p_pre, yte, mx, e) for e in EDGES},
        "market_only_avg": simulate(p_mkt, yte, avg, 0.0),
        "close_avg": {str(e): simulate(p_close_model, yc, tc[["AvgCH", "AvgCD", "AvgCA"]].values, e) for e in EDGES},
        "close_tw": {str(e): simulate(p_close_model, yc, tc[["AvgCH", "AvgCD", "AvgCA"]].values * TW_FACTOR, e) for e in EDGES},
    }
    res["by_league"] = {}
    for d, idx in test.groupby("div").indices.items():
        res["by_league"][DIV_LEAGUE[d]] = {"n": int(len(idx)), "market": round(logloss(p_mkt[idx], yte[idx]), 4),
                                          "model": round(logloss(p_pre[idx], yte[idx]), 4)}

    # 給看板用的參數：用全部已完賽比賽（包含測試季）重新訓練；測試季成績上面已經記下來了
    full = df[enough & recent]
    _, m_fp, sc_fp = fitter(full, PRE_FEATURES)
    _, m_fc, sc_fc = fitter(full.dropna(subset=["c_h"]), CLOSE_FEATURES)
    # 每個國家：最近一季有出賽的隊（頂級＋次級都放，開季前升級隊也查得到）
    latest = {}
    for (c, _), sn in LAST_SEEN.items():
        latest[c] = max(latest.get(c, sn), sn)
    top_of = {COUNTRY[d]: lg for d, lg in DIV_LEAGUE.items()}
    cur = {}
    for k, sn in LAST_SEEN.items():
        if sn == latest[k[0]]:
            cur.setdefault(top_of[k[0]], []).append(k)
    params = {
        "generated_utc": res["generated_utc"], "elo_home": ELO_HOME,
        "pre": export(m_fp, sc_fp, PRE_FEATURES), "close": export(m_fc, sc_fc, CLOSE_FEATURES),
        "elo": {lg: {t: round(LAST_ELO[(c, t)], 1) for c, t in ks} for lg, ks in cur.items()},
        "pi": {lg: {t: [round(v, 4) for v in LAST_PI[(c, t)]] for c, t in ks} for lg, ks in cur.items()},
        "level": {lg: {t: (1 if LAST_TEAM_DIV[(c, t)] in DIV_LEAGUE else 2) for c, t in ks} for lg, ks in cur.items()},
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(os.path.join(OUT_DIR, "report_1x2.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT_DIR, "params_1x2.json"), "w", encoding="utf-8") as f:
        json.dump(params, f, ensure_ascii=False, indent=1)
    return res


def load_seasons():
    return [os.path.basename(p)[:-4].split("_")[1] for p in glob.glob(os.path.join(EU_DIR, "*.csv"))]


if __name__ == "__main__":
    r = run()
    print(json.dumps({k: r[k] for k in ("train_games", "test_games", "accuracy", "hit_rate")}, ensure_ascii=False, indent=1))
    print(json.dumps(r["betting"], ensure_ascii=False, indent=1))
    print(json.dumps(r["by_league"], ensure_ascii=False))
    print(json.dumps(r["calibration"], ensure_ascii=False))
    print(json.dumps(r["weights"], ensure_ascii=False))
