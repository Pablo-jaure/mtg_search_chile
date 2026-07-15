import asyncio
import hmac
import os
import secrets
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from supabase_store import SupabaseConfig, SupabaseError, SupabaseStore, card_key


load_dotenv()

# Reutiliza la lógica del cotizador original sin ejecutar su interfaz Streamlit.
_source = Path(__file__).with_name("mtg_cotizador.py").read_text(encoding="utf-8")
_core = _source.split("# Interfaz Streamlit", 1)[0]
_core = _core.replace("import streamlit as st\n", "").replace("import pandas as pd\n", "")
exec(compile(_core, "mtg_cotizador.py", "exec"), globals())

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("FLASK_ENV") == "production" or bool(os.environ.get("RENDER")),
    MAX_CONTENT_LENGTH=1_000_000,
)

supabase_config = SupabaseConfig(
    url=os.environ.get("SUPABASE_URL", ""),
    publishable_key=os.environ.get("SUPABASE_PUBLISHABLE_KEY", ""),
    secret_key=os.environ.get("SUPABASE_SECRET_KEY", ""),
)
supabase = SupabaseStore(supabase_config) if supabase_config.configured else None


def configured_origins() -> set[str]:
    configured = os.environ.get("origins_autorizados", "")
    origins = {value.strip().rstrip("/") for value in configured.split(",") if value.strip()}
    origins.update({"http://127.0.0.1:5000", "http://localhost:5000"})
    return origins


def local_redirect_target(candidate: str | None, fallback: str) -> str:
    if candidate:
        parts = urlsplit(candidate)
        if not parts.scheme and not parts.netloc and candidate.startswith("/"):
            return candidate
    return fallback

