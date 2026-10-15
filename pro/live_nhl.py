"""
職業版・NHL 實戰記錄：每天算「還沒開打的比賽」模型勝率，跟 Pinnacle 盤口比，記下來；打完再跟收盤比
================================================================
規則（跟練習區一樣，先訂好不改）：模型（NHL 第 2 版開盤版：上一場名單、守門員用猜的）勝率 × Pinnacle 當下賠率 − 1 ≥ 15% → 記一注。
- 每一場只在「第一次看到」時決定一次（之後不改）；決定時用的是那一刻的 Pinnacle 賠率。
- 這一季已經打完、系統上線前的比賽：用我們第一次記到的 Pinnacle 賠率回補（標記「回補」）；模型只用比賽前一天以前的資料，所以是公平的。
- 打完後：CLV＝Pinnacle 收盤（開賽前最後一筆，去抽水）勝率 × 決定時賠率 − 1；輸贏照實際結果（含延長賽、PK）。
輸出：docs/data/pro/live/nhl.csv（每一場）、docs/data/pro/live/nhl_summary.json
用法：python3 -m pro.live_nhl
"""
import csv
import json
import math
import os
from datetime import datetime, timedelta, timezone

import numpy as np

from pro import lines as L
from pro import nhl_model as V1
from pro import nhl_player_model as NH

OUT = os.path.join(NH.OUT, "live")
PATH = os.path.join(OUT, "nhl.csv")
EDGE = 0.15
EDGE_MAX = 0.30          # 10/15 地基檢查後加上：比 Pinnacle 多看好 > 30% 通常是資料錯或我們漏了消息，不下
FIELDS = ["game_id", "date", "home", "away", "decided_utc", "how", "p_model", "odds_home", "odds_away", "fair_home_dec",
          "pick", "edge", "close_fair_home", "clv", "result", "profit"]


def season_start_year(now):
    return now.year if now.month >= 8 else now.year - 1


def us_date(t):
    return (t - timedelta(hours=6)).date()


