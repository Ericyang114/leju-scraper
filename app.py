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

DISTRICT_INFO = {
    "桃園區": {
        "intro": "桃園區是桃園市的行政與商業核心，擁有桃園市政府、桃園火車站及完整的商業機能。近年來中路、小檜溪、經國等重劃區快速發展，吸引大量新建案進駐，為桃園市推案量最大的行政區。",
        "traffic": "台鐵桃園站提供北上台北（約 25 分鐘）、南下中壢的便利交通；台 1 線、台 4 線及台 66 線快速道路貫穿全區；機場捷運桃園站可直達桃園國際機場及台北車站。捷運綠線（中壢延伸線）預計經過本區，串聯高鐵桃園站。",
        "school": "明星學區包含武陵高中、桃園高中、桃園女中、東安國中等，學區資源完整，為桃園市家長購屋首選行政區之一。",
        "life": "桃園統領百貨、大廟口商圈、中正藝文特區、桃園展演中心等生活休閒設施完備；大型量販店、連鎖餐飲集中，日常生活機能成熟。",
    },
}


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
    info  = DISTRICT_INFO.get(district_name)
    return render_template("district.html",
                           district_name=district_name,
                           stats=stats,
                           info=info)


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


@app.route("/redevelopment")
def redevelopment():
    """桃園市重劃區行情總覽頁。"""
    ZONES = [
        # 機場捷運沿線
        {"group": "機場捷運沿線重劃區", "sid": 11116, "name": "青埔 A18 高鐵生活圈",   "district": "大園區",
         "desc": "桃園高鐵站核心商圈，鄰近 IKEA、好市多、台灣世界棒球訓練中心。捷運機場線直達台北車站約 30 分鐘，為桃園新興生活圈人氣最高的區域。"},
        {"group": "機場捷運沿線重劃區", "sid": 11117, "name": "青埔 A17 領航站生活圈", "district": "大園區",
         "desc": "鄰近 Xpark 水族館、桃園展演中心，規劃大型商業設施持續到位，居住機能日漸成熟。"},
        {"group": "機場捷運沿線重劃區", "sid": 11115, "name": "青埔 A19 體育園區",    "district": "中壢區",
         "desc": "桃園國家體育場、桃園市立圖書館總館坐落本區，為青埔南端新興發展重心，未來中壢延伸捷運線規劃中。"},
        {"group": "機場捷運沿線重劃區", "sid": 11026, "name": "A10 山鼻重劃區",       "district": "蘆竹區",
         "desc": "機場捷運 A10 站周邊，鄰近桃園國際機場，近年大量建案推出，為北桃園快速成長的住宅重劃區。"},
        # A7 重劃區
        {"group": "A7 站重劃區（龜山）", "sid": 11174, "name": "A7 文青國小區",        "district": "龜山區",
         "desc": "A7 重劃區北側核心，文青非營利幼兒園及未來國小預定地，學區完整，為自住首選分區。"},
        {"group": "A7 站重劃區（龜山）", "sid": 11173, "name": "A7 中心商業區",        "district": "龜山區",
         "desc": "A7 捷運站正出口商業核心，規劃購物中心、辦公商業用地，是整個 A7 重劃區的商業發展重心。"},
        {"group": "A7 站重劃區（龜山）", "sid": 11175, "name": "A7 郵政物流區",        "district": "龜山區",
         "desc": "A7 南側住商混合區，鄰近中華郵政物流中心，住宅供給量大，成交筆數穩定。"},
        {"group": "A7 站重劃區（龜山）", "sid": 11176, "name": "A7 樂善國小區",        "district": "龜山區",
         "desc": "A7 西側住宅區，樂善非營利幼兒園及預定國小基地，生活圈規劃完整，近年交屋量大。"},
        {"group": "A7 站重劃區（龜山）", "sid": 11177, "name": "A7 體育大學區",        "district": "龜山區",
         "desc": "緊鄰國立體育大學，A7 重劃區外圍，房價相對親民，適合預算有限的首購族。"},
        # 桃園市區重劃
        {"group": "桃園市區重劃區",     "sid": 11017, "name": "中路重劃區",            "district": "桃園區",
         "desc": "桃園市政中心旁，生活機能完整成熟，知名學區林立，為桃園市精華住宅區之一，長期保值性強。"},
        {"group": "桃園市區重劃區",     "sid": 11019, "name": "小檜溪重劃區",          "district": "桃園區",
         "desc": "鄰近桃園高鐵延伸計畫站點預定地，為桃園市近年推案量最大的新興重劃區，各大建商集中推案。"},
        {"group": "桃園市區重劃區",     "sid": 10587, "name": "經國重劃區",            "district": "桃園區",
         "desc": "緊鄰桃園市政府特區，生活機能成熟，學區優質，為桃園市中心近年持續穩定的住宅重劃區。"},
        # 其他重劃區
        {"group": "其他重劃區",         "sid": 11241, "name": "八德擴大重劃區",         "district": "八德區",
         "desc": "八德市區最大規模都市重劃計畫，規劃完整住宅社區，鄰近台 66 線，交通便利，近年推案量持續增加。"},
        {"group": "其他重劃區",         "sid": 11226, "name": "A20 興南重劃區",         "district": "中壢區",
         "desc": "機場捷運 A20 站周邊，中壢區北端新興重劃區，均價為中壢最高，為近年中壢區人氣最旺的指標重劃區。"},
        {"group": "其他重劃區",         "sid": 11596, "name": "桃園航空城",             "district": "大園區",
         "desc": "國家重大建設計畫，規劃面積逾 3,100 公頃，配合桃園機場第三航廈擴建，預計帶動大量就業人口與住宅需求。"},
        {"group": "其他重劃區",         "sid": 11029, "name": "過嶺重劃區",             "district": "觀音區",
         "desc": "觀音區最具代表性的住宅重劃區，近年建設持續到位，房價親民，吸引首購族及換屋族進駐。"},
        {"group": "其他重劃區",         "sid": 11237, "name": "草漯重劃區",             "district": "觀音區",
         "desc": "觀音區北側重劃區，鄰近桃園工業區群，住宅供給穩定，為觀音區最大的住宅重劃開發區域。"},
    ]

    sids = [z["sid"] for z in ZONES]
    stats_map = db.get_subareas_stats_by_sids(sids)

    groups: dict = {}
    for z in ZONES:
        s = stats_map.get(z["sid"], {})
        z["avg_unit_price"] = s.get("avg_unit_price")
        z["tx_count"]       = s.get("tx_count", 0)
        z["latest_date"]    = s.get("latest_date")
        g = z["group"]
        groups.setdefault(g, []).append(z)

    return render_template("redevelopment.html", groups=groups)


@app.route("/healthz")
def healthz():
    """Render health check endpoint."""
    return "ok", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s %(message)s")
    app.run(host="0.0.0.0", port=port, debug=False)
