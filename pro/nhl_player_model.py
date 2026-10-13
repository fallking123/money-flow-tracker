"""
職業版・NHL 第 2 版：先發守門員＋每位球員評分（職業團隊的做法）
================================================================
第 1 版：整隊的射門品質（xG）、多一人、守門＋終結都是「整隊」算，誰上場、誰守門都不知道。
第 2 版（資料：每場每位球員的上場時間等＝fastRhockey／sportsdataverse（MIT）；每一次射門的 xG＝MoneyPuck.com）：
- 守門員：自己面對的射門，「應該被進幾球（xG）」減掉「實際被進幾球」＝幫球隊多救幾球（GSAx），
  每一次射門平均多少；守門員差異很大但運氣也很大，拉回平均的程度最多。跟著人走。
- 每位球員（前鋒、後衛分開）每 60 分鐘：自己射門的 xG、得分、助攻、射正、在場時的正負值、
  阻擋射門、抄截減失誤、撞人、犯規分鐘；上場時間少的往「新人平均」拉。
- 今天誰上場，用每個人平常的上場時間加權，加起來＝這隊今天的強度。
- 再加上第 1 版的整隊數據（教練體系、戰術），背靠背、休息天數。
兩種「知道誰上場」（公平檢查）：actual＝今天實際上場的球員和先發守門員（開賽前約 1 小時公布）；
  prev＝上一場的名單，先發守門員猜最近 10 場最常先發的那位（背靠背的第二場猜另一位）——開盤時就知道。
注意：2024–25、2025–26 第 1 版考過，第 2 版在那兩季只當參考；冰球舊盤口有問題，挑設定只看比賽結果的準度。
用法：python3 -m pro.nhl_player_model --tune / --lineups / --reference-test
"""
import csv
import gzip
import json
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
from scipy.stats import poisson
from sklearn.linear_model import LogisticRegression

from pro import nhl_model as V1
from pro import us_eval as E

D = V1.D
OUT = V1.OUT
# 球員每 60 分鐘的數據（順序固定）
SK = ["ixg", "g", "a", "sog", "pm", "blk", "tkgv", "hits", "pim"]
NAMES = ["射門品質 xG", "進球", "助攻", "射正", "正負值", "阻擋射門", "抄截減失誤", "撞人", "犯規", "守門員", "第 1 版：整隊數據",
         "背靠背", "休息差"]