def main():
    now = datetime.now(timezone.utc)
    season = season_start_year(now)
    games = V1.load()
    played = {(g["dt"].date(), g["h"], g["a"]): g for g in games if g["season"] == season}
    pins = L.load_pin("nhl")
    pin_idx = {}
    for pg in pins:
        h, a = V1.canon(pg.home), V1.canon(pg.away)
        if h and a:
            pin_idx[(us_date(pg.t), h, a)] = pg
    upcoming = []
    for (d, h, a), pg in pin_idx.items():
        if pg.t > now and (d, h, a) not in played and pg.t < now + timedelta(hours=40):
            upcoming.append({"game_id": "P" + str(pg.pid), "season": season, "dt": datetime(d.year, d.month, d.day), "h": h, "a": a,
                             "y": None, "oc_h": None, "oc_a": None, "oo_h": None, "oo_a": None, "total_line": None, "total": None, "src": None,
                             "upcoming": True})
    allg = sorted(games + upcoming, key=lambda g: (g["dt"], g["game_id"]))
    R = json.load(open(os.path.join(NH.OUT, "us_report.json"), encoding="utf-8"))
    c1, c2 = R["nhl"]["chosen"], R["nhl2"]["chosen"]
    v1f = {f["game_id"]: f for f in V1.features(allg, c1["half_life"], c1["ridge"])}
    feats = NH.features(allg, NH.load_players(), {**c2, "lineup": "prev"}, v1f)
    te = [f for f in feats if f["season"] == season]
    preds, _ = NH.second_stage(feats, season, c2.get("C", 1.0))
    model = {f["game_id"]: (f, p) for f, p in zip(te, preds)}

    os.makedirs(OUT, exist_ok=True)
    old = {r["game_id"]: r for r in csv.DictReader(open(PATH, encoding="utf-8"))} if os.path.exists(PATH) else {}
    rows = dict(old)
    for gid, (f, p) in model.items():
        d = f["dt"].date()
        pg = pin_idx.get((d, f["h"], f["a"]))
        if pg is None:
            continue
        key = str(pg.pid)                       # 用 Pinnacle 編號當同一場的代號（回補和實戰一致）
        if key in rows and rows[key].get("decided_utc"):
            r = rows[key]
        else:
            started = pg.t <= now
            when = pg.first_time() if started else now
            st = pg.state(when)
            fair = L.fair_ml(st, False)
            if not fair:
                continue
            oh, oa = st[("moneyline", "home")][1], st[("moneyline", "away")][1]
            ph = p["p"]
            eh, ea = ph * oh - 1, (1 - ph) * oa - 1
            ok = lambda e: EDGE <= e <= EDGE_MAX
            pick = "home" if ok(eh) and eh >= ea else "away" if ok(ea) else ""
            r = {"game_id": key, "date": d.isoformat(), "home": f["h"], "away": f["a"], "decided_utc": when.strftime("%Y-%m-%dT%H:%MZ"),
                 "how": "回補" if started else "實戰", "p_model": round(ph, 4), "odds_home": oh, "odds_away": oa,
                 "fair_home_dec": round(fair["home"], 4), "pick": pick, "edge": round(max(eh, ea), 4)}
            rows[key] = r
        # 結算
        if pg.t <= now and not r.get("close_fair_home"):
            cf = L.fair_ml(pg.close(), False)
            if cf:
                r["close_fair_home"] = round(cf["home"], 4)
        if r.get("pick") and r.get("close_fair_home") and not r.get("clv"):
            q = float(r["close_fair_home"]) if r["pick"] == "home" else 1 - float(r["close_fair_home"])
            o = float(r["odds_home"] if r["pick"] == "home" else r["odds_away"])
            r["clv"] = round(q * o - 1, 4)
        pl = played.get((d, f["h"], f["a"]))
        if pl and pl.get("y") is not None and not r.get("result"):
            r["result"] = "home" if pl["y"] == 1 else "away"
            if r.get("pick"):
                o = float(r["odds_home"] if r["pick"] == "home" else r["odds_away"])
                r["profit"] = round(o - 1 if r["pick"] == r["result"] else -1.0, 4)
    out = sorted(rows.values(), key=lambda r: (r["date"], r["game_id"]))
    with open(PATH, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore", restval="")
        w.writeheader()
        w.writerows(out)
    picks = [r for r in out if r.get("pick")]
    clv = [float(r["clv"]) for r in picks if r.get("clv") not in ("", None)]
    prof = [float(r["profit"]) for r in picks if r.get("profit") not in ("", None)]
    # 全部比賽：模型 vs 決定時的 Pinnacle，收盤往哪邊移
    mv = [(float(r["p_model"]) - float(r["fair_home_dec"]), float(r["close_fair_home"]) - float(r["fair_home_dec"]))
          for r in out if r.get("close_fair_home") not in ("", None)]
    tow = sum(1 for d, m in mv if d * m > 0 and abs(m) > 0.005)
    awy = sum(1 for d, m in mv if d * m < 0 and abs(m) > 0.005)
    ms = lambda xs: [round(float(np.mean(xs)), 4), round(float(np.std(xs) / math.sqrt(len(xs))), 4) if len(xs) > 1 else None, len(xs)] if xs else None
    summ = {"updated_utc": now.strftime("%Y-%m-%dT%H:%MZ"), "season": f"{season}-{(season + 1) % 100:02d}", "rule": "模型比 Pinnacle 多看好 15%–30%",
            "games": len(out), "games_settled": len(mv), "picks": len(picks), "clv": ms(clv), "profit": ms(prof),
            "move_toward": tow, "move_away": awy, "pending": [r for r in out if r.get("pick") and not r.get("result")]}
    json.dump(summ, open(os.path.join(OUT, "nhl_summary.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in summ.items() if k != "pending"}, ensure_ascii=False))
    for r in summ["pending"]:
        print("待開打：", r["date"], r["away"], "@", r["home"], "押", r["pick"], "模型", r["p_model"], "賠率", r["odds_home"], r["odds_away"])


if __name__ == "__main__":
    main()
