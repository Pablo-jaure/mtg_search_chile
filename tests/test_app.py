import gzip
import hashlib
import hmac
import json
import time
import uuid

import app as module
from bs4 import BeautifulSoup
from supabase_store import SupabaseError


class FakeSupabase:
    def __init__(self, role="user", status="active"):
        self.role = role
        self.status = status
        self.saved = []

    def public_settings(self):
        return {"url": "https://example.supabase.co", "publishable_key": "public"}

    def authenticate(self, token):
        if token != "valid":
            return None
        return {"id": "user-1", "email": "user@example.com", "access_token": token,
                "profile": {"display_name": "User", "role": self.role, "status": self.status}}

    def touch_last_seen(self, *_): pass
    def get_favorite_stores(self, *_): return []
    def get_stores(self, *_): return []
    def account_counts(self, *_): return {"wishlist": 0, "favorites": 0, "searches": 0, "carts": 0}
    def get_wishlist(self, *_): return self.saved
    def get_search_history(self, *_): return []
    def get_search_detail(self, *_):
        return {"run": {"id": "run-1", "created_at": "2026-07-15T00:00:00Z", "query_text": "1x Bolt", "status": "completed", "card_count": 1, "result_count": 0}, "cards": []}
    def get_cart_history(self, *_): return []
    def save_wishlist_item(self, token, user_id, name, quantity, notes):
        self.saved.append({"id": "item-1", "card_name": name, "desired_quantity": int(quantity), "notes": notes})
    def update_wishlist_item(self, token, user_id, item_id, *, acquired):
        self.updated_wishlist = {"id": item_id, "acquired": acquired}
    def configure_wishlist_price_alert(self, token, item_id, target, enabled):
        self.price_alert = {"id": item_id, "target": target, "enabled": enabled}
    def claim_tracker_nonce(self, nonce):
        if getattr(self, "nonce", None) == nonce: return False
        self.nonce = nonce
        return True
    def admin_users(self, _=None): return []
    def admin_audit(self, _=100): return []
    def admin_usage_metrics(self):
        return {"database": {}, "price_tracker": {}, "stores": [], "cards": [], "daily": []}


def csrf(client):
    client.get("/")
    with client.session_transaction() as session:
        return session["csrf_token"]


def logged_in(client):
    client.set_cookie("sb_access_token", "valid")


