"""
職業版・NHL 實戰週報：每一場都看「收盤有沒有往模型那邊移」（不只規則觸發的那幾注）
================================================================
規則觸發一季只有約 50 注，靠輸贏要好幾季才看得出來；每一場都看 CLV 快很多。
每一場：用決定時的 Pinnacle 賠率，押模型期望值比較高的那一邊（不管多少），打完跟 Pinnacle 收盤比：
- clv：收盤（去抽水）勝率 × 決定時賠率 − 1（下注的人真的拿到的，含抽水）
- base：兩邊各押一半的 CLV＝「只是付抽水」的水準；clv 比 base 高才代表模型挑邊有用
- move：收盤勝率 − 決定時勝率（都去抽水），站在模型那一邊看，單位＝百分點；> 0 ＝往模型移
資料：docs/data/pro/live/nhl.csv（pro/live_nhl.py 產生）。build_page.py 呼叫 weekly()。
"""
import math
from datetime import date, timedelta


def _f(v):
    try:
        return float(v) if v not in ("", None) else None
    except ValueError:
        return None


def _stat(xs):
    n = len(xs)
    if not n:
        return None
    m = sum(xs) / n
    se = math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1)) / math.sqrt(n) if n > 1 else None
    return {"n": n, "mean": round(m, 4), "se": None if se is None else round(se, 4)}


def game_rows(rows):
    """每一場打完、有收盤的比賽 → {week, how, clv, base, move, rule}"""
    out = []
    for r in rows:
        cf, p, oh, oa, fd = (_f(r.get(k)) for k in ("close_fair_home", "p_model", "odds_home", "odds_away", "fair_home_dec"))
        if None in (cf, p, oh, oa, fd) or oh <= 1 or oa <= 1:
            continue
        home = p * oh - 1 >= (1 - p) * oa - 1
        q, o = (cf, oh) if home else (1 - cf, oa)
        d = date.fromisoformat(r["date"])
        out.append({"week": (d - timedelta(days=d.weekday())).isoformat(), "how": r.get("how") or "",
                    "clv": q * o - 1, "base": (cf * oh + (1 - cf) * oa) / 2 - 1,
                    "move": (cf - fd) if home else (fd - cf), "rule": bool(r.get("pick")),
                    "rule_clv": _f(r.get("clv")) if r.get("pick") else None})
    return out


def _agg(gs):
    tow = sum(1 for g in gs if g["move"] > 0.005)
    awy = sum(1 for g in gs if g["move"] < -0.005)
    edge = [g["clv"] - g["base"] for g in gs]   # 比「只付抽水」好多少
    return {"n": len(gs), "clv": _stat([g["clv"] for g in gs]), "base": _stat([g["base"] for g in gs]),
            "edge": _stat(edge), "move": _stat([g["move"] for g in gs]), "toward": tow, "away": awy,
            "rule_n": sum(g["rule"] for g in gs), "rule_clv": _stat([g["rule_clv"] for g in gs if g["rule_clv"] is not None])}


def weekly(rows):
    gs = game_rows(rows)
    weeks = []
    for w in sorted({g["week"] for g in gs}):
        sel = [g for g in gs if g["week"] == w]
        hows = {g["how"] for g in sel}
        weeks.append({"week": w, "how": "回補" if hows == {"回補"} else ("實戰" if hows == {"實戰"} else "混合"), **_agg(sel)})
    return {"all": _agg(gs), "live": _agg([g for g in gs if g["how"] == "實戰"]), "weeks": weeks}


if __name__ == "__main__":
    import csv
    import json
    import os
    p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs", "data", "pro", "live", "nhl.csv")
    print(json.dumps(weekly(list(csv.DictReader(open(p, encoding="utf-8")))), ensure_ascii=False, indent=1))
