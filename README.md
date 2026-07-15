# MTG Search Chile

Cotizador local de cartas Magic: The Gathering que consulta precios en tiendas chilenas y muestra los resultados en una interfaz Flask con Bootstrap.

## Inicio rápido en Windows

1. Instala Python 3.10 o superior y activa la opción **Add Python to PATH**.
2. Descarga o clona este repositorio.
3. Ejecuta `iniciar_web.bat`.
4. Abre [http://127.0.0.1:5000](http://127.0.0.1:5000) si el navegador no se abre automáticamente.

El iniciador crea el entorno virtual `.venv`, instala las dependencias y levanta el servidor Flask.

## Inicio manual

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python app.py
```

Agrega cartas por nombre con sugerencias de Scryfall o importa una lista de Arena,
MTGO o Moxfield. Las cantidades no son necesarias: formatos antiguos como
`4x Lightning Bolt` siguen siendo compatibles, pero se busca cada nombre una vez.

La wishlist utiliza el mismo autocompletado. Cada entrada representa una carta,
sin cantidad, y puede incluir notas y un precio objetivo.

## Despliegue en Render

El repositorio incluye un `render.yaml` para desplegar la interfaz Flask como
servicio web. Render instala `requirements.txt` y ejecuta:

```text
gunicorn app:app
```

La aplicación también respeta la variable `PORT` cuando se inicia directamente
con `python app.py`.

## Price tracker de wishlist

Cada carta de la wishlist puede tener un precio objetivo en CLP. La función
`wishlist-price-tracker` procesa una carta por invocación, consulta el endpoint
interno firmado de Render y envía una sola alerta mediante Resend cuando el
precio mínimo es igual o inferior al objetivo.

El esquema está en
`supabase/migrations/20260715050000_wishlist_price_tracker.sql`. Después de
desplegar la función y configurar sus secretos, crea en Vault
`price_tracker_function_url` y `price_tracker_cron_secret`, y ejecuta
`supabase/cron/wishlist_price_tracker.sql` para habilitar el ciclo de seis horas.
El cron se mantiene separado de las migraciones para que nunca se active antes
de que Render, Resend y la Edge Function estén listos.

GitHub Actions valida cada pull request y cada cambio en `main`. Si los checks
de `main` terminan correctamente, el job de despliegue inicia una nueva versión
en Render mediante su API.
