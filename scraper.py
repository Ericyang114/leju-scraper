"""
樂居網站 桃園區實價登錄爬蟲
策略：curl_cffi 偽裝 Chrome 繞過 Cloudflare；
      以「月份查詢」替代分頁，每次查一個月的資料，
      確保每個查詢的結果 ≤ 20 筆，不需 sessionToken。
"""
import calendar
import hashlib
import json
import logging
import time
from datetime import date, datetime, timedelta

from curl_cffi import requests as cf_requests

import db

log = logging.getLogger(__name__)

LEJU_WEB  = "https://www.leju.com.tw"
API_BASE  = "https://api.leju.com.tw/api"
CITY_CODE = "H"
CITY_NAME = "桃園市"
POST_CODE = "330"   # 桃園區
SEED_SID  = 11019   # 小檜溪重劃區，用於暖機 CF session

API_HEADERS = {
    "Referer":         f"{LEJU_WEB}/",
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
    "Origin":          LEJU_WEB,
}
FULL_SCRAPE_FROM = "2020-01-01"   # 初始全量抓取起始（改成更早的日期可獲取更多歷史）


# ── Session bootstrap ────────────────────────────────────────────────────────

def make_session() -> cf_requests.Session:
    """建立 curl_cffi session，先訪問主頁取得 Cloudflare cookies。"""
    impersonations = ["chrome124", "chrome110", "chrome107", "safari17_0", "safari15_5"]
    last_exc = None
    for imp in impersonations:
        try:
            s = cf_requests.Session(impersonate=imp)
            log.info("暖機 Cloudflare session (impersonate=%s)…", imp)
            r = s.get(
                f"{LEJU_WEB}/price_list/{CITY_NAME}?sid={SEED_SID}",
                headers={"Accept": "text/html", "Accept-Language": "zh-TW,zh;q=0.9"},
                timeout=30,
            )
            log.info("CF warmup status=%s cookies=%s", r.status_code, list(s.cookies.keys()))
            if r.status_code < 400:
                time.sleep(2)   # 等 CF cookies 穩定
                # 再暖機一次 API 子網域
                try:
                    s.get(
                        f"{API_BASE}/region_price/subarea/list",
                        params={"post_code": POST_CODE},
                        headers={**API_HEADERS, "Accept": "text/html"},
                        timeout=15,
                    )
                except Exception:
                    pass
                time.sleep(1)
                return s
        except Exception as exc:
            last_exc = exc
            log.warning("impersonate=%s 失敗: %s", imp, exc)
    raise RuntimeError(f"所有 impersonation 皆失敗: {last_exc}")


# ── Fetch helpers ────────────────────────────────────────────────────────────

