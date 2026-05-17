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
    "中壢區": {
        "intro": "中壢區是桃園市人口最多的行政區，也是南桃園的商業重心。擁有中壢火車站、中原大學、元智大學等知名院校，青埔重劃區（A19–A21）為近年最熱門的新興住宅區，均價已成為桃園最高之一。",
        "traffic": "台鐵中壢站、內壢站提供便捷南北通勤；機場捷運 A19、A20、A21 站貫穿青埔重劃區，直達台北車站約 35 分鐘；台 1 線、台 66 線串聯桃園各區。",
        "school": "中壢高中、中壢家商、薜家國中等為主要學校；中原大學、元智大學坐落本區，高教資源豐富，吸引雙薪家庭購屋定居。",
        "life": "中壢 SOGO、中壢觀光夜市、中壢老街商圈等生活機能完整；青埔區域有家樂福、各大連鎖超市及 IKEA（大園區交界），發展迅速。",
    },
    "大溪區": {
        "intro": "大溪區保留豐富的歷史文化與自然景觀，以大溪老街、李騰芳古厝聞名全台。近年埔頂重劃區開發，吸引喜愛自然生活的首購族與換屋族，房價為桃園市中段親民水準。",
        "traffic": "台 4 線、台 7 線為主要對外道路；距桃園市區約 20 分鐘車程；無捷運或火車站，以自備車輛為主要交通方式。",
        "school": "大溪高中、大溪國中為主要學校，整體學區完整，校風純樸。",
        "life": "大溪老街商圈、大溪木藝生態博物館、大溪河濱公園等文化休閒景點豐富；日常生活機能集中於市區，生活步調悠閒。",
    },
    "楊梅區": {
        "intro": "楊梅區以工業與住宅混合發展為特色，擁有幼獅工業區及楊梅工業區，近年楊梅市區及富岡一帶住宅持續穩定成長，房價相對親民，適合在新竹或桃園上班的通勤族。",
        "traffic": "台鐵楊梅站、富岡站提供北上桃園（約 15 分鐘）、南下新竹的通勤選擇；國道 1 號楊梅交流道銜接南北，交通條件優異。",
        "school": "楊梅高中、瑞原國中、楊梅國中為主要學校，學區資源穩定。",
        "life": "楊梅市區商業機能完整，家樂福楊梅店提升日常購物便利性；埔心牧場等休閒農場增添生活品質；夜市、傳統市場一應俱全。",
    },
    "蘆竹區": {
        "intro": "蘆竹區緊鄰桃園國際機場，機場捷運 A10 山鼻站周邊近年大量住宅建案推出，為北桃園快速崛起的重點重劃區。南崁一帶生活機能成熟，適合需往返台北、機場的通勤族。",
        "traffic": "機場捷運 A10 山鼻站可直達台北車站（約 40 分鐘）及桃園機場（約 5 分鐘）；國道 2 號連接桃園各區與台北；南崁交流道銜接國道 1 號，對外交通十分便利。",
        "school": "蘆竹高中、南崁國中為主要學校；臨近林口，部分居民跨區就讀林口學區。",
        "life": "南崁商圈有家樂福、各大連鎖餐飲及量販店；A10 重劃區商業機能持續建置中；林口三井 OUTLET 車程約 15 分鐘。",
    },
    "大園區": {
        "intro": "大園區因鄰近桃園國際機場而聞名，青埔高鐵特區（A17、A18 站）是台灣近年最受矚目的新興重劃區之一，IKEA、好市多、台灣棒球訓練中心及多項大型設施陸續進駐。桃園航空城為國家重大建設計畫，預計帶動本區長期人口成長。",
        "traffic": "機場捷運 A17、A18 站可直達台北車站（約 35 分鐘）；國道 2 號機場系統交流道銜接國道 1 號；桃園國際機場坐落本區，對外交通極為便利。",
        "school": "大園國際高中、大園國中為主要學校；青埔新興社區入住人口增加，學校資源持續擴充。",
        "life": "青埔特區有 Xpark 水族館、桃園展演中心、IKEA；好市多桃園店、家樂福等大型量販店進駐；台 61 線沿線商業機能也日趨完整。",
    },
    "龜山區": {
        "intro": "龜山區緊鄰台北林口，機場捷運 A7 站周邊重劃區為近年桃園市最熱門的新興住宅區之一。距台北市通勤時間短，加上長庚醫院優質醫療資源，吸引大量北漂族在此購屋置產。",
        "traffic": "機場捷運 A7 站可直達台北車站（約 22 分鐘），為 A7 重劃區最大居住優勢；國道 2 號、台 4 線串聯桃園各區；林口長庚醫院車程約 10 分鐘。",
        "school": "文青、樂善非營利幼兒園坐落 A7 重劃區；龜山高中、龜山國中為主要中學；輔仁大學、長庚大學鄰近本區。",
        "life": "林口三井 OUTLET 車程約 10 分鐘；A7 重劃區商業設施持續到位；長庚醫院周邊醫療、餐飲資源完善，整體宜居性高。",
    },
    "八德區": {
        "intro": "八德區近年以八德擴大重劃區為發展重心，完整規劃的住宅社區快速崛起，房價親民且生活機能持續完善，是桃園首購族與換屋族的熱門選擇之一。",
        "traffic": "台 1 線、台 66 線快速道路銜接桃園市區及中壢；距桃園火車站約 15 分鐘車程；無捷運站，以自備車輛為主要交通方式。",
        "school": "八德高中、八德國中、大成國中為主要學校，學區完整穩定。",
        "life": "八德愛買、特力屋等大型量販店提供完整購物選擇；廣豐新天地為本區主要休閒商業中心；八德興豐路餐飲商圈生活機能成熟。",
    },
    "龍潭區": {
        "intro": "龍潭區以客家文化與科技產業為特色，台積電龍潭廠等高科技廠商進駐，帶動周邊住宅需求穩定成長。龍潭大池等自然景觀使本區兼具產業發展與宜居生活特色。",
        "traffic": "國道 3 號龍潭交流道提供南北向交通；台 4 線連接中壢、大溪；距桃園市區約 20 分鐘車程，以自備車輛為主。",
        "school": "龍潭高中、龍潭國中為主要學校；鄰近中央大學、元智大學，高教資源可及性佳。",
        "life": "龍潭市區商業機能穩定成熟；台積電廠區周邊餐飲密集；龍潭大池休閒園區、石門水庫為居民日常休憩的優質去處。",
    },
    "平鎮區": {
        "intro": "平鎮區為桃園南部重要住宅區，生活機能成熟、交通便利，擁有完善的中小學學區，房價相對中壢略為親民，吸引首購族及中壢上班族在此購屋。",
        "traffic": "台 1 線、台 66 線快速道路串聯中壢、桃園；距台鐵中壢站約 10 分鐘車程；無捷運站，以自備車輛為主。",
        "school": "平鎮高中、平鎮國中、忠貞國中為主要學校；中原大學、元智大學車程約 10 分鐘。",
        "life": "家樂福平鎮店、各大連鎖超市及餐飲完整；龍岡忠貞市場為知名滇緬美食聚集地，為本區最具特色的飲食文化景點。",
    },
    "新屋區": {
        "intro": "新屋區以農業與漁業為主，海岸線綿長，擁有新屋綠色走廊、永安漁港等特色景點，生活步調悠閒純樸。房價為桃園市最親民的行政區之一，適合喜愛自然環境的購屋者。",
        "traffic": "台 1 線、台 15 線為主要對外道路；距中壢市區約 20 分鐘、距楊梅約 15 分鐘車程；以自備車輛為主要交通方式。",
        "school": "新屋高中、新屋國中為主要學校，校園環境純樸，學生人數規模適中。",
        "life": "永安漁港海鮮餐廳聚集；新屋綠色走廊、蓮園等休閒景點豐富；日常生活機能集中於市區，整體生活步調悠閒。",
    },
    "觀音區": {
        "intro": "觀音區兼具工業與住宅發展，觀音工業區為台灣重要的製造業聚集地。過嶺重劃區與草漯重劃區為近年主要住宅開發區域，房價親民，吸引首購族進駐，近年成交量持續成長。",
        "traffic": "台 15 線、台 61 線西濱快速道路串聯沿海各區；國道 1 號楊梅交流道可銜接；距桃園市區約 25–30 分鐘，以自備車輛為主。",
        "school": "觀音高中、觀音國中為主要學校，整體教育資源穩定完整。",
        "life": "過嶺商圈、草漯一帶便利商店及餐飲持續增加；觀音蓮花節為年度特色活動；整體生活機能較市區略為不足，正隨重劃區發展持續改善。",
    },
    "復興區": {
        "intro": "復興區為桃園市唯一的山地原住民行政區，擁有角板山、拉拉山等知名自然景點，以觀光農業為主要產業。住宅市場規模極小，幾乎無大樓社區，房地產交易極為稀少，以土地交易為主。",
        "traffic": "台 7 線為唯一主要對外道路；距桃園市區約 40–60 分鐘，山區道路蜿蜒，需自備車輛，冬季霧季需特別留意行車安全。",
        "school": "復興高中為唯一高中，提供原住民族特色教育課程，寄宿制度完善。",
        "life": "以觀光農業為主，角板山行館、拉拉山水蜜桃為知名特產；日常生活機能需至大溪或龍潭補給，適合嚮往山居生活的購屋者。",
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


@app.route("/inspection")
def inspection():
    """看屋注意事項頁。"""
    return render_template("inspection.html")


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
