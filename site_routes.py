"""前台頁面、聯絡表單、sitemap、robots、照片輸出。不改實價同步。"""
from urllib.parse import quote
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, redirect, render_template, request, session

import content
import db
from auth import require_csrf
from brand import SERVICE_ORDER, SERVICES, TOOLS, WHY

site_bp = Blueprint("site", __name__)


def seo(title, description, path, crumbs=None, robots="index, follow", image=""):
    return {
        "title": title,
        "description": description,
        "path": path,
        "crumbs": crumbs or [],
        "robots": robots,
        "image": image,
    }


def _districts():
    from app import NTPC_DISTRICTS, TAOYUAN_DISTRICTS
    return list(TAOYUAN_DISTRICTS) + list(NTPC_DISTRICTS)


def _safe_next(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw.startswith("/") or raw.startswith("//") or "\\" in raw:
        return "/contact"
    return raw


def _with_sent(url: str) -> str:
    path, _, frag = url.partition("#")
    join = "&" if "?" in path else "?"
    path = path + join + "sent=1"
    return path + (("#" + frag) if frag else "")


@site_bp.route("/")
def home():
    from app import _cached
    if request.args.get("q"):
        return redirect("/tools?" + request.query_string.decode())
    profile = content.get_profile()
    faqs = content.public_faqs()
    base = content.base_url()
    schema = content.agent_schema(profile, base)
    if faqs:
        schema["@graph"].append(content.faq_node(faqs[:8], base))
    return render_template(
        "home.html",
        seo=seo(
            "桃園買房賣房｜老楊房快說 楊肇寧・永慶不動產｜實價登錄與房產試算",
            "桃園・鶯歌房仲楊肇寧（老楊房快說・永慶不動產小檜溪喆禮加盟店，營業員）。查實價登錄、土增稅／房地合一／房貸試算，協助買房規劃、屋主售屋、換屋銜接與置產評估。",
            "/",
        ),
        page_schema=schema,
        why=WHY,
        tools=TOOLS,
        services=SERVICES,
        service_order=SERVICE_ORDER,
        districts=_districts(),
        listings=content.public_listings(),
        testimonials=content.public_testimonials(),
        faqs=faqs[:8],
        global_stats=_cached("global_stats", db.get_global_stats),
        last_scrape=_cached("last_scrape", db.get_last_scrape),
    )


@site_bp.route("/tools")
def tools():
    from app import _cached
    return render_template(
        "landing.html",
        stats=_cached("subarea_stats", db.get_subarea_stats),
        last_scrape=_cached("last_scrape", db.get_last_scrape),
        global_stats=_cached("global_stats", db.get_global_stats),
        seo_title="桃園房產試算｜房貸・房地合一・土增稅・實價登錄｜老楊房快說",
        seo_description="土地增值稅、房地合一、購屋能力、房貸、買賣雜費、坪數與車位換算、行情落點、租金投報，並可查桃園、鶯歌實價登錄。試算僅供參考，不是估價報告書。老楊房快說楊肇寧。",
        seo_path="/tools",
        crumbs=[("首頁", "/"), ("試算工具", "")],
    )


@site_bp.route("/about")
def about():
    return render_template(
        "about.html",
        seo=seo(
            "關於我｜楊肇寧・老楊房快說・永慶不動產營業員",
            "楊肇寧，大家叫我老楊，永慶不動產小檜溪喆禮加盟店營業員。服務桃園市與新北市鶯歌區，用實價登錄與試算工具把行情攤開來。",
            "/about",
            [("首頁", "/"), ("關於我", "")],
        ),
        page_schema=content.agent_schema(content.get_profile(), content.base_url()),
        why=WHY,
    )


@site_bp.route("/services")
def services():
    return render_template(
        "services.html",
        seo=seo(
            "買房・售屋・換屋・置產｜老楊房快說服務",
            "楊肇寧的四種服務：買房規劃、屋主售屋、換屋銜接、置產評估。先把數字算清楚，再決定要不要進場。",
            "/services",
            [("首頁", "/"), ("服務", "")],
        ),
        services=SERVICES,
        service_order=SERVICE_ORDER,
    )


@site_bp.route("/services/<slug>")
def service_detail(slug):
    item = SERVICES.get(slug)
    if not item:
        abort(404)
    return render_template(
        "service.html",
        seo=seo(
            item["seo_title"],
            item["seo_desc"],
            "/services/" + slug,
            [("首頁", "/"), ("服務", "/services"), (item["nav"], "")],
        ),
        service=item,
    )


@site_bp.route("/listings")
def listings():
    return render_template(
        "listings.html",
        seo=seo(
            "在售物件｜桃園買房｜老楊房快說",
            "楊肇寧目前上架的出售物件。沒有看到適合的，直接傳區域與預算。",
            "/listings",
            [("首頁", "/"), ("在售物件", "")],
        ),
        listings=content.public_listings(),
    )


@site_bp.route("/listings/<int:lid>")
def listing_detail(lid):
    row = content.get_listing(lid)
    if not row:
        abort(404)
    public = content.is_public_listing(row)
    if not public and not session.get("admin_logged_in"):
        abort(404)
    image = ""
    if row["photos"]:
        image = content.base_url() + f"/media/{row['photos'][0]['media_id']}"
    title = row["title"]
    desc = (row.get("description") or "桃園在售物件。")[:150]
    return render_template(
        "listing.html",
        seo=seo(
            f"{title}｜老楊房快說",
            desc,
            f"/listings/{lid}",
            [("首頁", "/"), ("在售物件", "/listings"), (title, "")],
            robots="index, follow" if public else "noindex, nofollow",
            image=image,
        ),
        listing=row,
        preview=not public,
    )


@site_bp.route("/testimonials")
def testimonials():
    return render_template(
        "testimonials.html",
        seo=seo(
            "成交見證｜老楊房快說",
            "客戶願意公開、且已取得本人同意的回饋。沒有同意的內容不會上架。",
            "/testimonials",
            [("首頁", "/"), ("成交見證", "")],
        ),
        testimonials=content.public_testimonials(),
    )


@site_bp.route("/faq")
def faq():
    faqs = content.public_faqs()
    base = content.base_url()
    schema = {"@context": "https://schema.org", "@graph": [content.faq_node(faqs, base)]}
    return render_template(
        "faq.html",
        seo=seo(
            "買房賣房常見問題｜桃園房仲 FAQ｜老楊房快說",
            "桃園現在買還是等、青埔 A7 中壢八德怎麼選、看屋要注意什麼、房子怎麼估、賣房稅費、換屋順序與置產報酬。",
            "/faq",
            [("首頁", "/"), ("常見問題", "")],
        ),
        page_schema=schema,
        faqs=faqs,
    )


@site_bp.route("/articles")
def articles():
    return render_template(
        "articles.html",
        seo=seo(
            "買房避坑攻略｜看屋與售屋｜老楊房快說",
            "看屋前要檢查什麼、屋主賣房前可以先想清楚的事。文章由老楊房快說整理，不取代驗屋或稅務意見。",
            "/articles",
            [("首頁", "/"), ("避坑攻略", "")],
        ),
        articles=content.public_articles(),
    )


@site_bp.route("/articles/<slug>")
def article_detail(slug):
    row = content.get_article_by_slug(slug)
    if not row:
        abort(404)
    public = content.is_public_article(row)
    if not public and not session.get("admin_logged_in"):
        abort(404)
    return render_template(
        "article.html",
        seo=seo(
            f"{row['title']}｜老楊房快說",
            (row.get("summary") or row["title"])[:150],
            "/articles/" + row["slug"],
            [("首頁", "/"), ("避坑攻略", "/articles"), (row["title"], "")],
            robots="index, follow" if public else "noindex, nofollow",
        ),
        article=row,
        preview=not public,
    )


@site_bp.route("/contact", methods=["GET", "POST"])
def contact():
    error = None
    form = {}
    if request.method == "POST":
        form = request.form
        if (request.form.get("website") or "").strip():
            return redirect(_with_sent(_safe_next(request.form.get("next"))))
        require_csrf()
        now_ts = __import__("time").time()
        last = session.get("inquiry_at") or 0
        if now_ts - float(last) < 20:
            error = "送出太頻繁，請稍後再試，或直接打電話、加 LINE。"
        else:
            try:
                content.add_inquiry(request.form, request.form.get("source_path") or request.path)
                session["inquiry_at"] = now_ts
                return redirect(_with_sent(_safe_next(request.form.get("next"))))
            except ValueError as exc:
                error = str(exc)
    return render_template(
        "contact.html",
        seo=seo(
            "聯絡楊肇寧｜LINE・電話・諮詢｜老楊房快說",
            "加 LINE ID 0935195944，或撥 0935-195-944。買房、賣房、換屋、置產都可以先傳區域與預算。",
            "/contact",
            [("首頁", "/"), ("聯絡", "")],
        ),
        page_schema=content.agent_schema(content.get_profile(), content.base_url()),
        error=error,
        form=form,
    )


@site_bp.route("/privacy")
def privacy():
    return render_template(
        "legal.html",
        seo=seo(
            "隱私政策｜老楊房快說",
            "老楊房快說如何處理聯絡表單、行情訂閱信箱與瀏覽器暫存。",
            "/privacy",
            [("首頁", "/"), ("隱私政策", "")],
        ),
        kind="privacy",
    )


@site_bp.route("/disclaimer")
def disclaimer():
    return render_template(
        "legal.html",
        seo=seo(
            "免責聲明｜老楊房快說",
            "實價登錄與試算僅供參考，不是不動產估價報告書，不得作為融資、訴訟或稅務申報依據。",
            "/disclaimer",
            [("首頁", "/"), ("免責聲明", "")],
        ),
        kind="disclaimer",
    )


@site_bp.route("/media/<int:mid>")
def media(mid):
    row = content.get_media(mid)
    if not row:
        abort(404)
    blob = row["data"]
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    return Response(
        bytes(blob),
        mimetype=row["content_type"] or "image/jpeg",
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@site_bp.route("/robots.txt")
def robots():
    base = content.base_url()
    body = (
        "User-agent: *\n"
        "Allow: /\n"
        "Disallow: /admin\n"
        "Disallow: /dashboard\n"
        "Disallow: /api/\n"
        f"Sitemap: {base}/sitemap.xml\n"
    )
    return Response(body, mimetype="text/plain")


@site_bp.route("/sitemap.xml")
def sitemap():
    base = content.base_url()
    paths = [
        "/", "/about", "/services", "/services/buy", "/services/sell", "/services/swap",
        "/services/invest", "/tools", "/price", "/redevelopment", "/inspection",
        "/listings", "/testimonials", "/faq", "/articles", "/contact",
        "/privacy", "/disclaimer",
    ]
    for dist in _districts():
        paths.append("/price/" + quote(dist["name"]))
    subareas, communities = content.sitemap_market()
    for row in subareas:
        paths.append(f"/subarea/{row['sid']}")
    for row in communities:
        name = quote(row["name"] or "", safe="")
        if name:
            paths.append(f"/community/{row['sid']}?name={name}")
    for row in content.public_listings():
        paths.append(f"/listings/{row['id']}")
    for row in content.public_articles():
        paths.append("/articles/" + quote(row["slug"]))
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    seen = set()
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        loc = escape(base + path)
        lines.append(f"<url><loc>{loc}</loc></url>")
    lines.append("</urlset>")
    return Response("\n".join(lines), mimetype="application/xml")
