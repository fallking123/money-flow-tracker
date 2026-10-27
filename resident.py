"""
常駐工作：不靠 GitHub 排程準時，自己看時鐘抓資料
================================================================
GitHub 的免費排程不保證準時（實測設每 10 分鐘，實際常常 20–40 分鐘才跑一次），
開賽前 5 分鐘的截圖因此漏了不少場。改成：一個工作一直開著（最多 6 小時），自己看時鐘做事：

- 每 10 分鐘（:00、:10、:20…）：美國四大資金流向＋其他玩法＋Pinnacle＋模型記錄＋划算注（跟 scrape_odds.yml 一樣的步驟）
- 每小時 :25：足球（跟 scrape_soccer.yml 一樣的步驟）
- 每場比賽開賽前 5 分鐘：截最後一筆（跟 final_snapshot.yml 一樣，存在 *_final.csv）
- 每次做完就 commit＋push，並更新心跳檔 docs/data/state/resident.json

交棒：resident.yml 每小時排一次，同一時間只會有一個在跑、一個在排隊；
這個跑到 5 小時 40 分（如果 8 分鐘內有比賽要截，就截完再走）就結束，排隊的那個馬上接手。
備援：原本的三個排程還在，開頭先看心跳檔，常駐工作 25 分鐘內有心跳就直接跳過，沒有才照舊做。

用法：python resident.py            （常駐）
      python resident.py --alive    （有心跳就 exit 0，給舊排程判斷要不要跳過）
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
HEARTBEAT = os.path.join(HERE, "docs", "data", "state", "resident.json")
CYCLE_MIN = 10
SOCCER_AT = 25          # 每小時幾分抓足球
RUN_MIN = 340           # 跑多久就交棒（5 小時 40 分；GitHub 一個工作最多 6 小時）
FINAL_LEAD_MIN = 5
HANDOFF_GUARD_MIN = 8   # 要交棒時，這麼多分鐘內有比賽要截，就等截完再走
ALIVE_MIN = 25
US_STEPS = ["python scrape_extra.py", "python scrape_pinnacle.py mlb,nba,nfl,nhl", "python -m pro.injury_watch nba",
            "python track_models.py mlb,nba,nfl,nhl", "python alerts.py mlb,nba,nfl,nhl"]
SOCCER_STEPS = ["python scrape_soccer.py", "python scrape_pinnacle.py soccer",
                "python track_models.py soccer", "python alerts.py soccer", "python niche_ledger.py"]   # 冷門玩法帳本（10/27）


def now():
    return datetime.now(timezone.utc)


def log(msg):
    print(f"[{now():%H:%M:%S}Z] {msg}", flush=True)


def sh(cmd, timeout=600, env=None):
    try:
        r = subprocess.run(cmd, shell=True, cwd=HERE, timeout=timeout, env=env)
        return r.returncode
    except subprocess.TimeoutExpired:
        log(f"逾時：{cmd}")
        return 124


def git_save(msg):
    sh("git add docs/data")
    if subprocess.run("git diff --cached --quiet", shell=True, cwd=HERE).returncode == 0:
        return
    sh(f'git commit -q -m "{msg}"')
    for i in range(6):
        if sh("git pull -q --rebase") == 0 and sh("git push -q") == 0:
            return
        sh("git rebase --abort", timeout=60)
        if i >= 2 and sh("git pull -q --rebase -X theirs") == 0 and sh("git push -q") == 0:
            log("有衝突，用這邊的版本存檔")
            return
        time.sleep(10)
    log("push 失敗，下一輪再試")


def heartbeat(info):
    os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
    with open(HEARTBEAT, "w", encoding="utf-8") as f:
        json.dump({**info, "beat": now().strftime("%Y-%m-%dT%H:%M:%SZ")}, f, ensure_ascii=False, indent=1)


def alive():
    try:
        with open(HEARTBEAT, encoding="utf-8") as f:
            beat = datetime.strptime(json.load(f)["beat"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return now() - beat < timedelta(minutes=ALIVE_MIN)
    except Exception:
        return False


_browser_ready = False


def us_cycle():
    global _browser_ready
    if os.path.exists(os.path.join(HERE, ".nothing_due")):
        os.remove(os.path.join(HERE, ".nothing_due"))
    code = sh("python scrape_odds.py")
    if code == 3:
        log("直接讀取被擋，改用瀏覽器模式")
        if not _browser_ready:
            sh("pip install -q playwright==1.47.0 && playwright install --with-deps chromium", timeout=900)
            _browser_ready = True
        sh("python scrape_odds.py --browser")
    if os.path.exists(os.path.join(HERE, ".nothing_due")):
        return False
    for c in US_STEPS:
        if sh(c) != 0:
            log(f"失敗但不影響主資料：{c}")
    return True


def soccer_cycle():
    for c in SOCCER_STEPS:
        if sh(c) != 0:
            log(f"失敗但不影響主資料：{c}")


def next_slot(t, every_min, offset_min=0):
    """t 之後（不含）下一個整點對齊的時間，例如每 10 分鐘 → :00 :10 …；offset_min＝每小時第幾分"""
    base = t.replace(second=0, microsecond=0)
    m = base.minute
    if every_min == 60:
        cand = base.replace(minute=offset_min)
        return cand if cand > t else cand + timedelta(hours=1)
    nxt = (m // every_min + 1) * every_min
    return base.replace(minute=0) + timedelta(minutes=nxt)


def main():
    sys.path.insert(0, HERE)
    import scrape_odds as SO

    start = now()
    deadline = start + timedelta(minutes=RUN_MIN)
    info = {"run_id": os.environ.get("GITHUB_RUN_ID", "local"), "started": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "deadline": deadline.strftime("%Y-%m-%dT%H:%M:%SZ")}
    log(f"常駐工作開始，{deadline:%H:%M}Z 交棒")
    done = SO.final_load_done()
    targets = []
    next_us, next_soccer = start, next_slot(start, 60, SOCCER_AT)
    stats = {"us": 0, "soccer": 0, "final": 0}
    while True:
        t = now()
        # 1) 開賽前 5 分鐘：時間到了、還沒開打、還沒截過的
        due = [x for x in targets if x[0] - timedelta(minutes=FINAL_LEAD_MIN) <= t + timedelta(seconds=20) and x[2] not in done]
        if due:
            first = min(x[0] for x in due)
            batch = [x for x in due if x[0] - first <= timedelta(minutes=2)]
            n = SO.final_capture(batch, done)
            done = SO.final_save_done(done)
            stats["final"] += n
            targets = [x for x in targets if x[2] not in done]
            heartbeat({**info, **stats})
            git_save("開賽前 5 分鐘快照")
            continue
        # 2) 每 10 分鐘：美國四大
        if t >= next_us:
            log("美國四大：資金流向／Pinnacle／模型記錄／划算注")
            us_cycle()
            stats["us"] += 1
            targets = SO.final_targets(now(), done)
            heartbeat({**info, **stats, "next_final": targets[0][0].strftime("%Y-%m-%dT%H:%MZ") if targets else None})
            git_save("資金流向快照更新")
            next_us = next_slot(now(), CYCLE_MIN)
            continue
        # 3) 每小時 :25：足球
        if t >= next_soccer:
            log("足球")
            soccer_cycle()
            stats["soccer"] += 1
            heartbeat({**info, **stats})
            git_save("足球資料更新")
            next_soccer = next_slot(now(), 60, SOCCER_AT)
            continue
        # 4) 交棒
        if t >= deadline:
            soon = [x for x in targets if x[0] - timedelta(minutes=FINAL_LEAD_MIN) <= t + timedelta(minutes=HANDOFF_GUARD_MIN)]
            if not soon:
                log(f"交棒：美國 {stats['us']} 輪、足球 {stats['soccer']} 輪、開賽前截了 {stats['final']} 場")
                break
        # 睡到下一件事（最多 30 秒醒來看一次，開賽時間可能會改）
        nxt = [next_us, next_soccer] + [x[0] - timedelta(minutes=FINAL_LEAD_MIN) for x in targets]
        wait = max(1.0, min(30.0, (min(nxt) - now()).total_seconds()))
        time.sleep(wait)


if __name__ == "__main__":
    if "--alive" in sys.argv:
        sys.exit(0 if alive() else 1)
    main()
