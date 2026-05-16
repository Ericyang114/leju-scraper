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

# ── 桃園市行政區對照表 ─────────────────────────────────────────────────────────

TAOYUAN_DISTRICTS = [
    {"name": "桃園區", "post_code": "330"},
    {"name": "中壢區", "post_code": "320"},
    {"name": "大溪區", "post_code": "335"},
    {"name": "楊梅區", "post_code": "326"},
    {"name": "蘆竹區", "post_code": "338"},
    {"name": "大園區", "post_code": "337"},
    {"name": "龜山區", "post_code": "333"},
    {"name": "八德區", "post_code": "334"},
    {"name": "龍潭區", "post_code": "325"},
    {"name": "平鎮區", "post_code": "324"},
    {"name": "新屋區", "post_code": "327"},
    {"name": "觀音區", "post_code": "328"},
    {"name": "復興區", "post_code": "336"},
]

_POST_CODE_MAP = {d["post_code"]: d["name"] for d in TAOYUAN_DISTRICTS}


# ── 路由 ──────────────────────────────────────────────────────────────────────

@app.route("/")
def landing():
    stats = db.get_subarea_stats()
    last  = db.get_last_scrape()
    return render_template("landing.html", stats=stats, last_scrape=last)


@app.route("/price")
def price_districts():
    """桃園市各行政區選擇頁。"""
    district_stats = {r["post_code"]: r for r in db.get_district_stats()}
    districts = []
    for d in TAOYUAN_DISTRICTS:
        stat = district_stats.get(d["post_code"], {})
        districts.append({
            "name":          d["name"],
            "post_code":     d["post_code"],
            "subarea_count": stat.get("subarea_count", 0),
            "tx_count":      stat.get("tx_count", 0),
            "avg_unit_price":stat.get("avg_unit_price"),
            "latest_date":   stat.get("latest_date"),
            "has_data":      bool(stat.get("tx_count", 0)),
        })
    return render_template("districts.html", districts=districts)


@app.route("/price/<district_name>")
def price_district(district_name):
    """某行政區的生活圈列表。"""
    d = next((x for x in TAOYUAN_DISTRICTS if x["name"] == district_name), None)
    if not d:
        return "找不到該行政區", 404
    stats = db.get_subareas_by_post_code(d["post_code"])
    return render_template("district.html",
                           district_name=district_name,
                           stats=stats)


@app.route("/dashboard")
def index():
    stats   = db.get_subarea_stats()
    last    = db.get_last_scrape()
    running = _scrape_running
    return render_template("index.html", stats=stats, last_scrape=last, running=running)


@app.route("/subarea/<int:sid>")
def subarea(sid):
    sa = db.get_subarea_by_sid(sid)
    if not sa:
        return redirect(url_for("landing"))

    page           = max(1, int(request.args.get("page", 1)))
    per_page       = 50
    age_filter     = request.args.get("age", "all")
    type_filter    = request.args.get("type", "all")
    special_filter = request.args.get("special", "exclude")
    date_from      = request.args.get("date_from", "")
    date_to        = request.args.get("date_to", "")

    valid_ages    = {"all", "presale", "ready", "0-5", "5-10", "10-20", "20+"}
    valid_special = {"all", "exclude", "only"}
    if age_filter     not in valid_ages:    age_filter     = "all"
    if special_filter not in valid_special: special_filter = "exclude"

    total, txs  = db.get_transactions(
        sid, page=page, per_page=per_page,
        age_filter=age_filter, type_filter=type_filter,
        special_filter=special_filter, date_from=date_from, date_to=date_to,
    )
    total_pages    = max(1, math.ceil(total / per_page))
    bldg_types     = db.get_building_types(sid)
    filtered_stats = db.get_filtered_stats(
        sid, age_filter=age_filter, type_filter=type_filter,
        special_filter=special_filter, date_from=date_from, date_to=date_to,
    )
    trend = db.get_subarea_quarterly_trend(sid)

    return render_template(
        "subarea.html",
        subarea=sa,
        transactions=txs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        age_filter=age_filter,
        type_filter=type_filter,
        special_filter=special_filter,
        date_from=date_from,
        date_to=date_to,
        bldg_types=bldg_types,
        filtered_stats=filtered_stats,
        trend=trend,
    )


