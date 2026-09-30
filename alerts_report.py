"""
推播用：列出「上一次推播之後」新出現、而且還沒開賽的划算注（alerts.py 記的）
排程任務「划算注推播」固定在 SLOTS 這幾個台灣時間跑，所以「上一次」就是前一個時段。
沒有新的就印 NONE。

用法：python alerts_report.py            （照現在時間算）
      python alerts_report.py --hours 24  （列最近 24 小時的，測試用）
"""
import sys
from datetime import datetime, timedelta, timezone

from sports_common import active_sports, parse_time, read_rows
from alerts import MK, path_for

TW = timezone(timedelta(hours=8))
SLOTS = [7, 8, 9, 10, 12, 18, 20, 22]   # 台灣時間幾點推播（要跟排程任務一致）
SLACK_MIN = 10                          # 排程常晚幾分鐘開始，多抓一點避免漏掉
LG = {"epl": "英超", "laliga": "西甲", "seriea": "義甲", "bundesliga": "德甲", "ligue1": "法甲", "ucl": "歐冠"}


def prev_slot(now):
    """現在這次之前的上一個推播時段（台灣時間整點）"""
    local = now.astimezone(TW)
    cands = []
    for d in (0, 1):
        day = (local - timedelta(days=d)).date()
        for h in SLOTS:
            cands.append(datetime(day.year, day.month, day.day, h, tzinfo=TW))
    cur = max(c for c in cands if c <= local)          # 這次（排程觸發的時段）
    return max(c for c in cands if c < cur)


def report(now, since):
    rows = []
    for sport in list(active_sports()) + ["soccer"]:
        for r in read_rows(path_for(sport)):
            if parse_time(r["created_utc"]) > since - timedelta(minutes=SLACK_MIN) and parse_time(r["game_time_utc"]) > now:
                rows.append(r)
    if not rows:
        return "NONE"
    # 同一個選項台彩、美國都划算就合成一行
    by = {}
    for r in rows:
        by.setdefault((r["game_id"], r["market"], r["side"], r["line"]), []).append(r)
    items = sorted(by.values(), key=lambda rs: rs[0]["game_time_utc"])
    lines = [f"划算的注 {len(items)} 個（期望值 ≥ +2%）"]
    for rs in items:
        r = rs[0]
        t = parse_time(r["game_time_utc"]).astimezone(TW).strftime("%m/%d %H:%M")
        lg = LG.get(r["league"], "足球") if r["sport"] == "soccer" else r["sport"].upper()
        match = f"{r['home_zh']} vs {r['away_zh']}" if r["sport"] == "soccer" else f"{r['away_zh']} @ {r['home_zh']}"
        parts = []
        for x in sorted(rs, key=lambda x: x["kind"] != "tw"):
            ev = float(x["ev"]) * 100
            if x["kind"] == "tw":
                src = "實際" if x["odds_src"] == "actual" else "估"
                stake = f"，建議下本金 {float(x['stake_pct']):.1f}%" if x["stake_pct"] else ""
                parts.append(f"台彩 {float(x['odds']):.2f}（{src}）期望值 {ev:+.1f}%{stake}")
            else:
                parts.append(f"美國賠率 {float(x['odds']):.2f} 期望值 {ev:+.1f}%")
        need = (1.02) / float(r["p"])
        lines.append(f"・{t} {lg} {match}｜{MK[r['market']]} {r['pick_zh']}｜" + "；".join(parts)
                     + ("" if any(x["kind"] == "tw" for x in rs) else f"（台彩要 ≥ {need:.2f} 才划算）"))
    lines.append("勝率來源：獨贏用模型一，讓分／大小用 Pinnacle。下注前看一下台彩實際賠率，在看板「我的投注」填上就會算建議金額。")
    return "\n".join(lines)


if __name__ == "__main__":
    now = datetime.now(timezone.utc)
    if "--hours" in sys.argv:
        since = now - timedelta(hours=float(sys.argv[sys.argv.index("--hours") + 1]))
    else:
        since = prev_slot(now)
    print(report(now, since))
