"""
職業版・第 1 階段：足球比分模型（不看任何賠率）
================================================================
做法（Dixon–Coles 類型，職業團隊做足球最常見的起點）：
- 每隊一個「攻擊力」、一個「防守力」，加上每個聯賽的主場優勢和平均進球數。
- 預測：主隊進球數 ~ Poisson(λ主)、客隊 ~ Poisson(λ客)，
  log λ主 = 聯賽平均 + 主場 + 主隊攻擊 − 客隊防守；log λ客 = 聯賽平均 + 客隊攻擊 − 主隊防守。
  再用 ρ 修正 0:0、1:0、0:1、1:1 這幾個低比分（實際上和局比單純 Poisson 多）。
- 越近的比賽越重要（半衰期 half-life 天）；隊伍評分往 0（聯賽平均）拉一點，避免場數少的時候亂跳。
- 同一個國家的一、二級聯賽一起算：升降級的球隊評分會延續；另外學「剛升級／剛降級／新加入」的平均修正。
- 進球有很多運氣，所以也試「射正次數」：目標＝w × 進球 ＋ (1−w) × 射正換算的進球（w=1 就是只看進球）。

嚴格照時間順序：每週一個截止點，只用截止點以前的比賽訓練，預測接下來 7 天的比賽，一路往前推。
- 2014/15：暖身（只拿來學，不算成績）
- 2015/16–2019/20：只當訓練資料
- 2020/21–2024/25：驗證（挑設定只能看這裡）
- 2025/26–2026/27：最後的考試，挑好設定之後只跑一次（--final-test），結果寫進 test_log.json

用法：
  python3 -m pro.soccer_model --tune          在驗證季比較各種設定
  python3 -m pro.soccer_model --final-test    用挑好的設定，考最後兩季一次
輸出：docs/data/pro/soccer_preds_<設定>.csv.gz（每場預測＋各家收盤，查帳用）、docs/data/pro/soccer_report.json
"""
import csv
import glob
import gzip
import json
import math
import os
import sys
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.stats import poisson

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EU = os.path.join(ROOT, "docs", "data", "soccer", "eu")
OUT = os.path.join(ROOT, "docs", "data", "pro")
COUNTRIES = {"英格蘭": ("E0", "E1"), "西班牙": ("SP1", "SP2"), "義大利": ("I1", "I2"), "德國": ("D1", "D2"), "法國": ("F1", "F2")}
DIV_ZH = {"E0": "英超", "E1": "英冠", "SP1": "西甲", "SP2": "西乙", "I1": "義甲", "I2": "義乙", "D1": "德甲", "D2": "德乙", "F1": "法甲", "F2": "法乙"}
START_PRED = datetime(2015, 7, 1)
VALID = (datetime(2020, 7, 1), datetime(2025, 7, 1))
TEST = (datetime(2025, 7, 1), datetime(2027, 7, 1))
MAXG = 10


def num(v):
    try:
        x = float(v)
        return x if math.isfinite(x) and x > 0 else None
    except (TypeError, ValueError):
        return None


def flt(v):
    """可以是 0 或負數（射正次數、讓分線）"""
    try:
        x = float(v)
        return x if math.isfinite(x) else None
    except (TypeError, ValueError):
        return None


def parse_dt(d, t):
    dd, mm, yy = d.split("/")
    y = int(yy) + (2000 if len(yy) == 2 else 0)
    hh, mi = (t.split(":") if t and ":" in t else ("15", "00"))
    return datetime(y, int(mm), int(dd), int(hh), int(mi))


