"""
資料庫層：自動偵測環境
- 有 DATABASE_URL 環境變數 → PostgreSQL（Render 雲端）
- 無 DATABASE_URL → SQLite（本機開發）
"""
import os
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, date

DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_PATH      = os.environ.get("DB_PATH", "leju.db")
IS_POSTGRES  = bool(DATABASE_URL)
PH           = "%s" if IS_POSTGRES else "?"   # SQL 佔位符

if IS_POSTGRES:
    import psycopg2
    import psycopg2.extras
    # Render 有時會給 postgres:// 開頭，psycopg2 需要 postgresql://
    _db_url = DATABASE_URL.replace("postgres://", "postgresql://", 1)


# ── 連線 ──────────────────────────────────────────────────────────────────────

@contextmanager
def get_conn():
    if IS_POSTGRES:
        conn = psycopg2.connect(_db_url)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()


# ── 查詢輔助 ──────────────────────────────────────────────────────────────────

def _rows(conn, sql, params=()):
    """回傳 list[dict]"""
    if IS_POSTGRES:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _row(conn, sql, params=()):
    """回傳單筆 dict 或 None"""
    if IS_POSTGRES:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            r = cur.fetchone()
            return dict(r) if r else None
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def _scalar(conn, sql, params=()):
    """回傳單一數值"""
    if IS_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            r = cur.fetchone()
            return r[0] if r else None
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def _exec(conn, sql, params=()):
    """執行非 SELECT 語句"""
    if IS_POSTGRES:
        with conn.cursor() as cur:
            cur.execute(sql, params)
    else:
        conn.execute(sql, params)


# ── 初始化資料庫 ──────────────────────────────────────────────────────────────

def init_db():
    with get_conn() as conn:
        if IS_POSTGRES:
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS subareas (
                    sid        INTEGER PRIMARY KEY,
                    name       TEXT NOT NULL,
                    post_code  TEXT NOT NULL,
                    updated_at TEXT
                )
            """)
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS transactions (
                    id               TEXT PRIMARY KEY,
                    sid              INTEGER NOT NULL,
                    transaction_date TEXT,
                    address          TEXT,
                    community        TEXT,
                    floor            TEXT,
                    total_floor      TEXT,
                    age              TEXT,
                    total_price      REAL,
                    unit_price       REAL,
                    total_area       REAL,
                    house_area       REAL,
                    parking_type     TEXT,
                    parking_price    REAL,
                    parking_area     REAL,
                    floor_ratio      TEXT,
                    building_type    TEXT,
                    is_special_trade INTEGER DEFAULT 0,
                    raw_data         TEXT,
                    scraped_at       TEXT
                )
            """)
            _exec(conn, "CREATE INDEX IF NOT EXISTS idx_tx_sid     ON transactions(sid)")
            _exec(conn, "CREATE INDEX IF NOT EXISTS idx_tx_date    ON transactions(transaction_date DESC)")
            _exec(conn, "CREATE INDEX IF NOT EXISTS idx_tx_special ON transactions(is_special_trade)")
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS scrape_log (
                    id            SERIAL PRIMARY KEY,
                    scraped_at    TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    message       TEXT,
                    records_count INTEGER DEFAULT 0
                )
            """)
        else:
            # SQLite（本機）
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS subareas (
                    sid        INTEGER PRIMARY KEY,
                    name       TEXT NOT NULL,
                    post_code  TEXT NOT NULL,
                    updated_at TEXT
                );
                CREATE TABLE IF NOT EXISTS transactions (
                    id               TEXT PRIMARY KEY,
                    sid              INTEGER NOT NULL,
                    transaction_date TEXT,
                    address          TEXT,
                    community        TEXT,
                    floor            TEXT,
                    total_floor      TEXT,
                    age              TEXT,
                    total_price      REAL,
                    unit_price       REAL,
                    total_area       REAL,
                    house_area       REAL,
                    parking_type     TEXT,
                    parking_price    REAL,
                    parking_area     REAL,
                    floor_ratio      TEXT,
                    building_type    TEXT,
                    raw_data         TEXT,
                    scraped_at       TEXT,
                    FOREIGN KEY (sid) REFERENCES subareas(sid)
                );
                CREATE INDEX IF NOT EXISTS idx_tx_sid  ON transactions(sid);
                CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(transaction_date DESC);
                CREATE TABLE IF NOT EXISTS scrape_log (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    scraped_at    TEXT NOT NULL,
                    status        TEXT NOT NULL,
                    message       TEXT,
                    records_count INTEGER DEFAULT 0
                );
            """)
            try:
                conn.execute("ALTER TABLE transactions ADD COLUMN is_special_trade INTEGER DEFAULT 0")
            except Exception:
                pass
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_special ON transactions(is_special_trade)")
            conn.execute("""
                UPDATE transactions
                SET is_special_trade = CAST(json_extract(raw_data, '$.is_special_trade') AS INTEGER)
                WHERE (is_special_trade IS NULL OR is_special_trade = 0)
                  AND raw_data IS NOT NULL
                  AND json_extract(raw_data, '$.is_special_trade') IS NOT NULL
            """)


