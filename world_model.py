"""
全球足球模型（五大聯賽以外的賽事用；五大聯賽還是用原本的模型一 soccer_model.py，不動）
================================================================
1. 強弱分數（Elo，照時間順序一場一場更新，跟 eloratings.net 同一套算法）：
   - 俱樂部：ESPN 所有賽事（各國聯賽、盃賽、歐冠／歐霸／歐協聯…）一起算。ESPN 的球隊編號在所有賽事都一樣，
     歐洲賽事把各國聯賽串起來，所以「葡超第 1 名 vs 英超中段」也比得出來。
     第一次出現的球隊：用它所在聯賽目前的平均分數再扣一點（升級隊通常比較弱）；沒有聯賽資料的（小國球隊）從 1350 開始。
   - 國家隊：martj42/international_results（CC0，1872 年起每一場國際賽），世界盃 K=60、洲際盃 50、資格賽 40、其他盃賽 30、友誼賽 20。
   - 進球差越大，分數變動越多；主場 +主場優勢（中立場地沒有）。
2. 主／和／客機率（跟原本模型一同一種做法）：多類別羅吉斯迴歸，輸入＝市場賠率（去抽水後的兩個對數比）＋Elo 差。
   用五大聯賽＋次級聯賽的歷史比賽學（football-data 的 Pinnacle 賽前賠率），學到的係數套到所有賽事。
   國家隊沒有歷史賠率，用同一組係數（Elo 的刻度一樣）。
3. 驗證：照時間順序，最後兩季（2023/24、2024/25）只拿來考。另外單獨看「只用 Elo」在國家隊比賽準不準。
輸出：docs/data/soccer/model/world_params.json（看板算機率用）、world_report.json（成績單）
用法：python3 world_model.py
"""
import csv
import glob
import json
import math
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np
from sklearn.linear_model import LogisticRegression

ROOT = os.path.dirname(os.path.abspath(__file__))
W = os.path.join(ROOT, "docs", "data", "soccer", "world")
EU = os.path.join(ROOT, "docs", "data", "soccer", "eu")
OUT = os.path.join(ROOT, "docs", "data", "soccer", "model")
LEAGUE_SLUG = {"E0": "eng.1", "E1": "eng.2", "SP1": "esp.1", "SP2": "esp.2", "I1": "ita.1", "I2": "ita.2",
               "D1": "ger.1", "D2": "ger.2", "F1": "fra.1", "F2": "fra.2"}
CUP_LIKE = ("uefa.", "eng.fa", "eng.league_cup", "esp.copa", "ita.coppa", "ger.dfb", "fra.coupe", "conmebol.")
HFA = 65.0            # 俱樂部主場優勢（Elo 分）
HFA_N = 100.0         # 國家隊主場優勢
TEST_FROM = datetime(2023, 7, 1)


def gd_mult(d):
    d = abs(d)
    return 1.0 if d <= 1 else 1.5 if d == 2 else (11 + d) / 8


def expect(dr):
    return 1 / (10 ** (-dr / 400) + 1)


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


# ───────── 俱樂部 ─────────
def load_club():
    rows = []
    for f in glob.glob(os.path.join(W, "espn_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8")):
            hg, ag = to_int(r["hg"]), to_int(r["ag"])
            if hg is None or ag is None or not r["home_id"] or not r["away_id"]:
                continue
            rows.append({"date": r["date"], "comp": r["comp"], "event": r["event"], "h": r["home_id"], "a": r["away_id"],
                         "hn": r["home"], "an": r["away"], "hg": hg, "ag": ag, "neutral": r.get("neutral") == "1"})
    seen, out = set(), []
    for r in sorted(rows, key=lambda r: (r["date"], r["event"])):
        if r["event"] in seen:
            continue
        seen.add(r["event"])
        out.append(r)
    return out


def club_elo(rows):
    """回傳：每場賽前的 (主分, 客分)，以及最後的分數表"""
    R, name, home_lg, last_seen = {}, {}, {}, {}
    lg_sum = defaultdict(lambda: [0.0, 0])          # 聯賽 → 目前所有隊分數總和
    pre = {}
    for r in rows:
        is_cup = r["comp"].startswith(CUP_LIKE)
        for side in ("h", "a"):
            t = r[side]
            if t not in R:
                if not is_cup and lg_sum[r["comp"]][1] >= 6:
                    s, n = lg_sum[r["comp"]]
                    R[t] = s / n - 40
                else:
                    R[t] = 1350.0 if is_cup else 1450.0
                if not is_cup:
                    home_lg[t] = r["comp"]
                    lg_sum[r["comp"]][0] += R[t]
                    lg_sum[r["comp"]][1] += 1
            elif not is_cup and home_lg.get(t) != r["comp"]:      # 換聯賽（升降級）
                old = home_lg.get(t)
                if old:
                    lg_sum[old][0] -= R[t]
                    lg_sum[old][1] -= 1
                home_lg[t] = r["comp"]
                lg_sum[r["comp"]][0] += R[t]
                lg_sum[r["comp"]][1] += 1
            name[t] = r["hn"] if side == "h" else r["an"]
            last_seen[t] = r["date"]
        rh, ra = R[r["h"]], R[r["a"]]
        pre[r["event"]] = (rh, ra)
        dr = rh + (0 if r["neutral"] else HFA) - ra
        res = 1.0 if r["hg"] > r["ag"] else 0.5 if r["hg"] == r["ag"] else 0.0
        k = (30 if is_cup else 20) * gd_mult(r["hg"] - r["ag"])
        ch = k * (res - expect(dr))
        R[r["h"]] += ch
        R[r["a"]] -= ch
        for t, c in ((r["h"], ch), (r["a"], -ch)):
            lg = home_lg.get(t)
            if lg:
                lg_sum[lg][0] += c
    return pre, R, name, home_lg, last_seen


