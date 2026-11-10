"""
前台內容：個人資料、物件、照片、見證、FAQ、文章、諮詢名單。
沿用 db.py 的連線，同一套 SQL 佔位符，SQLite 與 PostgreSQL 都能建表。

照片存在 media_files（SQLite BLOB／PostgreSQL BYTEA），不寫進網站資料夾。
Render 免費方案的磁碟在重新部署時會清空；資料庫（本機 SQLite、線上 Neon）會留著，
所以照片不會因為重新部署而消失。取捨是資料庫容量與讀取速度，單張會先縮成 JPEG。
"""
import os
import re
import uuid
from datetime import datetime
from io import BytesIO

import db
from brand import FAQ_SEED

PH = db.PH

PROFILE_DEFAULTS = {
    "name": "楊肇寧",
    "nickname": "老楊",
    "brand": "老楊房快說",
    "hero_title": "先誠實，再成交",
    "hero_subtitle": "桃園買房、賣房，先把行情算清楚｜老楊房快說・永慶不動產 楊肇寧",
    "hero_tags": "桃園市・鶯歌｜青埔・A7・中壢・八德・龜山・蘆竹",
    "hero_help": "我能幫你：買房規劃・屋主售屋・換屋銜接・置產評估",
    "about_lead": "先誠實，再成交。房子是決策，不是衝動。先看數字，再談喜不喜歡。",
    "about_name_line": "楊肇寧，大家叫我老楊",
    "specialty": "用內政部實價登錄與自建試算工具，把行情、稅費、貸款負擔攤開給你自己檢驗",
    "service_areas": "桃園市（含中壢、八德、蘆竹、龜山、大園、青埔等）、新北市鶯歌區",
    "familiar_areas": "青埔高鐵、A7、小檜溪、中路、八德擴大、航空城、鳳鳴",
    "years_public": "",
    "phone_display": "0935-195-944",
    "phone_tel": "0935195944",
    "line_id": "0935195944",
    "line_url": "https://line.me/ti/p/qkAJ5hcj7m",
    "store_name": "永慶不動產小檜溪喆禮加盟店",
    "company_name": "喆禮資產開發有限公司",
    "tax_id": "93695949",
    "license_no": "桃地價字第1130018676號",
    "store_address": "桃園市桃園區中央街321號",
    "store_phone": "(03)347-0915",
    "store_phone_tel": "033470915",
    "store_fax": "(03)347-5039",
    "hq_service_phone": "0800-306888",
    "broker_name": "李姿璇",
    "broker_license": "(113)桃市經字第002019號",
    "agent_license": "(114)登字第487462號",
    "facebook_url": "https://facebook.com/yangtalkhouse",
    "instagram_url": "",
    "youtube_url": "",
    "threads_url": "",
    "tiktok_url": "",
    "shop_591_url": "https://www.591.com.tw/broker47759",
    "lewu_url": "",
    "yungching_url": "",
    "team_note": "我所在的永慶不動產小檜溪喆禮加盟店，夥伴日常一起開發與帶看、物件資訊互通。你要找的房子、要賣的價格，有人一起推、一起顧流程。",
    "team_label": "",
    "franchise_notice": "每一家加盟店均為獨立經營之經紀業，加盟店與加盟總部均為不同法人，財務與法律責任各自獨立。",
    "contact_title": "買房、賣房、換屋，從一次聊天開始",
    "contact_body": "傳預算、社區名稱或售屋地址給我。能先在站上試算的，我會請你先算一版，聊天時對數字比較快。",
}

PROFILE_KEYS = list(PROFILE_DEFAULTS.keys())
URL_KEYS = {
    "line_url", "facebook_url", "instagram_url", "youtube_url", "threads_url",
    "tiktok_url", "shop_591_url", "lewu_url", "yungching_url",
}
SOCIAL_FIELDS = [
    ("facebook_url", "Facebook"),
    ("instagram_url", "Instagram"),
    ("youtube_url", "YouTube"),
    ("threads_url", "Threads"),
    ("tiktok_url", "TikTok"),
    ("shop_591_url", "591"),
    ("lewu_url", "樂屋網"),
    ("yungching_url", "永慶個人頁"),
]


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def base_url() -> str:
    configured = os.environ.get("CANONICAL_BASE_URL", "").strip().rstrip("/")
    if configured:
        return configured
    try:
        from flask import has_request_context, request
        if has_request_context():
            return request.url_root.rstrip("/")
    except Exception:
        pass
    return os.environ.get("RENDER_URL", "https://leju-scraper.onrender.com").rstrip("/")


