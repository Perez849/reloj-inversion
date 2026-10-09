# Worker de recomendaciones con Claude

La web es estática (GitHub Pages) y no puede guardar una clave de API. Este Worker la guarda
como secreto, llama a Claude con búsqueda web y filtra la respuesta: solo salen compañías con
datos respaldados por URLs que Claude encontró de verdad en la búsqueda.

## Despliegue (una vez)
```
cd worker
npx wrangler login
npx wrangler secret put ANTHROPIC_API_KEY     # pega tu clave de console.anthropic.com
npx wrangler deploy                           # te da https://reloj-ia.<tu-cuenta>.workers.dev
```
Después pon esa URL en `docs/assets/config.js` (`window.RELOJ_IA_URL = "https://…"`) y haz push.

Coste: cada pulsación hace una llamada con hasta 8 búsquedas web (del orden de céntimos).
`MAX_PER_HOUR` limita las peticiones por IP; `ALLOWED_ORIGIN` limita desde qué web se puede llamar.