# ───────── 國家隊 ─────────
def intl_k(tour):
    t = tour.lower()
    if t == "fifa world cup":
        return 60
    if "qualification" in t:
        return 40
    if t in ("uefa euro", "copa américa", "copa america", "african cup of nations", "afc asian cup", "gold cup", "confederations cup"):
        return 50
    if "nations league" in t:
        return 40
    if t == "friendly":
        return 20
    return 30


def nat_elo():
    R, last = defaultdict(lambda: 1500.0), {}
    rows = []
    for r in csv.DictReader(open(os.path.join(W, "intl_results.csv"), encoding="utf-8")):
        hg, ag = to_int(r["home_score"]), to_int(r["away_score"])
        if hg is None or ag is None:
            continue
        neutral = r["neutral"].upper() == "TRUE"
        h, a = r["home_team"], r["away_team"]
        rh, ra = R[h], R[a]
        dr = rh + (0 if neutral else HFA_N) - ra
        if r["date"] >= "2000-01-01":
            rows.append({"date": r["date"], "dr": dr, "y": 0 if hg > ag else 1 if hg == ag else 2, "tour": r["tournament"], "neutral": neutral})
        res = 1.0 if hg > ag else 0.5 if hg == ag else 0.0
        ch = intl_k(r["tournament"]) * gd_mult(hg - ag) * (res - expect(dr))
        R[h] += ch
        R[a] -= ch
        last[h] = last[a] = r["date"]
    return rows, dict(R), last


# ───────── 對 football-data（歷史賠率）─────────
def fd_rows():
    out = []
    for f in glob.glob(os.path.join(EU, "*.csv")):
        div = os.path.basename(f).split("_")[0]
        if div not in LEAGUE_SLUG:
            continue
        for r in csv.DictReader(open(f, encoding="latin-1")):
            try:
                d, m, y = r["Date"].split("/")
                y = int(y) + (2000 if len(y) == 2 else 0)
                dt = datetime(y, int(m), int(d))
                hg, ag = int(r["FTHG"]), int(r["FTAG"])
                ps = [float(r[k]) for k in ("PSH", "PSD", "PSA")]
            except (ValueError, KeyError, TypeError):
                continue
            if any(o <= 1 for o in ps):
                continue
            out.append({"div": div, "dt": dt, "home": r["HomeTeam"], "away": r["AwayTeam"], "hg": hg, "ag": ag, "ps": ps})
    return out


def link_fd(fd, rows):
    """football-data 一場 → ESPN 一場：同聯賽、日期差 ≤ 1 天、比分一樣，先投票對隊名再配對"""
    from datetime import timedelta
    idx = defaultdict(list)
    for r in rows:
        idx[(r["comp"], r["date"])].append(r)
    votes = defaultdict(Counter)
    for f in fd:
        slug = LEAGUE_SLUG[f["div"]]
        c = [r for dd in (-1, 0, 1) for r in idx.get((slug, (f["dt"] + timedelta(days=dd)).strftime("%Y-%m-%d")), [])
             if r["hg"] == f["hg"] and r["ag"] == f["ag"]]
        if len(c) == 1:
            votes[(f["div"], f["home"])][c[0]["h"]] += 1
            votes[(f["div"], f["away"])][c[0]["a"]] += 1
    tm = {k: v.most_common(1)[0][0] for k, v in votes.items() if v.most_common(1)[0][1] >= 2}
    out = []
    for f in fd:
        h, a = tm.get((f["div"], f["home"])), tm.get((f["div"], f["away"]))
        if not h or not a:
            continue
        slug = LEAGUE_SLUG[f["div"]]
        c = [r for dd in (-1, 0, 1) for r in idx.get((slug, (f["dt"] + timedelta(days=dd)).strftime("%Y-%m-%d")), []) if r["h"] == h and r["a"] == a]
        if len(c) == 1:
            out.append((f, c[0]))
    return out


def feats(odds, dr):
    inv = [1 / o for o in odds]
    s = sum(inv)
    ph, pd_, pa = (x / s for x in inv)
    return [math.log(ph / pa), math.log(pd_ / pa), dr / 100.0], [ph, pd_, pa]


def ll(p, y):
    return -math.log(max(p[y], 1e-9))


