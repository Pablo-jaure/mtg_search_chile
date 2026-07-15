from types import SimpleNamespace

import app as module
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
    def get_wishlist(self, *_): return self.saved
    def save_wishlist_item(self, token, user_id, name, quantity, notes):
        self.saved.append({"id": "item-1", "card_name": name, "desired_quantity": int(quantity), "notes": notes})
    def update_wishlist_item(self, token, user_id, item_id, *, acquired):
        self.updated_wishlist = {"id": item_id, "acquired": acquired}
    def admin_users(self, _=None): return []
    def admin_audit(self, _=100): return []
    def admin_usage_metrics(self):
        return {"database": {}, "stores": [], "cards": [], "daily": []}


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
