"""
基準賠率（使用者 2026-10-26 指定）：用 Pinnacle 和 bet365 這兩家世界級大莊家當基準。
- 兩家都有 → 取平均（把兩家的機率平均，再換回賠率）
- 只有一家 → 用那一家
- 都沒有 → 呼叫的地方自己退回美國共識盤
用在：估台彩賠率、校正「台彩在機率上加多少」。美國賠率的策略照舊用美國共識盤結算。

資料：
- Pinnacle：scrape_pinnacle.py（美國四大每 10 分、足球每小時；只記開賽前）→ g["pin"]["l"]＝開賽前最後一筆
- bet365：美國四大 odds_books_YYYY-MM.csv 的 Bet365.US.NJ（SportsBettingDime，每 10 分）→ g["b365"]
  足球目前沒有即時的 bet365（football-data 一週才更新兩次，太舊不用）。
"""
from sports_common import parse_time, read_rows, recent_monthly_files

B365_BOOK = "Bet365.US.NJ"
MKT = {"moneyline": "ml", "spread": "sp", "total": "ou"}


def am_to_dec(v):
    try:
        a = float(v)
    except (TypeError, ValueError):
        return None
    if a == 0:
        return None
    return round(1 + (a / 100 if a > 0 else 100 / -a), 4)


def _f(v):
    try:
        return float(v) if v not in (None, "") else None
    except ValueError:
        return None


def load_b365(sport, months=2):
    """{sbd_id: [(時間, 玩法, 邊, 盤口, 十進位賠率), ...]}（按時間排好）"""
    out = {}
    for path in recent_monthly_files(sport, "odds_books", months=months):
        for r in read_rows(path):
            if r["book"] != B365_BOOK or r["market"] not in MKT:
                continue
            o = am_to_dec(r["odds_american"])
            if not o:
                continue
            out.setdefault(r["sbd_id"], []).append((r["timestamp_utc"], MKT[r["market"]], r["side"], _f(r["line"]), o))
    for v in out.values():
        v.sort(key=lambda x: x[0])
    return out


def b365_snap(rows, t):
    """開賽前最後一筆 → {'ml': {away, home}, 'sp': {away: [盤口, 賠率], home: [...]}, 'ou': {line, over, under}}"""
    if not rows:
        return None
    last = {}
    for ts, mkt, side, ln, o in rows:
        if t is not None and parse_time(ts) >= t:
            break
        last[(mkt, side)] = (ln, o)
    if not last:
        return None
    out = {}
    ml = {s: o for (m, s), (_, o) in last.items() if m == "ml"}
    if len(ml) == 2:
        out["ml"] = ml
    sp = {s: [ln, o] for (m, s), (ln, o) in last.items() if m == "sp" and ln is not None}
    if len(sp) == 2:
        out["sp"] = sp
    ov, un = last.get(("ou", "over")), last.get(("ou", "under"))
    if ov and un and ov[0] is not None and ov[0] == un[0]:
        out["ou"] = {"line": ov[0], "over": ov[1], "under": un[1]}
    return out or None


def _side(snap, mkt, key, line):
    """某一家這一注的賠率（盤口要一樣才算）"""
    if not snap or not snap.get(mkt):
        return None
    s = snap[mkt]
    if mkt == "ml":
        o = s.get(key)
    elif mkt == "sp":
        v = s.get(key)
        o = v[1] if v and (line is None or (v[0] is not None and abs(v[0] - line) < 1e-6)) else None
    else:
        o = s.get(key) if (line is None or (s.get("line") is not None and abs(s["line"] - line) < 1e-6)) else None
    return o if o and o > 1 else None


def pick(g, mkt, key, line=None):
    """這一注的基準賠率 → (賠率, 來源 'pin+b365'／'pin'／'b365')；兩家都沒有回傳 (None, None)"""
    if not g:
        return None, None
    p = _side(((g.get("pin") or {}).get("l")), mkt, key, line)
    b = _side(g.get("b365"), mkt, key, line)
    if p and b:
        return round(2 / (1 / p + 1 / b), 4), "pin+b365"
    if p:
        return p, "pin"
    if b:
        return b, "b365"
    return None, None
