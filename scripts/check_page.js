/* Comprueba que app.js e index.html encajan.
 *
 * El fallo que motiva esto: se subió el app.js nuevo a la raíz del repo y a
 * docs/data/, pero docs/index.html carga assets/app.js, que se quedó en la
 * versión vieja. El código antiguo escribía en #robustBlock y #btStats, que ya
 * no existían en el HTML nuevo, así que reventaba en la tercera línea de
 * render() y todo lo que venía después —cartera, validación, diagnóstico,
 * metodología— no llegaba a pintarse. En el navegador no se ve ningún error:
 * solo media página en blanco.
 *
 * Aquí se cruzan los identificadores que app.js escribe con los que index.html
 * declara, en las dos direcciones, y se avisa de copias descolgadas del fichero.
 */
const fs = require("fs");
const path = require("path");

const APP = "docs/assets/app.js";
const HTML = "docs/index.html";
const app = fs.readFileSync(APP, "utf8");
const html = fs.readFileSync(HTML, "utf8");

const fallos = [];

// 1. Identificadores que el JS escribe y que el HTML tiene que declarar.
const usados = new Set();
for (const m of app.matchAll(/\$\(\s*["'`]#([\w-]+)["'`]\s*\)/g)) usados.add(m[1]);
const declarados = new Set(
  [...html.matchAll(/id\s*=\s*["']([\w-]+)["']/g)].map(m => m[1]));
// los que crea el propio JS al inyectar plantillas
for (const m of app.matchAll(/id\s*=\s*["'\\]*([\w-]+)["'\\]*/g)) declarados.add(m[1]);

const huerfanos = [...usados].filter(id => !declarados.has(id));
if (huerfanos.length) {
  fallos.push(`app.js escribe en identificadores que no existen en index.html: ${huerfanos.join(", ")}`);
}

// 2. El <script> que carga la página tiene que ser el fichero comprobado.
const src = (html.match(/<script\s+src\s*=\s*["']([^"']+)["']/) || [])[1];
if (!src) {
  fallos.push("index.html no carga ningún script.");
} else {
  const real = path.normalize(path.join(path.dirname(HTML), src));
  if (real !== path.normalize(APP)) {
    fallos.push(`index.html carga ${real}, pero el fichero comprobado es ${APP}.`);
  }
}

// 3. Copias sueltas de app.js fuera de su sitio: son la causa del despiste.
const sueltas = ["app.js", "docs/data/app.js", "docs/app.js", "style.css", "docs/data/style.css"]
  .filter(f => fs.existsSync(f));
if (sueltas.length) {
  console.log(`Aviso: hay copias descolgadas que la página no usa: ${sueltas.join(", ")}. ` +
    `Si editas una de ellas creyendo que es la buena, el panel no cambiará.`);
}

if (fallos.length) {
  console.error("La página está rota:\n - " + fallos.join("\n - "));
  process.exit(1);
}
console.log(`OK: ${usados.size} identificadores comprobados, index.html carga ${src}.`);
