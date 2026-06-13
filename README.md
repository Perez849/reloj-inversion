# Reloj de la Inversión

Dashboard web del Reloj de la Inversión, alojado en GitHub Pages y actualizado automáticamente cada día mediante GitHub Actions.

El sistema descarga datos de FRED, calcula 28 indicadores macroeconómicos, entrena un modelo logístico supervisado para clasificar la fase del ciclo económico, y genera recomendaciones para 25 clases de activos.

## Cómo se estructura

```
.
├── investment_clock.py        ← motor principal (NO modificar)
├── ic_export_json.py          ← exporta el estado actual a docs/data.json
├── docs/
│   ├── index.html             ← la web (GitHub Pages la sirve desde aquí)
│   └── data.json              ← datos generados (auto-actualizado)
└── .github/workflows/
    └── update-clock.yml        ← ejecuta el Python cada día y actualiza data.json
```

## Puesta en marcha (una sola vez)

### 1. Crear el repositorio
Crea un repositorio nuevo en GitHub (público o privado) y sube todos estos archivos respetando la estructura de carpetas anterior.

```bash
git init
git add .
git commit -m "Reloj de la Inversión inicial"
git branch -M main
git remote add origin https://github.com/Perez849/reloj-inversion.git
git push -u origin main
```

### 2. Activar GitHub Pages
En tu repositorio:
1. Ve a **Settings → Pages**
2. En **Source**, selecciona **Deploy from a branch**
3. En **Branch**, elige `main` y carpeta `/docs`
4. Guarda

En 1-2 minutos tu reloj estará disponible en:
```
https://perez849.github.io/reloj-inversion/
```

### 3. Activar GitHub Actions
1. Ve a la pestaña **Actions** de tu repositorio
2. Si te pide habilitar workflows, acéptalo
3. El workflow se ejecutará automáticamente cada día a las 06:30 UTC
4. Para ejecutarlo manualmente ahora mismo: **Actions → Actualizar Reloj de la Inversión → Run workflow**

## Cómo funciona la actualización automática

Cada día, GitHub Actions:
1. Instala Python y las dependencias (pandas, numpy, scikit-learn, requests)
2. Ejecuta `ic_export_json.py`, que reutiliza toda la lógica de `investment_clock.py`
3. Genera un `docs/data.json` actualizado con la fase actual, scoring, recomendaciones y diagnóstico
4. Hace commit y push del nuevo `data.json` si ha cambiado

La web `index.html` lee `data.json` y dibuja el dashboard. Es 100% estático, no requiere servidor.

## Probar en local

Para ver la web en tu ordenador antes de subirla:

```bash
cd docs
python3 -m http.server 8000
# Abre http://localhost:8000 en el navegador
```

Para regenerar `data.json` en local:

```bash
python3 ic_export_json.py docs
```

## Notas

- El modelo logístico (`ic_logistic_model.pkl`) se reentrena automáticamente si no existe o si los datos han cambiado.
- La primera ejecución del workflow puede tardar 2-3 minutos (descarga FRED + entrena el modelo).
- No constituye asesoramiento financiero. Es una herramienta de análisis cuantitativo.
