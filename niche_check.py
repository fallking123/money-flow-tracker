"""
拿台彩冷門玩法賠率對帳本（niche_ledger_*.csv）
用法：python3 niche_check.py 運動 玩法 period 邊 [盤口] [台彩賠率] [--units Corners|Bookings] [--team home|away]
  例：python3 niche_check.py nhl moneyline 1 home "" 2.6          # 冰球第一節主隊（Pinnacle 第一節獨贏是兩邊，平手退錢）
      python3 niche_check.py soccer total 1 under 0.5 3.2           # 足球上半場小 0.5（＝半場 0:0）
      python3 niche_check.py nba team_total 3 over 28.5 1.75 --team home
印出：帳本裡這個選項的場數、Pinnacle 平均公平機率、實際贏的比例；給了台彩賠率就算兩種期望值
"""
import argparse
import csv
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("sport")
    ap.add_argument("market", choices=["moneyline", "spread", "total", "team_total"])
    ap.add_argument("period")
    ap.add_argument("side")
    ap.add_argument("line", nargs="?", default="")
    ap.add_argument("tw", nargs="?", type=float, default=None)
    ap.add_argument("--units", default="Regular")
    ap.add_argument("--team", default="")
    a = ap.parse_args()
    rows = [r for f in sorted(glob.glob(os.path.join(HERE, "docs", "data", "niche_ledger_*.csv"))) for r in csv.DictReader(open(f, encoding="utf-8"))]
    sel = [r for r in rows if r["sport"] == a.sport and r["units"] == a.units and r["period"] == a.period and r["market"] == a.market
           and r["side"] == a.side and r["team"] == a.team and (a.line == "" or abs(float(r["line"] or 0) - float(a.line)) < 1e-9)]
    done = [r for r in sel if r["result"] != ""]
    if not sel:
        print("帳本裡沒有這個選項")
        return
    fp = sum(float(r["fair_p"]) for r in sel) / len(sel)
    print(f"帳本：{len(sel)} 場（有結果 {len(done)}）・Pinnacle 平均公平機率 {fp * 100:.1f}%")
    if done:
        win = sum(1 for r in done if float(r["result"]) > 0) / len(done)
        push = sum(1 for r in done if float(r["result"]) == 0) / len(done)
        print(f"實際：贏 {win * 100:.1f}%・平 {push * 100:.1f}%")
    if a.tw:
        print(f"台彩 {a.tw}：用 Pinnacle 機率算期望值 {(fp * a.tw - 1) * 100:+.1f}%；保本機率 {100 / a.tw:.1f}%")


if __name__ == "__main__":
    main()