# ── 寫入 ──────────────────────────────────────────────────────────────────────

def upsert_subareas(subareas: list):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for s in subareas:
            _exec(conn, f"""
                INSERT INTO subareas (sid, name, post_code, updated_at)
                VALUES ({PH},{PH},{PH},{PH})
                ON CONFLICT (sid) DO UPDATE SET
                    name=EXCLUDED.name,
                    post_code=EXCLUDED.post_code,
                    updated_at=EXCLUDED.updated_at
            """, (s["sid"], s["name"], s["post_code"], now))


def upsert_transactions(records: list):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for r in records:
            _exec(conn, f"""
                INSERT INTO transactions (
                    id, sid, transaction_date, address, community,
                    floor, total_floor, age, total_price, unit_price,
                    total_area, house_area, parking_type, parking_price,
                    parking_area, floor_ratio, building_type, is_special_trade,
                    raw_data, scraped_at
                ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},
                          {PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
                ON CONFLICT (id) DO UPDATE SET
                    transaction_date=EXCLUDED.transaction_date,
                    address=EXCLUDED.address,
                    community=EXCLUDED.community,
                    floor=EXCLUDED.floor,
                    total_floor=EXCLUDED.total_floor,
                    age=EXCLUDED.age,
                    total_price=EXCLUDED.total_price,
                    unit_price=EXCLUDED.unit_price,
                    total_area=EXCLUDED.total_area,
                    house_area=EXCLUDED.house_area,
                    parking_type=EXCLUDED.parking_type,
                    parking_price=EXCLUDED.parking_price,
                    parking_area=EXCLUDED.parking_area,
                    floor_ratio=EXCLUDED.floor_ratio,
                    building_type=EXCLUDED.building_type,
                    is_special_trade=EXCLUDED.is_special_trade,
                    raw_data=EXCLUDED.raw_data,
                    scraped_at=EXCLUDED.scraped_at
            """, (
                r.get("id"), r.get("sid"), r.get("transaction_date"),
                r.get("address"), r.get("community"), r.get("floor"),
                r.get("total_floor"), r.get("age"),
                r.get("total_price"), r.get("unit_price"),
                r.get("total_area"), r.get("house_area"),
                r.get("parking_type"), r.get("parking_price"), r.get("parking_area"),
                r.get("floor_ratio"), r.get("building_type"),
                r.get("is_special_trade", 0),
                json.dumps(r.get("_raw", {}), ensure_ascii=False), now,
            ))


def log_scrape(status: str, message: str = None, count: int = 0):
    with get_conn() as conn:
        _exec(conn, f"""
            INSERT INTO scrape_log (scraped_at, status, message, records_count)
            VALUES ({PH},{PH},{PH},{PH})
        """, (datetime.now().isoformat(), status, message, count))


# ── 讀取 ──────────────────────────────────────────────────────────────────────

def get_subareas() -> list:
    with get_conn() as conn:
        return _rows(conn, "SELECT * FROM subareas ORDER BY name")


