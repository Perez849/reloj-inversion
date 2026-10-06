/* Cloudflare Worker: recomendaciones de compañías con Claude + búsqueda web.
 *
 * La web (GitHub Pages) no puede guardar la clave de la API, así que este proxy la guarda
 * como secreto, llama a Claude con la herramienta de búsqueda web y devuelve SOLO lo que se
 * puede respaldar con fuentes:
 *   - cada dato tiene que traer una URL que Claude haya encontrado de verdad en la búsqueda
 *     (se comprueba aquí contra los resultados reales; si no está, el dato se descarta);
 *   - una compañía sin ningún dato verificable se descarta;
 *   - si queda vacío, la respuesta lo dice en vez de rellenar.
 * Despliegue: ver worker/README.md
 */
const ANTHROPIC_URL = "https://api.anthropic.com/v1/messages";
const hits = new Map(); // límite por IP, en memoria (best-effort)

const SYSTEM = `Eres un analista de renta variable prudente. Recibes una fase del ciclo económico
(reloj de inversión), un sector y un subsector que, según el histórico, rinde mejor que su sector
en esa fase. Tu tarea: proponer 3 a 5 compañías cotizadas REALES de ese subsector (pueden estar o
no en el ETF sectorial; EE.UU. o Europa, con liquidez) que a día de hoy tengan mejores argumentos
para comportarse bien en ese entorno.

Reglas innegociables:
1. Usa la búsqueda web para basarte en información reciente (resultados, guías de la empresa,
   cartera de pedidos, noticias regulatorias, valoración, revisiones de analistas). No uses solo tu memoria.
2. Cada argumento ("dato") debe ser un hecho concreto con su fuente (URL que hayas visto en la búsqueda,
   título y fecha). Nada de cifras sin fuente. Si no encuentras fuente, no lo afirmes.
3. No inventes tickers, cifras ni noticias. Si no estás seguro de que una compañía exista o cotice, no la incluyas.
4. No des precios objetivo ni prometas rentabilidad. Incluye siempre al menos un riesgo concreto por compañía.
5. "confianza" mide la calidad de la evidencia encontrada (alta: varios datos recientes y consistentes;
   media: algún dato sólido; baja: evidencia escasa o indirecta), no la certeza de que suba.
6. Si la evidencia es insuficiente para 3 compañías, devuelve menos, o ninguna, y explícalo en "limites".
7. Explica brevemente por qué encaja con la fase macro indicada (no solo con el sector).
Responde en español. Termina con UN ÚNICO bloque JSON entre \`\`\`json y \`\`\` con esta forma exacta:
{"resumen":"...","companias":[{"nombre":"...","ticker":"...","bolsa":"...","tesis":"...",
"por_que_ahora":[{"dato":"...","fuente_url":"https://...","fuente_titulo":"...","fecha":"AAAA-MM-DD"}],
"riesgos":["..."],"confianza":"alta|media|baja"}],"limites":"..."}`;

function cors(origin, env) {
  const allowed = (env.ALLOWED_ORIGIN || "https://perez849.github.io").split(",").map(s => s.trim());
  const ok = allowed.includes(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : allowed[0],
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Vary": "Origin",
  };
}

const json = (obj, status, headers) =>
  new Response(JSON.stringify(obj), { status, headers: { "Content-Type": "application/json", ...headers } });

function clean(s, n) { return String(s ?? "").replace(/[\u0000-\u001f]/g, " ").slice(0, n); }

function extractJson(text) {
  const fence = text.match(/```json\s*([\s\S]*?)```/i);
  const raw = fence ? fence[1] : (text.match(/\{[\s\S]*\}\s*$/) || [""])[0];
  try { return JSON.parse(raw); } catch { return null; }
}