def fetch_subareas(s: cf_requests.Session) -> list[dict]:
    """取得桃園區所有生活圈清單。"""
    r = s.get(
        f"{API_BASE}/region_price/subarea/list",
        params={"post_code": POST_CODE},
        headers=API_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    raw = data.get("data") or data
    if not isinstance(raw, list):
        return []
    return [
        {
            "sid":       int(item["id"]),
            "name":      item.get("small_area_name") or item.get("name") or str(item["id"]),
            "post_code": POST_CODE,
        }
        for item in raw
        if item.get("id") and (item.get("small_area_status", 1) == 1)
    ]


def _make_tx_id(sid: int, item: dict) -> str:
    key = (
        f"{sid}|{item.get('transaction_date','')}"
        f"|{item.get('address','')}"
        f"|{item.get('floor','')}"
        f"|{item.get('total_price','')}"
    )
    return hashlib.md5(key.encode()).hexdigest()


def _parse_transaction(sid: int, item: dict) -> dict:
    floor_val    = item.get("floor") or []
    floor_str    = str(floor_val[0]) if isinstance(floor_val, list) and floor_val else str(floor_val or "")
    parking_list = item.get("parking_type") or []
    parking_type = parking_list[0] if isinstance(parking_list, list) and parking_list else str(parking_list or "")
    age          = item.get("transaction_age")
    age_str      = "預售" if age is not None and age < 0 else (str(age) if age is not None else None)
    ratio        = item.get("public_area_ratio")
    ratio_str    = f"{ratio}%" if ratio else None

    # 擷取座標（API 回傳字串，轉 float；無則留 None）
    def _fl(v):
        try: return float(v)
        except (TypeError, ValueError): return None

    return {
        "id":               _make_tx_id(sid, item),
        "sid":              sid,
        "transaction_date": item.get("transaction_date"),
        "address":          item.get("address"),
        "community":        item.get("object_title"),
        "floor":            floor_str,
        "total_floor":      str(item.get("total_floor") or ""),
        "age":              age_str,
        "total_price":      item.get("total_price"),
        "unit_price":       item.get("unit_price_ping"),
        "total_area":       item.get("total_area_ping"),
        "house_area":       item.get("house_area_ping"),
        "parking_type":     parking_type,
        "parking_price":    item.get("total_parking_price"),
        "parking_area":     item.get("parking_area_ping"),
        "floor_ratio":      ratio_str,
        "building_type":    item.get("building_type"),
        "is_special_trade": int(item.get("is_special_trade") or 0),
        "lat":              _fl(item.get("latitude")),
        "lon":              _fl(item.get("longitude")),
        "_raw":             item,
    }


_PER_PAGE = 20   # API hard limit without sessionToken


def _query_once(
    s: cf_requests.Session,
    sid: int,
    name: str,
    date_start: str,
    date_end: str,
) -> list[dict]:
    """單次 API 呼叫，最多回傳 _PER_PAGE 筆。"""
    params = {
        "city_code":             CITY_CODE,
        "city_name":             CITY_NAME,
        "post_code":             POST_CODE,
        "tag":                   31,
        "tag_id":                sid,
        "text":                  name,
        "building_type":         0,
        "date_start":            date_start,
        "date_end":              date_end,
        "lower_total_price":     0,
        "upper_total_price":     9999,
        "lower_unit_price":      0,
        "upper_unit_price":      999,
        "lower_total_area_ping": 0,
        "upper_total_area_ping": 999,
        "lower_house_area_ping": 0,
        "upper_house_area_ping": 999,
        "lower_transaction_age": -10,
        "upper_transaction_age": 999,
        "floor":                 999,
        "special_trade":         1,
        "sort_by":               1,
        "sort_method":           2,
        "page":                  1,
        "per_page":              _PER_PAGE,
    }
    try:
        r = s.get(f"{API_BASE}/search/transactions", params=params, headers=API_HEADERS, timeout=20)
        r.raise_for_status()
        body  = r.json()
        items = body.get("data") or []
        return [_parse_transaction(sid, item) for item in items if isinstance(items, list)]
    except Exception as exc:
        log.warning("  查詢 sid=%s %s~%s 失敗: %s", sid, date_start, date_end, exc)
        return []


def _fetch_range(
    s: cf_requests.Session,
    sid: int,
    name: str,
    date_start: str,
    date_end: str,
    depth: int = 0,
) -> list[dict]:
    """抓取日期範圍內的所有資料。
    若回傳剛好 _PER_PAGE 筆（可能被截斷），自動對半拆分再遞迴查詢，
    直到每段結果 < _PER_PAGE 筆或已縮小至單日為止。
    """
    records = _query_once(s, sid, name, date_start, date_end)

    # 結果不足上限，或已達最大遞迴深度（防護），直接回傳
    if len(records) < _PER_PAGE or depth >= 6:
        if len(records) == _PER_PAGE and depth >= 6:
            log.warning("  sid=%s %s~%s 達遞迴上限，可能仍有資料未抓", sid, date_start, date_end)
        return records

    # 結果剛好等於上限：對半切
    start_d = datetime.strptime(date_start, "%Y-%m-%d").date()
    end_d   = datetime.strptime(date_end,   "%Y-%m-%d").date()

    if start_d >= end_d:
        # 已縮小到單日，無法再切
        log.warning("  sid=%s %s 單日超過 %d 筆，部分資料可能遺漏", sid, date_start, _PER_PAGE)
        return records

    mid_d  = start_d + (end_d - start_d) // 2
    next_d = mid_d + timedelta(days=1)

    log.debug("  sid=%s 區間 %s~%s 達上限，拆分查詢 (depth=%d)",
              sid, date_start, date_end, depth)

    time.sleep(0.25)
    left  = _fetch_range(s, sid, name, date_start,             mid_d.strftime("%Y-%m-%d"), depth + 1)
    time.sleep(0.25)
    right = _fetch_range(s, sid, name, next_d.strftime("%Y-%m-%d"), date_end,              depth + 1)

    # 合併並去重（同 id 只保留一筆）
    seen: set = set()
    merged: list = []
    for r in left + right:
        if r["id"] not in seen:
            seen.add(r["id"])
            merged.append(r)
    return merged


def _month_ranges(from_str: str, to_str: str) -> list[tuple[str, str]]:
    """產生從 from_str 到 to_str 的每月日期範圍列表。"""
    result = []
    cur = datetime.strptime(from_str, "%Y-%m-%d").date().replace(day=1)
    end = datetime.strptime(to_str, "%Y-%m-%d").date()
    while cur <= end:
        _, last_day = calendar.monthrange(cur.year, cur.month)
        month_end   = cur.replace(day=last_day)
        if month_end > end:
            month_end = end
        result.append((cur.strftime("%Y-%m-%d"), month_end.strftime("%Y-%m-%d")))
        if cur.month == 12:
            cur = cur.replace(year=cur.year + 1, month=1)
        else:
            cur = cur.replace(month=cur.month + 1)
    return result


def fetch_subarea_by_months(
    s: cf_requests.Session,
    sid: int,
    name: str,
    date_start: str,
) -> list[dict]:
    """以月份遍歷方式抓取生活圈所有交易資料。
    若某月超過 20 筆（API 上限），自動對半拆分確保不漏抓。
    """
    today  = date.today().strftime("%Y-%m-%d")
    ranges = _month_ranges(date_start, today)
    all_records: list = []

    for d_start, d_end in ranges:
        records = _fetch_range(s, sid, name, d_start, d_end)
        if records:
            all_records.extend(records)
            log.info("  %-16s %s ~ %s  → %d 筆", name, d_start, d_end, len(records))
        time.sleep(0.3)

    return all_records


# ── Main entry ───────────────────────────────────────────────────────────────

def scrape() -> bool:
    """主流程：取得 session → 爬所有生活圈 → 寫入 DB。"""
    db.init_db()

    try:
        s = make_session()
    except Exception as exc:
        msg = f"建立 session 失敗: {exc}"
        log.error(msg)
        db.log_scrape("error", msg)
        return False

    try:
        subareas = fetch_subareas(s)
    except Exception as exc:
        msg = f"取得生活圈失敗: {exc}"
        log.error(msg)
        db.log_scrape("error", msg)
        return False

    if not subareas:
        msg = f"找不到生活圈（post_code={POST_CODE}）"
        log.error(msg)
        db.log_scrape("error", msg)
        return False

    log.info("找到 %d 個生活圈", len(subareas))
    db.upsert_subareas(subareas)

    # --- 決定抓取起始日期（增量更新）---
    last = db.get_last_scrape()
    if last and last["status"] == "success" and last.get("scraped_at"):
        # 增量更新：從上次成功日往前 30 天
        prev       = datetime.fromisoformat(last["scraped_at"])
        date_start = (prev - timedelta(days=30)).strftime("%Y-%m-%d")
        log.info("增量更新，date_start=%s", date_start)
    else:
        date_start = FULL_SCRAPE_FROM
        log.info("全量抓取，date_start=%s", date_start)

    # --- 月份遍歷抓取 ---
    total_records = 0
    for sa in subareas:
        records = fetch_subarea_by_months(s, sa["sid"], sa["name"], date_start)
        if records:
            db.upsert_transactions(records)
            total_records += len(records)

    msg = f"完成：{len(subareas)} 個生活圈，共 {total_records} 筆交易"
    log.info("=== %s ===", msg)
    db.log_scrape("success", msg, total_records)
    return True


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("scraper.log", encoding="utf-8"),
        ],
    )
    scrape()
