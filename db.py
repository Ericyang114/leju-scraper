"""
資料庫層：自動偵測環境
- 有 DATABASE_URL 環境變數 → PostgreSQL（Render 雲端）
- 無 DATABASE_URL → SQLite（本機開發）
"""
import os
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
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS community_coords (
                    community TEXT NOT NULL,
                    sid       INTEGER NOT NULL,
                    lat       REAL,
                    lon       REAL,
                    PRIMARY KEY (community, sid)
                )
            """)
            _exec(conn, """
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id           SERIAL PRIMARY KEY,
                    email        TEXT NOT NULL,
                    community    TEXT NOT NULL,
                    sid          INTEGER,
                    latest_seen  TEXT,
                    created_at   TEXT NOT NULL,
                    UNIQUE(email, community)
                )
            """)
            # 從現有 raw_data 反填座標（只填尚未有記錄的）
            _exec(conn, """
                INSERT INTO community_coords (community, sid, lat, lon)
                SELECT
                    community, sid,
                    CAST(raw_data::jsonb->>'latitude'  AS NUMERIC),
                    CAST(raw_data::jsonb->>'longitude' AS NUMERIC)
                FROM transactions
                WHERE raw_data IS NOT NULL
                  AND community IS NOT NULL
                  AND raw_data::jsonb->>'latitude' IS NOT NULL
                  AND raw_data::jsonb->>'longitude' IS NOT NULL
                ON CONFLICT (community, sid) DO NOTHING
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
                CREATE TABLE IF NOT EXISTS community_coords (
                    community TEXT NOT NULL,
                    sid       INTEGER NOT NULL,
                    lat       REAL,
                    lon       REAL,
                    PRIMARY KEY (community, sid)
                );
                CREATE TABLE IF NOT EXISTS subscriptions (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    email        TEXT NOT NULL,
                    community    TEXT NOT NULL,
                    sid          INTEGER,
                    latest_seen  TEXT,
                    created_at   TEXT NOT NULL,
                    UNIQUE(email, community)
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
            # 從現有 raw_data 反填座標
            conn.execute("""
                INSERT OR IGNORE INTO community_coords (community, sid, lat, lon)
                SELECT
                    community, sid,
                    CAST(json_extract(raw_data, '$.latitude')  AS REAL),
                    CAST(json_extract(raw_data, '$.longitude') AS REAL)
                FROM transactions
                WHERE raw_data IS NOT NULL
                  AND community IS NOT NULL
                  AND json_extract(raw_data, '$.latitude') IS NOT NULL
                  AND json_extract(raw_data, '$.longitude') IS NOT NULL
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
            # 同步寫入社區座標（僅補缺，不覆蓋）
            if r.get("lat") and r.get("lon") and r.get("community") and r.get("sid"):
                _exec(conn, f"""
                    INSERT INTO community_coords (community, sid, lat, lon)
                    VALUES ({PH},{PH},{PH},{PH})
                    ON CONFLICT (community, sid) DO NOTHING
                """, (r["community"], r["sid"], r["lat"], r["lon"]))
            _exec(conn, f"""
                INSERT INTO transactions (
                    id, sid, transaction_date, address, community,
                    floor, total_floor, age, total_price, unit_price,
                    total_area, house_area, parking_type, parking_price,
                    parking_area, floor_ratio, building_type, is_special_trade,
                    scraped_at
                ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},
                          {PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
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
                    scraped_at=EXCLUDED.scraped_at
            """, (
                r.get("id"), r.get("sid"), r.get("transaction_date"),
                r.get("address"), r.get("community"), r.get("floor"),
                r.get("total_floor"), r.get("age"),
                r.get("total_price"), r.get("unit_price"),
                r.get("total_area"), r.get("house_area"),
                r.get("parking_type"), r.get("parking_price"), r.get("parking_area"),
                r.get("floor_ratio"), r.get("building_type"),
                r.get("is_special_trade", 0), now,
            ))


def log_scrape(status: str, message: str = None, count: int = 0):
    with get_conn() as conn:
        _exec(conn, f"""
            INSERT INTO scrape_log (scraped_at, status, message, records_count)
            VALUES ({PH},{PH},{PH},{PH})
        """, (datetime.now().isoformat(), status, message, count))


def upsert_community_coords(records: list):
    """寫入社區座標（僅當尚無記錄時才寫）。
    records: list of dict with keys: community, sid, lat, lon
    """
    with get_conn() as conn:
        for r in records:
            if not r.get("lat") or not r.get("lon"):
                continue
            _exec(conn, f"""
                INSERT INTO community_coords (community, sid, lat, lon)
                VALUES ({PH},{PH},{PH},{PH})
                ON CONFLICT (community, sid) DO NOTHING
            """, (r["community"], r["sid"], r["lat"], r["lon"]))


# ── 讀取 ──────────────────────────────────────────────────────────────────────

def get_subareas() -> list:
    with get_conn() as conn:
        return _rows(conn, "SELECT * FROM subareas ORDER BY name")


def get_community_coords(community: str, sid: int = None) -> dict | None:
    """查詢社區座標，sid 可省略（取第一筆）。"""
    with get_conn() as conn:
        if sid:
            return _row(conn, f"""
                SELECT lat, lon FROM community_coords
                WHERE community={PH} AND sid={PH}
                  AND lat IS NOT NULL AND lon IS NOT NULL
            """, (community, sid))
        return _row(conn, f"""
            SELECT lat, lon FROM community_coords
            WHERE community={PH}
              AND lat IS NOT NULL AND lon IS NOT NULL
            ORDER BY sid LIMIT 1
        """, (community,))


def get_district_stats() -> list:
    """各區統計摘要（有資料的才回傳）。"""
    three_yr = _three_year_roc()
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT
                s.post_code,
                COUNT(DISTINCT s.sid)                                              AS subarea_count,
                COUNT(t.id)                                                        AS tx_count,
                ROUND(CAST(AVG(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1)              AS avg_unit_price,
                MAX(t.transaction_date)                                            AS latest_date
            FROM subareas s
            LEFT JOIN transactions t ON s.sid = t.sid
            GROUP BY s.post_code
            HAVING COUNT(t.id) > 0
        """, (three_yr,))


def get_subareas_by_post_code(post_code: str) -> list:
    """取得某區（郵遞區號）的所有生活圈及統計。"""
    three_yr = _three_year_roc()
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT
                s.sid, s.name, s.post_code, s.updated_at,
                COUNT(t.id)                                                        AS tx_count,
                ROUND(CAST(AVG(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1)              AS avg_unit_price,
                ROUND(CAST(MAX(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1)              AS max_unit_price,
                ROUND(CAST(MIN(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1)              AS min_unit_price,
                MAX(CASE WHEN (t.is_special_trade IS NULL OR t.is_special_trade=0)
                         THEN t.transaction_date END)                              AS latest_date
            FROM subareas s
            LEFT JOIN transactions t ON s.sid = t.sid
            WHERE s.post_code = {PH}
            GROUP BY s.sid, s.name, s.post_code, s.updated_at
            ORDER BY tx_count DESC NULLS LAST
        """, (three_yr, three_yr, three_yr, post_code))


def get_subarea_quarterly_trend(
    sid: int,
    age_filter: str = "all",
    type_filter: str = "all",
    special_filter: str = "exclude",
    date_from: str = "",
    date_to: str = "",
) -> list:
    """回傳生活圈每季均價走勢，支援篩選條件。無日期範圍時預設近5年。"""
    clauses, params = _build_clauses(
        [f"sid={PH}", "unit_price > 0"], [sid],
        age_filter, type_filter, special_filter, date_from, date_to,
    )
    if not date_from:
        clauses.append(f"transaction_date >= {PH}")
        params.append(_five_year_roc())
    where = " AND ".join(clauses)
    with get_conn() as conn:
        rows = _rows(conn, f"""
            SELECT transaction_date, unit_price
            FROM transactions
            WHERE {where}
        """, params)

    from collections import defaultdict
    buckets: dict = defaultdict(list)
    for r in rows:
        raw = (r.get("transaction_date") or "").strip()
        parts = raw.replace("-", "/").split("/")
        if len(parts) >= 2:
            try:
                roc_yr  = int(parts[0])
                month   = int(parts[1])
                year    = roc_yr + 1911 if roc_yr < 200 else roc_yr
                quarter = (month - 1) // 3 + 1
                buckets[(year, quarter)].append(float(r["unit_price"]))
            except (ValueError, TypeError):
                continue

    result = []
    for (year, q) in sorted(buckets.keys()):
        prices = buckets[(year, q)]
        if prices:
            result.append({
                "label": f"{year} Q{q}",
                "avg":   round(sum(prices) / len(prices), 1),
                "count": len(prices),
            })
    return result


def get_subareas_stats_by_sids(sids: list) -> dict:
    """批次查詢多個 sid 的近3年均價統計，回傳 {sid: {...}} dict。"""
    if not sids:
        return {}
    three_yr = _three_year_roc()
    placeholders = ",".join([PH] * len(sids))
    with get_conn() as conn:
        rows = _rows(conn, f"""
            SELECT
                sid,
                COUNT(*) AS tx_count,
                ROUND(CAST(AVG(CASE WHEN unit_price > 0
                               AND transaction_date >= {PH}
                               AND (is_special_trade IS NULL OR is_special_trade=0)
                               THEN unit_price END) AS NUMERIC), 1) AS avg_unit_price,
                MAX(transaction_date) AS latest_date
            FROM transactions
            WHERE sid IN ({placeholders})
            GROUP BY sid
        """, [three_yr] + sids)
    return {r["sid"]: dict(r) for r in rows}


def get_subarea_latest_date(sid: int) -> str | None:
    """回傳某生活圈最新的交易日期，無資料則回傳 None。"""
    with get_conn() as conn:
        return _scalar(conn, f"""
            SELECT MAX(transaction_date) FROM transactions WHERE sid={PH}
        """, (sid,))


def get_subarea_stats() -> list:
    three_yr = _three_year_roc()
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
        """, (three_yr, three_yr, three_yr))


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


def _two_year_roc() -> str:
    """回傳2年前年初的民國 YYY/MM 字串（例：113/01），用於周遭近2年篩選。"""
    roc_year = date.today().year - 1911 - 2
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
                s.post_code,
                COUNT(*) AS tx_count,
                ROUND(CAST(AVG(CASE WHEN t.unit_price > 0
                               AND t.transaction_date >= {PH}
                               AND (t.is_special_trade IS NULL OR t.is_special_trade=0)
                               THEN t.unit_price END) AS NUMERIC), 1) AS avg_unit_price,
                (SELECT address FROM transactions t2
                 WHERE t2.community = t.community AND t2.sid = t.sid
                   AND t2.address IS NOT NULL AND t2.address != ''
                 ORDER BY t2.transaction_date DESC LIMIT 1) AS sample_address
            FROM transactions t
            JOIN subareas s ON s.sid = t.sid
            WHERE t.community LIKE {PH}
              AND t.community IS NOT NULL
              AND t.community != ''
            GROUP BY t.community, t.sid, s.name, s.post_code
            ORDER BY
              CASE WHEN t.community = {PH} THEN 0 ELSE 1 END,
              tx_count DESC
            LIMIT {PH}
        """, (three_yr, q, query, limit))


def get_community_quarterly_trend(name: str, sid: int = None) -> list:
    """回傳社區每季均價走勢（近3年，排除特殊交易，node 含車位需自行扣除）。"""
    from collections import defaultdict
    three_yr = _three_year_roc()
    clauses = [
        f"community={PH}",
        "unit_price > 0",
        f"transaction_date >= {PH}",
        "(is_special_trade IS NULL OR is_special_trade=0)",
    ]
    params: list = [name, three_yr]
    if sid:
        clauses.append(f"sid={PH}")
        params.append(sid)
    where = " AND ".join(clauses)
    with get_conn() as conn:
        rows = _rows(conn, f"""
            SELECT transaction_date, unit_price
            FROM transactions
            WHERE {where}
            ORDER BY transaction_date ASC
        """, params)

    buckets: dict = defaultdict(list)
    for r in rows:
        raw = (r.get("transaction_date") or "").strip()
        parts = raw.replace("-", "/").split("/")
        if len(parts) >= 2:
            try:
                roc_yr  = int(parts[0])
                month   = int(parts[1])
                year    = roc_yr + 1911 if roc_yr < 200 else roc_yr
                quarter = (month - 1) // 3 + 1
                buckets[(year, quarter)].append(float(r["unit_price"]))
            except (ValueError, TypeError):
                continue

    result = []
    for (year, q) in sorted(buckets.keys()):
        prices = buckets[(year, q)]
        if prices:
            result.append({
                "label": f"{year} Q{q}",
                "avg":   round(sum(prices) / len(prices), 1),
                "count": len(prices),
            })
    return result


def get_community_estimate(name: str, sid: int = None) -> dict | None:
    """估價器：指數時間衰減 + 同生活圈周遭補充加權估價（方法二A）。
    資料窗口：2 年
    同社區  : weight = e^(-0.06 × 距今月數)
    同生活圈: weight = 0.10 × e^(-0.08 × 距今月數)
    先判斷社區性質（預售 or 成屋），再 IQR 過濾同社區離群值，最後合併加權平均。
    - 成屋社區：排除預售屋成交（age='預售'）
    - 預售社區：排除成屋成交（age!='預售'），僅保留預售登錄
    """
    import math, statistics
    from collections import Counter

    two_yr = _two_year_roc()
    today  = date.today()

    def _months_ago(tx_date: str) -> float:
        try:
            parts = tx_date.split("/")
            wy    = int(parts[0]) + 1911
            m     = int(parts[1])
            return max(0.0, (today.year - wy) * 12 + (today.month - m))
        except Exception:
            return 24.0

    def _adj_price(r):
        hp = (r["total_price"] or 0) - (r["parking_price"] or 0)
        ha = (r["total_area"]  or 0) - (r["parking_area"]  or 0)
        return hp / ha if hp > 0 and ha > 0 else None

    def _parse_age(r):
        a = r.get("age")
        if not a or a == "預售":
            return None
        try:
            return int(a)
        except Exception:
            return None

    # ── Step 1：先撈近 2 年同社區全部資料，判斷社區性質 ──────────
    c_cl_all = [f"community={PH}",
                "(is_special_trade IS NULL OR is_special_trade=0)",
                f"transaction_date>={PH}", "total_price>0", "total_area>0"]
    c_p_all  = [name, two_yr]
    if sid:
        c_cl_all.append(f"sid={PH}"); c_p_all.append(sid)

    with get_conn() as conn:
        c_rows_all = _rows(conn, f"""
            SELECT community, total_price, total_area,
                   parking_price, parking_area, transaction_date, age, building_type
            FROM transactions WHERE {" AND ".join(c_cl_all)}
            ORDER BY transaction_date DESC
        """, c_p_all)

    # 若 2 年內無資料，往前擴展至 3 年（避免空白）
    if not c_rows_all:
        three_yr = _three_year_roc()
        c_p_all[-1 if not sid else -2] = three_yr  # 替換日期參數
        # 重新用正確方式替換
        c_p_fallback = [name, three_yr]
        if sid:
            c_p_fallback.append(sid)
        with get_conn() as conn:
            c_rows_all = _rows(conn, f"""
                SELECT community, total_price, total_area,
                       parking_price, parking_area, transaction_date, age, building_type
                FROM transactions WHERE {" AND ".join(c_cl_all)}
                ORDER BY transaction_date DESC
            """, c_p_fallback)

    # 判斷社區性質：有任何成屋成交（age != '預售'）→ 成屋社區
    # 只有全部都是預售登錄、完全沒有成屋成交，才視為預售社區
    has_completed = any(r.get("age") != "預售" for r in c_rows_all)
    is_presale_community = (len(c_rows_all) > 0 and not has_completed)

    # ── Step 2：依社區性質篩選同社區 & 周遭 ──────────────────────
    if is_presale_community:
        age_clause = "AND age='預售'"          # 預售社區：只要預售登錄
    else:
        age_clause = "AND (age IS NULL OR age!='預售')"  # 成屋社區：排除預售

    c_cl = [f"community={PH}",
            "(is_special_trade IS NULL OR is_special_trade=0)",
            f"transaction_date>={PH}", "total_price>0", "total_area>0"]
    c_p  = [name, two_yr]
    if sid:
        c_cl.append(f"sid={PH}"); c_p.append(sid)

    n_rows: list = []
    if sid:
        n_cl = [f"sid={PH}", f"community!={PH}", "community IS NOT NULL",
                "(is_special_trade IS NULL OR is_special_trade=0)",
                f"transaction_date>={PH}", "total_price>0", "total_area>0"]
        n_p  = [sid, name, two_yr]

    with get_conn() as conn:
        c_rows = _rows(conn, f"""
            SELECT community, total_price, total_area,
                   parking_price, parking_area, transaction_date, age, building_type
            FROM transactions WHERE {" AND ".join(c_cl)} {age_clause}
            ORDER BY transaction_date DESC
        """, c_p)
        if sid:
            n_rows = _rows(conn, f"""
                SELECT total_price, total_area,
                       parking_price, parking_area, transaction_date, age, building_type
                FROM transactions WHERE {" AND ".join(n_cl)} {age_clause}
                ORDER BY transaction_date DESC LIMIT 300
            """, n_p)

    if not c_rows and not n_rows:
        return {"community": name, "tx_count": 0}

    # ── 同社區調整單價 + IQR 過濾 ─────────────────────────────────
    c_prices = [(p, r["transaction_date"])
                for r in c_rows if (p := _adj_price(r)) is not None]
    tx_raw = len(c_prices)

    if tx_raw >= 5:
        vals = sorted(p for p, _ in c_prices)
        q1   = statistics.quantiles(vals, n=4)[0]
        q3   = statistics.quantiles(vals, n=4)[2]
        iqr  = q3 - q1
        lo, hi   = q1 - 1.0 * iqr, q3 + 1.0 * iqr
        c_prices = [(p, d) for p, d in c_prices if lo <= p <= hi] or c_prices

    # ── 中位數地板保護（剔除 < 中位數 × 65% 的異常值）──────────
    if c_prices:
        med_floor = statistics.median([p for p, _ in c_prices])
        c_prices  = [(p, d) for p, d in c_prices if p >= med_floor * 0.65] or c_prices

    # ── 周遭篩選①：物件類型需與社區相同 ─────────────────────────
    # 物件類型參考來源：c_rows_all（含全部資料，避免篩後為空）
    c_types = [r.get("building_type") for r in c_rows_all if r.get("building_type")]
    if c_types and n_rows:
        main_type = Counter(c_types).most_common(1)[0][0]
        n_rows = [r for r in n_rows if r.get("building_type") == main_type]

    # ── 周遭篩選②：屋齡 ±7 年（預售社區跳過）────────────────────
    if not is_presale_community:
        c_ages = [a for r in c_rows_all if (a := _parse_age(r)) is not None]
        if c_ages and n_rows:
            med_age = statistics.median(c_ages)
            n_rows  = [r for r in n_rows
                       if (a := _parse_age(r)) is not None and med_age - 7 <= a <= med_age + 7]

    all_n_prices = [(p, r["transaction_date"])
                    for r in n_rows if (p := _adj_price(r)) is not None]

    if c_prices and all_n_prices:
        ref  = statistics.median([p for p, _ in c_prices])
        n_lo, n_hi = ref * 0.70, ref * 1.30
        n_prices = [(p, d) for p, d in all_n_prices if n_lo <= p <= n_hi]
    else:
        n_prices = all_n_prices

    # ── 指數衰減加權平均（BASE_N 0.10）──────────────────────────
    LAMBDA_C, LAMBDA_N, BASE_N = 0.06, 0.08, 0.10
    wsum = wt = 0.0
    for price, d in c_prices:
        w = math.exp(-LAMBDA_C * _months_ago(d))
        wsum += price * w; wt += w
    for price, d in n_prices:
        w = BASE_N * math.exp(-LAMBDA_N * _months_ago(d))
        wsum += price * w; wt += w

    if wt == 0:
        return {"community": name, "tx_count": 0}

    avg_p = wsum / wt

    # ── 車位統計（2年窗口無資料時往前查全期歷史）─────────────────
    p_prices, p_areas = [], []
    for r in c_rows:
        pp, pa = r["parking_price"] or 0, r["parking_area"] or 0
        if pp > 0 and pa > 0:
            p_prices.append(pp); p_areas.append(pa)

    if not p_prices:
        # 往前查同社區歷史全期車位資料（不限日期）
        pk_cl = [f"community={PH}", "parking_price>0", "parking_area>0",
                 "(is_special_trade IS NULL OR is_special_trade=0)"]
        pk_p  = [name]
        if sid:
            pk_cl.append(f"sid={PH}"); pk_p.append(sid)
        with get_conn() as conn:
            pk_rows = _rows(conn, f"""
                SELECT parking_price, parking_area FROM transactions
                WHERE {" AND ".join(pk_cl)}
                ORDER BY transaction_date DESC LIMIT 50
            """, pk_p)
        for r in pk_rows:
            pp, pa = r["parking_price"] or 0, r["parking_area"] or 0
            if pp > 0 and pa > 0:
                p_prices.append(pp); p_areas.append(pa)

    filtered_vals = sorted(p for p, _ in c_prices)
    latest = (c_rows or c_rows_all)[0]["transaction_date"]

    # ── Q1、Q3（同社區成交集中區間）──────────────────────────────
    if len(filtered_vals) >= 4:
        q1_disp = statistics.quantiles(filtered_vals, n=4)[0]
        q3_disp = statistics.quantiles(filtered_vals, n=4)[2]
    elif filtered_vals:
        q1_disp = min(filtered_vals)
        q3_disp = max(filtered_vals)
    else:
        q1_disp = q3_disp = None

    return {
        "community":          (c_rows[0] if c_rows else c_rows_all[0]).get("community", name),
        "tx_count":           len(c_prices),
        "tx_raw":             tx_raw,
        "tx_nearby":          len(n_prices),
        "is_presale":         is_presale_community,
        "avg_unit_price":     round(avg_p, 1),
        "max_unit_price":     round(max(filtered_vals), 1) if filtered_vals else None,
        "min_unit_price":     round(min(filtered_vals), 1) if filtered_vals else None,
        "q1":                 round(q1_disp, 1) if q1_disp is not None else None,
        "q3":                 round(q3_disp, 1) if q3_disp is not None else None,
        "latest_date":        latest,
        "avg_parking_price":  round(sum(p_prices)/len(p_prices), 0) if p_prices else None,
        "avg_parking_area":   round(sum(p_areas) /len(p_areas),  1) if p_areas  else None,
        "parking_sample":     len(p_prices),
    }


def get_subarea_by_sid(sid: int) -> dict | None:
    with get_conn() as conn:
        return _row(conn, f"SELECT * FROM subareas WHERE sid={PH}", (sid,))


def get_subarea_temperature(sid: int) -> dict:
    """成交年比趨勢：近12個月 vs 去年同期12個月。
    實價登錄有 3–6 個月申報延遲，用年比消除季節因素、拉大窗口降低影響。
    回傳 level ('hot'|'warm'|'cold')、兩期筆數、年增率、期間說明。
    """
    today = date.today()

    def _roc_month(offset_months: int) -> str:
        y = today.year
        m = today.month - offset_months
        while m <= 0:
            m += 12; y -= 1
        return f"{y - 1911}/{m:02d}"

    DELAY = 3   # 固定往前移 3 個月，避開尚未完整登錄的近期月份

    # 近12個月（可靠期間）：截止到 3 個月前（例：今天5月 → 截止2月）
    cur_from  = _roc_month(12 + DELAY)
    cur_to    = _roc_month(DELAY)

    # 去年同期12個月
    prev_from = _roc_month(24 + DELAY)
    prev_to   = _roc_month(12 + DELAY)

    # 顯示用期間標籤（ROC 轉西元年方便閱讀）
    def _roc_to_label(roc: str) -> str:
        parts = roc.split("/")
        return f"{int(parts[0])+1911}/{parts[1]}"

    cur_label  = f"{_roc_to_label(cur_from)}–{_roc_to_label(cur_to)}"
    prev_label = f"{_roc_to_label(prev_from)}–{_roc_to_label(prev_to)}"

    with get_conn() as conn:
        cur_row = _row(conn, f"""
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE sid={PH}
              AND transaction_date>={PH} AND transaction_date<{PH}
              AND (is_special_trade IS NULL OR is_special_trade=0)
        """, (sid, cur_from, cur_to))
        prev_row = _row(conn, f"""
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE sid={PH}
              AND transaction_date>={PH} AND transaction_date<{PH}
              AND (is_special_trade IS NULL OR is_special_trade=0)
        """, (sid, prev_from, prev_to))

    cur_cnt  = cur_row["cnt"]  if cur_row  else 0
    prev_cnt = prev_row["cnt"] if prev_row else 0

    if prev_cnt == 0:
        ratio = 1.0
        pct   = None
    else:
        ratio = cur_cnt / prev_cnt
        pct   = round((ratio - 1) * 100)

    if ratio >= 1.15:
        level = "hot"
    elif ratio <= 0.85:
        level = "cold"
    else:
        level = "warm"

    return {
        "level":      level,
        "cur_cnt":    cur_cnt,
        "prev_cnt":   prev_cnt,
        "ratio":      round(ratio, 2),
        "pct":        pct,          # 年增率 %（None 表示去年無資料）
        "cur_label":  cur_label,
        "prev_label": prev_label,
    }


def add_subscription(email: str, community: str, sid: int = None) -> str:
    """新增訂閱。回傳 'created' 或 'exists'。"""
    now = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # 取該社區目前最新成交日期作為 latest_seen 基準
    with get_conn() as conn:
        row = _row(conn, f"""
            SELECT transaction_date FROM transactions
            WHERE community={PH} {"AND sid="+PH if sid else ""}
            ORDER BY transaction_date DESC LIMIT 1
        """, (community, sid) if sid else (community,))
        latest = row["transaction_date"] if row else None
        try:
            if IS_POSTGRES:
                _exec(conn, f"""
                    INSERT INTO subscriptions (email, community, sid, latest_seen, created_at)
                    VALUES ({PH},{PH},{PH},{PH},{PH})
                    ON CONFLICT (email, community) DO NOTHING
                """, (email, community, sid, latest, now))
                with conn.cursor() as cur:
                    cur.execute("SELECT COUNT(*) FROM subscriptions WHERE email=%s AND community=%s AND created_at=%s", (email, community, now))
                    created = cur.fetchone()[0] > 0
            else:
                try:
                    conn.execute("""
                        INSERT OR IGNORE INTO subscriptions (email, community, sid, latest_seen, created_at)
                        VALUES (?,?,?,?,?)
                    """, (email, community, sid, latest, now))
                    created = conn.total_changes > 0
                except Exception:
                    created = False
        except Exception:
            created = False
    return "created" if created else "exists"


def get_subscriptions_needing_notify() -> list:
    """查出所有有新成交（比 latest_seen 新）的訂閱。"""
    with get_conn() as conn:
        return _rows(conn, f"""
            SELECT s.id, s.email, s.community, s.sid, s.latest_seen,
                   t.transaction_date AS new_date,
                   t.unit_price
            FROM subscriptions s
            JOIN transactions t ON t.community = s.community
              AND (s.sid IS NULL OR t.sid = s.sid)
              AND t.transaction_date > COALESCE(s.latest_seen, '000/00')
              AND (t.is_special_trade IS NULL OR t.is_special_trade = 0)
            ORDER BY s.id, t.transaction_date DESC
        """, ())


def update_subscription_seen(sub_id: int, latest_date: str):
    with get_conn() as conn:
        _exec(conn, f"UPDATE subscriptions SET latest_seen={PH} WHERE id={PH}", (latest_date, sub_id))


def clear_scrape_log():
    with get_conn() as conn:
        _exec(conn, "DELETE FROM scrape_log")


def get_last_scrape() -> dict | None:
    with get_conn() as conn:
        return _row(conn, "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1")


def get_global_stats() -> dict:
    """回傳全站統計：總成交筆數、最新成交月份（ROC）。"""
    with get_conn() as conn:
        total = _scalar(conn, "SELECT COUNT(*) FROM transactions") or 0
        latest = _scalar(conn,
            "SELECT MAX(transaction_date) FROM transactions "
            "WHERE (is_special_trade IS NULL OR is_special_trade=0)"
        )
    # latest 格式如 "113/04"，取前6字元即可
    latest_month = (latest or "")[:6]
    return {"total_tx": total, "latest_month": latest_month}
