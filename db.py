import sqlite3
import json
import os
from contextlib import contextmanager
from datetime import datetime

DB_PATH = os.environ.get("DB_PATH", "leju.db")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        # Step 1: base tables (without is_special_trade in CREATE TABLE — handled via migration)
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

        # Step 2: migration — add is_special_trade column if missing
        try:
            conn.execute("ALTER TABLE transactions ADD COLUMN is_special_trade INTEGER DEFAULT 0")
        except Exception:
            pass  # column already exists

        # Step 3: index on is_special_trade (safe now that column exists)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tx_special ON transactions(is_special_trade)")

        # Step 4: backfill from raw_data for existing rows
        conn.execute("""
            UPDATE transactions
            SET is_special_trade = CAST(
                json_extract(raw_data, '$.is_special_trade') AS INTEGER
            )
            WHERE (is_special_trade IS NULL OR is_special_trade = 0)
              AND raw_data IS NOT NULL
              AND json_extract(raw_data, '$.is_special_trade') IS NOT NULL
        """)


def upsert_subareas(subareas: list):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for s in subareas:
            conn.execute("""
                INSERT INTO subareas (sid, name, post_code, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(sid) DO UPDATE SET
                    name=excluded.name,
                    post_code=excluded.post_code,
                    updated_at=excluded.updated_at
            """, (s["sid"], s["name"], s["post_code"], now))


def upsert_transactions(records: list):
    now = datetime.now().isoformat()
    with get_conn() as conn:
        for r in records:
            conn.execute("""
                INSERT INTO transactions (
                    id, sid, transaction_date, address, community,
                    floor, total_floor, age, total_price, unit_price,
                    total_area, house_area, parking_type, parking_price,
                    parking_area, floor_ratio, building_type, is_special_trade,
                    raw_data, scraped_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    transaction_date=excluded.transaction_date,
                    address=excluded.address,
                    community=excluded.community,
                    floor=excluded.floor,
                    total_floor=excluded.total_floor,
                    age=excluded.age,
                    total_price=excluded.total_price,
                    unit_price=excluded.unit_price,
                    total_area=excluded.total_area,
                    house_area=excluded.house_area,
                    parking_type=excluded.parking_type,
                    parking_price=excluded.parking_price,
                    parking_area=excluded.parking_area,
                    floor_ratio=excluded.floor_ratio,
                    building_type=excluded.building_type,
                    is_special_trade=excluded.is_special_trade,
                    raw_data=excluded.raw_data,
                    scraped_at=excluded.scraped_at
            """, (
                r.get("id"), r.get("sid"), r.get("transaction_date"),
                r.get("address"), r.get("community"), r.get("floor"),
                r.get("total_floor"), r.get("age"),
                r.get("total_price"), r.get("unit_price"),
                r.get("total_area"), r.get("house_area"),
                r.get("parking_type"), r.get("parking_price"), r.get("parking_area"),
                r.get("floor_ratio"), r.get("building_type"),
                r.get("is_special_trade", 0),
                json.dumps(r.get("_raw"), ensure_ascii=False), now,
            ))


def log_scrape(status: str, message: str = None, count: int = 0):
    with get_conn() as conn:
        conn.execute("""
            INSERT INTO scrape_log (scraped_at, status, message, records_count)
            VALUES (?, ?, ?, ?)
        """, (datetime.now().isoformat(), status, message, count))


def get_subareas() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM subareas ORDER BY name"
        ).fetchall()]