def safe_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("https://") or url.startswith("http://"):
        return url
    return ""


def e164(display: str) -> str:
    digits = re.sub(r"\D", "", display or "")
    if digits.startswith("0"):
        digits = "886" + digits[1:]
    return f"+{digits}" if digits else ""


def _insert(conn, sql: str, params: tuple):
    if db.IS_POSTGRES:
        import psycopg2.extras  # noqa: F401
        with conn.cursor() as cur:
            cur.execute(sql + " RETURNING id", params)
            return cur.fetchone()[0]
    cur = conn.execute(sql, params)
    return cur.lastrowid


def _flag(value) -> int:
    return 1 if str(value) in {"1", "true", "True", "on", "yes"} else 0


def init_content():
    with db.get_conn() as conn:
        if db.IS_POSTGRES:
            _exec_pg(conn)
        else:
            _exec_sqlite(conn)
        _seed(conn)


def _exec_sqlite(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS site_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS media_files (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            filename     TEXT,
            content_type TEXT NOT NULL,
            byte_size    INTEGER NOT NULL DEFAULT 0,
            data         BLOB NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            title        TEXT NOT NULL,
            district     TEXT,
            address      TEXT,
            price_label  TEXT,
            layout       TEXT,
            ping         TEXT,
            age_text     TEXT,
            floor_text   TEXT,
            parking      TEXT,
            description  TEXT,
            external_url TEXT,
            status       TEXT NOT NULL DEFAULT 'draft',
            is_demo      INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS listing_photos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            listing_id INTEGER NOT NULL,
            media_id   INTEGER NOT NULL,
            caption    TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS testimonials (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            client_label TEXT NOT NULL,
            area         TEXT,
            quote        TEXT NOT NULL,
            consent      INTEGER NOT NULL DEFAULT 0,
            published    INTEGER NOT NULL DEFAULT 0,
            is_demo      INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS faqs (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            question   TEXT NOT NULL,
            answer     TEXT NOT NULL,
            category   TEXT,
            published  INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS articles (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            title      TEXT NOT NULL,
            slug       TEXT NOT NULL UNIQUE,
            summary    TEXT,
            body       TEXT,
            category   TEXT,
            published  INTEGER NOT NULL DEFAULT 0,
            is_demo    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inquiries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            phone        TEXT NOT NULL,
            contact_line TEXT,
            email        TEXT,
            intent       TEXT,
            message      TEXT NOT NULL,
            source_path  TEXT,
            status       TEXT NOT NULL DEFAULT 'new',
            created_at   TEXT NOT NULL
        );
    """)


def _exec_pg(conn):
    stmts = [
        """
        CREATE TABLE IF NOT EXISTS site_settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS media_files (
            id           SERIAL PRIMARY KEY,
            filename     TEXT,
            content_type TEXT NOT NULL,
            byte_size    INTEGER NOT NULL DEFAULT 0,
            data         BYTEA NOT NULL,
            created_at   TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS listings (
            id           SERIAL PRIMARY KEY,
            title        TEXT NOT NULL,
            district     TEXT,
            address      TEXT,
            price_label  TEXT,
            layout       TEXT,
            ping         TEXT,
            age_text     TEXT,
            floor_text   TEXT,
            parking      TEXT,
            description  TEXT,
            external_url TEXT,
            status       TEXT NOT NULL DEFAULT 'draft',
            is_demo      INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS listing_photos (
            id         SERIAL PRIMARY KEY,
            listing_id INTEGER NOT NULL,
            media_id   INTEGER NOT NULL,
            caption    TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS testimonials (
            id           SERIAL PRIMARY KEY,
            client_label TEXT NOT NULL,
            area         TEXT,
            quote        TEXT NOT NULL,
            consent      INTEGER NOT NULL DEFAULT 0,
            published    INTEGER NOT NULL DEFAULT 0,
            is_demo      INTEGER NOT NULL DEFAULT 0,
            sort_order   INTEGER NOT NULL DEFAULT 0,
            created_at   TEXT NOT NULL,
            updated_at   TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS faqs (
            id         SERIAL PRIMARY KEY,
            question   TEXT NOT NULL,
            answer     TEXT NOT NULL,
            category   TEXT,
            published  INTEGER NOT NULL DEFAULT 1,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS articles (
            id         SERIAL PRIMARY KEY,
            title      TEXT NOT NULL,
            slug       TEXT NOT NULL UNIQUE,
            summary    TEXT,
            body       TEXT,
            category   TEXT,
            published  INTEGER NOT NULL DEFAULT 0,
            is_demo    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS inquiries (
            id           SERIAL PRIMARY KEY,
            name         TEXT NOT NULL,
            phone        TEXT NOT NULL,
            contact_line TEXT,
            email        TEXT,
            intent       TEXT,
            message      TEXT NOT NULL,
            source_path  TEXT,
            status       TEXT NOT NULL DEFAULT 'new',
            created_at   TEXT NOT NULL
        )
        """,
    ]
    for sql in stmts:
        db._exec(conn, sql)


def _has_flag(conn, key: str) -> bool:
    return db._row(conn, f"SELECT key FROM site_settings WHERE key={PH}", (key,)) is not None


def _set_flag(conn, key: str):
    db._exec(conn,
             f"INSERT INTO site_settings (key, value) VALUES ({PH},{PH}) ON CONFLICT (key) DO NOTHING",
             (key, "1"))


def _seed(conn):
    for key, value in PROFILE_DEFAULTS.items():
        db._exec(conn,
                 f"INSERT INTO site_settings (key, value) VALUES ({PH},{PH}) ON CONFLICT (key) DO NOTHING",
                 (key, value))
    now = _now()
    if not _has_flag(conn, "seed_faq_v1"):
        for i, (cat, q, a) in enumerate(FAQ_SEED, start=1):
            _insert(conn, f"""
                INSERT INTO faqs (question, answer, category, published, sort_order, created_at, updated_at)
                VALUES ({PH},{PH},{PH},1,{PH},{PH},{PH})
            """, (q, a, cat, i, now, now))
        _set_flag(conn, "seed_faq_v1")
    if not _has_flag(conn, "seed_demo_listing_v1"):
        _insert(conn, f"""
            INSERT INTO listings (
                title, district, address, price_label, layout, ping, age_text, floor_text,
                parking, description, external_url, status, is_demo, sort_order, created_at, updated_at
            ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},1,0,{PH},{PH})
        """, (
            "【示範資料，請勿上架】物件範例",
            "桃園區",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "這筆是系統示範，不是真實在售物件，也沒有真實價格。請改成你自己的物件、取消「示範資料」之後再上架。前台預設不會顯示。",
            "",
            "draft",
            now, now,
        ))
        _set_flag(conn, "seed_demo_listing_v1")
    if not _has_flag(conn, "seed_demo_story_v1"):
        _insert(conn, f"""
            INSERT INTO testimonials (
                client_label, area, quote, consent, published, is_demo, sort_order, created_at, updated_at
            ) VALUES ({PH},{PH},{PH},0,0,1,0,{PH},{PH})
        """, (
            "【示範】王先生",
            "桃園區",
            "這是示範文字，不是真實客戶回饋。未勾選本人同意，預設不上架。請改成當事人同意過的原文再公開。",
            now, now,
        ))
        _set_flag(conn, "seed_demo_story_v1")
    if not _has_flag(conn, "seed_articles_v1"):
        _insert(conn, f"""
            INSERT INTO articles (title, slug, summary, body, category, published, is_demo, created_at, updated_at)
            VALUES ({PH},{PH},{PH},{PH},{PH},1,0,{PH},{PH})
        """, (
            "看屋前，先把這份清單看完",
            "viewing-checklist",
            "看屋前的功課、現場要問的事、兩次看屋怎麼排。完整清單在站內看屋注意事項。",
            "看房之前，先把功課做完，現場才問得出重點。\n\n"
            "站內「看屋注意事項」已經整理好看屋前必做的功課、現場必問的題目、兩次看屋的策略差異，以及屋況修繕費用怎麼對照。修繕金額會因屋況差很多，頁面上的表只是參考區間，不是報價。\n\n"
            "重大結構、漏水或壁癌，建議另請專業驗屋。帶看時我會依屋況提醒議價與修繕風險，不代替驗屋報告。\n\n"
            "完整清單：/inspection",
            "買方避坑",
            now, now,
        ))
        _insert(conn, f"""
            INSERT INTO articles (title, slug, summary, body, category, published, is_demo, created_at, updated_at)
            VALUES ({PH},{PH},{PH},{PH},{PH},0,1,{PH},{PH})
        """, (
            "【示範草稿，請勿上架】賣房避坑必備",
            "demo-seller-pitfalls",
            "示範草稿。尚未撰寫，預設不上架。",
            "這是示範草稿，不是已確認的屋主攻略，預設不上架。\n\n"
            "可以在後台改寫定價、專任與一般委託、稅費實拿等內容，確認後再取消示範並上架。請勿直接公開這則示範。",
            "屋主避坑",
            now, now,
        ))
        _set_flag(conn, "seed_articles_v1")


def get_profile() -> dict:
    data = dict(PROFILE_DEFAULTS)
    with db.get_conn() as conn:
        rows = db._rows(conn, "SELECT key, value FROM site_settings")
    for row in rows:
        if row["key"] in data:
            data[row["key"]] = row["value"] if row["value"] is not None else ""
    data["job_title"] = "營業員"
    for key in URL_KEYS:
        data[key] = safe_url(data.get(key, ""))
    if not data.get("phone_tel"):
        data["phone_tel"] = re.sub(r"\D", "", data.get("phone_display") or "")
    return data


def save_profile(form):
    with db.get_conn() as conn:
        for key in PROFILE_KEYS:
            value = (form.get(key) or "").strip()
            value = value.replace("專業經紀人", "營業員")
            if len(value) > 4000:
                value = value[:4000]
            if key in URL_KEYS and value:
                value = safe_url(value)
                if not value:
                    raise ValueError(f"{key} 請填 http:// 或 https:// 開頭的網址，沒有就留白。")
            db._exec(conn, f"""
                INSERT INTO site_settings (key, value) VALUES ({PH},{PH})
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value
            """, (key, value))


def social_links(profile: dict | None = None) -> list:
    profile = profile or get_profile()
    items = []
    if profile.get("line_url"):
        items.append(("LINE", profile["line_url"]))
    for key, label in SOCIAL_FIELDS:
        if profile.get(key):
            items.append((label, profile[key]))
    return items


def _public_listing_sql(alias="l"):
    return (
        f"{alias}.status='published' AND {alias}.is_demo=0 "
        f"AND {alias}.title NOT LIKE '%示範%'"
    )


def is_public_listing(row) -> bool:
    if not row:
        return False
    if _flag(row.get("is_demo")):
        return False
    if (row.get("status") or "") != "published":
        return False
    if "示範" in (row.get("title") or ""):
        return False
    return True


def is_public_story(row) -> bool:
    if not row:
        return False
    return (
        _flag(row.get("published"))
        and _flag(row.get("consent"))
        and not _flag(row.get("is_demo"))
        and "示範" not in (row.get("quote") or "")
        and "示範" not in (row.get("client_label") or "")
    )


def is_public_article(row) -> bool:
    if not row:
        return False
    return _flag(row.get("published")) and not _flag(row.get("is_demo")) and "示範" not in (row.get("title") or "")


def public_listings():
    with db.get_conn() as conn:
        return db._rows(conn, f"""
            SELECT l.*,
              (SELECT media_id FROM listing_photos p
                WHERE p.listing_id=l.id ORDER BY p.sort_order, p.id LIMIT 1) AS cover_id
            FROM listings l
            WHERE {_public_listing_sql()}
            ORDER BY l.sort_order ASC, l.id DESC
        """)


def admin_listings():
    with db.get_conn() as conn:
        return db._rows(conn, """
            SELECT l.*,
              (SELECT media_id FROM listing_photos p
                WHERE p.listing_id=l.id ORDER BY p.sort_order, p.id LIMIT 1) AS cover_id,
              (SELECT COUNT(*) FROM listing_photos p WHERE p.listing_id=l.id) AS photo_count
            FROM listings l
            ORDER BY l.sort_order ASC, l.id DESC
        """)


def get_listing(lid: int):
    with db.get_conn() as conn:
        row = db._row(conn, f"SELECT * FROM listings WHERE id={PH}", (lid,))
        if not row:
            return None
        row["photos"] = db._rows(conn, f"""
            SELECT * FROM listing_photos WHERE listing_id={PH} ORDER BY sort_order, id
        """, (lid,))
        row["external_url"] = safe_url(row.get("external_url") or "")
        return row


def _listing_from_form(form) -> dict:
    status = (form.get("status") or "draft").strip()
    if status not in {"draft", "published", "archived"}:
        status = "draft"
    try:
        sort_order = int(form.get("sort_order") or 0)
    except ValueError:
        sort_order = 0
    return {
        "title": (form.get("title") or "").strip()[:120],
        "district": (form.get("district") or "").strip()[:20],
        "address": (form.get("address") or "").strip()[:200],
        "price_label": (form.get("price_label") or "").strip()[:40],
        "layout": (form.get("layout") or "").strip()[:40],
        "ping": (form.get("ping") or "").strip()[:40],
        "age_text": (form.get("age_text") or "").strip()[:40],
        "floor_text": (form.get("floor_text") or "").strip()[:40],
        "parking": (form.get("parking") or "").strip()[:40],
        "description": (form.get("description") or "").strip()[:8000],
        "external_url": (form.get("external_url") or "").strip(),
        "status": status,
        "is_demo": 1 if form.get("is_demo") else 0,
        "sort_order": sort_order,
    }


def _validate_listing(data: dict):
    if not data["title"]:
        raise ValueError("請填物件標題。")
    if data["external_url"]:
        data["external_url"] = safe_url(data["external_url"])
        if not data["external_url"]:
            raise ValueError("外部連結請填 http:// 或 https:// 開頭，或留白。")
    if data["status"] == "published":
        if data["is_demo"] or "示範" in data["title"]:
            raise ValueError("示範物件不能上架。請改成真實物件、取消「示範資料」，再改為上架。")


def save_listing(lid, form) -> int:
    data = _listing_from_form(form)
    _validate_listing(data)
    now = _now()
    with db.get_conn() as conn:
        if lid:
            db._exec(conn, f"""
                UPDATE listings SET
                    title={PH}, district={PH}, address={PH}, price_label={PH}, layout={PH},
                    ping={PH}, age_text={PH}, floor_text={PH}, parking={PH}, description={PH},
                    external_url={PH}, status={PH}, is_demo={PH}, sort_order={PH}, updated_at={PH}
                WHERE id={PH}
            """, (
                data["title"], data["district"], data["address"], data["price_label"], data["layout"],
                data["ping"], data["age_text"], data["floor_text"], data["parking"], data["description"],
                data["external_url"], data["status"], data["is_demo"], data["sort_order"], now, lid,
            ))
            return int(lid)
        return _insert(conn, f"""
            INSERT INTO listings (
                title, district, address, price_label, layout, ping, age_text, floor_text, parking,
                description, external_url, status, is_demo, sort_order, created_at, updated_at
            ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
        """, (
            data["title"], data["district"], data["address"], data["price_label"], data["layout"],
            data["ping"], data["age_text"], data["floor_text"], data["parking"], data["description"],
            data["external_url"], data["status"], data["is_demo"], data["sort_order"], now, now,
        ))


def delete_listing(lid: int):
    with db.get_conn() as conn:
        photos = db._rows(conn, f"SELECT media_id FROM listing_photos WHERE listing_id={PH}", (lid,))
        db._exec(conn, f"DELETE FROM listing_photos WHERE listing_id={PH}", (lid,))
        for photo in photos:
            db._exec(conn, f"DELETE FROM media_files WHERE id={PH}", (photo["media_id"],))
        db._exec(conn, f"DELETE FROM listings WHERE id={PH}", (lid,))


def normalize_image(raw: bytes) -> tuple[bytes, str]:
    if not raw:
        raise ValueError("空檔案。")
    if len(raw) > 8_000_000:
        raise ValueError("單張原始圖請小於 8MB。")
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise ValueError("伺服器尚未安裝圖片處理套件 Pillow。") from exc
    Image.MAX_IMAGE_PIXELS = 24_000_000
    try:
        im = Image.open(BytesIO(raw))
        im = ImageOps.exif_transpose(im)
        im = im.convert("RGB")
    except Exception as exc:
        raise ValueError("讀不到這張圖，請改傳 JPG、PNG 或 WEBP。") from exc
    im.thumbnail((1600, 1600))
    out = BytesIO()
    im.save(out, format="JPEG", quality=82, optimize=True)
    data = out.getvalue()
    if len(data) > 1_600_000:
        im.thumbnail((1200, 1200))
        out = BytesIO()
        im.save(out, format="JPEG", quality=72, optimize=True)
        data = out.getvalue()
    return data, "image/jpeg"


def add_photo(listing_id: int, filename: str, raw: bytes) -> int:
    data, content_type = normalize_image(raw)
    now = _now()
    with db.get_conn() as conn:
        media_id = _insert(conn, f"""
            INSERT INTO media_files (filename, content_type, byte_size, data, created_at)
            VALUES ({PH},{PH},{PH},{PH},{PH})
        """, (os.path.basename(filename or "photo.jpg")[:120], content_type, len(data), data, now))
        count = db._scalar(conn, f"SELECT COUNT(*) FROM listing_photos WHERE listing_id={PH}", (listing_id,)) or 0
        _insert(conn, f"""
            INSERT INTO listing_photos (listing_id, media_id, caption, sort_order)
            VALUES ({PH},{PH},{PH},{PH})
        """, (listing_id, media_id, "", int(count)))
        return media_id


def delete_photo(listing_id: int, photo_id: int):
    with db.get_conn() as conn:
        row = db._row(conn, f"SELECT media_id FROM listing_photos WHERE id={PH} AND listing_id={PH}",
                      (photo_id, listing_id))
        if not row:
            return
        db._exec(conn, f"DELETE FROM listing_photos WHERE id={PH}", (photo_id,))
        db._exec(conn, f"DELETE FROM media_files WHERE id={PH}", (row["media_id"],))


def get_media(mid: int):
    with db.get_conn() as conn:
        return db._row(conn, f"SELECT id, content_type, data FROM media_files WHERE id={PH}", (mid,))


def public_testimonials():
    with db.get_conn() as conn:
        rows = db._rows(conn, """
            SELECT * FROM testimonials
            WHERE published=1 AND consent=1 AND is_demo=0
              AND client_label NOT LIKE '%示範%'
              AND quote NOT LIKE '%示範%'
            ORDER BY sort_order ASC, id DESC
        """)
    return rows


def admin_testimonials():
    with db.get_conn() as conn:
        return db._rows(conn, "SELECT * FROM testimonials ORDER BY sort_order ASC, id DESC")


def get_testimonial(tid: int):
    with db.get_conn() as conn:
        return db._row(conn, f"SELECT * FROM testimonials WHERE id={PH}", (tid,))


def save_testimonial(tid, form) -> int:
    data = {
        "client_label": (form.get("client_label") or "").strip()[:80],
        "area": (form.get("area") or "").strip()[:40],
        "quote": (form.get("quote") or "").strip()[:2000],
        "consent": 1 if form.get("consent") else 0,
        "published": 1 if form.get("published") else 0,
        "is_demo": 1 if form.get("is_demo") else 0,
        "sort_order": int(form.get("sort_order") or 0) if str(form.get("sort_order") or "0").lstrip("-").isdigit() else 0,
    }
    if not data["client_label"] or not data["quote"]:
        raise ValueError("請填稱呼與見證內容。")
    if data["published"]:
        if not data["consent"]:
            raise ValueError("需勾選已取得本人同意，才能上架。")
        if data["is_demo"] or "示範" in data["client_label"] or "示範" in data["quote"]:
            raise ValueError("示範見證不能上架。請改成真實內容並取消示範。")
    now = _now()
    with db.get_conn() as conn:
        if tid:
            db._exec(conn, f"""
                UPDATE testimonials SET
                    client_label={PH}, area={PH}, quote={PH}, consent={PH}, published={PH},
                    is_demo={PH}, sort_order={PH}, updated_at={PH}
                WHERE id={PH}
            """, (
                data["client_label"], data["area"], data["quote"], data["consent"], data["published"],
                data["is_demo"], data["sort_order"], now, tid,
            ))
            return int(tid)
        return _insert(conn, f"""
            INSERT INTO testimonials (
                client_label, area, quote, consent, published, is_demo, sort_order, created_at, updated_at
            ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
        """, (
            data["client_label"], data["area"], data["quote"], data["consent"], data["published"],
            data["is_demo"], data["sort_order"], now, now,
        ))


def delete_testimonial(tid: int):
    with db.get_conn() as conn:
        db._exec(conn, f"DELETE FROM testimonials WHERE id={PH}", (tid,))


def public_faqs():
    with db.get_conn() as conn:
        return db._rows(conn, """
            SELECT * FROM faqs WHERE published=1 ORDER BY sort_order ASC, id ASC
        """)


def admin_faqs():
    with db.get_conn() as conn:
        return db._rows(conn, "SELECT * FROM faqs ORDER BY sort_order ASC, id ASC")


def get_faq(fid: int):
    with db.get_conn() as conn:
        return db._row(conn, f"SELECT * FROM faqs WHERE id={PH}", (fid,))


def save_faq(fid, form) -> int:
    question = (form.get("question") or "").strip()[:200]
    answer = (form.get("answer") or "").strip()[:4000]
    category = (form.get("category") or "").strip()[:20]
    published = 1 if form.get("published") else 0
    try:
        sort_order = int(form.get("sort_order") or 0)
    except ValueError:
        sort_order = 0
    if not question or not answer:
        raise ValueError("請填問題與回答。")
    now = _now()
    with db.get_conn() as conn:
        if fid:
            db._exec(conn, f"""
                UPDATE faqs SET question={PH}, answer={PH}, category={PH}, published={PH},
                    sort_order={PH}, updated_at={PH}
                WHERE id={PH}
            """, (question, answer, category, published, sort_order, now, fid))
            return int(fid)
        return _insert(conn, f"""
            INSERT INTO faqs (question, answer, category, published, sort_order, created_at, updated_at)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH})
        """, (question, answer, category, published, sort_order, now, now))


def delete_faq(fid: int):
    with db.get_conn() as conn:
        db._exec(conn, f"DELETE FROM faqs WHERE id={PH}", (fid,))


def _slugify(raw: str) -> str:
    raw = (raw or "").strip().lower()
    raw = re.sub(r"[^a-z0-9\-]+", "-", raw).strip("-")
    return raw[:80]


def public_articles():
    with db.get_conn() as conn:
        return db._rows(conn, """
            SELECT * FROM articles
            WHERE published=1 AND is_demo=0 AND title NOT LIKE '%示範%'
            ORDER BY id DESC
        """)


def admin_articles():
    with db.get_conn() as conn:
        return db._rows(conn, "SELECT * FROM articles ORDER BY id DESC")


def get_article(aid: int):
    with db.get_conn() as conn:
        return db._row(conn, f"SELECT * FROM articles WHERE id={PH}", (aid,))


def get_article_by_slug(slug: str):
    with db.get_conn() as conn:
        return db._row(conn, f"SELECT * FROM articles WHERE slug={PH}", (slug,))


def save_article(aid, form) -> int:
    title = (form.get("title") or "").strip()[:160]
    summary = (form.get("summary") or "").strip()[:300]
    body = (form.get("body") or "").strip()[:20000]
    category = (form.get("category") or "").strip()[:40]
    published = 1 if form.get("published") else 0
    is_demo = 1 if form.get("is_demo") else 0
    slug = _slugify(form.get("slug") or "")
    if not title or not body:
        raise ValueError("請填標題與內文。")
    if published and (is_demo or "示範" in title):
        raise ValueError("示範文章不能上架。請取消示範並改掉標題後再上架。")
    now = _now()
    with db.get_conn() as conn:
        if not slug:
            slug = f"post-{aid}" if aid else "pending-" + uuid.uuid4().hex[:10]
        other = db._row(conn, f"SELECT id FROM articles WHERE slug={PH}" + (f" AND id<>{PH}" if aid else ""),
                        (slug, aid) if aid else (slug,))
        if other:
            raise ValueError("這個網址代碼已被另一篇文章使用。")
        if aid:
            db._exec(conn, f"""
                UPDATE articles SET title={PH}, slug={PH}, summary={PH}, body={PH}, category={PH},
                    published={PH}, is_demo={PH}, updated_at={PH}
                WHERE id={PH}
            """, (title, slug, summary, body, category, published, is_demo, now, aid))
            if slug.startswith("pending-") or slug == f"post-{aid}":
                pass
            return int(aid)
        new_id = _insert(conn, f"""
            INSERT INTO articles (title, slug, summary, body, category, published, is_demo, created_at, updated_at)
            VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH},{PH})
        """, (title, slug, summary, body, category, published, is_demo, now, now))
        if slug.startswith("pending-"):
            final = f"post-{new_id}"
            db._exec(conn, f"UPDATE articles SET slug={PH} WHERE id={PH}", (final, new_id))
        return new_id


def delete_article(aid: int):
    with db.get_conn() as conn:
        db._exec(conn, f"DELETE FROM articles WHERE id={PH}", (aid,))


def add_inquiry(form, source_path: str) -> int:
    name = (form.get("name") or "").strip()[:40]
    phone = (form.get("phone") or "").strip()[:20]
    contact_line = (form.get("contact_line") or "").strip()[:40]
    email = (form.get("email") or "").strip()[:120]
    intent = (form.get("intent") or "").strip()[:20]
    message = (form.get("message") or "").strip()[:2000]
    if not name:
        raise ValueError("請填怎麼稱呼。")
    if not re.fullmatch(r"[\d\-\+\(\)\s]{8,20}", phone):
        raise ValueError("請填可以打得通的電話。")
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("Email 格式看起來不對，可以留白。")
    if intent not in {"買房規劃", "屋主售屋", "換屋銜接", "置產評估", "其他"}:
        intent = "其他"
    if not message:
        raise ValueError("請寫一下想談的內容。")
    now = _now()
    with db.get_conn() as conn:
        return _insert(conn, f"""
            INSERT INTO inquiries (
                name, phone, contact_line, email, intent, message, source_path, status, created_at
            ) VALUES ({PH},{PH},{PH},{PH},{PH},{PH},{PH},'new',{PH})
        """, (name, phone, contact_line, email, intent, message, (source_path or "")[:200], now))


def admin_inquiries():
    with db.get_conn() as conn:
        return db._rows(conn, "SELECT * FROM inquiries ORDER BY id DESC")


def inquiry_rows_for_csv():
    return admin_inquiries()


def mark_inquiry(iid: int, status: str):
    if status not in {"new", "read"}:
        status = "read"
    with db.get_conn() as conn:
        db._exec(conn, f"UPDATE inquiries SET status={PH} WHERE id={PH}", (status, iid))


def delete_inquiry(iid: int):
    with db.get_conn() as conn:
        db._exec(conn, f"DELETE FROM inquiries WHERE id={PH}", (iid,))


def counts() -> dict:
    with db.get_conn() as conn:
        def n(sql):
            return db._scalar(conn, sql) or 0
        return {
            "listings": n("SELECT COUNT(*) FROM listings"),
            "listings_on": n("SELECT COUNT(*) FROM listings WHERE status='published' AND is_demo=0"),
            "stories": n("SELECT COUNT(*) FROM testimonials"),
            "stories_on": n("SELECT COUNT(*) FROM testimonials WHERE published=1 AND consent=1 AND is_demo=0"),
            "faqs": n("SELECT COUNT(*) FROM faqs WHERE published=1"),
            "articles": n("SELECT COUNT(*) FROM articles"),
            "articles_on": n("SELECT COUNT(*) FROM articles WHERE published=1 AND is_demo=0"),
            "inquiries_new": n("SELECT COUNT(*) FROM inquiries WHERE status='new'"),
            "inquiries": n("SELECT COUNT(*) FROM inquiries"),
        }


def sitemap_market():
    with db.get_conn() as conn:
        subareas = db._rows(conn, "SELECT sid, name FROM subareas ORDER BY sid")
        communities = db._rows(conn, """
            SELECT community AS name, sid
            FROM transactions
            WHERE community IS NOT NULL AND TRIM(community) <> ''
            GROUP BY community, sid
            ORDER BY community
        """)
    return subareas, communities


def agent_schema(profile: dict, url: str) -> dict:
    same = []
    for key in ("facebook_url", "instagram_url", "youtube_url", "threads_url", "tiktok_url",
                "shop_591_url", "lewu_url", "yungching_url", "line_url"):
        if profile.get(key):
            same.append(profile[key])
    phone = e164(profile.get("phone_display") or "")
    store_phone = e164(profile.get("store_phone") or "")
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "RealEstateAgent",
                "@id": url + "/#agent",
                "name": profile.get("name") or "楊肇寧",
                "alternateName": profile.get("brand") or "老楊房快說",
                "jobTitle": "營業員",
                "telephone": phone,
                "url": url + "/",
                "image": url + "/static/images/avatar.png",
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": profile.get("store_address") or "",
                    "addressCountry": "TW",
                },
                "areaServed": ["桃園市", "新北市鶯歌區"],
                "identifier": {
                    "@type": "PropertyValue",
                    "name": "不動產營業員證號",
                    "value": profile.get("agent_license") or "",
                },
                "worksFor": {"@id": url + "/#store"},
                "sameAs": same,
            },
            {
                "@type": "LocalBusiness",
                "@id": url + "/#store",
                "name": profile.get("store_name") or "",
                "legalName": profile.get("company_name") or "",
                "taxID": profile.get("tax_id") or "",
                "telephone": store_phone,
                "address": {
                    "@type": "PostalAddress",
                    "streetAddress": profile.get("store_address") or "",
                    "addressCountry": "TW",
                },
                "url": url + "/",
                "image": url + "/static/images/avatar.png",
                "brand": {"@type": "Brand", "name": "永慶不動產"},
                "employee": {"@id": url + "/#agent"},
            },
        ],
    }


def faq_node(faqs, url: str) -> dict:
    return {
        "@type": "FAQPage",
        "@id": url + "/faq#faq",
        "mainEntity": [
            {
                "@type": "Question",
                "name": item["question"],
                "acceptedAnswer": {"@type": "Answer", "text": item["answer"]},
            }
            for item in faqs
        ],
    }