# ───────── 讀資料 ─────────
def load():
    rows = []
    for f in sorted(glob.glob(os.path.join(EU, "*.csv"))):
        div, ss = os.path.basename(f)[:-4].split("_")
        with open(f, encoding="latin-1") as fh:
            for r in csv.DictReader(fh):
                if not r.get("HomeTeam") or r.get("FTR") not in ("H", "D", "A"):
                    continue
                try:
                    dt = parse_dt(r["Date"], r.get("Time"))
                    hg, ag = int(r["FTHG"]), int(r["FTAG"])
                except (ValueError, KeyError):
                    continue
                g = lambda *ks: tuple(num(r.get(k)) for k in ks)
                rows.append({
                    "div": div, "season": ss, "dt": dt, "home": r["HomeTeam"].strip(), "away": r["AwayTeam"].strip(),
                    "hg": hg, "ag": ag, "hst": flt(r.get("HST")), "ast": flt(r.get("AST")),
                    "ps": g("PSH", "PSD", "PSA"), "psc": g("PSCH", "PSCD", "PSCA"), "bfc": g("BFECH", "BFECD", "BFECA"),
                    "avg": g("AvgH", "AvgD", "AvgA"), "avgc": g("AvgCH", "AvgCD", "AvgCA"), "b365": g("B365H", "B365D", "B365A"),
                    "ou_pc": g("PC>2.5", "PC<2.5"), "ou_bfc": g("BFEC>2.5", "BFEC<2.5"), "ou_avgc": g("AvgC>2.5", "AvgC<2.5"),
                    "ahc": flt(r.get("AHCh")),
                    "ah_pc": g("PCAHH", "PCAHA"), "ah_bfc": g("BFECAHH", "BFECAHA"),
                })
    rows.sort(key=lambda r: r["dt"])
    return rows


def fair(odds):
    if not odds or any(o is None or o <= 1 for o in odds):
        return None
    inv = [1 / o for o in odds]
    s = sum(inv)
    return [x / s for x in inv]


# ───────── 升降級旗標（每隊每季：這季的級別跟上一季比）─────────
def season_flags(rows):
    order = sorted({r["season"] for r in rows})
    prev = {s: order[i - 1] if i else None for i, s in enumerate(order)}
    tier = {}
    for r in rows:
        lvl = 1 if r["div"] in ("E0", "SP1", "I1", "D1", "F1") else 2
        tier[(r["home"], r["season"])] = lvl
        tier[(r["away"], r["season"])] = lvl
    flags = {}
    for (team, s), lvl in tier.items():
        p = prev[s]
        if p is None:
            flags[(team, s)] = (0, 0, 0)
            continue
        lp = tier.get((team, p))
        if lp is None:
            flags[(team, s)] = (0, 0, 1)        # 新加入（從更低級別上來）
        elif lp > lvl:
            flags[(team, s)] = (1, 0, 0)        # 剛升級
        elif lp < lvl:
            flags[(team, s)] = (0, 1, 0)        # 剛降級
        else:
            flags[(team, s)] = (0, 0, 0)
    return flags


