# 🍷 RepoSommelier (español)

**El buscador inteligente de repos de GitHub para personas e IAs.** Dile lo que quieres hacer, **en cualquier idioma**, y te da **los mejores repos para tu necesidad**, del mejor al peor. Te explica por qué, te dice la verdad de la licencia y te avisa de lo importante.

> Un sumiller no te sirve el vino más caro: te sirve el mejor para *tu* platillo, *tu* gusto y *tu* presupuesto.

```bash
python3 reposommelier.py "hacer videos 3D animados con código"
python3 reposommelier.py "transcribir audio en español" --cpu --free --commercial   # sin GPU, gratis, deja ganar dinero
python3 reposommelier.py --verdict owner/repo good "nos funcionó"                     # le enseñas (good/bueno o bad/malo)
python3 reposommelier.py --history
```

## Qué hace
1. **Entiende** tu necesidad en cualquier idioma y escribe 6 búsquedas cortas con nombres de herramientas reales.
2. **Busca** en GitHub y **descarta** lo que no sirve: archivados, copias (forks), listas «awesome», sin código, abandonados y de juguete.
3. **Lee el README** de los 25 mejores: si se instala fácil, si tiene demo, si pide GPU o una API de pago, si tiene pruebas y si está hecho para agentes.
4. Un **juez** (Gemini) califica de 0 a 10 qué tanto te sirve cada repo **a ti**, usando tu perfil (`data/profile.json`: tu equipo, tus reglas y lo que ya tienes).
5. **Puntúa** de 0 a 100 y lo pone en un nivel: **Usar ya**, **Adaptar** o **Estudiar**.
6. Te da **3 recomendaciones**: el mejor, el mejor gratis sin GPU y la promesa nueva.
7. **Aprende** de tus veredictos.

## Bloqueos: lo que NO funciona donde estás HOY
```bash
python3 reposommelier.py "ver videos de YouTube" --where cloud --verify
python3 reposommelier.py "..." --blockers yt-dlp gpu cookies
```
- **Nunca borra:** los repos bloqueados salen en una segunda lista, «⛔ No funcionan donde estás HOY», con la razón.
- **Por búsqueda y por lugar:** perfiles `profiles/cloud.json` y `profiles/laptop.json` (o los tuyos en `data/profiles/`). Cada búsqueda empieza de cero.
- Si un repo usa algo bloqueado pero **puede funcionar sin eso**, se queda con un aviso.
- **`--verify`** prueba cada bloqueo una vez, sin saltarse nada. Si ya funciona, lo quita y te avisa.
- El **historial** guarda la fecha y la razón, y te avisa si un repo apartado antes ya se puede usar.

## Noticias y repos del momento
- `--news`: además de GitHub, lee lo que se comenta en Hacker News, Lobsters y dev.to (últimos 120 días).
- `--trending`: los repos del momento (últimos 7 días), revisados contra tu perfil. GitHub Trending bloquea servidores; su sustituto legítimo es la búsqueda oficial de GitHub.
- **X y Reddit** (donde más se comparten repos) bloquean servidores. Solo se leen por caminos permitidos y con tu propia clave: `FIRECRAWL_API_KEY` o `BRAVE_API_KEY` (buscadores que indexan publicaciones públicas), la API oficial de Reddit (gratis para uso personal) o la de X (de pago). Sin clave te lo dice; nunca raspa páginas ni usa cookies.
- Marca los repos con estrellas sospechosamente rápidas (a veces son falsas o trampas con malware).

## Plan B: sustitutos legítimos de lo bloqueado
Si un repo queda apartado, te dice cómo usarlo de todas formas **solo por caminos permitidos**: versión para CPU del mismo modelo (busca repos sustitutos, por ejemplo F5-TTS → F5-TTS-ONNX), modelo local en vez de API de pago, instalación directa en vez de Docker, o darle el archivo tú. Nunca propone proxies, trucos con cookies ni resolvedores de captcha.

## Modo cacería (`hunt.py`): busca una y otra vez hasta que algo funcione donde estás
Ronda tras ronda agrega búsquedas nuevas y lee más fuentes: búsqueda de repos y **búsqueda de código** de GitHub (encuentra repos por lo que su código hace de verdad), npm, Hugging Face Spaces, Hacker News (historias y comentarios), Lobsters, dev.to y X/Reddit con clave. Le dices la **evidencia** de que funciona (`--works-if`) y se detiene en cuanto encuentra; si no hay repo, busca **conectores** con MCPSommelier.

Responde en el idioma en que preguntes; también puedes elegirlo con `--lang es`.

**Seguridad:** solo **lee** datos públicos. Nunca clona, instala ni corre lo que encuentra. Revisa el código antes de usar cualquier repo.

## Alternativas gratis a un producto de paga
```bash
python3 reposommelier.py --alternativa Loom          # o simplemente: "quiero dejar de pagar Loom"
python3 reposommelier.py "quiero dejar de pagar Notion, Canva y Calendly"   # varias apps: una búsqueda por cada una
```
Detecta «alternativa a X / dejar de pagar X / parar de pagar X / replace X», busca en GitHub y en openalternative.co,
y pone primero los proyectos probados (las estrellas pesan más; los nuevos con menos de 20 estrellas bajan; los que solo
comparten el nombre se van abajo). Cada reemplazo real lleva 🔁.