STORE_SLUGS = {
    "BloodMoon Games": "bloodmoon-games",
    "Card Nexus": "card-nexus",
    "Cartas La Fortaleza": "cartas-la-fortaleza",
    "Cartas Magic Sur": "cartas-magic-sur",
    "Cat Lotus": "cat-lotus",
    "Dragon Durmiente": "dragon-durmiente",
    "Game of Magic": "game-of-magic",
    "Gamequest": "gamequest",
    "Ineko Card Shop": "ineko-card-shop",
    "La Comarca": "la-comarca",
    "La Cripta": "la-cripta",
    "MagicSur": "magicsur",
    "Rhystic Bazaar": "rhystic-bazaar",
    "Singles Winterland": "singles-winterland",
    "Valhalla Store": "valhalla-store",
    "Card Souls": "card-souls",
    "Magic4Ever": "magic4ever",
    "Oasis Games": "oasis-games",
    "Pay to Win": "pay-to-win",
    "Piedra Bruja": "piedra-bruja",
    "Zendicard": "zendicard",
    "Chronomagic": "chronomagic",
    "Marketplace Scry": "marketplace-scry",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def csrf_token() -> str:
    token = session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["csrf_token"] = token
    return token


def valid_csrf() -> bool:
    expected = session.get("csrf_token", "")
    provided = request.headers.get("X-CSRF-Token") or request.form.get("csrf_token", "")
    return bool(expected and provided and hmac.compare_digest(expected, provided))


@app.before_request
def load_request_user():
    g.user = None
    if supabase:
        token = request.cookies.get("sb_access_token", "")
        if token:
            g.user = supabase.authenticate(token)

    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        exempt = request.endpoint in {"auth_session"}
        if not exempt and not valid_csrf():
            abort(400, "Token CSRF inválido o ausente")


@app.context_processor
def inject_globals():
    return {
        "current_user": g.get("user"),
        "csrf_token": csrf_token,
        "supabase_public": supabase.public_settings() if supabase else None,
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            flash("Inicia sesión con Google para usar esta función.", "warning")
            return redirect(url_for("inicio"))
        if g.user["profile"]["status"] != "active":
            abort(403, "Cuenta suspendida")
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for("inicio"))
        profile = g.user["profile"]
        if profile["role"] != "admin" or profile["status"] != "active":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


async def cotizar_web(cartas):
    limits = httpx.Limits(max_keepalive_connections=40, max_connections=100)
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tiendas = [
            buscar_en_tienda(client, sem, nombre, config, carta)
            for carta in cartas
            for nombre, config in TIENDAS_CONFIG.items()
        ]
        scryfall = [obtener_info_scryfall(client, sem, carta) for carta in cartas]
        respuestas, fichas = await asyncio.gather(
            asyncio.gather(*tiendas), asyncio.gather(*scryfall)
        )

    resultados, logs = [], []
    for encontrados, log in respuestas:
        resultados.extend(encontrados)
        logs.append(log)
    return resultados, {item["buscado"]: item for item in fichas}, logs


def crear_resumen_tiendas(resultados):
    agrupados = {}
    for fila in resultados:
        dato = agrupados.setdefault(
            fila["Tienda"], {"cartas": set(), "precios": [], "resultados": 0}
        )
        dato["cartas"].add(fila["Carta Buscada"])
        dato["precios"].append(fila["Precio"])
        dato["resultados"] += 1

    resumen = []
    for tienda, dato in agrupados.items():
        fila_resumen = {
            "tienda": tienda,
            "store_slug": STORE_SLUGS.get(tienda, card_key(tienda)),
            "cartas": len(dato["cartas"]),
            "minimo": min(dato["precios"]),
            "promedio": round(sum(dato["precios"]) / len(dato["precios"])),
            "resultados": dato["resultados"],
        }

        candidatas = [
            fila
            for fila in resultados
            if fila["Tienda"] == tienda and fila.get("Shopify Variant ID")
        ]
        if candidatas:
            mejores = {}
            for fila in candidatas:
                carta = fila["Carta Buscada"]
                if carta not in mejores or fila["Precio"] < mejores[carta]["Precio"]:
                    mejores[carta] = fila
            seleccionadas = list(mejores.values())
            partes = urlsplit(seleccionadas[0]["Link"])
            variantes = ",".join(
                f'{fila["Shopify Variant ID"]}:1' for fila in seleccionadas
            )
            fila_resumen.update(
                plataforma_carrito="shopify",
                carrito_url=f"{partes.scheme}://{partes.netloc}/cart/{variantes}",
                carrito_cartas=len(seleccionadas),
                carrito_total=sum(fila["Precio"] for fila in seleccionadas),
                carrito_items=[
                    {
                        "card": fila["Carta Buscada"],
                        "product": fila["Producto Encontrado"],
                        "price_clp": fila["Precio"],
                    }
                    for fila in seleccionadas
                ],
            )

        candidatas_woo = [
            fila
            for fila in resultados
            if fila["Tienda"] == tienda and fila.get("WooCommerce Compra")
        ]
        if candidatas_woo:
            mejores = {}
            for fila in candidatas_woo:
                carta = fila["Carta Buscada"]
                if carta not in mejores or fila["Precio"] < mejores[carta]["Precio"]:
                    mejores[carta] = fila
            seleccionadas = list(mejores.values())
            partes = urlsplit(seleccionadas[0]["Link"])
            base_url = f"{partes.scheme}://{partes.netloc}"
            urls_agregar = []
            for fila in seleccionadas:
                compra = fila["WooCommerce Compra"]
                parametros = {"add-to-cart": compra["product_id"], "quantity": 1}
                if compra.get("variation_id"):
                    parametros["variation_id"] = compra["variation_id"]
                    parametros.update(compra.get("attributes") or {})
                urls_agregar.append(f"{base_url}/?{urlencode(parametros)}")
            fila_resumen.update(
                plataforma_carrito="woocommerce",
                carrito_urls=urls_agregar,
                carrito_url=urljoin(
                    base_url,
                    seleccionadas[0]["WooCommerce Compra"].get("cart_url") or "/cart/",
                ),
                carrito_cartas=len(seleccionadas),
                carrito_total=sum(fila["Precio"] for fila in seleccionadas),
                carrito_omitidas=len(dato["cartas"]) - len(seleccionadas),
                carrito_items=[
                    {
                        "card": fila["Carta Buscada"],
                        "product": fila["Producto Encontrado"],
                        "price_clp": fila["Precio"],
                    }
                    for fila in seleccionadas
                ],
            )

        resumen.append(fila_resumen)
    return sorted(resumen, key=lambda item: (-item["cartas"], item["tienda"]))


def favorite_context():
    if not g.user or not supabase:
        return [], {}, set()
    favorites = supabase.get_favorite_stores(g.user["access_token"], g.user["id"])
    stores = supabase.get_stores(g.user["access_token"])
    store_by_name = {row["name"]: row for row in stores}
    favorite_slugs = {item["stores"]["slug"] for item in favorites if item.get("stores")}
    return favorites, store_by_name, favorite_slugs


@app.route("/health")
def health():
    return jsonify(status="ok", supabase_configured=bool(supabase))


@app.route("/", methods=["GET", "POST"])
def inicio():
    lista = request.args.get(
        "cards", "1x Skullclamp\n1x Nest of Scarabs\n1x Lightning Bolt"
    )
    contexto = {"lista": lista, "tiendas": TIENDAS_CONFIG, "search_run_id": None}
    try:
        _, store_by_name, favorite_slugs = favorite_context()
    except SupabaseError:
        store_by_name, favorite_slugs = {}, set()
    contexto.update(store_by_name=store_by_name, favorite_store_slugs=favorite_slugs)

    if request.method == "POST":
        lista = request.form.get("lista", "")
        cartas = parsear_lista_bulk(lista)
        contexto.update(lista=lista, cartas=cartas)
        if not cartas:
            contexto["error"] = "No se reconoció ninguna carta en la lista."
        elif len(cartas) > 100:
            contexto["error"] = "El máximo es de 100 cartas distintas por búsqueda."
        else:
            started = time.perf_counter()
            try:
                resultados, scryfall, logs = asyncio.run(cotizar_web(cartas))
                for fila in resultados:
                    fila["Store Slug"] = STORE_SLUGS.get(
                        fila["Tienda"], card_key(fila["Tienda"])
                    )
                contexto.update(
                    resultados=resultados,
                    por_carta={
                        carta: sorted(
                            (
                                fila
                                for fila in resultados
                                if fila["Carta Buscada"] == carta
                            ),
                            key=lambda fila: fila["Precio"],
                        )
                        for carta in cartas
                    },
                    scryfall=scryfall,
                    resumen=crear_resumen_tiendas(resultados),
                    logs=logs,
                )
                if g.user and supabase:
                    try:
                        run_id = supabase.persist_search(
                            g.user["access_token"],
                            g.user["id"],
                            lista,
                            cartas,
                            scryfall,
                            resultados,
                            round((time.perf_counter() - started) * 1000),
                        )
                        contexto["search_run_id"] = run_id
                    except SupabaseError:
                        contexto["persistence_warning"] = (
                            "La cotización terminó, pero no pudo guardarse en tu historial."
                        )
            except Exception as exc:
                contexto["error"] = f"No se pudo completar la cotización: {exc}"

    return render_template("index.html", **contexto)


@app.route("/auth/callback")
def auth_callback():
    return render_template("auth_callback.html")


@app.route("/auth/session", methods=["POST"])
def auth_session():
    origin = request.headers.get("Origin", "").rstrip("/")
    request_origin = request.host_url.rstrip("/")
    if origin and origin not in configured_origins() and origin != request_origin:
        return jsonify(error="Origen no autorizado"), 403
    if not supabase:
        return jsonify(error="Supabase no está configurado"), 503
    payload = request.get_json(silent=True) or {}
    access_token = payload.get("access_token", "")
    user = supabase.authenticate(access_token)
    if not user:
        return jsonify(error="Sesión inválida"), 401
    if user["profile"]["status"] != "active":
        return jsonify(error="Cuenta suspendida"), 403
    try:
        supabase.touch_last_seen(access_token, user["id"])
    except SupabaseError:
        app.logger.warning("No se pudo actualizar last_seen_at", exc_info=True)
    response = jsonify(
        user={
            "id": user["id"],
            "email": user["email"],
            "display_name": user["profile"].get("display_name"),
            "role": user["profile"]["role"],
        }
    )
    response.set_cookie(
        "sb_access_token",
        access_token,
        max_age=3600,
        httponly=True,
        secure=app.config["SESSION_COOKIE_SECURE"],
        samesite="Lax",
    )
    return response


@app.route("/auth/logout", methods=["POST"])
def auth_logout():
    response = redirect(url_for("inicio"))
    response.delete_cookie("sb_access_token")
    session.clear()
    return response


@app.route("/account")
@login_required
def account():
    counts = supabase.account_counts(g.user["id"])
    favorites = supabase.get_favorite_stores(g.user["access_token"], g.user["id"])
    return render_template("account.html", counts=counts, favorites=favorites)


@app.route("/account/favorite-stores")
@login_required
def favorite_stores():
    favorites = supabase.get_favorite_stores(g.user["access_token"], g.user["id"])
    return render_template("favorite_stores.html", favorites=favorites)


@app.route("/account/profile", methods=["POST"])
@login_required
def update_account():
    display_name = request.form.get("display_name", "").strip()[:200]
    supabase.update_profile(
        g.user["access_token"], g.user["id"], {"display_name": display_name}
    )
    flash("Perfil actualizado.", "success")
    return redirect(url_for("account"))


@app.route("/account/delete-request", methods=["POST"])
@login_required
def request_account_deletion():
    supabase.update_profile(
        g.user["access_token"],
        g.user["id"],
        {"deletion_requested_at": utc_now_iso()},
    )
    flash("Solicitud de eliminación registrada.", "warning")
    return redirect(url_for("account"))


@app.route("/wishlist", methods=["GET", "POST"])
@login_required
def wishlist():
    if request.method == "POST":
        name = request.form.get("card_name", "").strip()
        if not name:
            flash("Indica el nombre de una carta.", "danger")
        else:
            supabase.save_wishlist_item(
                g.user["access_token"],
                g.user["id"],
                name,
                request.form.get("desired_quantity", 1),
                request.form.get("notes"),
            )
            flash("Carta guardada en tu wishlist.", "success")
        return redirect(local_redirect_target(request.form.get("next"), url_for("wishlist")))
    items = supabase.get_wishlist(g.user["access_token"], g.user["id"])
    return render_template("wishlist.html", items=items)


@app.route("/wishlist/<item_id>/delete", methods=["POST"])
@login_required
def delete_wishlist(item_id):
    supabase.delete_wishlist_item(g.user["access_token"], g.user["id"], item_id)
    flash("Carta eliminada de tu wishlist.", "success")
    return redirect(url_for("wishlist"))


@app.route("/wishlist/<item_id>/status", methods=["POST"])
@login_required
def update_wishlist_status(item_id):
    supabase.update_wishlist_item(
        g.user["access_token"],
        g.user["id"],
        item_id,
        acquired=request.form.get("acquired") == "true",
    )
    flash("Estado de wishlist actualizado.", "success")
    return redirect(url_for("wishlist"))


@app.route("/favorites/<int:store_id>", methods=["POST"])
@login_required
def add_favorite(store_id):
    supabase.add_favorite_store(g.user["access_token"], g.user["id"], store_id)
    flash("Tienda agregada a favoritas.", "success")
    return redirect(local_redirect_target(request.form.get("next"), url_for("inicio")))


@app.route("/favorites/<int:store_id>/delete", methods=["POST"])
@login_required
def delete_favorite(store_id):
    supabase.remove_favorite_store(g.user["access_token"], g.user["id"], store_id)
    flash("Tienda eliminada de favoritas.", "success")
    return redirect(local_redirect_target(request.form.get("next"), url_for("account")))


@app.route("/history/searches")
@login_required
def search_history():
    searches = supabase.get_search_history(g.user["access_token"], g.user["id"])
    return render_template("search_history.html", searches=searches)


@app.route("/history/searches/<run_id>")
@login_required
def search_history_detail(run_id):
    detail = supabase.get_search_detail(g.user["access_token"], g.user["id"], run_id)
    if not detail:
        abort(404)
    return render_template("search_detail.html", detail=detail)


@app.route("/history/searches/delete", methods=["POST"])
@login_required
def delete_all_search_history():
    supabase.delete_search(g.user["access_token"], g.user["id"])
    flash("Historial de búsquedas eliminado.", "success")
    return redirect(url_for("search_history"))


@app.route("/history/searches/<run_id>/delete", methods=["POST"])
@login_required
def delete_search_history(run_id):
    supabase.delete_search(g.user["access_token"], g.user["id"], run_id)
    flash("Búsqueda eliminada.", "success")
    return redirect(url_for("search_history"))


@app.route("/history/carts")
@login_required
def cart_history():
    events = supabase.get_cart_history(g.user["access_token"], g.user["id"])
    return render_template("cart_history.html", events=events)


@app.route("/api/cart-events", methods=["POST"])
@login_required
def api_cart_event():
    payload = request.get_json(silent=True) or {}
    if not payload.get("destination_url"):
        return jsonify(error="destination_url es obligatorio"), 400
    supabase.record_cart_event(
        g.user["access_token"], g.user["id"], payload
    )
    return "", 204


@app.route("/admin")
@admin_required
def admin_dashboard():
    users = supabase.admin_users(request.args.get("q"))
    audit = supabase.admin_audit(100)
    usage = supabase.admin_usage_metrics()
    metrics = {
        "users": len(users),
        "active": sum(user["status"] == "active" for user in users),
        "admins": sum(user["role"] == "admin" for user in users),
        "searches": sum(int(user["search_count"]) for user in users),
        "carts": sum(int(user["cart_event_count"]) for user in users),
    }
    return render_template(
        "admin.html", users=users, audit=audit, metrics=metrics, usage=usage
    )


@app.route("/admin/users/<user_id>", methods=["POST"])
@admin_required
def admin_update_user(user_id):
    try:
        supabase.admin_update_user(
            g.user["id"],
            user_id,
            role=request.form.get("role"),
            status=request.form.get("status"),
        )
        flash("Usuario actualizado.", "success")
    except SupabaseError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin_dashboard"))


@app.route("/admin/users/<user_id>/delete", methods=["POST"])
@admin_required
def admin_delete_user(user_id):
    try:
        supabase.admin_delete_user(g.user["id"], user_id)
        flash("Usuario eliminado.", "success")
    except SupabaseError as exc:
        flash(str(exc), "danger")
    return redirect(url_for("admin_dashboard"))


@app.errorhandler(SupabaseError)
def handle_supabase_error(exc):
    app.logger.exception("Supabase error: %s", exc)
    if request.path.startswith("/api/"):
        return jsonify(error="No se pudo completar la operación"), 502
    flash("No se pudo completar la operación con Supabase.", "danger")
    return redirect(request.referrer or url_for("inicio"))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