# ───────── 模型 ─────────
class Country:
    def __init__(self, rows, flags, half_life, w_goals, ridge):
        self.rows = rows
        self.divs = sorted({r["div"] for r in rows})
        self.teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
        self.ti = {t: i for i, t in enumerate(self.teams)}
        self.di = {d: i for i, d in enumerate(self.divs)}
        self.hl, self.wg, self.ridge = half_life, w_goals, ridge
        n = len(rows)
        self.t = np.array([(r["dt"] - datetime(2000, 1, 1)).total_seconds() / 86400 for r in rows])
        self.h = np.array([self.ti[r["home"]] for r in rows])
        self.a = np.array([self.ti[r["away"]] for r in rows])
        self.d = np.array([self.di[r["div"]] for r in rows])
        self.hg = np.array([r["hg"] for r in rows], float)
        self.ag = np.array([r["ag"] for r in rows], float)
        self.hst = np.array([r["hst"] if r["hst"] is not None else np.nan for r in rows], float)
        self.ast = np.array([r["ast"] if r["ast"] is not None else np.nan for r in rows], float)
        self.fh = np.array([flags[(r["home"], r["season"])] for r in rows], float)
        self.fa = np.array([flags[(r["away"], r["season"])] for r in rows], float)
        self.T, self.D = len(self.teams), len(self.divs)
        self.x = np.zeros(2 * self.T + 2 * self.D + 6)
        self.x[2 * self.T:2 * self.T + self.D] = math.log(1.35)
        self.x[2 * self.T + self.D:2 * self.T + 2 * self.D] = 0.25
        self.rho = -0.05

    def unpack(self, x):
        T, D = self.T, self.D
        return x[:T], x[T:2 * T], x[2 * T:2 * T + D], x[2 * T + D:2 * T + 2 * D], x[2 * T + 2 * D:2 * T + 2 * D + 3], x[2 * T + 2 * D + 3:]

    def lam(self, x, idx):
        att, dfn, mu, home, aa, ad = self.unpack(x)
        h, a, d = self.h[idx], self.a[idx], self.d[idx]
        fh, fa = self.fh[idx], self.fa[idx]
        lh = mu[d] + home[d] + att[h] + fh @ aa - (dfn[a] + fa @ ad)
        la = mu[d] + att[a] + fa @ aa - (dfn[h] + fh @ ad)
        return np.exp(lh), np.exp(la)

    def targets(self, idx):
        yh, ya = self.hg[idx].copy(), self.ag[idx].copy()
        if self.wg < 1:
            sh, sa = self.hst[idx], self.ast[idx]
            ok = ~np.isnan(sh) & ~np.isnan(sa)
            if ok.sum() > 50:
                k = (yh[ok].sum() + ya[ok].sum()) / max(1.0, sh[ok].sum() + sa[ok].sum())   # 每一次射正大約值幾球
                yh[ok] = self.wg * yh[ok] + (1 - self.wg) * k * sh[ok]
                ya[ok] = self.wg * ya[ok] + (1 - self.wg) * k * sa[ok]
        return yh, ya

    def fit(self, cutoff_t):
        age = cutoff_t - self.t
        idx = np.where((age > 0) & (age < 5 * self.hl) & (age < 4 * 365))[0]
        if len(idx) < 200:
            return False
        w = np.power(0.5, age[idx] / self.hl)
        yh, ya = self.targets(idx)
        T, D = self.T, self.D
        h, a, d = self.h[idx], self.a[idx], self.d[idx]
        fh, fa = self.fh[idx], self.fa[idx]
        r = self.ridge

        def f(x):
            att, dfn, mu, home, aa, ad = self.unpack(x)
            lh = mu[d] + home[d] + att[h] + fh @ aa - (dfn[a] + fa @ ad)
            la = mu[d] + att[a] + fa @ aa - (dfn[h] + fh @ ad)
            eh, ea = np.exp(lh), np.exp(la)
            loss = np.sum(w * (eh - yh * lh + ea - ya * la)) + r * (np.sum(att ** 2) + np.sum(dfn ** 2)) + r * (np.sum(aa ** 2) + np.sum(ad ** 2))
            gh, ga = w * (eh - yh), w * (ea - ya)
            g_att = np.bincount(h, gh, T) + np.bincount(a, ga, T) + 2 * r * att
            g_dfn = -np.bincount(a, gh, T) - np.bincount(h, ga, T) + 2 * r * dfn
            g_mu = np.bincount(d, gh + ga, D)
            g_home = np.bincount(d, gh, D)
            g_aa = fh.T @ gh + fa.T @ ga + 2 * r * aa
            g_ad = -(fa.T @ gh + fh.T @ ga) + 2 * r * ad
            return loss, np.concatenate([g_att, g_dfn, g_mu, g_home, g_aa, g_ad])

        res = minimize(f, self.x, jac=True, method="L-BFGS-B", options={"maxiter": 300})
        self.x = res.x
        # ρ：固定 λ，用真正的比分找最好的低比分修正
        lh, la = self.lam(self.x, idx)
        hg, ag = self.hg[idx], self.ag[idx]
        m00, m10, m01, m11 = (hg == 0) & (ag == 0), (hg == 1) & (ag == 0), (hg == 0) & (ag == 1), (hg == 1) & (ag == 1)

        def nll(rho):
            tau = np.ones_like(lh)
            tau[m00] = 1 - lh[m00] * la[m00] * rho
            tau[m10] = 1 + la[m10] * rho
            tau[m01] = 1 + lh[m01] * rho
            tau[m11] = 1 - rho
            if np.any(tau <= 0):
                return 1e9
            return -np.sum(w * np.log(tau))

        self.rho = minimize_scalar(nll, bounds=(-0.25, 0.25), method="bounded").x
        return True


