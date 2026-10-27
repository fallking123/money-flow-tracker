"""
職業版・獨立網頁：重算 CLV 報告＋資料檢查，嵌進 pro/page.html，輸出 pro/dist/index.html（發布成獨立的 artifact）
用法：python3 -m pro.build_page
"""
import json
import os
from datetime import datetime, timezone

from pro import clv, datacheck

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    rep = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "soccer_report.json")
    data = {"generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
            "clv": clv.main(), "check": datacheck.main(),
            "soccer": json.load(open(rep, encoding="utf-8")) if os.path.exists(rep) else None}
    us = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "us_report.json")
    if os.path.exists(us):
        u = json.load(open(us, encoding="utf-8"))
        for k in u.values():           # 網頁不需要校準以外的大清單
            k["grid_n"] = len(k.pop("grid", None) or [])
        data["us"] = u
    # 特徵搜尋：每個運動一份紀錄；最終門檻依「這個運動總共試了幾次」重算
    from scipy.stats import norm
    data["search"] = {}
    for sp, fn in (("mlb", "search_log.json"), ("soccer", "search_log_soccer.json"), ("nba", "search_log_nba.json"), ("nfl", "search_log_nfl.json"), ("nhl", "search_log_nhl.json")):
        sl = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", fn)
        if not os.path.exists(sl):
            continue
        L = json.load(open(sl, encoding="utf-8"))
        n = len(L["tries"])
        thr = round(float(norm.ppf(1 - 0.05 / max(1, n))), 2)
        for t in L["tries"]:
            t["pass_final"] = bool(t["z"] >= thr and t["better_blocks"] >= 3 and not t.get("peek"))
            for k in ("blocks",):
                t.pop(k, None) if sp != "mlb" else None
        L["final_threshold"], L["n_tries"] = thr, n
        data["search"][sp] = L
    lv = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "live")
    if os.path.exists(os.path.join(lv, "nhl_summary.json")):
        import csv as _csv
        data["live_nhl"] = json.load(open(os.path.join(lv, "nhl_summary.json"), encoding="utf-8"))
        allr = list(_csv.DictReader(open(os.path.join(lv, "nhl.csv"), encoding="utf-8")))
        data["live_nhl"]["picks_list"] = [r for r in allr if r.get("pick")]
        from pro import live_report
        data["live_nhl"]["weekly"] = live_report.weekly(allr)   # 每一場都看收盤有沒有往模型移（週報）
        # 每日對照表：還沒打的＋最近 2 天打完的，每一場都列（不只有下注的）
        from datetime import timedelta as _td
        cut = (datetime.now(timezone.utc) - _td(days=2, hours=6)).date().isoformat()
        data["live_nhl"]["board"] = [{k: r.get(k) for k in ("date", "home", "away", "p_model", "fair_home_dec", "pick", "edge", "close_fair_home", "result", "how")}
                                     for r in allr if r["date"] >= cut or not r.get("result")]
    cp = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "combo_report.json")
    if os.path.exists(cp):
        data["combo"] = json.load(open(cp, encoding="utf-8"))
    au = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "audit_clean.json")
    if os.path.exists(au):
        data["audit"] = json.load(open(au, encoding="utf-8")).get("robust")
    rp = os.path.join(os.path.dirname(HERE), "docs", "data", "pro", "mlb_rule15.json")
    if os.path.exists(rp):
        data["rule15"] = json.load(open(rp, encoding="utf-8"))
    tpl = open(os.path.join(HERE, "page.html"), encoding="utf-8").read()
    js = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    out = tpl.replace("/*__DATA__*/null", js)
    os.makedirs(os.path.join(HERE, "dist"), exist_ok=True)
    path = os.path.join(HERE, "dist", "index.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(out)
    print(f"職業版網頁 → {path}（{len(out) // 1024} KB）")


if __name__ == "__main__":
    main()