def test_public_quote_page_and_protected_area(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    assert client.get("/").status_code == 200
    assert client.get("/wishlist").status_code == 302


def test_static_assets_skip_remote_auth_and_are_cacheable(monkeypatch):
    store = FakeSupabase()
    store.auth_calls = 0
    original_authenticate = store.authenticate

    def authenticate(token):
        store.auth_calls += 1
        return original_authenticate(token)

    store.authenticate = authenticate
    monkeypatch.setattr(module, "supabase", store)
    client = module.app.test_client()
    logged_in(client)

    response = client.get("/static/css/app.css")

    assert response.status_code == 200
    assert store.auth_calls == 0
    assert response.cache_control.max_age == 3600


def test_text_responses_are_gzip_compressed_when_supported(monkeypatch):
    monkeypatch.setattr(module, "supabase", None)
    response = module.app.test_client().get("/", headers={"Accept-Encoding": "gzip"})

    assert response.headers["Content-Encoding"] == "gzip"
    assert "Accept-Encoding" in response.headers.get("Vary", "")
    assert b"MTG Search Chile" in gzip.decompress(response.data)


def test_guest_can_quote_without_persistence(monkeypatch):
    async def fake_quote(_cards):
        result = {"Tienda": "Card Souls", "Carta Buscada": "Lightning Bolt",
                  "Producto Encontrado": "Lightning Bolt NM", "Precio": 1500,
                  "Link": "https://store.example/bolt", "Shopify Variant ID": "123"}
        return [result], {"Lightning Bolt": {"buscado": "Lightning Bolt", "nombre_real": "Lightning Bolt"}}, []

    monkeypatch.setattr(module, "supabase", FakeSupabase())
    monkeypatch.setattr(module, "cotizar_web", fake_quote)
    client = module.app.test_client()
    token = csrf(client)
    response = client.post("/", data={"csrf_token": token, "lista": "1x Lightning Bolt"})
    assert response.status_code == 200
    assert b"Lightning Bolt NM" in response.data
    assert b"offer-list" in response.data
    assert len(BeautifulSoup(response.data, "html.parser").select("a.product-link")) == 1
    assert b"Mejor precio" in response.data


def test_persistence_failure_does_not_break_quote(monkeypatch):
    async def fake_quote(_cards):
        return [], {"Lightning Bolt": {"buscado": "Lightning Bolt"}}, []

    store = FakeSupabase()
    store.persist_search = lambda *_: (_ for _ in ()).throw(SupabaseError("offline"))
    monkeypatch.setattr(module, "supabase", store)
    monkeypatch.setattr(module, "cotizar_web", fake_quote)
    client = module.app.test_client()
    logged_in(client)
    token = csrf(client)
    response = client.post("/", data={"csrf_token": token, "lista": "1x Lightning Bolt"})
    assert response.status_code == 200
    assert "no pudo guardarse" in response.get_data(as_text=True)


def test_mutations_require_csrf(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    logged_in(client)
    assert client.post("/wishlist", data={"card_name": "Bolt"}).status_code == 400


def test_authenticated_wishlist(monkeypatch):
    store = FakeSupabase()
    monkeypatch.setattr(module, "supabase", store)
    client = module.app.test_client()
    logged_in(client)
    token = csrf(client)
    response = client.post("/wishlist", data={"csrf_token": token, "card_name": "Lightning Bolt", "desired_quantity": 2})
    assert response.status_code == 302
    assert store.saved[0]["card_name"] == "Lightning Bolt"


def test_authenticated_user_can_mark_wishlist_item(monkeypatch):
    store = FakeSupabase()
    monkeypatch.setattr(module, "supabase", store)
    client = module.app.test_client()
    logged_in(client)
    token = csrf(client)
    response = client.post("/wishlist/item-1/status", data={"csrf_token": token, "acquired": "true"})
    assert response.status_code == 302
    assert store.updated_wishlist == {"id": "item-1", "acquired": True}


def test_authenticated_user_can_configure_price_alert(monkeypatch):
    store = FakeSupabase()
    monkeypatch.setattr(module, "supabase", store)
    client = module.app.test_client()
    logged_in(client)
    token = csrf(client)
    response = client.post(
        "/wishlist/item-1/price-alert",
        data={"csrf_token": token, "target_price_clp": "1500", "enabled": "true"},
    )
    assert response.status_code == 302
    assert store.price_alert == {"id": "item-1", "target": 1500, "enabled": True}


def signed_tracker_request(secret, payload, *, timestamp=None, nonce=None):
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = str(timestamp or int(time.time()))
    nonce = nonce or str(uuid.uuid4())
    signature = hmac.new(
        secret.encode(), f"{timestamp}.{nonce}.".encode() + body, hashlib.sha256
    ).hexdigest()
    return body, {
        "Content-Type": "application/json",
        "X-Tracker-Timestamp": timestamp,
        "X-Tracker-Nonce": nonce,
        "X-Tracker-Signature": signature,
    }


def test_internal_tracker_returns_minimum_offer(monkeypatch):
    async def fake_quote(_cards):
        return [
            {"Precio": 2000, "Tienda": "B", "Producto Encontrado": "Bolt B", "Link": "https://b"},
            {"Precio": 1200, "Tienda": "A", "Producto Encontrado": "Bolt A", "Link": "https://a"},
        ], {}, []

    monkeypatch.setenv("PRICE_TRACKER_INTERNAL_SECRET", "test-secret")
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    monkeypatch.setattr(module, "cotizar_web", fake_quote)
    client = module.app.test_client()
    body, headers = signed_tracker_request("test-secret", {"card_name": "Lightning Bolt"})
    response = client.post("/internal/price-tracker/check", data=body, headers=headers)
    assert response.status_code == 200
    assert response.json == {
        "offers_count": 2, "price_clp": 1200, "product_name": "Bolt A",
        "product_url": "https://a", "store_name": "A",
    }
    assert response.content_type == "application/json"
    assert response.get_data().decode("utf-8")


def test_internal_tracker_rejects_bad_signature_and_replay(monkeypatch):
    monkeypatch.setenv("PRICE_TRACKER_INTERNAL_SECRET", "test-secret")
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    body, headers = signed_tracker_request("wrong-secret", {"card_name": "Bolt"})
    assert client.post("/internal/price-tracker/check", data=body, headers=headers).status_code == 401

    async def fake_quote(_cards): return [], {}, []
    monkeypatch.setattr(module, "cotizar_web", fake_quote)
    body, headers = signed_tracker_request("test-secret", {"card_name": "Bolt"})
    assert client.post("/internal/price-tracker/check", data=body, headers=headers).status_code == 200
    assert client.post("/internal/price-tracker/check", data=body, headers=headers).status_code == 409


def test_non_admin_gets_403(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase(role="user"))
    client = module.app.test_client()
    logged_in(client)
    assert client.get("/admin").status_code == 403


def test_admin_can_open_panel(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase(role="admin"))
    client = module.app.test_client()
    logged_in(client)
    assert client.get("/admin").status_code == 200


def test_all_authenticated_pages_render(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    logged_in(client)
    for path in (
        "/account", "/account/favorite-stores", "/wishlist",
        "/history/searches", "/history/searches/run-1", "/history/carts",
    ):
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"site-navbar" in response.data


def test_frontend_assets_and_accessibility_hooks(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    response = client.get("/")
    assert b'Saltar al contenido' in response.data
    assert b'data-submit-loading' in response.data
    assert b'Buscando en tiendas chilenas' in response.data
    assert client.get("/static/css/app.css").status_code == 200
    assert client.get("/static/js/app.js").status_code == 200


def test_rendered_post_forms_keep_csrf_tokens(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    logged_in(client)
    for path in ("/", "/account", "/wishlist", "/account/favorite-stores"):
        soup = BeautifulSoup(client.get(path).data, "html.parser")
        for form in soup.select('form[method="post"]'):
            token = form.select_one('input[name="csrf_token"]')
            assert token is not None and token.get("value"), (path, str(form))


def test_auth_session_rejects_foreign_origin(monkeypatch):
    monkeypatch.setattr(module, "supabase", FakeSupabase())
    client = module.app.test_client()
    response = client.post("/auth/session", json={"access_token": "valid"}, headers={"Origin": "https://evil.example"})
    assert response.status_code == 403


def test_next_parameter_cannot_redirect_off_site(monkeypatch):
    store = FakeSupabase()
    monkeypatch.setattr(module, "supabase", store)
    client = module.app.test_client()
    logged_in(client)
    token = csrf(client)
    response = client.post("/wishlist", data={"csrf_token": token, "card_name": "Bolt", "next": "https://evil.example"})
    assert response.headers["Location"] == "/wishlist"