def score_matrix(lh, la, rho):
    gh = poisson.pmf(np.arange(MAXG + 1), lh)
    ga = poisson.pmf(np.arange(MAXG + 1), la)
    m = np.outer(gh, ga)
    m[0, 0] *= 1 - lh * la * rho
    m[1, 0] *= 1 + la * rho
    m[0, 1] *= 1 + lh * rho
    m[1, 1] *= 1 - rho
    m = np.clip(m, 0, None)
    return m / m.sum()


def ah_home_prob(m, line):
    """亞洲讓分（主隊讓 line，例如 −0.75）：回傳 (主隊贏這注, 客隊贏這注) 的機率，走盤（退款）不算；四分之一盤拆成兩半"""
    if line is None:
        return None
    parts = [line] if abs(line * 2 - round(line * 2)) < 1e-9 else [line - 0.25, line + 0.25]
    diff = np.subtract.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
    win = lose = 0.0
    for p in parts:
        adj = diff + p
        win += m[adj > 0].sum() / len(parts)
        lose += m[adj < 0].sum() / len(parts)
    s = win + lose
    return (win / s, lose / s) if s > 0 else None


# ───────── 一路往前預測 ─────────
def walk_forward(rows, half_life, w_goals, ridge, until=None, quiet=False):
    flags = season_flags(rows)
    preds = []
    for cname, divs in COUNTRIES.items():
        rs = [r for r in rows if r["div"] in divs]
        model = Country(rs, flags, half_life, w_goals, ridge)
        tt = model.t
        cut = START_PRED
        end = until or (rs[-1]["dt"] + timedelta(days=1))
        t0 = time.time()
        nfit = 0
        while cut < end:
            nxt = cut + timedelta(days=7)
            ct = (cut - datetime(2000, 1, 1)).total_seconds() / 86400
            nt = (nxt - datetime(2000, 1, 1)).total_seconds() / 86400
            idx = np.where((tt >= ct) & (tt < nt))[0]
            if len(idx):
                if model.fit(ct):
                    nfit += 1
                    lh, la = model.lam(model.x, idx)
                    for j, i in enumerate(idx):
                        m = score_matrix(lh[j], la[j], model.rho)
                        r = rs[i]
                        ph, pd, pa = np.tril(m, -1).sum(), np.trace(m), np.triu(m, 1).sum()
                        tot = np.add.outer(np.arange(MAXG + 1), np.arange(MAXG + 1))
                        pov = m[tot > 2.5].sum()
                        preds.append({**{k: r[k] for k in ("div", "season", "dt", "home", "away", "hg", "ag", "ps", "psc", "bfc", "avg", "avgc", "b365",
                                                             "ou_pc", "ou_bfc", "ou_avgc", "ahc", "ah_pc", "ah_bfc")},
                                      "lh": float(lh[j]), "la": float(la[j]), "p": (float(ph), float(pd), float(pa)), "pov": float(pov),
                                      "pah": ah_home_prob(m, r["ahc"])})
            cut = nxt
        if not quiet:
            print(f"  {cname}：{nfit} 次訓練，{time.time() - t0:.0f} 秒", flush=True)
    preds.sort(key=lambda p: p["dt"])
    return preds


# ───────── 成績單 ─────────
def ll(p):
    return -math.log(max(p, 1e-9))


def res_idx(p):
    return 0 if p["hg"] > p["ag"] else (1 if p["hg"] == p["ag"] else 2)


