"""
檢查常駐工作有沒有準時：從某個時間點起
- 美國四大每 10 分鐘那一輪，實際一小時跑幾次、最長隔多久（看 git 紀錄的「資金流向快照更新」）
- 開賽前 5 分鐘截圖：打完的比賽有幾場有截到、截在開賽前幾分鐘
用法：python3 check_resident.py 2026-10-12T13:33
"""
import csv
import glob
import statistics
import subprocess
import sys
from datetime import datetime, timezone


def main(since):
    t0 = datetime.fromisoformat(since).replace(tzinfo=timezone.utc)
    log = subprocess.run(["git", "log", f"--since={since}Z", "--format=%cI|%s"], capture_output=True, text=True).stdout.split("\n")
    us = sorted(datetime.fromisoformat(l.split("|")[0]).astimezone(timezone.utc) for l in log if l.endswith("資金流向快照更新"))
    if len(us) > 1:
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(us, us[1:])]
        hrs = (us[-1] - us[0]).total_seconds() / 3600
        print(f"美國四大每 10 分鐘：{len(us)} 輪，一小時 {len(us) / hrs:.1f} 次（目標 6），間隔中位數 {statistics.median(gaps):.0f} 分、最長 {max(gaps):.0f} 分")
    for sp in ("nfl", "nhl", "mlb", "nba"):
        fin = []
        for f in glob.glob(f"docs/data/{sp}/odds_history_*_final.csv"):
            fin += [r for r in csv.DictReader(open(f)) if r["timestamp_utc"] >= since]
        try:
            res = [r for r in csv.DictReader(open(f"docs/data/{sp}/results.csv")) if r["game_time_utc"][:16] >= since]
        except FileNotFoundError:
            continue
        if not res:
            continue
        ids = {r["sbd_id"] for r in fin}
        got = [r for r in res if r["sbd_id"] in ids]
        mins = sorted(float(r["hours_until_game"]) * 60 for r in fin)
        print(f"{sp.upper()}：打完 {len(res)} 場，開賽前有截到 {len(got)} 場"
              + (f"，截在開賽前 {mins[0]:.1f}–{mins[-1]:.1f} 分鐘" if mins else ""))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "2026-10-12T13:33")