def get_subarea_stats() -> list:
    five_yr = _five_year_roc()
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT
                s.sid, s.name, s.post_code, s.updated_at,
                COUNT(t.id) AS tx_count,
                ROUND(CAST(AVG(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 2) AS avg_unit_price,
                ROUND(CAST(MAX(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 2) AS max_unit_price,
                ROUND(CAST(MIN(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 2) AS min_unit_price,
                MAX(t.transaction_date) AS latest_date
            FROM subareas s
            LEFT JOIN transactions t ON s.sid = t.sid
            GROUP BY s.sid, s.name, s.post_code, s.updated_at
            ORDER BY avg_unit_price DESC NULLS LAST
        """, (five_yr, five_yr, five_yr))


def _iso_to_roc_ym(iso_date: str) -> str:
    """把西元日期（如 '2026-02-14'）轉成民國年/月（如 '115/02'）"""
    try:
        parts = iso_date.split("-")
        roc_year = int(parts[0]) - 1911
        month    = int(parts[1])
        return f"{roc_year:03d}/{month:02d}"
    except Exception:
        return iso_date


def _five_year_roc() -> str:
    """回傳5年前年初的民國 YYY/MM 字串（例：110/01），用於篩選近5年資料。"""
    roc_year = date.today().year - 1911 - 5
    return f"{roc_year:03d}/01"


def _three_year_roc() -> str:
    """回傳3年前年初的民國 YYY/MM 字串（例：112/01），用於估價器近3年篩選。"""
    roc_year = date.today().year - 1911 - 3
    return f"{roc_year:03d}/01"


def _build_clauses(
    base_clauses: list,
    base_params: list,
    age_filter: str = "all",
    type_filter: str = "all",
    special_filter: str = "exclude",
    date_from: str = "",
    date_to: str = "",
):
    clauses = list(base_clauses)
    params  = list(base_params)

    if age_filter == "presale":
        clauses.append("age='預售'")
    elif age_filter == "ready":
        clauses.append("(age!='預售' AND age IS NOT NULL AND age!='')")
    elif age_filter == "0-5":
        clauses.append("(CAST(age AS INTEGER) BETWEEN 0 AND 5 AND age!='預售')")
    elif age_filter == "5-10":
        clauses.append("(CAST(age AS INTEGER) BETWEEN 6 AND 10 AND age!='預售')")
    elif age_filter == "10-20":
        clauses.append("(CAST(age AS INTEGER) BETWEEN 11 AND 20 AND age!='預售')")
    elif age_filter == "20+":
        clauses.append("(CAST(age AS INTEGER) > 20 AND age!='預售')")

    if type_filter != "all":
        clauses.append(f"building_type={PH}")
        params.append(type_filter)

    if special_filter == "exclude":
        clauses.append("(is_special_trade IS NULL OR is_special_trade=0)")
    elif special_filter == "only":
        clauses.append("is_special_trade=1")

    if date_from:
        clauses.append(f"transaction_date >= {PH}")
        params.append(_iso_to_roc_ym(date_from))
    if date_to:
        clauses.append(f"transaction_date <= {PH}")
        params.append(_iso_to_roc_ym(date_to))

    return clauses, params


def get_transactions(
    sid: int,
    page: int = 1,
    per_page: int = 50,
    age_filter: str = "all",
    type_filter: str = "all",
    special_filter: str = "exclude",
    date_from: str = "",
    date_to: str = "",
) -> tuple:
    clauses, params = _build_clauses(
        [f"sid={PH}"], [sid],
        age_filter, type_filter, special_filter, date_from, date_to,
    )
    where  = " AND ".join(clauses)
    offset = (page - 1) * per_page

    with get_conn() as conn:
        total = _scalar(conn, f"SELECT COUNT(*) FROM transactions WHERE {where}", params)
        rows  = _rows(conn, f"""
            SELECT * FROM transactions
            WHERE {where}
            ORDER BY transaction_date DESC, scraped_at DESC
            LIMIT {PH} OFFSET {PH}
        """, params + [per_page, offset])
        return total, rows


def get_building_types(sid: int) -> list:
    with get_conn() as conn:
        rows = _rows(conn, f"""
            SELECT DISTINCT building_type FROM transactions
            WHERE sid={PH} AND building_type IS NOT NULL AND building_type!=''
            ORDER BY building_type
        """, (sid,))
        return [r["building_type"] for r in rows]


def get_community_stats(community: str, sid: int) -> dict | None:
    with get_conn() as conn:
        return _row(conn, f"""
            SELECT
                community, sid,
                COUNT(*)                                                              AS tx_count,
                ROUND(CAST(AVG(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 2)   AS avg_unit_price,
                ROUND(CAST(MAX(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 2)   AS max_unit_price,
                ROUND(CAST(MIN(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 2)   AS min_unit_price,
                ROUND(CAST(AVG(CASE WHEN total_price > 0 THEN total_price END) AS NUMERIC), 0) AS avg_total_price,
                MAX(transaction_date) AS latest_date,
                MIN(transaction_date) AS earliest_date,
                MAX(building_type)    AS building_type,
                MAX(age)              AS sample_age
            FROM transactions
            WHERE community={PH} AND sid={PH}
            GROUP BY community, sid
        """, (community, sid))


def get_community_yearly(community: str, sid: int) -> list:
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT
                SUBSTR(transaction_date, 1, 4)                                          AS year,
                COUNT(*)                                                                AS tx_count,
                ROUND(CAST(AVG(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 2) AS avg_unit_price
            FROM transactions
            WHERE community={PH} AND sid={PH}
              AND transaction_date IS NOT NULL
            GROUP BY SUBSTR(transaction_date, 1, 4)
            ORDER BY year ASC
        """, (community, sid))


def get_community_transactions(
    community: str,
    sid: int,
    page: int = 1,
    per_page: int = 50,
    special_filter: str = "exclude",
    date_from: str = "",
    date_to: str = "",
) -> tuple:
    clauses, params = _build_clauses(
        [f"community={PH}", f"sid={PH}"], [community, sid],
        special_filter=special_filter, date_from=date_from, date_to=date_to,
    )
    where  = " AND ".join(clauses)
    offset = (page - 1) * per_page
    with get_conn() as conn:
        total = _scalar(conn, f"SELECT COUNT(*) FROM transactions WHERE {where}", params)
        rows  = _rows(conn, f"""
            SELECT * FROM transactions
            WHERE {where}
            ORDER BY transaction_date DESC, scraped_at DESC
            LIMIT {PH} OFFSET {PH}
        """, params + [per_page, offset])
        return total, rows


def get_filtered_stats(
    sid: int,
    age_filter: str = "all",
    type_filter: str = "all",
    special_filter: str = "exclude",
    date_from: str = "",
    date_to: str = "",
) -> dict:
    """回傳目前篩選條件下的均價、最高、最低單價（用於 subarea 頁統計列）。
    未指定日期範圍時，預設只計算近5年資料（不含特殊交易）。"""
    clauses, params = _build_clauses(
        [f"sid={PH}"], [sid],
        age_filter, type_filter, special_filter, date_from, date_to,
    )
    # 若使用者未選擇起始日期，自動套用5年下限
    if not date_from:
        clauses.append(f"transaction_date >= {PH}")
        params.append(_five_year_roc())
    where = " AND ".join(clauses)
    with get_conn() as conn:
        return _row(conn, f"""
            SELECT
                ROUND(CAST(AVG(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 1) AS avg_unit_price,
                ROUND(CAST(MAX(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 1) AS max_unit_price,
                ROUND(CAST(MIN(CASE WHEN unit_price > 0 THEN unit_price END) AS NUMERIC), 1) AS min_unit_price
            FROM transactions WHERE {where}
        """, params) or {}


def search_communities(query: str, limit: int = 8) -> list:
    """搜尋社區名稱，回傳含近3年均價統計（用於估價器自動完成）。"""
    q = f"%{query}%"
    three_yr = _three_year_roc()
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT
                t.community AS name,
                t.sid,
                s.name AS subarea_name,
                COUNT(*) AS tx_count,
                ROUND(CAST(AVG(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1) AS avg_unit_price
            FROM transactions t
            JOIN subareas s ON s.sid = t.sid
            WHERE t.community LIKE {PH}
              AND t.community IS NOT NULL
              AND t.community != ''
            GROUP BY t.community, t.sid, s.name
            ORDER BY tx_count DESC
            LIMIT {PH}
        """, (three_yr, q, limit))


def get_community_estimate(name: str, sid: int = None) -> dict | None:
    """估價器：近3年成交資料，扣除車位後計算每坪單價，並以 IQR×1.5 剔除離群值。"""
    import statistics

    three_yr = _three_year_roc()
    clauses = [
        f"community={PH}",
        "(is_special_trade IS NULL OR is_special_trade=0)",
        f"transaction_date >= {PH}",
        "total_price > 0",
        "total_area  > 0",
    ]
    params = [name, three_yr]
    if sid:
        clauses.append(f"sid={PH}")
        params.append(sid)
    where = " AND ".join(clauses)

    with get_conn() as conn:
        rows = _rows(conn, f"""
            SELECT community, total_price, total_area,
                   parking_price, parking_area, transaction_date
            FROM transactions WHERE {where}
            ORDER BY transaction_date DESC
        """, params)

    if not rows:
        return {"community": name, "tx_count": 0}

    # ── 每筆扣掉車位，算純房屋每坪單價 ──────────────────────────────
    prices = []
    for r in rows:
        house_price = (r["total_price"] or 0) - (r["parking_price"] or 0)
        house_area  = (r["total_area"]  or 0) - (r["parking_area"]  or 0)
        if house_price > 0 and house_area > 0:
            prices.append(house_price / house_area)

    if not prices:
        return {"community": name, "tx_count": 0}

    tx_raw = len(prices)
    prices_sorted = sorted(prices)

    # ── IQR × 1.5 過濾（樣本 ≥ 5 才執行）────────────────────────────
    if tx_raw >= 5:
        q1, q3 = (statistics.quantiles(prices_sorted, n=4)[0],
                  statistics.quantiles(prices_sorted, n=4)[2])
        iqr = q3 - q1
        lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
        filtered = [p for p in prices_sorted if lo <= p <= hi]
        if not filtered:          # 萬一全被剔完就退回原始
            filtered = prices_sorted
    else:
        filtered = prices_sorted

    avg_p  = sum(filtered) / len(filtered)
    latest = rows[0]["transaction_date"] if rows else None

    # ── 車位統計（另外查，只取有車位資料的筆）────────────────────────
    p_prices = []
    p_areas  = []
    for r in rows:
        pp = r["parking_price"] or 0
        pa = r["parking_area"]  or 0
        if pp > 0 and pa > 0:
            p_prices.append(pp)
            p_areas.append(pa)

    avg_parking_price = round(sum(p_prices) / len(p_prices), 0) if p_prices else None
    avg_parking_area  = round(sum(p_areas)  / len(p_areas),  1) if p_areas  else None

    return {
        "community":        rows[0]["community"],
        "tx_count":         len(filtered),
        "tx_raw":           tx_raw,
        "avg_unit_price":   round(avg_p, 1),
        "max_unit_price":   round(max(filtered), 1),
        "min_unit_price":   round(min(filtered), 1),
        "latest_date":      latest,
        "avg_parking_price": avg_parking_price,   # 萬
        "avg_parking_area":  avg_parking_area,    # 坪/個
        "parking_sample":   len(p_prices),        # 有車位資料的筆數
    }


def get_subarea_by_sid(sid: int) -> dict | None:
    with get_conn() as conn:
        return _row(conn, f"SELECT * FROM subareas WHERE sid={PH}", (sid,))


def clear_scrape_log():
    with get_conn() as conn:
        _exec(conn, "DELETE FROM scrape_log")


def get_last_scrape() -> dict | None:
    with get_conn() as conn:
        return _row(conn, "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1")