def evaluate(preds, lo, hi, blend=None):
    S = [p for p in preds if lo <= p["dt"] < hi]
    out = {"n": len(S)}
    # 1) 1X2 準度：同一批比賽（有該家收盤的）比
    def cmp(key):
        sub = [p for p in S if fair(p[key])]
        if not sub:
            return None
        m = sum(ll(p["p"][res_idx(p)]) for p in sub) / len(sub)
        k = sum(ll(fair(p[key])[res_idx(p)]) for p in sub) / len(sub)
        base = [sum(res_idx(q) == i for q in sub) / len(sub) for i in range(3)]
        u = sum(ll(base[res_idx(p)]) for p in sub) / len(sub)
        return {"n": len(sub), "model": round(m, 4), "market": round(k, 4), "base": round(u, 4)}
    out["x12"] = {k: cmp(k) for k in ("psc", "bfc", "avgc", "ps", "avg")}
    # 2) 機率準不準（模型說 x%，實際開出幾 %）
    bins = defaultdict(lambda: [0, 0.0, 0])
    for p in S:
        r = res_idx(p)
        for i in range(3):
            b = min(int(p["p"][i] * 10), 9)
            bins[b][0] += 1
            bins[b][1] += p["p"][i]
            bins[b][2] += (r == i)
    out["calib"] = [{"bin": f"{b * 10}–{b * 10 + 10}%", "n": v[0], "pred": round(v[1] / v[0] * 100, 1), "real": round(v[2] / v[0] * 100, 1)}
                    for b, v in sorted(bins.items()) if v[0] >= 30]
    # 3) 大小 2.5、亞洲讓分（收盤那條線、半球盤才比，比較乾淨）
    def ou(key):
        sub = [p for p in S if fair(p[key])]
        if not sub:
            return None
        hit = lambda p: 0 if p["hg"] + p["ag"] > 2.5 else 1
        m = sum(ll((p["pov"], 1 - p["pov"])[hit(p)]) for p in sub) / len(sub)
        k = sum(ll(fair(p[key])[hit(p)]) for p in sub) / len(sub)
        return {"n": len(sub), "model": round(m, 4), "market": round(k, 4)}
    out["ou"] = {k: ou(k) for k in ("ou_pc", "ou_bfc", "ou_avgc")}

    def ah(key):
        sub = [p for p in S if fair(p[key]) and p["pah"] and p["ahc"] is not None and abs(p["ahc"] * 2 - round(p["ahc"] * 2)) < 1e-9 and abs(p["ahc"] - round(p["ahc"])) > 0.1]
        if not sub:
            return None
        hit = lambda p: 0 if p["hg"] - p["ag"] + p["ahc"] > 0 else 1
        m = sum(ll(p["pah"][hit(p)]) for p in sub) / len(sub)
        k = sum(ll(fair(p[key])[hit(p)]) for p in sub) / len(sub)
        return {"n": len(sub), "model": round(m, 4), "market": round(k, 4)}
    out["ah"] = {k: ah(k) for k in ("ah_pc", "ah_bfc")}
    # 4) 混合：市場＋模型（p ∝ 市場^a × 模型^b），a、b 只用驗證季學，考試季直接套用
    out["blend"] = blend_eval(S, blend)
    # 5) 職業最看重：模型跟「早盤」不一樣的時候，收盤有沒有往模型那邊移（CLV）
    out["clv"] = clv_eval(S)
    return out


def blend_fit(S, key):
    sub = [p for p in S if fair(p[key])]
    lm = np.log(np.array([fair(p[key]) for p in sub]))
    lp = np.log(np.array([p["p"] for p in sub]))
    y = np.array([res_idx(p) for p in sub])

    def f(ab):
        z = ab[0] * lm + ab[1] * lp
        z = z - z.max(1, keepdims=True)
        pr = np.exp(z) / np.exp(z).sum(1, keepdims=True)
        return -np.mean(np.log(pr[np.arange(len(y)), y]))
    r = minimize(f, [1.0, 0.0], method="Nelder-Mead")
    return [float(r.x[0]), float(r.x[1])]


