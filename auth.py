"""後台登入檢查與表單 CSRF。"""
import functools
import secrets

from flask import abort, redirect, request, session, url_for


def login_required(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login", next=request.path))
        return f(*args, **kwargs)
    return decorated


def csrf_token() -> str:
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def csrf_ok() -> bool:
    sent = request.form.get("_csrf") or ""
    saved = session.get("_csrf") or ""
    return bool(sent) and secrets.compare_digest(sent, saved)


def require_csrf():
    if not csrf_ok():
        abort(400, "表單已過期，請重新整理後再送出。")
