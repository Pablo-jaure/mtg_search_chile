import asyncio
import os
from pathlib import Path
from urllib.parse import urlencode, urljoin, urlsplit

from flask import Flask, render_template, request


# Reutiliza la lógica del cotizador original sin ejecutar su interfaz Streamlit.
_source = Path(__file__).with_name("mtg_cotizador.py").read_text(encoding="utf-8")
_core = _source.split("# Interfaz Streamlit", 1)[0]
_core = _core.replace("import streamlit as st\n", "").replace("import pandas as pd\n", "")
exec(compile(_core, "mtg_cotizador.py", "exec"), globals())

app = Flask(__name__)


async def cotizar_web(cartas):
    limits = httpx.Limits(max_keepalive_connections=40, max_connections=100)
    sem = asyncio.Semaphore(4)
    async with httpx.AsyncClient(limits=limits, follow_redirects=True) as client:
        tiendas = [
            buscar_en_tienda(client, sem, nombre, config, carta)
            for carta in cartas for nombre, config in TIENDAS_CONFIG.items()
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
            "cartas": len(dato["cartas"]),
            "minimo": min(dato["precios"]),
            "promedio": round(sum(dato["precios"]) / len(dato["precios"])),
            "resultados": dato["resultados"],
        }

        # Un carrito Shopify acepta variantes como /cart/ID:cantidad. Para no
        # agregar todas las ediciones encontradas, se elige la más barata con
        # stock de cada carta buscada dentro de esta tienda.
        candidatas = [
            fila for fila in resultados
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
            )

        candidatas_woo = [
            fila for fila in resultados
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
                parametros = {
                    "add-to-cart": compra["product_id"],
                    "quantity": 1,
                }
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
            )

        resumen.append(fila_resumen)
    return sorted(resumen, key=lambda item: (-item["cartas"], item["tienda"]))


@app.route("/", methods=["GET", "POST"])
def inicio():
    lista = "1x Skullclamp\n1x Nest of Scarabs\n1x Lightning Bolt"
    contexto = {"lista": lista, "tiendas": TIENDAS_CONFIG}

    if request.method == "POST":
        lista = request.form.get("lista", "")
        cartas = parsear_lista_bulk(lista)
        contexto.update(lista=lista, cartas=cartas)
        if not cartas:
            contexto["error"] = "No se reconoció ninguna carta en la lista."
        else:
            try:
                resultados, scryfall, logs = asyncio.run(cotizar_web(cartas))
                contexto.update(
                    resultados=resultados,
                    por_carta={
                        carta: sorted(
                            (fila for fila in resultados if fila["Carta Buscada"] == carta),
                            key=lambda fila: fila["Precio"],
                        ) for carta in cartas
                    },
                    scryfall=scryfall,
                    resumen=crear_resumen_tiendas(resultados),
                    logs=logs,
                )
            except Exception as exc:
                contexto["error"] = f"No se pudo completar la cotización: {exc}"

    return render_template("index.html", **contexto)


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG") == "1",
    )
