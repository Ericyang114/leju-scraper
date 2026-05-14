"""
Flask 後端 + APScheduler 每日自動更新
"""
import logging
import math
import os
import threading
from datetime import date, datetime

from flask import Flask, jsonify, redirect, render_template, request, url_for
from apscheduler.schedulers.background import BackgroundScheduler

import db
from scraper import scrape

log = logging.getLogger(__name__)

app = Flask(__name__)
db.init_db()

# ── 排程 ──────────────────────────────────────────────────────────────────────

_scrape_lock    = threading.Lock()
_scrape_running = False


def _run_scrape():
    global _scrape_running
    if _scrape_running:
        return
    _scrape_running = True
    try:
        scrape()
    finally:
        _scrape_running = False


def _needs_today_scrape() -> bool:
    """判斷今天是否還沒爬過（用於重啟後自動補抓）。"""
    last = db.get_last_scrape()
    if not last or last["status"] != "success":
        return True
    try:
        last_date = datetime.fromisoformat(last["scraped_at"]).date()
        return last_date < date.today()
    except Exception:
        return True


# 啟動時：若今天還沒有資料（首次部署或重啟後 DB 空了），自動開始抓取
if not _scrape_running:
    if _needs_today_scrape():
        log.info("啟動自動抓取（DB 無今日資料）")
        threading.Thread(target=_run_scrape, daemon=True).start()

# 每天凌晨 2:00 自動更新
scheduler = BackgroundScheduler(timezone="Asia/Taipei")
scheduler.add_job(_run_scrape, "cron", hour=2, minute=0, id="daily_scrape")
scheduler.start()

# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    stats   = db.get_subarea_stats()
    last    = db.get_last_scrape()
    running = _scrape_running
    return render_template("index.html", stats=stats, last_scrape=last, running=running)


@app.route("/subarea/<int:sid>")
def subarea(sid):
    sa = db.get_subarea_by_sid(sid)
    if not sa:
        return redirect(url_for("index"))

    page     = max(1, int(request.args.get("page", 1)))
    per_page = 50
    total, txs = db.get_transactions(sid, page=page, per_page=per_page)
    total_pages = max(1, math.ceil(total / per_page))

    return render_template(
        "subarea.html",
        subarea=sa,
        transactions=txs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
    )


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if _scrape_running:
        return jsonify({"status": "already_running", "message": "爬蟲執行中，請稍後"})
    threading.Thread(target=_run_scrape, daemon=True).start()
    return jsonify({"status": "started", "message": "已啟動，約需 2–5 分鐘"})


@app.route("/api/status")
def api_status():
    last = db.get_last_scrape()
    return jsonify({"running": _scrape_running, "last_scrape": last})


@app.route("/healthz")
def healthz():
    """Render health check endpoint."""
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    app.run(host="0.0.0.0", port=port, debug=False)
