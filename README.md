# QB Decision Margin: Margen de Decisión del QB

QB Decision Margin mide cuánto margen tiene un quarterback antes de que llegue la presión defensiva. Usa los datos del NFL Big Data Bowl en `data/`: 122 juegos de 2021, 8,557 jugadas de pase, más de 8 millones de filas de tracking a 10 FPS, y los archivos de jugadas, jugadores y PFF. El margen de decisión es el tiempo hasta la presión menos el tiempo de lanzamiento, ambos desde el snap. La presión es una definición operacional del equipo, no oficial de la NFL: un pass rusher (rol PFF "Pass Rush") entra a 2.0 yardas o menos del QB después del snap y se mantiene 2 frames consecutivos. La aplicación (FastAPI + React) muestra un resumen por categorías, compara quarterbacks y pass rushers, desglosa por formación y cobertura, y tiene un explorador de jugadas con filtros y detalle.

## Cómo ejecutarlo

Desde la raíz del proyecto, en Windows PowerShell:

```
cd dashboard; npm run build; cd ..
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --port 8000
```

Después abre `http://localhost:8000/`. La documentación de la API está en `http://localhost:8000/docs`.

Al arrancar, el backend procesa los 122 archivos de tracking de uno en uno, en unos 20 segundos. Durante ese tiempo la página muestra un aviso de carga. No escribe archivos y no modifica `data/`.

- **Desarrollo:** ejecuta `npm run dev` dentro de `dashboard/`. Vite redirige `/api` a `localhost:8000`.
- **Pruebas:** `.\.venv\Scripts\python.exe -m pytest backend/test_api.py -q`.
- **Validación metodológica:** `.\.venv\Scripts\python.exe -m backend.validate_pressure`.

## Limitaciones

- El tracking termina unos 0.5 s después del lanzamiento. Por eso el margen positivo exacto no pasa de unos 0.4 s y no mide todo el tiempo libre del QB.
- 3,610 jugadas son censuradas: no se observó presión antes del fin del tracking. Se muestran aparte, nunca entran en medias ni medianas de márgenes exactos y no significan que no hubo presión.
- La resolución es de 0.1 s (10 FPS). El umbral de 2 yardas puede contar como llegada un defensor que oscila justo en el borde del radio.
- Hit, hurry y sack son etiquetas de PFF, distintas de la presión detectada por tracking.
- Todas las comparaciones son asociaciones descriptivas, con su tamaño de muestra, y no implican causalidad. Los grupos con muestra pequeña no se ordenan ni se presentan como concluyentes.