@app.route("/community/<int:sid>")
def community(sid):
    sa = db.get_subarea_by_sid(sid)
    if not sa:
        return redirect(url_for("landing"))

    name = request.args.get("name", "").strip()
    if not name:
        return redirect(url_for("subarea", sid=sid))

    stats = db.get_community_stats(name, sid)
    if not stats:
        return redirect(url_for("subarea", sid=sid))

    yearly = db.get_community_yearly(name, sid)

    page           = max(1, int(request.args.get("page", 1)))
    per_page       = 50
    special_filter = request.args.get("special", "exclude")
    date_from      = request.args.get("date_from", "")
    date_to        = request.args.get("date_to", "")

    valid_special = {"all", "exclude", "only"}
    if special_filter not in valid_special: special_filter = "exclude"

    total, txs = db.get_community_transactions(
        name, sid, page=page, per_page=per_page,
        special_filter=special_filter, date_from=date_from, date_to=date_to,
    )
    total_pages = max(1, math.ceil(total / per_page))

    return render_template(
        "community.html",
        subarea=sa,
        community_name=name,
        stats=stats,
        yearly=yearly,
        transactions=txs,
        total=total,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        special_filter=special_filter,
        date_from=date_from,
        date_to=date_to,
    )


@app.route("/api/communities")
def api_communities():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])
    results = db.search_communities(q, limit=8)
    return jsonify(results)


@app.route("/api/community-coords")
def api_community_coords():
    name = request.args.get("name", "").strip()
    sid_str = request.args.get("sid", "")
    sid = int(sid_str) if sid_str.isdigit() else None
    if not name:
        return jsonify({"error": "name required"}), 400
    coords = db.get_community_coords(name, sid)
    if coords and coords.get("lat") and coords.get("lon"):
        return jsonify({"lat": coords["lat"], "lon": coords["lon"]})
    return jsonify({"error": "not found"}), 404


@app.route("/api/estimate")
def api_estimate():
    name = request.args.get("name", "").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    sid_str = request.args.get("sid", "")
    sid = int(sid_str) if sid_str.isdigit() else None
    result = db.get_community_estimate(name, sid)
    if not result:
        return jsonify({"tx_count": 0})
    return jsonify(result)


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    if _scrape_running:
        return jsonify({"status": "already_running", "message": "爬蟲執行中，請稍後"})
    full = request.args.get("full", "0") == "1"
    if full:
        # 強制全量：清除 scrape_log 讓 scraper 從 FULL_SCRAPE_FROM 重新開始
        db.clear_scrape_log()
    threading.Thread(target=_run_scrape, daemon=True).start()
    msg = "已啟動全量重新抓取，資料量大約需 20–40 分鐘" if full else "已啟動，約需 2–5 分鐘"
    return jsonify({"status": "started", "message": msg})


@app.route("/api/status")
def api_status():
    last = db.get_last_scrape()
    return jsonify({"running": _scrape_running, "last_scrape": last})


@app.route("/api/push-data", methods=["POST"])
def api_push_data():
    """本機爬蟲推送資料到雲端的接口（需 X-Api-Key 驗證）。"""
    expected_key = os.environ.get("PUSH_API_KEY", "")
    if not expected_key or request.headers.get("X-Api-Key", "") != expected_key:
        return jsonify({"error": "unauthorized"}), 401

    payload  = request.get_json(force=True, silent=True) or {}
    subareas = payload.get("subareas", [])
    txs      = payload.get("transactions", [])
    coords   = payload.get("community_coords", [])
    info     = payload.get("scrape_info", {})

    if subareas:
        db.upsert_subareas(subareas)
    if txs:
        db.upsert_transactions(txs)
    if coords:
        db.upsert_community_coords(coords)
    if info.get("status"):
        db.log_scrape(info["status"], info.get("message", ""), info.get("records_count", len(txs)))

    return jsonify({"status": "ok", "subareas": len(subareas),
                    "transactions": len(txs), "coords": len(coords)})


@app.route("/healthz")
def healthz():
    """Render health check endpoint."""
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    app.run(host="0.0.0.0", port=port, debug=False)
