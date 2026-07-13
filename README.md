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

Pega una lista como `4x Lightning Bolt`, inicia la cotización y revisa resultados por carta, tienda y diagnóstico.