def get_subarea_stats() -> list:
    with get_conn() as conn:
        return [dict(r) for r in conn.execute("""
            SELECT
                s.sid, s.name, s.post_code, s.updated_at,
                COUNT(t.id)                                                   AS tx_count,
                ROUND(AVG(CASE WHEN t.unit_price > 0 THEN t.unit_price END), 2) AS avg_unit_price,
                ROUND(MAX(CASE WHEN t.unit_price > 0 THEN t.unit_price END), 2) AS max_unit_price,
                ROUND(MIN(CASE WHEN t.unit_price > 0 THEN t.unit_price END), 2) AS min_unit_price,
                MAX(t.transaction_date)                                       AS latest_date
            FROM subareas s
            LEFT JOIN transactions t ON s.sid = t.sid
            GROUP BY s.sid
            ORDER BY avg_unit_price DESC NULLS LAST
        """).fetchall()]


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

    # age filter
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

    # building type filter
    if type_filter != "all":
        clauses.append("building_type=?")
        params.append(type_filter)

    # special trade filter (default: exclude)
    if special_filter == "exclude":
        clauses.append("(is_special_trade IS NULL OR is_special_trade=0)")
    elif special_filter == "only":
        clauses.append("is_special_trade=1")
    # "all" → no filter

    # date range
    if date_from:
        clauses.append("transaction_date >= ?")
        params.append(date_from)
    if date_to:
        clauses.append("transaction_date <= ?")
        params.append(date_to)

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
        ["sid=?"], [sid],
        age_filter, type_filter, special_filter, date_from, date_to,
    )
    where  = " AND ".join(clauses)
    offset = (page - 1) * per_page

    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM transactions WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM transactions
                WHERE {where}
                ORDER BY transaction_date DESC, scraped_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def get_building_types(sid: int) -> list[str]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT DISTINCT building_type FROM transactions
               WHERE sid=? AND building_type IS NOT NULL AND building_type!=''
               ORDER BY building_type""",
            (sid,),
        ).fetchall()
        return [r[0] for r in rows]


def get_community_stats(community: str, sid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("""
            SELECT
                community,
                sid,
                COUNT(*)                                                          AS tx_count,
                ROUND(AVG(CASE WHEN unit_price > 0 THEN unit_price END), 2)      AS avg_unit_price,
                ROUND(MAX(CASE WHEN unit_price > 0 THEN unit_price END), 2)      AS max_unit_price,
                ROUND(MIN(CASE WHEN unit_price > 0 THEN unit_price END), 2)      AS min_unit_price,
                ROUND(AVG(CASE WHEN total_price > 0 THEN total_price END), 0)    AS avg_total_price,
                MAX(transaction_date)                                             AS latest_date,
                MIN(transaction_date)                                             AS earliest_date,
                MAX(building_type)                                                AS building_type,
                MAX(age)                                                          AS sample_age
            FROM transactions
            WHERE community=? AND sid=?
        """, (community, sid)).fetchone()
        return dict(row) if row else None


def get_community_yearly(community: str, sid: int) -> list:
    with get_conn() as conn:
        rows = conn.execute("""
            SELECT
                SUBSTR(transaction_date, 1, 4)                                   AS year,
                COUNT(*)                                                          AS tx_count,
                ROUND(AVG(CASE WHEN unit_price > 0 THEN unit_price END), 2)      AS avg_unit_price
            FROM transactions
            WHERE community=? AND sid=?
              AND transaction_date IS NOT NULL
            GROUP BY year
            ORDER BY year ASC
        """, (community, sid)).fetchall()
        return [dict(r) for r in rows]


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
        ["community=?", "sid=?"], [community, sid],
        special_filter=special_filter, date_from=date_from, date_to=date_to,
    )
    where  = " AND ".join(clauses)
    offset = (page - 1) * per_page
    with get_conn() as conn:
        total = conn.execute(
            f"SELECT COUNT(*) FROM transactions WHERE {where}", params
        ).fetchone()[0]
        rows = conn.execute(
            f"""SELECT * FROM transactions
                WHERE {where}
                ORDER BY transaction_date DESC, scraped_at DESC
                LIMIT ? OFFSET ?""",
            params + [per_page, offset],
        ).fetchall()
        return total, [dict(r) for r in rows]


def get_subarea_by_sid(sid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subareas WHERE sid=?", (sid,)).fetchone()
        return dict(row) if row else None


def clear_scrape_log():
    with get_conn() as conn:
        conn.execute("DELETE FROM scrape_log")


def get_last_scrape() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
