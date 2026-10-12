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
            k.pop("grid", None)
        data["us"] = u
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