def blend_eval(S, blend):
    out = {}
    for key in ("psc", "bfc"):
        sub = [p for p in S if fair(p[key])]
        if len(sub) < 300:
            continue
        ab = (blend or {}).get(key) or blend_fit(sub, key)
        lm = np.log(np.array([fair(p[key]) for p in sub]))
        lp = np.log(np.array([p["p"] for p in sub]))
        y = np.array([res_idx(p) for p in sub])
        z = ab[0] * lm + ab[1] * lp
        z = z - z.max(1, keepdims=True)
        pr = np.exp(z) / np.exp(z).sum(1, keepdims=True)
        mix = float(-np.mean(np.log(pr[np.arange(len(y)), y])))
        mk = float(-np.mean(lm[np.arange(len(y)), y]))
        # 運氣範圍：每場差多少的標準誤
        dif = -np.log(pr[np.arange(len(y)), y]) + lm[np.arange(len(y)), y]
        out[key] = {"n": len(sub), "a": round(ab[0], 3), "b": round(ab[1], 3), "mix": round(mix, 5), "market": round(mk, 5),
                    "gain": round(mk - mix, 5), "se": round(float(dif.std() / math.sqrt(len(dif))), 5)}
    return out


def clv_eval(S):
    """早盤＝Pinnacle 賽前（PSH，大約賽前 2–3 天），收盤＝Pinnacle 收盤（PSCH）；一定要同一家比，才不會把「各家價錢不同」誤當成移動。
    （2026-10-12 修正：原本早盤缺的時候改用各家平均，跟 Pinnacle 收盤比會失真，已拿掉。）
    模型勝率 × 早盤賠率 − 1 ≥ 門檻 才下（用早盤賠率下注），看：收盤有沒有往這邊移（dp）、CLV、實際輸贏"""
    res = {}
    for th in (0.0, 0.03, 0.05, 0.10):
        dps, clv, roi, n = [], [], [], 0
        for p in S:
            early = p["ps"]
            fe, fc = fair(early), fair(p["psc"])
            if not fe or not fc:
                continue
            r = res_idx(p)
            for i in range(3):
                ev = p["p"][i] * early[i] - 1
                if ev < th or ev > 1.0:
                    continue
                n += 1
                dps.append(fc[i] - fe[i])
                clv.append(early[i] * fc[i] - 1)
                roi.append(early[i] - 1 if r == i else -1)
        if n:
            ms = lambda xs: (round(float(np.mean(xs)), 5), round(float(np.std(xs) / math.sqrt(len(xs))), 5))
            res[str(th)] = {"n": n, "dp": ms(dps), "clv": ms(clv), "roi": ms(roi),
                            "toward": round(sum(1 for x in dps if x > 0.002) / n, 3), "away": round(sum(1 for x in dps if x < -0.002) / n, 3)}
    # 斜率：模型比早盤多看好幾 %，收盤平均移動幾 %（所有比賽、三個選項）
    xs, ys = [], []
    for p in S:
        early = p["ps"]
        fe, fc = fair(early), fair(p["psc"])
        if not fe or not fc:
            continue
        for i in range(3):
            xs.append(p["p"][i] - fe[i])
            ys.append(fc[i] - fe[i])
    if xs:
        x, y = np.array(xs), np.array(ys)
        slope = float((x * y).sum() / (x * x).sum())
        resid = y - slope * x
        se = float(math.sqrt((resid ** 2).sum() / (len(x) - 1) / (x * x).sum()))
        res["slope"] = {"n": len(x), "slope": round(slope, 4), "se": round(se, 4)}
    return res


def save_preds(preds, tag):
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, f"soccer_preds_{tag}.csv.gz")
    with gzip.open(path, "wt", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["div", "date", "home", "away", "hg", "ag", "lam_h", "lam_a", "p_h", "p_d", "p_a", "p_over25", "ahc", "p_ah_home",
                    "psc_h", "psc_d", "psc_a", "bfc_h", "bfc_d", "bfc_a", "ps_h", "ps_d", "ps_a"])
        for p in preds:
            g = lambda k: list(p[k]) if p[k] else ["", "", ""]
            w.writerow([p["div"], p["dt"].strftime("%Y-%m-%d %H:%M"), p["home"], p["away"], p["hg"], p["ag"], round(p["lh"], 4), round(p["la"], 4),
                        *[round(x, 4) for x in p["p"]], round(p["pov"], 4), p["ahc"] if p["ahc"] is not None else "",
                        round(p["pah"][0], 4) if p["pah"] else "", *g("psc"), *g("bfc"), *g("ps")])
    return path