def main():
    rows = load_club()
    pre, R, name, home_lg, last_seen = club_elo(rows)
    print(f"俱樂部：{len(rows)} 場、{len(R)} 隊", flush=True)
    pairs = link_fd(fd_rows(), rows)
    print(f"對到 football-data（有 Pinnacle 賠率）：{len(pairs)} 場", flush=True)
    X, Y, M, T = [], [], [], []
    for f, r in pairs:
        rh, ra = pre[r["event"]]
        x, m = feats(f["ps"], rh + HFA - ra)
        X.append(x)
        Y.append(0 if f["hg"] > f["ag"] else 1 if f["hg"] == f["ag"] else 2)
        M.append(m)
        T.append(f["dt"])
    X, Y, M, T = np.array(X), np.array(Y), np.array(M), np.array(T)
    warm = T >= datetime(2016, 7, 1)          # 前兩年 Elo 還在熱身，不拿來學
    tr, te = warm & (T < TEST_FROM), T >= TEST_FROM
    mu, sd = X[tr].mean(0), X[tr].std(0) + 1e-9
    lr = LogisticRegression(C=1.0, max_iter=3000).fit((X[tr] - mu) / sd, Y[tr])
    P = lr.predict_proba((X[te] - mu) / sd)
    # 只用 Elo（不看賠率）的版本，看 Elo 本身準不準
    lr_e = LogisticRegression(C=1.0, max_iter=3000).fit(X[tr][:, 2:], Y[tr])
    Pe = lr_e.predict_proba(X[te][:, 2:])
    rep = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "club_games": len(rows), "club_teams": len(R),
           "fd_linked": len(pairs), "train_games": int(tr.sum()), "test_games": int(te.sum()),
           "club_test": {"market": round(float(np.mean([ll(m, y) for m, y in zip(M[te], Y[te])])), 4),
                         "model": round(float(np.mean([ll(p, y) for p, y in zip(P, Y[te])])), 4),
                         "elo_only": round(float(np.mean([ll(p, y) for p, y in zip(Pe, Y[te])])), 4),
                         "base": round(float(np.mean([ll(np.bincount(Y[tr], minlength=3) / tr.sum(), y) for y in Y[te]])), 4)},
           "coef": {"features": ["主客市場對數比", "和客市場對數比", "Elo 差/100"], "classes": ["H", "D", "A"],
                    "coef": lr.coef_.round(4).tolist()}}
    # 國家隊：只用 Elo（沒有歷史賠率）
    nrows, NR, nlast = nat_elo()
    ntr = [r for r in nrows if r["date"] < "2020-01-01"]
    nte = [r for r in nrows if r["date"] >= "2022-01-01"]
    Xn = lambda rs: np.array([[r["dr"] / 100.0] for r in rs])
    lr_n = LogisticRegression(C=1.0, max_iter=3000).fit(Xn(ntr), [r["y"] for r in ntr])
    Pn = lr_n.predict_proba(Xn(nte))
    base_n = np.bincount([r["y"] for r in ntr], minlength=3) / len(ntr)
    rep["national_test"] = {"games": len(nte), "elo_only": round(float(np.mean([ll(p, r["y"]) for p, r in zip(Pn, nte)])), 4),
                            "base": round(float(np.mean([ll(base_n, r["y"]) for r in nte])), 4),
                            "hit": round(float(np.mean([int(np.argmax(p) == r["y"]) for p, r in zip(Pn, nte)])) * 100, 1)}
    # 最終參數：用全部資料重學一次（看板用）
    lr_all = LogisticRegression(C=1.0, max_iter=3000).fit((X[warm] - mu) / sd, Y[warm])
    lr_n_all = LogisticRegression(C=1.0, max_iter=3000).fit(Xn(nrows), [r["y"] for r in nrows])
    cut = lambda d: d >= "2023-01-01"
    params = {"generated_utc": rep["generated_utc"], "hfa": HFA, "hfa_n": HFA_N,
              "mix": {"features": ["lm_h", "lm_d", "elo_d"], "mean": mu.round(6).tolist(), "scale": sd.round(6).tolist(),
                      "coef": lr_all.coef_.round(6).tolist(), "intercept": lr_all.intercept_.round(6).tolist(),
                      "classes": [["H", "D", "A"][int(c)] for c in lr_all.classes_]},
              "elo_only_n": {"coef": lr_n_all.coef_.round(6).tolist(), "intercept": lr_n_all.intercept_.round(6).tolist()},
              "clubs": {t: {"r": round(R[t], 1), "n": name[t], "lg": home_lg.get(t, "")} for t in R if cut(last_seen[t])},
              "nations": {t: round(v, 1) for t, v in NR.items() if cut(nlast.get(t, ""))}}
    os.makedirs(OUT, exist_ok=True)
    json.dump(params, open(os.path.join(OUT, "world_params.json"), "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    json.dump(rep, open(os.path.join(OUT, "world_report.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    top = sorted(params["clubs"].items(), key=lambda kv: -kv[1]["r"])[:15]
    print("俱樂部前 15：", [(v["n"], v["r"], v["lg"]) for k, v in top])
    print("國家隊前 10：", sorted(params["nations"].items(), key=lambda kv: -kv[1])[:10])


if __name__ == "__main__":
    main()
