import streamlit as st
import asyncio
import httpx
import pandas as pd
import re
import json
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────────────────────────────────────
# TIENDAS CHILENAS — 23 sitios activos (Reino Eldrazi offline / DNS fail)
# ─────────────────────────────────────────────────────────────────────────────
# Tipos de scraper:
#   shopify_api    → /search/suggest.json  (JSON nativo, lo más confiable)
#                    con fallback automático a HTML cuando Cloudflare bloquea
#   woocommerce    → HTML de WooCommerce (?s=&post_type=product)
#   jumpseller     → Plataforma Jumpseller (/search?q=)
#   scry_marketplace → marketplace.scry.cl (plataforma propia)
# ─────────────────────────────────────────────────────────────────────────────
TIENDAS_CONFIG = {
    # ── WooCommerce ──────────────────────────────────────────────────────────
    "BloodMoon Games":     {"url_buscar": "https://bloodmoongames.cl/?s={carta}&post_type=product",        "tipo": "woocommerce"},
    "Card Nexus":          {"url_buscar": "https://cardnexus.cl/?s={carta}&post_type=product",             "tipo": "woocommerce"},
    "Cartas La Fortaleza": {"url_buscar": "https://www.cartaslafortaleza.cl/?s={carta}&post_type=product", "tipo": "woocommerce"},
    "Cartas Magic Sur":    {"url_buscar": "https://www.cartasmagicsur.cl/?s={carta}&post_type=product",    "tipo": "woocommerce"},
    "Cat Lotus":           {"url_buscar": "https://catlotus.cl/?s={carta}&post_type=product",              "tipo": "woocommerce"},
    "Dragon Durmiente":    {"url_buscar": "https://dragondurmiente.cl/?s={carta}&post_type=product",       "tipo": "woocommerce"},
    "Game of Magic":       {"url_buscar": "https://www.gameofmagictienda.cl/?s={carta}&post_type=product", "tipo": "woocommerce"},
    "Gamequest":           {"url_buscar": "https://gamequest.cl/?s={carta}&post_type=product",             "tipo": "woocommerce"},
    "Ineko Card Shop":     {"url_buscar": "https://inekosingles.com/?s={carta}&post_type=product",         "tipo": "woocommerce"},
    "La Comarca":          {"url_buscar": "https://www.tiendalacomarca.cl/?s={carta}&post_type=product",   "tipo": "woocommerce"},
    "La Cripta":           {"url_buscar": "https://lacripta.cl/?s={carta}&post_type=product",              "tipo": "woocommerce"},
    "MagicSur":            {"url_buscar": "https://www.magicsur.cl/?s={carta}&post_type=product",          "tipo": "woocommerce"},
    "Rhystic Bazaar":      {"url_buscar": "https://rhysticbazaar.cl/?s={carta}&post_type=product",         "tipo": "woocommerce"},
    "Singles Winterland":  {"url_buscar": "https://singleswinterland.cl/?s={carta}&post_type=product",     "tipo": "woocommerce"},
    "Valhalla Store":      {"url_buscar": "https://valhallastore.cl/?s={carta}&post_type=product",         "tipo": "woocommerce"},

    # ── Shopify (JSON + fallback HTML automático si Cloudflare bloquea) ──────
    "Card Souls":  {"url_buscar": "https://www.cardsouls.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12", "tipo": "shopify_api"},
    "Magic4Ever":  {"url_buscar": "https://magic4ever.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12",    "tipo": "shopify_api"},
    "Oasis Games": {"url_buscar": "https://oasisgames.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12",    "tipo": "shopify_api"},
    "Pay to Win":  {"url_buscar": "https://www.paytowin.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12",  "tipo": "shopify_api"},
    "Piedra Bruja":{"url_buscar": "https://piedrabruja.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12",   "tipo": "shopify_api"},
    "Zendicard":   {"url_buscar": "https://zendicard.cl/search/suggest.json?q={carta}&resources[type]=product&resources[limit]=12",     "tipo": "shopify_api"},

    # ── Jumpseller ───────────────────────────────────────────────────────────
    "Chronomagic": {"url_buscar": "https://www.chronomagic.cl/search?q={carta}", "tipo": "jumpseller"},

    # ── Marketplace propio ───────────────────────────────────────────────────
    "Marketplace Scry": {"url_buscar": "https://marketplace.scry.cl/buscar?q={carta}", "tipo": "scry_marketplace"},
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es-419,es;q=0.9,en;q=0.8",
}

SEARCH_CONCURRENCY = 8
DETAIL_CONCURRENCY = 8
DETAIL_CONCURRENCY_PER_STORE = 2
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
REQUEST_RETRY_DELAYS = (0.5, 1.5)

