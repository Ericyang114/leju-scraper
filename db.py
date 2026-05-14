import sqlite3
import json
from contextlib import contextmanager
from datetime import datetime

DB_PATH = "leju.db"


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
                    parking_area, floor_ratio, building_type, raw_data, scraped_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
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


def get_transactions(sid: int, page: int = 1, per_page: int = 50) -> tuple:
    offset = (page - 1) * per_page
    with get_conn() as conn:
        total = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE sid=?", (sid,)
        ).fetchone()[0]
        rows = conn.execute("""
            SELECT * FROM transactions
            WHERE sid=?
            ORDER BY transaction_date DESC, scraped_at DESC
            LIMIT ? OFFSET ?
        """, (sid, per_page, offset)).fetchall()
        return total, [dict(r) for r in rows]


def get_subarea_by_sid(sid: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM subareas WHERE sid=?", (sid,)).fetchone()
        return dict(row) if row else None


def get_last_scrape() -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM scrape_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