def fnum(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def toi(s):
    try:
        m, sec = str(s).split(":")
        return int(m) + int(sec) / 60
    except ValueError:
        return 0.0


def _rows(name):
    """舊檔＋這一季的小檔（實戰時每天下載，不 commit）；同一場以小檔為準"""
    cur = os.path.join(D, name.replace(".csv.gz", "_cur.csv.gz"))
    cur_rows = []
    if os.path.exists(cur):
        with gzip.open(cur, "rt", encoding="utf-8") as f:
            cur_rows = list(csv.DictReader(f))
    cur_games = {r["game_id"] for r in cur_rows}
    with gzip.open(os.path.join(D, name), "rt", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["game_id"] not in cur_games:
                yield r
    yield from cur_rows


def load_players():
    ixg = defaultdict(float)
    for r in _rows("shot_players.csv.gz"):
        ixg[(r["game_id"], r["player"])] += fnum(r["xg"])
    gk = {}
    for r in _rows("shot_goalies.csv.gz"):
        gk[(r["game_id"], r["goalie"])] = (fnum(r["att"]), fnum(r["xg"]), fnum(r["ga"]))
    sk = defaultdict(list)
    if True:
        for r in _rows("skater_box.csv.gz"):
            gid, pid = r["game_id"], r["player_id"]
            t = toi(r["toi"])
            if t <= 0:
                continue
            v = np.array([t, ixg.get((gid, pid), 0.0), fnum(r["goals"]), fnum(r["assists"]), fnum(r["shots_on_goal"]), fnum(r["plus_minus"]),
                          fnum(r["blocked_shots"]), fnum(r["takeaways"]) - fnum(r["giveaways"]), fnum(r["hits"]), fnum(r["pim"])])
            sk[gid].append((r["home_away"], pid, "D" if r["position"] == "D" else "F", v))
    gb = defaultdict(list)
    if True:
        for r in _rows("goalie_box.csv.gz"):
            gid, pid = r["game_id"], r["player_id"]
            att, xg, ga = gk.get((gid, pid), (0.0, 0.0, 0.0))
            gb[gid].append((r["home_away"], pid, r["starter"] == "True", toi(r["toi"]), att, xg, ga))
    return sk, gb


class Decay:
    def __init__(self, hl):
        self.hl, self.v = hl, {}

    def get(self, k, now):
        x = self.v.get(k)
        if x is None:
            return None
        return x[1] * 0.5 ** ((now - x[0]) / self.hl)

    def add(self, k, now, arr):
        cur = self.get(k, now)
        self.v[k] = (now, arr.copy() if cur is None else cur + arr)


def features(games, box, cfg, v1feat):
    sk, gb = box
    P = Decay(cfg["hl_p"])                 # 球員：上場分鐘＋各項數據
    G = Decay(cfg["hl_g"])                 # 守門員：射門數、xG、失分
    NEWP = {"F": Decay(365.0), "D": Decay(365.0)}     # 新人平均
    NEWG = Decay(730.0)
    career, gcareer = defaultdict(float), defaultdict(float)
    etoi, cur_team, pos_of = {}, {}, {}
    last_lu, starts, last_date = {}, defaultdict(list), {}
    mode = cfg.get("lineup", "actual")
    KP, KG = cfg["k_p"], cfg["k_g"]
    out = []
    by_day = defaultdict(list)
    for g in games:
        by_day[g["dt"]].append(g)
    for day in sorted(by_day):
        now = (day - datetime(2000, 1, 1)).days
        prior = {}
        for pos in ("F", "D"):
            x = NEWP[pos].get("x", now)
            prior[pos] = x[1:] / x[0] * 60 if x is not None and x[0] > 500 else np.zeros(len(SK))
        ng = NEWG.get("x", now)
        g_prior = (ng[1] - ng[2]) / ng[0] if ng is not None and ng[0] > 300 else -0.002

        def prate(pid):
            x = P.get(pid, now)
            pos = pos_of.get(pid, "F")
            if x is None:
                return prior[pos]
            return (x[1:] + prior[pos] / 60 * KP) / (x[0] + KP) * 60

        def grate(pid):
            x = G.get(pid, now)
            if x is None:
                return g_prior
            return ((x[1] - x[2]) + g_prior * KG) / (x[0] + KG)

        for g in by_day[day]:
            gid = g["game_id"]
            vf = v1feat.get(gid)
            if vf is None or (gid not in sk and not g.get("upcoming")):      # upcoming＝還沒打的比賽（實戰用，只能用開盤版名單）
                continue
            f = {}
            for side, ha in (("h", "home"), ("a", "away")):
                team = g[side]
                if mode == "prev" and team in last_lu:
                    lu = [p for p in last_lu[team] if cur_team.get(p) == team]
                    hist = starts[team][-10:]
                    if hist:
                        cnt = Counter(hist)
                        order = [p for p, _ in cnt.most_common()]
                        goalie = order[0]
                        if last_date.get(team) and (day - last_date[team]).days <= 1 and hist[-1] == goalie and len(order) > 1:
                            goalie = order[1]
                    else:
                        goalie = None
                else:
                    lu = [pid for (h, pid, pos, v) in sk.get(gid, []) if h == ha]
                    goalie = next((pid for (h, pid, st, t, *_) in gb.get(gid, []) if h == ha and st), None)
                w = np.array([etoi.get(p, 12.0) for p in lu]) if lu else np.array([1.0])
                w = w / w.sum() * 5.0               # 場上 5 個人
                rates = np.array([prate(p) for p in lu]) if lu else np.zeros((1, len(SK)))
                f[side] = (w @ rates, grate(goalie) if goalie else g_prior)
            (sh, gh), (sa, ga) = f["h"], f["a"]
            x = list(sh - sa) + [(gh - ga) * 100]
            out.append({**{k: g[k] for k in ("game_id", "season", "dt", "h", "a", "y", "oc_h", "oc_a", "oo_h", "oo_a", "total_line", "total", "src")},
                        "x": x + vf["x"], "xt": [sh[0] + sa[0], sh[1] + sa[1], sh[2] + sa[2], (gh + ga) * 100] + vf["xt"]})
        # 更新
        for g in by_day[day]:
            gid = g["game_id"]
            if gid not in sk:
                continue
            for side, ha in (("h", "home"), ("a", "away")):
                team = g[side]
                lu = []
                for (h, pid, pos, v) in sk[gid]:
                    if h != ha:
                        continue
                    lu.append(pid)
                    pos_of[pid] = pos
                    cur_team[pid] = team
                    if career[pid] < 300:
                        NEWP[pos].add("x", now, v)
                    career[pid] += v[0]
                    P.add(pid, now, v)
                    etoi[pid] = etoi[pid] * 0.85 + v[0] * 0.15 if pid in etoi else v[0]
                if lu:
                    last_lu[team] = lu
                for (h, pid, st, t, att, xg, gav) in gb.get(gid, []):
                    if h != ha or att <= 0:
                        continue
                    arr = np.array([att, xg, gav])
                    if gcareer[pid] < 500:
                        NEWG.add("x", now, arr)
                    gcareer[pid] += att
                    G.add(pid, now, arr)
                    if st:
                        starts[team] = (starts[team] + [pid])[-12:]
                last_date[team] = day
    return out


def second_stage(feats, season, C):
    tr = [f for f in feats if V1.FIRST_TRAIN < f["season"] < season and f["y"] is not None]
    te = [f for f in feats if f["season"] == season]
    if len(tr) < 3000 or not te:
        return [], None
    X = np.array([f["x"] for f in tr])
    mu, sd = X.mean(0), X.std(0) + 1e-9
    lr = LogisticRegression(C=C, max_iter=2000).fit((X - mu) / sd, np.array([f["y"] for f in tr]))
    trt = [f for f in tr if f["total"] is not None]
    Xt = np.array([[1, *f["xt"]] for f in trt])
    bt = np.linalg.lstsq(Xt, np.array([f["total"] for f in trt], float), rcond=None)[0]
    pr = lr.predict_proba((np.array([f["x"] for f in te]) - mu) / sd)[:, 1]
    out = []
    for f, p in zip(te, pr):
        tm = float(np.array([1, *f["xt"]]) @ bt)
        r = {"season": f["season"], "date": f["dt"].strftime("%Y-%m-%d"), "home": f["h"], "away": f["a"], "p": float(p), "y": f["y"], "src": f["src"],
             "oc_h": f["oc_h"], "oc_a": f["oc_a"], "oo_h": f["oo_h"], "oo_a": f["oo_a"],
             "pc": E.devig2(f["oc_h"], f["oc_a"]), "po": E.devig2(f["oo_h"], f["oo_a"]), "pred_t": tm}
        T = f["total_line"]
        if T and f["total"] is not None:
            r["ou"] = float(1 - poisson.cdf(int(T), tm)) if T != int(T) else float(1 - poisson.cdf(int(T), tm))
            r["ou_hit"] = None if f["total"] == T else int(f["total"] > T)
        out.append(r)
    names = NAMES[:10] + [f"第 1 版：{k}" for k in ("5 對 5", "多一人", "終結與守門", "進球", )] + NAMES[11:]
    return out, dict(zip(names, [round(float(x), 3) for x in lr.coef_[0]]))


def v1_features(games):
    R = json.load(open(os.path.join(OUT, "us_report.json"), encoding="utf-8"))["nhl"]["chosen"]
    return {f["game_id"]: f for f in V1.features(games, R["half_life"], R["ridge"])}


def run(games, box, v1f, cfg, seasons):
    feats = features(games, box, cfg, v1f)
    preds, coefs = [], None
    for s in range(seasons[0], seasons[1] + 1):
        p, c = second_stage(feats, s, cfg["C"])
        preds += p
        coefs = c or coefs
    return preds, coefs


GRID = [{"hl_p": hp, "k_p": kp, "hl_g": hg, "k_g": kg, "C": 1.0}
        for hp in (365.0, 730.0) for kp in (300.0, 1000.0) for hg in (730.0,) for kg in (1000.0, 3000.0)]


def main():
    rep_path = os.path.join(OUT, "us_report.json")
    rep = json.load(open(rep_path, encoding="utf-8")) if os.path.exists(rep_path) else {}
    R = rep.get("nhl2", {})
    games = V1.load()
    box = load_players()
    v1f = v1_features(games)
    print(f"NHL v2：{len(games)} 場、{len(box[0])} 場有球員資料", flush=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    if "--smoke" in sys.argv:
        for mode in ("actual", "prev"):
            preds, coefs = run(games, box, v1f, {**GRID[0], "lineup": mode}, (2018, 2019))
            ev = V1.evaluate(preds)
            print(mode, ev["ll_model_all"], ev["ll_base_all"], ev["n_all"], coefs, flush=True)
    elif "--tune" in sys.argv:
        grid = []
        for cfg in GRID:
            preds, _ = run(games, box, v1f, cfg, V1.VALID)
            ev = V1.evaluate(preds)
            grid.append({**cfg, "ll_model": ev["ll_model_all"], "ll_base": ev["ll_base_all"], "n": ev["n_all"]})
            print(json.dumps(grid[-1]), flush=True)
        best = min(grid, key=lambda g: g["ll_model"])
        R.update({"grid": grid, "chosen": {k: best[k] for k in GRID[0]}, "tuned_utc": stamp})
        E.save_sport(rep_path, "nhl2", R)
        print("NHL v2 挑好：", R["chosen"])
    elif "--lineups" in sys.argv:
        base = {k: v for k, v in R["chosen"].items() if k != "lineup"}
        cmp_ = {}
        for mode in ("actual", "prev"):
            preds, cf = run(games, box, v1f, {**base, "lineup": mode}, V1.VALID)
            ev = V1.evaluate(preds)
            cmp_[mode] = {"valid": ev, "coefs": cf, "blend_ab": [ev["ml"]["blend"]["a"], ev["ml"]["blend"]["b"]] if ev.get("ml") else [1.0, 0.0]}
            print(mode, ev["ll_model_all"], ev["ll_base_all"], (ev.get("ml") or {}).get("ll_close"), flush=True)
        R["chosen"] = {**base, "lineup": "actual"}
        R["valid"], R["coefs"], R["blend_ab"] = cmp_["actual"]["valid"], cmp_["actual"]["coefs"], cmp_["actual"]["blend_ab"]
        R["open_model"] = {"lineup": "prev", **cmp_["prev"]}
        E.save_sport(rep_path, "nhl2", R)
    elif "--reference-test" in sys.argv:
        if R.get("ref_test"):
            print("NHL v2 參考考試已經跑過了")
            return
        c = R["chosen"]
        # 混合比例：驗證季的冰球盤口不能用，跟第 1 版一樣在考試季前用 2022 起的資料學不到 → 用第 1 版的作法：考試季內只報告，不混合
        preds, _ = run(games, box, v1f, c, V1.TEST)
        ev = V1.evaluate(preds)
        po, _ = run(games, box, v1f, {**c, "lineup": "prev"}, V1.TEST)
        evo = V1.evaluate(po)
        R["ref_test"] = {"run_utc": stamp, "config": c, **ev, "open_model": evo,
                         "note": "這兩季第 1 版考過；第 2 版只用驗證季挑設定，這裡跑一次當參考"}
        E.save_sport(rep_path, "nhl2", R)
        log = os.path.join(OUT, "test_log.json")
        L = json.load(open(log, encoding="utf-8"))
        L.append({"stage": 3, "sport": "nhl2", "run_utc": stamp, "config": c, "note": "第 2 版參考考試（只當參考）"})
        json.dump(L, open(log, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("NHL v2 參考：", ev["ml"]["ll_model"], ev["ml"]["ll_close"], evo["ml"]["ll_model"])


if __name__ == "__main__":
    main()
