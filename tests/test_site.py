"""前台架構與內容後台。使用獨立 SQLite，不連正式資料庫。"""
import base64
import os
import re
import tempfile
import unittest
from io import BytesIO

os.environ["DISABLE_AUTO_SCRAPE"] = "1"
os.environ.pop("DATABASE_URL", None)
os.environ["DB_PATH"] = tempfile.mktemp(prefix="leju-site-", suffix=".db")
os.environ["CANONICAL_BASE_URL"] = "https://example.test"
os.environ["ADMIN_PASSWORD"] = "leju2024"

import app as app_module  # noqa: E402
import content  # noqa: E402


class SiteTests(unittest.TestCase):
    def setUp(self):
        self.client = app_module.app.test_client()

    def test_home_brand_and_no_forbidden_claims(self):
        html = self.client.get("/").get_data(as_text=True)
        self.assertIn("先誠實，再成交", html)
        self.assertIn("營業員", html)
        self.assertNotIn("專業經紀人", html)
        self.assertNotIn("五大第一", html)
        self.assertNotIn("百萬業績", html)
        self.assertNotIn("多年", html)
        self.assertFalse(re.search(r"楊肇寧.{0,8}經紀人|經紀人.{0,8}楊肇寧", html))
        self.assertIn("桃地價字第1130018676號", html)
        self.assertIn("每一家加盟店均為獨立經營之經紀業", html)
        self.assertIn('rel="canonical" href="https://example.test/"', html)
        self.assertIn("RealEstateAgent", html)
        self.assertIn("LocalBusiness", html)
        self.assertIn("FAQPage", html)
        self.assertNotIn("年資", html)

    def test_tools_and_old_query_redirect(self):
        tools = self.client.get("/tools").get_data(as_text=True)
        for label in ("土地增值稅", "房地合一", "購屋能力", "房貸", "買賣雜費", "坪數換算", "車位折算", "租金投報"):
            self.assertIn(label, tools)
        self.assertNotIn("專業經紀人", tools)
        moved = self.client.get("/?q=測試社區&sid=1")
        self.assertEqual(moved.status_code, 302)
        self.assertIn("/tools?q=", moved.headers["Location"])

    def test_public_pages_and_existing_routes(self):
        pages = [
            "/about", "/services", "/services/buy", "/services/sell", "/services/swap",
            "/services/invest", "/listings", "/testimonials", "/faq", "/articles",
            "/articles/viewing-checklist", "/contact", "/privacy", "/disclaimer",
            "/price", "/price/桃園區", "/price/鶯歌區", "/redevelopment", "/inspection",
            "/robots.txt", "/sitemap.xml",
        ]
        for path in pages:
            res = self.client.get(path)
            self.assertEqual(res.status_code, 200, path)
        inspection = self.client.get("/inspection").get_data(as_text=True)
        self.assertIn("inspect-wm", inspection)
        self.assertIn("永慶不動產 楊肇寧 0935-195-944", inspection)
        self.assertIn("pointer-events: none", inspection)
        home = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("inspect-wm", home)
        self.assertEqual(self.client.get("/price/沒有這區").status_code, 404)
        self.assertEqual(self.client.get("/services/nope").status_code, 404)
        robots = self.client.get("/robots.txt").get_data(as_text=True)
        self.assertIn("Sitemap: https://example.test/sitemap.xml", robots)
        self.assertIn("Disallow: /api/", robots)
        sitemap = self.client.get("/sitemap.xml").get_data(as_text=True)
        self.assertIn("/price/", sitemap)
        self.assertTrue("桃園" in sitemap or "%E6%A1%83%E5%9C%92" in sitemap)
        self.assertIn("/articles/viewing-checklist", sitemap)
        self.assertNotIn("demo-seller-pitfalls", sitemap)
        listings = self.client.get("/listings").get_data(as_text=True)
        self.assertNotIn("示範資料", listings)
        stories = self.client.get("/testimonials").get_data(as_text=True)
        self.assertNotIn("不是真實客戶", stories)

    def test_push_data_still_rejects_missing_key(self):
        res = self.client.post("/api/push-data", json={"transactions": []})
        self.assertEqual(res.status_code, 401)

    def _login(self):
        page = self.client.get("/admin/login").get_data(as_text=True)
        token = re.search(r'name="_csrf" value="([^"]+)"', page).group(1)
        res = self.client.post("/admin/login", data={"password": "leju2024", "_csrf": token},
                               follow_redirects=False)
        self.assertEqual(res.status_code, 302)

    def _csrf(self, path):
        html = self.client.get(path).get_data(as_text=True)
        return re.search(r'name="_csrf" value="([^"]+)"', html).group(1)

    def test_contact_and_admin_flow(self):
        token = self._csrf("/contact")
        res = self.client.post("/contact", data={
            "_csrf": token,
            "name": "測試",
            "phone": "0912000111",
            "intent": "買房規劃",
            "message": "想問桃園區",
            "next": "/contact",
            "source_path": "/contact",
            "website": "",
        }, follow_redirects=True)
        self.assertIn("已收到", res.get_data(as_text=True))

        self._login()
        admin = self.client.get("/admin/listings")
        self.assertEqual(admin.status_code, 200)
        body = admin.get_data(as_text=True)
        self.assertIn("示範", body)
        self.assertIn("物件", body)

        demo = content.admin_listings()[0]
        token = self._csrf(f"/admin/listings/{demo['id']}")
        blocked = self.client.post(f"/admin/listings/{demo['id']}", data={
            "_csrf": token,
            "title": demo["title"],
            "status": "published",
            "is_demo": "on",
            "description": demo["description"],
        }, follow_redirects=True)
        self.assertIn("不能上架", blocked.get_data(as_text=True))
        self.assertEqual(self.client.get("/listings").status_code, 200)
        self.assertNotIn(demo["title"], self.client.get("/listings").get_data(as_text=True))

        story = content.admin_testimonials()[0]
        token = self._csrf(f"/admin/testimonials/{story['id']}")
        denied = self.client.post(f"/admin/testimonials/{story['id']}", data={
            "_csrf": token,
            "client_label": "林先生",
            "area": "桃園區",
            "quote": "這是沒有同意的文字",
            "published": "on",
        }, follow_redirects=True)
        self.assertIn("本人同意", denied.get_data(as_text=True))
        self.assertNotIn("沒有同意的文字", self.client.get("/testimonials").get_data(as_text=True))

        token = self._csrf("/admin/listings/new")
        png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
        )
        created = self.client.post("/admin/listings/new", data={
            "_csrf": token,
            "title": "測試用物件",
            "district": "桃園區",
            "price_label": "請改成真實價格",
            "description": "測試描述",
            "status": "published",
            "sort_order": "1",
            "photos": (BytesIO(png), "dot.png"),
        }, follow_redirects=True)
        self.assertEqual(created.status_code, 200)
        self.assertIn("已儲存", created.get_data(as_text=True))
        public = self.client.get("/listings").get_data(as_text=True)
        self.assertIn("測試用物件", public)
        self.assertNotIn("示範資料，請勿上架", public)

        csv_res = self.client.get("/admin/inquiries.csv")
        self.assertEqual(csv_res.status_code, 200)
        text = csv_res.get_data(as_text=True)
        self.assertIn("0912000111", text)
        self.assertIn("想問桃園區", text)

        anon = app_module.app.test_client()
        self.assertEqual(anon.get("/admin/inquiries.csv").status_code, 302)
        self.assertEqual(anon.get("/dashboard").status_code, 302)


if __name__ == "__main__":
    unittest.main()
