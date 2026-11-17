"""內容後台。沿用既有 /admin/login，不改實價同步與 /api/push-data。"""
import csv
import io

from flask import Blueprint, Response, flash, redirect, render_template, request, url_for

import content
from auth import login_required, require_csrf

admin_bp = Blueprint("cms", __name__, url_prefix="/admin")

DISTRICTS = [
    "桃園區", "中壢區", "大溪區", "楊梅區", "蘆竹區", "大園區", "龜山區", "八德區",
    "龍潭區", "平鎮區", "新屋區", "觀音區", "復興區", "鶯歌區",
]


def _photos_from_request(lid: int):
    notes = []
    for fh in request.files.getlist("photos"):
        if not fh or not fh.filename:
            continue
        try:
            content.add_photo(lid, fh.filename, fh.read())
        except ValueError as exc:
            notes.append(f"{fh.filename}：{exc}")
    return notes


@admin_bp.route("/")
@login_required
def home():
    return render_template("cms/home.html", counts=content.counts())


@admin_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    if request.method == "POST":
        require_csrf()
        try:
            content.save_profile(request.form)
            flash("個人資料已儲存。前台空白的年資與社群連結不會顯示。", "ok")
        except ValueError as exc:
            flash(str(exc), "error")
        return redirect(url_for("cms.profile"))
    return render_template("cms/profile.html", profile=content.get_profile())


@admin_bp.route("/listings")
@login_required
def listings():
    return render_template("cms/listings.html", rows=content.admin_listings())


@admin_bp.route("/listings/new", methods=["GET", "POST"])
@admin_bp.route("/listings/<int:lid>", methods=["GET", "POST"])
@login_required
def listing_form(lid=None):
    row = content.get_listing(lid) if lid else None
    if lid and not row:
        flash("找不到這筆物件。", "error")
        return redirect(url_for("cms.listings"))
    if request.method == "POST":
        require_csrf()
        try:
            saved = content.save_listing(lid, request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            draft = dict(request.form)
            draft["photos"] = (row or {}).get("photos") or []
            draft["id"] = lid
            return render_template(
                "cms/listing_form.html",
                listing=draft,
                districts=DISTRICTS,
            )
        notes = _photos_from_request(saved)
        if notes:
            flash("物件已儲存，但部分照片沒放上去：" + "；".join(notes), "error")
        else:
            flash("物件已儲存。", "ok")
        return redirect(url_for("cms.listing_form", lid=saved))
    return render_template("cms/listing_form.html", listing=row, districts=DISTRICTS)


@admin_bp.route("/listings/<int:lid>/delete", methods=["POST"])
@login_required
def listing_delete(lid):
    require_csrf()
    content.delete_listing(lid)
    flash("物件已刪除。", "ok")
    return redirect(url_for("cms.listings"))


@admin_bp.route("/listings/<int:lid>/photos/<int:pid>/delete", methods=["POST"])
@login_required
def photo_delete(lid, pid):
    require_csrf()
    content.delete_photo(lid, pid)
    flash("照片已刪除。", "ok")
    return redirect(url_for("cms.listing_form", lid=lid))


@admin_bp.route("/testimonials")
@login_required
def testimonials():
    return render_template("cms/testimonials.html", rows=content.admin_testimonials())


@admin_bp.route("/testimonials/new", methods=["GET", "POST"])
@admin_bp.route("/testimonials/<int:tid>", methods=["GET", "POST"])
@login_required
def testimonial_form(tid=None):
    row = content.get_testimonial(tid) if tid else None
    if tid and not row:
        flash("找不到這則見證。", "error")
        return redirect(url_for("cms.testimonials"))
    if request.method == "POST":
        require_csrf()
        try:
            saved = content.save_testimonial(tid, request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("cms/testimonial_form.html", item=request.form)
        flash("見證已儲存。", "ok")
        return redirect(url_for("cms.testimonial_form", tid=saved))
    return render_template("cms/testimonial_form.html", item=row)


@admin_bp.route("/testimonials/<int:tid>/delete", methods=["POST"])
@login_required
def testimonial_delete(tid):
    require_csrf()
    content.delete_testimonial(tid)
    flash("見證已刪除。", "ok")
    return redirect(url_for("cms.testimonials"))


@admin_bp.route("/faqs")
@login_required
def faqs():
    return render_template("cms/faqs.html", rows=content.admin_faqs())


@admin_bp.route("/faqs/new", methods=["GET", "POST"])
@admin_bp.route("/faqs/<int:fid>", methods=["GET", "POST"])
@login_required
def faq_form(fid=None):
    row = content.get_faq(fid) if fid else None
    if fid and not row:
        flash("找不到這題。", "error")
        return redirect(url_for("cms.faqs"))
    if request.method == "POST":
        require_csrf()
        try:
            saved = content.save_faq(fid, request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("cms/faq_form.html", item=request.form)
        flash("FAQ 已儲存。", "ok")
        return redirect(url_for("cms.faq_form", fid=saved))
    return render_template("cms/faq_form.html", item=row)


@admin_bp.route("/faqs/<int:fid>/delete", methods=["POST"])
@login_required
def faq_delete(fid):
    require_csrf()
    content.delete_faq(fid)
    flash("FAQ 已刪除。", "ok")
    return redirect(url_for("cms.faqs"))


@admin_bp.route("/articles")
@login_required
def articles():
    return render_template("cms/articles.html", rows=content.admin_articles())


@admin_bp.route("/articles/new", methods=["GET", "POST"])
@admin_bp.route("/articles/<int:aid>", methods=["GET", "POST"])
@login_required
def article_form(aid=None):
    row = content.get_article(aid) if aid else None
    if aid and not row:
        flash("找不到這篇文章。", "error")
        return redirect(url_for("cms.articles"))
    if request.method == "POST":
        require_csrf()
        try:
            saved = content.save_article(aid, request.form)
        except ValueError as exc:
            flash(str(exc), "error")
            return render_template("cms/article_form.html", item=request.form)
        flash("文章已儲存。", "ok")
        return redirect(url_for("cms.article_form", aid=saved))
    return render_template("cms/article_form.html", item=row)


@admin_bp.route("/articles/<int:aid>/delete", methods=["POST"])
@login_required
def article_delete(aid):
    require_csrf()
    content.delete_article(aid)
    flash("文章已刪除。", "ok")
    return redirect(url_for("cms.articles"))


@admin_bp.route("/inquiries")
@login_required
def inquiries():
    return render_template("cms/inquiries.html", rows=content.admin_inquiries())


@admin_bp.route("/inquiries.csv")
@login_required
def inquiries_csv():
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at", "status", "name", "phone", "line", "email", "intent", "message", "source"])
    for row in content.inquiry_rows_for_csv():
        writer.writerow([
            row["id"], row["created_at"], row["status"], row["name"], row["phone"],
            row.get("contact_line") or "", row.get("email") or "", row.get("intent") or "",
            row.get("message") or "", row.get("source_path") or "",
        ])
    return Response(
        "\ufeff" + buf.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": "attachment; filename=inquiries.csv"},
    )


@admin_bp.route("/inquiries/<int:iid>/status", methods=["POST"])
@login_required
def inquiry_status(iid):
    require_csrf()
    content.mark_inquiry(iid, request.form.get("status") or "read")
    return redirect(url_for("cms.inquiries"))


@admin_bp.route("/inquiries/<int:iid>/delete", methods=["POST"])
@login_required
def inquiry_delete(iid):
    require_csrf()
    content.delete_inquiry(iid)
    flash("這筆名單已刪除。", "ok")
    return redirect(url_for("cms.inquiries"))