export default {
  async fetch(req, env) {
    const origin = req.headers.get("Origin") || "";
    const h = cors(origin, env);
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: h });
    if (req.method !== "POST") return json({ error: "Método no permitido" }, 405, h);
    const allowed = (env.ALLOWED_ORIGIN || "https://perez849.github.io").split(",").map(s => s.trim());
    if (!allowed.includes(origin)) return json({ error: "Origen no permitido" }, 403, h);
    if (!env.ANTHROPIC_API_KEY) return json({ error: "Falta el secreto ANTHROPIC_API_KEY en el Worker" }, 500, h);

    const ip = req.headers.get("CF-Connecting-IP") || "?";
    const now = Date.now();
    const recent = (hits.get(ip) || []).filter(t => now - t < 3600_000);
    if (recent.length >= Number(env.MAX_PER_HOUR || 12)) return json({ error: "Demasiadas peticiones, espera un rato" }, 429, h);
    recent.push(now); hits.set(ip, recent);

    let body;
    try { body = await req.json(); } catch { return json({ error: "JSON no válido" }, 400, h); }
    const phase = clean(body.phase, 40), sector = clean(body.sector, 80), sub = clean(body.subsector, 80);
    if (!phase || !sector || !sub) return json({ error: "Faltan phase, sector o subsector" }, 400, h);
    const alt = clean(body.alt_phase, 40), date = clean(body.date, 12);
    const edge = Number.isFinite(+body.edge_pp) ? (+body.edge_pp).toFixed(1) : null;
    const etf = Array.isArray(body.etf_names) ? body.etf_names.slice(0, 8).map(x => clean(x, 60)).join(", ") : "";
    const user = `Fase actual: ${phase}${alt ? ` (segunda fase: ${alt})` : ""}. Fecha del dato macro: ${date}.
Sector: ${sector}. Subsector: ${sub}.${edge ? ` Histórico: en esta fase el subsector ha rendido ${edge} pp/año frente a su sector completo (dato pasado, no predicción).` : ""}
${etf ? `Mayores posiciones hoy en el ETF sectorial (solo contexto, no estás limitado a ellas): ${etf}.` : ""}
Hoy es ${new Date().toISOString().slice(0, 10)}. Propón compañías con criterio y fuentes recientes.`;

    const r = await fetch(ANTHROPIC_URL, {
      method: "POST",
      headers: { "x-api-key": env.ANTHROPIC_API_KEY, "anthropic-version": "2023-06-01", "content-type": "application/json" },
      body: JSON.stringify({
        model: env.MODEL || "claude-sonnet-5-5",
        max_tokens: 4000,
        system: SYSTEM,
        tools: [{ type: env.SEARCH_TOOL || "web_search_20250305", name: "web_search", max_uses: 8 }],
        messages: [{ role: "user", content: user }],
      }),
    });
    if (!r.ok) {
      const t = await r.text();
      return json({ error: `Error de la API de Claude (${r.status})`, detail: t.slice(0, 300) }, 502, h);
    }
    const data = await r.json();

    // URLs que de verdad aparecieron en la búsqueda (resultados y citas)
    const seen = new Set();
    for (const b of data.content || []) {
      if (b.type === "web_search_tool_result" && Array.isArray(b.content)) {
        for (const x of b.content) if (x.url) seen.add(x.url);
      }
      if (b.type === "text" && Array.isArray(b.citations)) {
        for (const c of b.citations) if (c.url) seen.add(c.url);
      }
    }
    const text = (data.content || []).filter(b => b.type === "text").map(b => b.text).join("\n");
    const parsed = extractJson(text);
    if (!parsed || !Array.isArray(parsed.companias)) {
      return json({ error: "Claude no devolvió un resultado estructurado; vuelve a intentarlo" }, 502, h);
    }

    let dropped = 0;
    const companias = [];
    for (const c of parsed.companias.slice(0, 6)) {
      const ticker = clean(c.ticker, 12).toUpperCase();
      if (!/^[A-Z0-9.\-]{1,10}$/.test(ticker)) { dropped++; continue; }
      const datos = (Array.isArray(c.por_que_ahora) ? c.por_que_ahora : []).filter(d => {
        const ok = typeof d.fuente_url === "string" && seen.has(d.fuente_url) && d.dato;
        if (!ok) dropped++;
        return ok;
      }).slice(0, 5).map(d => ({
        dato: clean(d.dato, 400), fuente_url: d.fuente_url, fuente_titulo: clean(d.fuente_titulo, 140), fecha: clean(d.fecha, 12),
      }));
      if (!datos.length) { dropped++; continue; }   // sin ningún dato verificable no se muestra
      companias.push({
        nombre: clean(c.nombre, 80), ticker, bolsa: clean(c.bolsa, 30), tesis: clean(c.tesis, 500),
        por_que_ahora: datos,
        riesgos: (Array.isArray(c.riesgos) ? c.riesgos : []).slice(0, 3).map(x => clean(x, 240)),
        confianza: ["alta", "media", "baja"].includes(c.confianza) ? c.confianza : "baja",
      });
    }
    return json({
      generado: new Date().toISOString(), modelo: data.model || env.MODEL,
      resumen: clean(parsed.resumen, 600), limites: clean(parsed.limites, 500),
      companias, descartados_sin_fuente: dropped, fuentes_consultadas: seen.size,
    }, 200, h);
  },
};
