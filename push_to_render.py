"""
本機執行腳本：
1. 在你的電腦上爬取 leju.com.tw 資料（不受雲端 IP 封鎖）
2. 自動推送到 Render 上的網站

每天執行一次即可，建議用 Windows 工作排程器自動化。
"""
import json
import logging
import os
import sqlite3
import sys
import time

import requests

# ── 設定 ─────────────────────────────────────────────────────────────────────
RENDER_URL   = os.environ.get("RENDER_URL",   "https://yanghousetalk.onrender.com")
PUSH_API_KEY = os.environ.get("PUSH_API_KEY", "")
LOCAL_DB     = os.path.join(os.path.dirname(__file__), "leju.db")
BATCH_SIZE   = 300   # 每批推送筆數，避免 timeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(os.path.dirname(__file__), "push.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ── 讀取本機 DB ───────────────────────────────────────────────────────────────

def read_local_db():
    conn = sqlite3.connect(LOCAL_DB)
    conn.row_factory = sqlite3.Row

    subareas = [dict(r) for r in conn.execute("SELECT sid, name, post_code FROM subareas")]

    rows = conn.execute("""
        SELECT id, sid, transaction_date, address, community,
               floor, total_floor, age, total_price, unit_price,
               total_area, house_area, parking_type, parking_price,
               parking_area, floor_ratio, building_type,
               is_special_trade, raw_data
        FROM transactions
        ORDER BY transaction_date DESC
    """).fetchall()

    transactions = []
    for r in rows:
        d = dict(r)
        raw_str = d.pop("raw_data", None)
        try:
            d["_raw"] = json.loads(raw_str) if raw_str else {}
        except Exception:
            d["_raw"] = {}
        transactions.append(d)

    last = conn.execute(
        "SELECT status, message, records_count FROM scrape_log ORDER BY id DESC LIMIT 1"
    ).fetchone()
    scrape_info = dict(last) if last else {}

    conn.close()
    return subareas, transactions, scrape_info


# ── 推送到 Render ─────────────────────────────────────────────────────────────

def push(payload: dict, label: str):
    resp = requests.post(
        f"{RENDER_URL}/api/push-data",
        json=payload,
        headers={"X-Api-Key": PUSH_API_KEY, "Content-Type": "application/json"},
        timeout=120,
    )
    resp.raise_for_status()
    log.info("%s → %s", label, resp.json())


def push_all(subareas, transactions, scrape_info):
    # 1. 推送生活圈
    push({"subareas": subareas, "transactions": [], "scrape_info": {}},
         f"生活圈 {len(subareas)} 個")

    # 2. 分批推送交易
    total = len(transactions)
    for i in range(0, total, BATCH_SIZE):
        batch = transactions[i: i + BATCH_SIZE]
        push({"subareas": [], "transactions": batch, "scrape_info": {}},
             f"交易 {i+1}–{min(i+BATCH_SIZE, total)}/{total}")
        time.sleep(0.5)

    # 3. 更新爬取記錄
    push({"subareas": [], "transactions": [], "scrape_info": scrape_info},
         "scrape_log 更新")


# ── 主流程 ────────────────────────────────────────────────────────────────────

def main():
    if not PUSH_API_KEY:
        log.error("請先設定 PUSH_API_KEY 環境變數！")
        sys.exit(1)

    # Step 1: 本機爬取
    log.info("=== Step 1: 開始爬取 leju.com.tw ===")
    from scraper import scrape
    ok = scrape()
    if not ok:
        log.error("爬取失敗，中止推送。")
        sys.exit(1)

    # Step 2: 讀取本機資料
    log.info("=== Step 2: 讀取本機資料 ===")
    subareas, transactions, scrape_info = read_local_db()
    log.info("生活圈 %d 個，交易 %d 筆", len(subareas), len(transactions))

    # Step 3: 推送到 Render
    log.info("=== Step 3: 推送到 %s ===", RENDER_URL)
    push_all(subareas, transactions, scrape_info)
    log.info("=== 完成！資料已同步到網站 ===")


if __name__ == "__main__":
    main()