# Tiendas que necesitan inspección manual (se muestran en tab de ayuda)
TIENDAS_PENDIENTES_INSPECCION = {
    "BloodMoon Games":  "https://bloodmoongames.cl/?s=Lightning+Bolt&post_type=product",
    "Cat Lotus":        "https://catlotus.cl/?s=Lightning+Bolt&post_type=product",
    "Chronomagic":      "https://www.chronomagic.cl/search?q=Lightning+Bolt",
    "Game of Magic":    "https://www.gameofmagictienda.cl/?s=Lightning+Bolt&post_type=product",
    "Magic4Ever":       "https://magic4ever.cl/search?type=product&q=Lightning+Bolt",
    "MagicSur":         "https://www.magicsur.cl/?s=Lightning+Bolt&post_type=product",
    "Marketplace Scry": "https://marketplace.scry.cl/buscar?q=Lightning+Bolt",
    "Valhalla Store":   "https://valhallastore.cl/?s=Lightning+Bolt&post_type=product",
    "Zendicard":        "https://zendicard.cl/search?type=product&q=Lightning+Bolt",
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _get_with_retries(client, url, *, headers, timeout, sem=None, local_sem=None):
    """GET con límites de concurrencia y reintentos para fallos transitorios."""
    async def solicitar():
        if sem is not None and local_sem is not None:
            async with sem:
                async with local_sem:
                    return await client.get(url, headers=headers, timeout=timeout)
        if sem is not None:
            async with sem:
                return await client.get(url, headers=headers, timeout=timeout)
        if local_sem is not None:
            async with local_sem:
                return await client.get(url, headers=headers, timeout=timeout)
        return await client.get(url, headers=headers, timeout=timeout)

    for intento in range(len(REQUEST_RETRY_DELAYS) + 1):
        try:
            respuesta = await solicitar()
            if getattr(respuesta, "status_code", 200) not in RETRYABLE_STATUS_CODES:
                return respuesta
        except httpx.RequestError:
            if intento == len(REQUEST_RETRY_DELAYS):
                raise
        if intento < len(REQUEST_RETRY_DELAYS):
            await asyncio.sleep(REQUEST_RETRY_DELAYS[intento])
    return respuesta


def parsear_lista_bulk(texto: str) -> list[str]:
    patron = re.compile(r"^(?:(?P<n>\d+)[xX]?\s+)?(?P<nombre>[^([\n*#]+)")
    cartas = []
    for linea in texto.strip().split("\n"):
        linea = linea.strip()
        if not linea or linea.lower().startswith(("sideboard","sb:","//","deck","maybeboard")):
            continue
        m = patron.match(linea)
        if m:
            nombre = re.sub(r"\s+\([A-Z0-9]+\).*$", "", m.group("nombre")).strip()
            if nombre:
                cartas.append(nombre)
    return list(dict.fromkeys(cartas))


def es_match(buscado: str, encontrado: str) -> bool:
    def n(t): return re.sub(r"[^a-z0-9\s]", "", t.lower())
    b, e = n(buscado), n(encontrado)
    if b in e or e in b: return True
    palabras = [p for p in b.split() if len(p) > 2]
    return bool(palabras) and all(p in e for p in palabras)


def parse_precio(texto: str) -> int | None:
    texto = str(texto).strip()
    # Un número JSON como 8400.00 usa punto decimal; un precio chileno como
    # $8.400 usa el punto como separador de miles.
    if re.fullmatch(r"\d+[.,]\d{2}", texto):
        return round(float(texto.replace(",", ".")))
    coincidencias = re.findall(r"\d[\d.]*", texto)
    if not coincidencias:
        return None
    d = coincidencias[-1].replace(".", "")
    return int(d) if len(d) >= 3 else None


def dominio(url: str) -> str:
    return url.split("/")[2]


def make_link(href: str, base_url: str) -> str:
    if href and href.startswith("/"):
        return f"https://{dominio(base_url)}{href}"
    return href or base_url


# ─────────────────────────────────────────────────────────────────────────────
# Parsers por plataforma
# ─────────────────────────────────────────────────────────────────────────────

def parse_shopify_json(r, carta, nombre_tienda, url) -> tuple[list, str]:
    ct = r.headers.get("content-type", "")
    if "application/json" not in ct.lower():
        return [], "🔒 Cloudflare: bloqueó JSON → usar fallback HTML"
    data = r.json()
    prods = data.get("resources", {}).get("results", {}).get("products", [])
    resultados = []
    for p in prods:
        titulo = p.get("title", "")
        if not p.get("available", True) and p.get("available") is not None: continue
        if not es_match(carta, titulo): continue
        precio = parse_precio(str(p.get("price", "")))
        if not precio: continue
        resultados.append({
            "Carta Buscada": carta, "Tienda": nombre_tienda,
            "Producto Encontrado": titulo, "Precio": precio,
            "Link": f"https://{dominio(url)}{p.get('url', '')}",
        })
    diag = f"✅ {len(resultados)} resultado(s)" if resultados else "Sin stock"
    return resultados, diag


async def actualizar_precios_shopify(client, resultados: list, sem=None, local_sem=None) -> list:
    """Reemplaza el precio base de búsqueda por el menor precio con stock real.

    Shopify Search entrega el mínimo histórico de todas las variantes, incluyendo
    variantes agotadas. El endpoint público ``producto.js`` contiene el stock y
    el precio vigente (en centavos) de cada variante.
    """
    local_sem = local_sem or asyncio.Semaphore(DETAIL_CONCURRENCY_PER_STORE)

    async def actualizar(resultado):
        try:
            producto_url = resultado["Link"].split("?", 1)[0].rstrip("/") + ".js"
            respuesta = await _get_with_retries(
                client, producto_url, headers=HEADERS, timeout=10.0,
                sem=sem, local_sem=local_sem,
            )
            respuesta.raise_for_status()
            variantes = respuesta.json().get("variants", [])
            disponibles = [v for v in variantes if v.get("available") and v.get("price") is not None]
            if not disponibles:
                return None

            variante = min(disponibles, key=lambda v: int(v["price"]))
            resultado["Precio"] = round(int(variante["price"]) / 100)
            resultado["Stock Verificado"] = True
            resultado["Shopify Variant ID"] = str(variante["id"])
            nombre_variante = variante.get("title", "").strip()
            if nombre_variante and nombre_variante.lower() != "default title":
                resultado["Producto Encontrado"] += f" — {nombre_variante}"
            return resultado
        except Exception:
            # Si una tienda bloquea el endpoint de variantes, se conserva el
            # resultado de búsqueda para no perder completamente el producto.
            return resultado

    actualizados = await asyncio.gather(*(actualizar(resultado) for resultado in resultados))
    return [resultado for resultado in actualizados if resultado is not None]


def _objetos_json(valor):
    """Recorre diccionarios/listas de JSON-LD sin asumir una estructura fija."""
    if isinstance(valor, dict):
        yield valor
        for hijo in valor.values():
            yield from _objetos_json(hijo)
    elif isinstance(valor, list):
        for hijo in valor:
            yield from _objetos_json(hijo)


def _stock_y_precio_ficha(html: str) -> tuple[bool | None, int | None, dict | None]:
    """Obtiene disponibilidad y menor precio con stock desde una ficha HTML."""
    soup = BeautifulSoup(html, "html.parser")
    ofertas_stock = []
    vio_stock_explicito = False
    cart_el = soup.select_one(
        "a.cart-contents[href], a[href*='/carrito/'], a[href*='/cart/']"
    )
    cart_url = cart_el.get("href") if cart_el is not None else None

    # Variantes WooCommerce: el atributo contiene stock y precio por variante.
    for formulario in soup.select("form.variations_form[data-product_variations]"):
        try:
            variantes = json.loads(formulario.get("data-product_variations", "[]"))
            product_id = formulario.get("data-product_id")
            for variante in variantes:
                vio_stock_explicito = True
                disponible = variante.get("is_in_stock") and variante.get("is_purchasable", True)
                if disponible:
                    precio = parse_precio(variante.get("display_price", ""))
                    if precio:
                        ofertas_stock.append((precio, {
                            "product_id": str(product_id or variante.get("product_id", "")),
                            "variation_id": str(variante.get("variation_id", "")),
                            "attributes": variante.get("attributes") or {},
                            "cart_url": cart_url,
                        }))
        except (json.JSONDecodeError, TypeError):
            pass

    # Schema.org / JSON-LD funciona en WooCommerce, Jumpseller y varios temas.
    for script in soup.select("script[type='application/ld+json']"):
        try:
            data = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for objeto in _objetos_json(data):
            tipo = objeto.get("@type", "")
            if tipo not in ("Offer", "AggregateOffer"):
                continue
            disponibilidad = str(objeto.get("availability", "")).lower()
            if disponibilidad:
                vio_stock_explicito = True
            disponible = "instock" in disponibilidad or "limitedavailability" in disponibilidad
            if disponible:
                precio = parse_precio(objeto.get("price") or objeto.get("lowPrice") or "")
                if precio:
                    ofertas_stock.append((precio, None))

    if ofertas_stock:
        comprables = [oferta for oferta in ofertas_stock if oferta[1] and oferta[1].get("product_id")]
        precio, compra = min(comprables or ofertas_stock, key=lambda oferta: oferta[0])
        if compra and compra.get("variation_id"):
            return True, precio, compra
        # Un producto simple expone su ID en el formulario o botón de compra.
        id_el = soup.select_one(
            "form.cart [name='add-to-cart'][value], "
            "button[name='add-to-cart'][value], [data-product_id]"
        )
        product_id = None
        if id_el is not None:
            product_id = id_el.get("value") or id_el.get("data-product_id")
        compra_simple = {"product_id": str(product_id), "cart_url": cart_url} if product_id else None
        return True, precio, compra_simple
    if vio_stock_explicito:
        return False, None, None

    # Metadatos y controles de compra como respaldo cuando no hay JSON público.
    disponibilidad = soup.select_one(
        "meta[property='product:availability'], [itemprop='availability'], .stock"
    )
    if disponibilidad is not None:
        estado = " ".join(filter(None, [
            disponibilidad.get("content"), disponibilidad.get("href"),
            disponibilidad.get_text(" ", strip=True),
        ])).lower()
        if any(x in estado for x in ("outofstock", "out-of-stock", "agotado", "sin existencias", "sin stock")):
            return False, None, None
        if any(x in estado for x in ("instock", "in-stock", "in stock", "hay existencias", "disponible")):
            precio_meta = soup.select_one("meta[property='product:price:amount'], [itemprop='price']")
            precio = parse_precio(precio_meta.get("content", "")) if precio_meta is not None else None
            id_el = soup.select_one(
                "form.cart [name='add-to-cart'][value], "
                "button[name='add-to-cart'][value], [data-product_id]"
            )
            product_id = (id_el.get("value") or id_el.get("data-product_id")) if id_el is not None else None
            compra = {"product_id": str(product_id), "cart_url": cart_url} if product_id else None
            return True, precio, compra

    boton = soup.select_one(
        "button[name='add-to-cart']:not([disabled]), .single_add_to_cart_button:not(.disabled), "
        "input[name='add_to_cart']:not([disabled])"
    )
    if boton is not None:
        product_id = boton.get("value") or boton.get("data-product_id")
        compra = {"product_id": str(product_id), "cart_url": cart_url} if product_id else None
        return True, None, compra
    return None, None, None


async def verificar_fichas_html(client, resultados: list, sem=None, local_sem=None) -> tuple[list, int, int]:
    """Valida stock en fichas WooCommerce/Jumpseller y actualiza su precio."""
    local_sem = local_sem or asyncio.Semaphore(DETAIL_CONCURRENCY_PER_STORE)

    async def verificar(resultado):
        try:
            respuesta = await _get_with_retries(
                client, resultado["Link"], headers=HEADERS, timeout=12.0,
                sem=sem, local_sem=local_sem,
            )
            if respuesta.status_code != 200:
                return resultado, 0, 1
            stock, precio, compra = _stock_y_precio_ficha(respuesta.text)
            if stock is False:
                return None, 1, 0
            inconcluso = int(stock is None)
            if stock is not None:
                resultado["Stock Verificado"] = True
            if precio:
                resultado["Precio"] = precio
            if compra and compra.get("product_id"):
                resultado["WooCommerce Compra"] = compra
            return resultado, 0, inconcluso
        except Exception:
            return resultado, 0, 1

    respuestas = await asyncio.gather(*(verificar(resultado) for resultado in resultados))
    verificados = [resultado for resultado, _, _ in respuestas if resultado is not None]
    descartados = sum(descartado for _, descartado, _ in respuestas)
    inconclusos = sum(inconcluso for _, _, inconcluso in respuestas)
    return verificados, descartados, inconclusos


def parse_shopify_html_fallback(html: str, carta, nombre_tienda, base_url) -> tuple[list, str]:
    """Fallback HTML para cuando Cloudflare bloquea el JSON API de Shopify."""
    soup = BeautifulSoup(html, "html.parser")
    resultados = []

    # Selectores comunes en temas Shopify para páginas de búsqueda
    prods = soup.select(
        ".product-item, .grid__item, .search-result, "
        ".product-block, .card-wrapper, .product-card, "
        "li.grid__item, .search__results .grid__item"
    )

    for p in prods:
        titulo_el = p.select_one(
            ".product-item__title, .card__heading a, .full-unstyled-link, "
            "h2 a, h3 a, .product-title, .product-card__name, "
            ".product__title, a.product-item__title"
        )
        precio_el = p.select_one(
            ".price .money, .price__regular .money, "
            ".product-price .money, .price-item--regular, "
            ".product-card__price, .price, .money"
        )
        if not titulo_el: continue
        titulo = titulo_el.text.strip()
        if not es_match(carta, titulo): continue
        precio = parse_precio(precio_el.text) if precio_el else None
        if not precio: continue
        link = make_link(titulo_el.get("href") or (p.select_one("a") or {}).get("href"), base_url)
        resultados.append({
            "Carta Buscada": carta, "Tienda": nombre_tienda,
            "Producto Encontrado": titulo, "Precio": precio, "Link": link,
        })

    diag = f"✅ {len(resultados)} resultado(s) [HTML]" if resultados else "Sin stock [HTML fallback]"
    return resultados, diag


def parse_woocommerce(r, carta, nombre_tienda, url) -> tuple[list, str]:
    soup = BeautifulSoup(r.text, "html.parser")

    # Selector amplio — cubre la mayoría de temas WooCommerce
    prods = soup.select(
        # Estándar WooCommerce
        "ul.products li.product, li.product, "
        # Temas custom frecuentes
        ".type-product, article.product, "
        ".product-grid-item, .product-card, "
        ".product-block, .product-element, "
        ".grid-item, .product-item, "
        # Elementor / WP Bakery
        ".woocommerce-loop-product, "
        ".wd-entities-by-id .product, "
        # Temas de mercado (Flatsome, Avada, etc.)
        ".product-small, .product-col, "
        ".box-image, .product-outer, "
        # WoodMart, XStore
        ".product-grid-wrapper .product, "
        ".wd-product, "
        # Astra / Generatepress
        ".ast-woo-product-loop-item"
    )

    if not prods:
        html_l = r.text.lower()
        sin_stock = ["no se encontraron", "no products were found", "sin resultados",
                     "no hay productos", "0 productos", "no results", "nothing found",
                     "no se han encontrado"]
        if any(m in html_l for m in sin_stock):
            return [], "Sin stock"
        return [], "⚠️ HTML no convencional — necesita inspección manual"

    resultados = []
    for prod in prods:
        cls = " ".join(prod.get("class", [])).lower()
        if "outofstock" in cls or "out-of-stock" in cls: continue
        txt = prod.text.lower()
        if any(x in txt for x in ["agotado", "sin stock", "leer más", "read more"]): continue

        titulo_el = prod.select_one(
            ".woocommerce-loop-product__title, .product-title, "
            "h2, h3, .title, .product-name, "
            "a.product-title, .wd-entities-title a, "
            ".product-small__title, .woocommerce-loop-product__link, "
            ".product-info__title, .card__title"
        )
        price_el = prod.select_one(
            ".price, .amount, .woocommerce-Price-amount, "
            ".price-box, .product-price, .price__amount, "
            ".woocommerce-Price-currencySymbol ~ span"
        )
        if not titulo_el or not price_el: continue

        titulo = titulo_el.text.strip()
        if not es_match(carta, titulo): continue

        bloques = price_el.select("bdi, .woocommerce-Price-amount")
        precio = parse_precio(bloques[-1].text if bloques else price_el.text)
        if not precio: continue

        # Extraer link (evitar cart/wishlist/quick-view)
        link = None
        SKIP = {"add-to-cart","cart","wishlist","quick-view","comparar","wishlist-icon"}
        if titulo_el.name == "a": link = titulo_el.get("href")
        if not link:
            for a in prod.select("a[href]"):
                h = a.get("href","")
                if h != "#" and not any(s in h.lower() for s in SKIP):
                    link = h; break
        link = make_link(link, url)

        resultados.append({
            "Carta Buscada": carta, "Tienda": nombre_tienda,
            "Producto Encontrado": titulo, "Precio": precio, "Link": link,
        })

    diag = f"✅ {len(resultados)} resultado(s)" if resultados else "Sin stock"
    return resultados, diag


def parse_jumpseller(r, carta, nombre_tienda, url) -> tuple[list, str]:
    soup = BeautifulSoup(r.text, "html.parser")

    # Jumpseller themes — varios selectores posibles
    prods = soup.select(
        # Temas estándar Jumpseller
        ".product-list .product, .product-list-item, "
        ".products-grid .product, .product-item, "
        # Tema "Berlin" y similares
        ".col-products .product, "
        # Fallback genérico
        ".product, [class*='product-col'], [class*='col-product']"
    )

    if not prods:
        return [], "⚠️ Jumpseller: HTML no convencional — necesita inspección manual"

    resultados = []
    for prod in prods:
        titulo_el = prod.select_one(
            "a.product-name, .product-name a, .product-title a, "
            "h2 a, h3 a, h4 a, .caption a, a.title, "
            ".product-info a, [class*='name'] a"
        )
        if not titulo_el:
            titulo_el = prod.select_one("a[href]")
        if not titulo_el: continue

        titulo = titulo_el.text.strip()
        if not titulo or not es_match(carta, titulo): continue

        precio_el = prod.select_one(
            ".product-price, .price, .price-new, "
            "[class*='price'], .amount, .product-current-price"
        )
        precio = parse_precio(precio_el.text) if precio_el else None
        if not precio: continue

        link = make_link(titulo_el.get("href"), url)
        resultados.append({
            "Carta Buscada": carta, "Tienda": nombre_tienda,
            "Producto Encontrado": titulo, "Precio": precio, "Link": link,
        })

    diag = f"✅ {len(resultados)} resultado(s)" if resultados else "Sin stock"
    return resultados, diag


def parse_scry_marketplace(r, carta, nombre_tienda, url) -> tuple[list, str]:
    soup = BeautifulSoup(r.text, "html.parser")

    # Scry.cl — React/Next.js con SSR; el HTML varía pero los precios suelen estar
    # en elementos con clases que contienen "price", "precio" o números con "$"
    prods = soup.select(
        "[class*='CardItem'], [class*='card-item'], [class*='result'], "
        "[class*='listing'], [class*='product'], [class*='offer'], "
        "article, .card, [class*='row']"
    )

    resultados = []
    dom = "marketplace.scry.cl"
    for prod in prods:
        clases = " ".join(prod.get("class", [])).lower()
        texto_stock = prod.get_text(" ", strip=True).lower()
        if any(x in clases or x in texto_stock for x in (
            "outofstock", "out-of-stock", "agotado", "sin stock", "vendido"
        )):
            continue
        txt_completo = prod.get_text(" ", strip=True)
        if not es_match(carta, txt_completo): continue

        precio_el = prod.select_one(
            "[class*='price'], [class*='precio'], [class*='cost'], "
            "[class*='valor'], [class*='Price']"
        )
        if not precio_el:
            m = re.search(r"\$\s?([\d\.]+)", txt_completo)
            precio_txt = m.group(0) if m else ""
        else:
            precio_txt = precio_el.text
        precio = parse_precio(precio_txt)
        if not precio: continue

        link_el = prod.select_one("a[href]")
        link = make_link(link_el["href"] if link_el else "", f"https://{dom}")

        tienda_el = prod.select_one("[class*='store'], [class*='seller'], [class*='tienda'], [class*='vendor'], [class*='Shop']")
        extra = f" [{tienda_el.text.strip()}]" if tienda_el else ""
        titulo_el = prod.select_one("[class*='name'], [class*='title'], [class*='Name'], h2, h3, strong")
        titulo = titulo_el.text.strip() if titulo_el else carta

        resultados.append({
            "Carta Buscada": carta, "Tienda": f"Scry{extra}",
            "Producto Encontrado": titulo, "Precio": precio, "Link": link,
        })

    diag = f"✅ {len(resultados)} resultado(s)" if resultados else "Sin stock (posible JS dinámico)"
    return resultados, diag


# ─────────────────────────────────────────────────────────────────────────────
# Scraper asíncrono central
# ─────────────────────────────────────────────────────────────────────────────
async def buscar_en_tienda(
    client, sem, nombre_tienda, config, carta, callback=None,
    detalle_sem=None, tienda_detalle_sem=None,
):
    url = config["url_buscar"].format(carta=carta.replace(" ", "+"))
    log = {"Tienda": nombre_tienda, "Consulta": carta, "Estado HTTP": "En cola", "Diagnóstico": "En cola"}

    async with sem:
        try:
            if callback: callback(f"🔍 {carta} → {nombre_tienda}…")
            r = await _get_with_retries(client, url, headers=HEADERS, timeout=15.0)
            log["Estado HTTP"] = f"HTTP {r.status_code}"

            if r.status_code != 200:
                log["Diagnóstico"] = f"⚠️ HTTP {r.status_code}"
                return [], log

            tipo = config["tipo"]

            if tipo == "shopify_api":
                resultados, diag = parse_shopify_json(r, carta, nombre_tienda, url)
                if resultados:
                    resultados = list({resultado["Link"]: resultado for resultado in resultados}.values())
                    resultados = await actualizar_precios_shopify(
                        client, resultados, detalle_sem, tienda_detalle_sem
                    )
                    diag = f"✅ {len(resultados)} resultado(s) con stock verificado"
                # Fallback HTML automático cuando Cloudflare bloquea el JSON
                if "Cloudflare" in diag:
                    fallback_url = f"https://{dominio(url)}/search?type=product&q={carta.replace(' ', '+')}"
                    try:
                        r2 = await _get_with_retries(
                            client, fallback_url, headers=HEADERS, timeout=15.0
                        )
                        if r2.status_code == 200:
                            resultados, diag = parse_shopify_html_fallback(r2.text, carta, nombre_tienda, fallback_url)
                            log["Estado HTTP"] += " → HTML fallback"
                    except Exception as e:
                        diag = f"🚨 Cloudflare + fallback falló: {e}"
            elif tipo == "woocommerce":
                resultados, diag = parse_woocommerce(r, carta, nombre_tienda, url)
                if resultados:
                    resultados = list({resultado["Link"]: resultado for resultado in resultados}.values())
                    resultados, fuera_stock, inconclusos = await verificar_fichas_html(
                        client, resultados, detalle_sem, tienda_detalle_sem
                    )
                    diag = (f"✅ {len(resultados)} resultado(s); {fuera_stock} sin stock descartado(s)"
                            f"; {inconclusos} no concluyente(s)")
            elif tipo == "jumpseller":
                resultados, diag = parse_jumpseller(r, carta, nombre_tienda, url)
                if resultados:
                    resultados = list({resultado["Link"]: resultado for resultado in resultados}.values())
                    resultados, fuera_stock, inconclusos = await verificar_fichas_html(
                        client, resultados, detalle_sem, tienda_detalle_sem
                    )
                    diag = (f"✅ {len(resultados)} resultado(s); {fuera_stock} sin stock descartado(s)"
                            f"; {inconclusos} no concluyente(s)")
            elif tipo == "scry_marketplace":
                resultados, diag = parse_scry_marketplace(r, carta, nombre_tienda, url)
            else:
                resultados, diag = [], f"Tipo desconocido: {tipo}"

            log["Diagnóstico"] = diag
            unicos = list({r["Link"]: r for r in resultados}.values())
            return unicos, log

        except json.JSONDecodeError:
            log["Diagnóstico"] = "🚨 JSON corrupto"
            return [], log
        except Exception as exc:
            log["Estado HTTP"] = "Error de red"
            log["Diagnóstico"] = f"🛑 {type(exc).__name__}: {exc}"
            return [], log


async def obtener_info_scryfall(client, sem, nombre, callback=None):
    url = f"https://api.scryfall.com/cards/named?fuzzy={nombre.replace(' ', '+')}"
    hdrs = {"User-Agent": "MTGChileCotizador/4.1", "Accept": "application/json"}
    async with sem:
        try:
            if callback: callback(f"🖼️ Scryfall: '{nombre}'…")
            r = await _get_with_retries(client, url, headers=hdrs, timeout=10.0)
            if r.status_code == 200:
                d = r.json()
                img = (d.get("image_uris") or {}).get("normal") or \
                      (d.get("card_faces", [{}])[0].get("image_uris") or {}).get("normal")
                usd = d.get("prices", {}).get("usd")
                return {"buscado": nombre, "nombre_real": d.get("name", nombre),
                        "imagen": img, "usd": float(usd) if usd else None}
        except Exception:
            pass
    return {"buscado": nombre, "nombre_real": nombre, "imagen": None, "usd": None}


async def cotizar_en_paralelo(lista_cartas, contenedor_status, barra_progreso):
    limits = httpx.Limits(max_keepalive_connections=40, max_connections=100)
    sem = asyncio.Semaphore(SEARCH_CONCURRENCY)
    detalle_sem = asyncio.Semaphore(DETAIL_CONCURRENCY)
    detalle_tienda_sems = {
        nombre: asyncio.Semaphore(DETAIL_CONCURRENCY_PER_STORE)
        for nombre in TIENDAS_CONFIG
    }
    total = len(TIENDAS_CONFIG) * len(lista_cartas) + len(lista_cartas)
    completadas = 0

    def tick(msg):
        nonlocal completadas
        completadas += 1
        pct = min(completadas / total, 1.0)
        barra_progreso.progress(pct, text=f"Progreso: {int(pct*100)}%  ({completadas}/{total})")
        contenedor_status.write(msg)

    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tareas_tiendas  = [buscar_en_tienda(
                               client, sem, n, c, carta, tick, detalle_sem,
                               detalle_tienda_sems[n],
                           )
                           for carta in lista_cartas for n, c in TIENDAS_CONFIG.items()]
        tareas_scryfall = [obtener_info_scryfall(client, sem, carta, tick)
                           for carta in lista_cartas]
        res_t, res_s = await asyncio.gather(
            asyncio.gather(*tareas_tiendas),
            asyncio.gather(*tareas_scryfall),
        )

    flat, logs = [], []
    for res, log in res_t:
        flat.extend(res)
        logs.append(log)
    return flat, {r["buscado"]: r for r in res_s}, logs


# ─────────────────────────────────────────────────────────────────────────────
# Interfaz Streamlit
# ─────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="MTG Chile Cotizador", layout="wide")
st.title("🃏 MTG Chile Bulk Optimizer v4.1")

col_input, col_results = st.columns([1, 3])

with col_input:
    st.subheader("📋 Lista de Cartas")
    lista_raw = st.text_area(
        "Pega tus cartas aquí:",
        value="1x Skullclamp\n1x Nest of Scarabs\n1x Lightning Bolt",
        height=320,
        help="Soporta formato Arena, MTGO, Moxfield. Ej: '4x Lightning Bolt'",
    )
    boton = st.button("🚀 Iniciar Cotización", type="primary", use_container_width=True)

    with st.expander(f"📍 {len(TIENDAS_CONFIG)} tiendas configuradas"):
        iconos = {"shopify_api": "🛍️", "woocommerce": "🛒", "jumpseller": "🏪", "scry_marketplace": "🔍"}
        for n in sorted(TIENDAS_CONFIG):
            t = TIENDAS_CONFIG[n]["tipo"]
            st.markdown(f"{iconos.get(t,'•')} **{n}** `{t}`")

    # ── Sección de inspección manual ─────────────────────────────────────────
    with st.expander("🔧 Tiendas que necesitan inspección manual"):
        st.markdown("""
**Cómo ayudarme a corregir estas tiendas:**

1. Abre la URL de búsqueda de cada tienda (columna "URL a Inspeccionar")
2. Busca cualquier carta como `Lightning Bolt`
3. Haz clic derecho sobre un **resultado de producto** → **Inspeccionar**
4. Para cada tienda, dime:
   - Clase del **contenedor** de cada producto (ej. `li.product` o `div.product-card`)
   - Clase del **título** (ej. `h2.product-title` o `a.product-name`)
   - Clase del **precio** (ej. `span.price` o `bdi`)
""")
        tabla_inspeccion = pd.DataFrame([
            {"Tienda": n, "Problema": "HTML no convencional / sin resultados", "URL a Inspeccionar": u}
            for n, u in TIENDAS_PENDIENTES_INSPECCION.items()
        ])
        st.dataframe(tabla_inspeccion, use_container_width=True, hide_index=True,
                     column_config={"URL a Inspeccionar": st.column_config.LinkColumn("URL", display_text="🔗 Abrir")})

with col_results:
    if boton:
        cartas = parsear_lista_bulk(lista_raw)
        if not cartas:
            st.error("No se reconoció ninguna carta.")
        else:
            st.subheader(f"⏳ Consultando {len(cartas)} carta(s) en {len(TIENDAS_CONFIG)} tiendas…")
            barra = st.progress(0.0, text="Inicializando…")

            with st.status("Ejecutando consultas…", expanded=True) as status_box:
                resultados_raw, scryfall_map, logs = asyncio.run(
                    cotizar_en_paralelo(cartas, status_box, barra)
                )
                status_box.update(
                    label=f"✅ Listo — {len(resultados_raw)} resultado(s) encontrados",
                    state="complete", expanded=False,
                )

            df_all = pd.DataFrame(resultados_raw) if resultados_raw else pd.DataFrame()

            tab_cartas, tab_tiendas, tab_debug = st.tabs([
                "🖼️ Por Carta", "🏢 Por Tienda", "🪲 Diagnóstico"
            ])

            # ── TAB 1: Por Carta ─────────────────────────────────────────────
            with tab_cartas:
                for carta in cartas:
                    info = scryfall_map.get(carta, {"nombre_real": carta, "imagen": None, "usd": None})
                    usd_txt = f" — USD ${info['usd']:.2f}" if info.get("usd") else ""
                    st.markdown(f"### ➡️ {info['nombre_real']}{usd_txt}")

                    # Imagen pequeña (80px) + tabla de precios al lado
                    c_img, c_tabla = st.columns([1, 6])
                    with c_img:
                        if info.get("imagen"):
                            st.image(info["imagen"], width=80)
                        else:
                            st.caption("Sin imagen")
                    with c_tabla:
                        if not df_all.empty:
                            df_carta = df_all[df_all["Carta Buscada"] == carta]
                            if not df_carta.empty:
                                st.dataframe(
                                    df_carta.sort_values("Precio")[["Tienda","Producto Encontrado","Precio","Link"]],
                                    use_container_width=True, hide_index=True,
                                    height=min(35 + len(df_carta) * 35, 300),
                                    column_config={
                                        "Link": st.column_config.LinkColumn("Enlace", display_text="🔗 Ir"),
                                        "Precio": st.column_config.NumberColumn("Precio CLP", format="$%d"),
                                    },
                                )
                            else:
                                st.info("Sin stock encontrado.")
                        else:
                            st.warning("Sin resultados.")
                    st.divider()

            # ── TAB 2: Por Tienda ────────────────────────────────────────────
            with tab_tiendas:
                if df_all.empty:
                    st.info("Sin resultados para mostrar.")
                else:
                    # Resumen global
                    resumen = (
                        df_all.groupby("Tienda")
                        .agg(
                            Cartas_Con_Stock=("Carta Buscada", "nunique"),
                            Precio_Min=("Precio", "min"),
                            Precio_Promedio=("Precio", "mean"),
                            Total_Resultados=("Producto Encontrado", "count"),
                        )
                        .sort_values("Cartas_Con_Stock", ascending=False)
                        .reset_index()
                    )
                    resumen["Precio_Promedio"] = resumen["Precio_Promedio"].round(0).astype(int)
                    st.markdown("#### Resumen por tienda")
                    st.dataframe(
                        resumen, use_container_width=True, hide_index=True,
                        column_config={
                            "Precio_Min":      st.column_config.NumberColumn("Precio mín.", format="$%d"),
                            "Precio_Promedio": st.column_config.NumberColumn("Precio prom.", format="$%d"),
                        },
                    )

                    # Detalle expandible por tienda
                    st.markdown("---")
                    st.markdown("#### Detalle de cartas por tienda")
                    tiendas_con_stock = resumen[resumen["Cartas_Con_Stock"] > 0]["Tienda"].tolist()
                    for tienda in tiendas_con_stock:
                        df_t = df_all[df_all["Tienda"] == tienda].sort_values(["Carta Buscada", "Precio"])
                        n_cartas = df_t["Carta Buscada"].nunique()
                        precio_total = df_t.groupby("Carta Buscada")["Precio"].min().sum()
                        with st.expander(
                            f"**{tienda}** — {n_cartas} carta(s) con stock  |  "
                            f"precio mín. total: ${precio_total:,.0f} CLP".replace(",", ".")
                        ):
                            st.dataframe(
                                df_t[["Carta Buscada","Producto Encontrado","Precio","Link"]],
                                use_container_width=True, hide_index=True,
                                column_config={
                                    "Link": st.column_config.LinkColumn("Enlace", display_text="🔗 Ir"),
                                    "Precio": st.column_config.NumberColumn("Precio CLP", format="$%d"),
                                },
                            )

            # ── TAB 3: Diagnóstico ───────────────────────────────────────────
            with tab_debug:
                df_logs = pd.DataFrame(logs)
                if not df_logs.empty:
                    # Colorear diagnósticos
                    resumen_debug = (
                        df_logs.groupby(["Tienda", "Estado HTTP", "Diagnóstico"])
                        .size().reset_index(name="Consultas")
                        .sort_values(["Tienda", "Diagnóstico"])
                    )
                    st.dataframe(resumen_debug, use_container_width=True, hide_index=True)

                    # Resumen rápido de estado
                    col_ok, col_warn, col_err = st.columns(3)
                    n_ok   = df_logs["Diagnóstico"].str.startswith("✅").sum()
                    n_warn = df_logs["Diagnóstico"].str.contains("⚠️|Sin stock|HTML").sum()
                    n_err  = df_logs["Diagnóstico"].str.contains("🚨|🛑|Cloudflare").sum()
                    col_ok.metric("✅ Con resultados", n_ok)
                    col_warn.metric("⚠️ Sin stock / HTML", n_warn)
                    col_err.metric("🚨 Errores", n_err)