def load_preds(tag):
    """讀回存檔的預測（不重跑模型），用來重算成績單"""
    out = []
    with gzip.open(os.path.join(OUT, f"soccer_preds_{tag}.csv.gz"), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            g = lambda *ks: tuple(float(r[k]) for k in ks) if all(r[k] for k in ks) else None
            out.append({"dt": datetime.strptime(r["date"], "%Y-%m-%d %H:%M"), "hg": int(r["hg"]), "ag": int(r["ag"]),
                        "p": g("p_h", "p_d", "p_a"), "ps": g("ps_h", "ps_d", "ps_a"), "psc": g("psc_h", "psc_d", "psc_a"), "bfc": g("bfc_h", "bfc_d", "bfc_a")})
    return out


GRID = [(hl, wg, rd) for hl in (90, 180, 365, 730) for wg in (1.0, 0.7, 0.5, 0.3) for rd in (1.0, 3.0, 8.0)]


def tune():
    rows = load()
    print(f"讀進 {len(rows)} 場")
    results = []
    for hl, wg, rd in GRID:
        t0 = time.time()
        preds = walk_forward(rows, hl, wg, rd, until=VALID[1], quiet=True)
        ev = evaluate(preds, *VALID)
        x = ev["x12"]["psc"]
        results.append({"half_life": hl, "w_goals": wg, "ridge": rd, "ll_model": x["model"], "ll_market": x["market"], "ll_base": x["base"],
                        "n": x["n"], "blend_gain": ev["blend"].get("psc", {}).get("gain"), "slope": ev["clv"].get("slope"), "sec": round(time.time() - t0)})
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    best = min(results, key=lambda r: r["ll_model"])
    return rows, results, best


def main():
    os.makedirs(OUT, exist_ok=True)
    rep_path = os.path.join(OUT, "soccer_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    if "--tune" in sys.argv:
        rows, results, best = tune()
        preds = walk_forward(rows, best["half_life"], best["w_goals"], best["ridge"], until=VALID[1])
        ev = evaluate(preds, *VALID)
        rep.update({"tuned_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "grid": results,
                    "chosen": {k: best[k] for k in ("half_life", "w_goals", "ridge")}, "valid": ev,
                    "blend_ab": {k: [v["a"], v["b"]] for k, v in ev["blend"].items()},
                    "data": {"matches": len(rows), "first": rows[0]["dt"].strftime("%Y-%m-%d"), "last": rows[-1]["dt"].strftime("%Y-%m-%d")}})
        json.dump(rep, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        save_preds(preds, "valid")
        print("驗證完成，選定：", rep["chosen"])
    elif "--final-test" in sys.argv:
        if rep.get("test"):
            print("最後兩季已經考過了（", rep["test"]["run_utc"], "），照規則不能重考。要重考請先跟使用者確認。")
            return
        c = rep["chosen"]
        rows = load()
        preds = walk_forward(rows, c["half_life"], c["w_goals"], c["ridge"])
        blend = {k: v for k, v in rep.get("blend_ab", {}).items()}
        ev = evaluate(preds, *TEST, blend=blend)
        rep["test"] = {"run_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"), "config": c, **ev}
        json.dump(rep, open(rep_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1, default=str)
        save_preds(preds, "all")
        log = os.path.join(OUT, "test_log.json")
        hist = json.load(open(log)) if os.path.exists(log) else []
        hist.append({"stage": 1, "sport": "soccer", "run_utc": rep["test"]["run_utc"], "config": c})
        json.dump(hist, open(log, "w"), ensure_ascii=False, indent=1)
        print("最後兩季考試完成")


if __name__ == "__main__":
    main()
