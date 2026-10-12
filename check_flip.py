"""
參考策略「模型一・低於 1.4 改押對面」累積夠了沒？（每週排程跑，夠了就提醒）
================================================================
「改過的注」＝模型一・台彩押的那邊台彩賠率低於 1.4、改押對面那一隊的注（已開獎）。
改過的注還不到 GOAL 注：只印 NONE。
到了：印出一段繁體中文報告（改過的注照原本押 vs 改押對面，各賺賠多少）。

用法：python3 check_flip.py
"""
import csv
import glob

from build_dashboard import FLIP_ODDS

GOAL = 100
UNIT = 1000
DONE = ("win", "loss", "push")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    rows = []
    for f in glob.glob("docs/data/*/model_picks.csv"):
        rows += list(csv.DictReader(open(f, encoding="utf-8")))
    side = {(r["game_id"], r["pick"]): r for r in rows if r["strategy"] in ("favorite", "underdog")}
    orig = flip = 0.0
    n = won_o = won_f = 0
    total_o = total_f = 0.0
    for r in rows:
        if r["strategy"] != "model1" or r["result"] not in DONE:
            continue
        pl = num(r["profit"]) or 0.0
        total_o += pl
        o = num(r["settle_odds"]) or num(r["tw_odds"])
        opp = {"home": "away", "away": "home"}.get(r["pick"])
        f = side.get((r["game_id"], opp)) if o and o < FLIP_ODDS and opp else None
        if not f or f["result"] not in DONE:
            total_f += pl
            continue
        fp = num(f["profit"]) or 0.0
        total_f += fp
        n += 1
        orig += pl
        flip += fp
        won_o += r["result"] == "win"
        won_f += f["result"] == "win"
    if n < GOAL:
        print("NONE")
        return
    better = flip > orig
    print(f"【參考策略累積到 {n} 注了】模型一・低於 {FLIP_ODDS} 改押對面\n"
          f"台彩賠率低於 {FLIP_ODDS} 的 {n} 注（每注 {UNIT:,} 元）：\n"
          f"・照模型一原本押：中 {won_o} 注，賺賠 {orig * UNIT:+,.0f} 元\n"
          f"・改押對面：中 {won_f} 注，賺賠 {flip * UNIT:+,.0f} 元\n"
          f"整個策略合計：模型一 {total_o * UNIT:+,.0f} 元 → 改押對面後 {total_f * UNIT:+,.0f} 元\n"
          f"結論：改押對面{'比較好' if better else '比較差'}（差 {abs(flip - orig) * UNIT:,.0f} 元）。"
          f"注數到 {GOAL} 注只是第一次檢查，差距在幾千元以內大多還是運氣；看板「模型」頁的「參考」那一段可以看最新的。")


if __name__ == "__main__":
    main()
