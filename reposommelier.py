#!/usr/bin/env python3
"""RepoSommelier — the smart GitHub repo finder for humans and AI agents.

Tell it what you want to build, in ANY language, and it returns the best GitHub repos for YOUR need, ranked best to
worst, with the reasons, the license truth and the warnings that matter (GPU, paid API, non-commercial...).
A sommelier does not pour the most expensive wine: it pours the best one for your dish, your taste and your budget.

    python3 reposommelier.py "make 3D animated shorts with code"
    python3 reposommelier.py "transcribir audio en español" --cpu --free --commercial
    python3 reposommelier.py "生成游戏音效" --lang zh --json             # any language in, any language out
    python3 reposommelier.py --verdict owner/repo good "worked great"   # teach it: shifts future rankings
    python3 reposommelier.py --history

How it works
 1. UNDERSTANDS the need (any language): Gemini writes 6 short GitHub queries with real tool names (fallback: a
    small synonym dictionary). GitHub search needs EVERY word to match, so queries stay 2-3 concrete words.
 2. SEARCHES GitHub (official search API through `gh`; 24 h cache) and merges candidates.
 3. DROPS archived repos, forks, "awesome" lists, no code, no description, dead (>18 months) and toys.
 4. READS THE README of the top 25: easy install? demo? needs a GPU? needs a paid API? tests? built for agents?
    and how much it talks about YOUR task.
 5. JUDGE (optional, Gemini): rates 0-10 how well each of the top 10 fits the task AND your profile
    (profile.json: hardware, rules, what you already have), with a one-line reason in your language.
 6. SCORES 0-100 = relevance 35 + judge 15 + popularity 15 + activity 15 + health 10 + license 10 + your verdicts.
 7. RETURNS the ranking with a tier (Use now >=70 / Adapt 55-69 / Study <55), warnings and 3 picks:
    best overall, best free & CPU-friendly, rising newcomer.
Read-only: it never clones, installs or runs what it finds. Always review a repo's code before using it.
"""

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = Path(os.environ.get("REPOSOMMELIER_DATA", HERE / "data"))
INDEX, CACHE = DATA / "index.json", DATA / "cache"
UA = {"User-Agent": "reposommelier/1.0"}
STOP = set("the a an of for to and or in on with using make create build tool tools app want need my "
           "de la el los las un una y o en con para por que a del al sin como hacer crear mi mis tu quiero necesito "
           "do da das dos um uma e com para fazer criar meu".split())
PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense", "0bsd", "cc0-1.0", "zlib"}
COPYLEFT = {"gpl-2.0", "gpl-3.0", "agpl-3.0", "lgpl-2.1", "lgpl-3.0"}
SYN = {"video": ["video", "motion graphics", "animation"], "3d": ["3d", "three.js", "blender", "webgl"],
       "audio": ["audio", "sound", "sfx"], "voice": ["tts", "voice", "speech"], "voz": ["tts", "voice", "speech"],
       "subtitles": ["subtitles", "captions"], "subtitulos": ["subtitles", "captions"], "edit": ["editing", "editor"],
       "editar": ["editing", "editor"], "image": ["image", "diffusion"], "imagen": ["image", "diffusion"],
       "music": ["music", "audio generation"], "musica": ["music", "audio generation"], "animation": ["animation", "animated"],
       "animacion": ["animation", "animated"], "transcribe": ["transcription", "whisper"], "transcribir": ["transcription", "whisper"],
       "agent": ["agent", "claude code", "mcp"], "agente": ["agent", "claude code", "mcp"], "automate": ["automation", "workflow"],
       "automatizar": ["automation", "workflow"], "download": ["download", "downloader"], "descargar": ["download", "downloader"]}

# Labels for human output. Other languages fall back to English (the judge still writes reasons in the user's language).
L = {
 "en": dict(title="Best repos for", cand="candidates", drop="dropped", read="READMEs read", judge="judge", best="Best",
            free="Best free & CPU-friendly", rising="Rising newcomer", cols="| # | Repo | Score | Tier | ⭐ | License | Updated | What it is | Judge | Warnings |",
            tiers=("Use now", "Adapt", "Study"), days="d", queries="Queries", saved="Saved",
            w=dict(nolic="⚠️ no clear license", copyleft="ℹ️ copyleft", nc="⚠️ non-commercial", gpu="🎮 needs GPU",
                   paid="💳 paid API", agent="🤖 agent-ready", new="🆕 new", hot="🔥 trending"),
            blocked="⛔ Does not work where you are TODAY", because="because it uses", partial="⚠️ works without",
            loses="but loses part of its features", was_blocked="was set aside on", now_ok="no longer blocked here",
            verified_ok="verified: {b} works here now, its repos are back in the ranking",
            verified_bad="verified: {b} is still blocked here", where="Where"),
 "es": dict(title="Mejores repos para", cand="candidatos", drop="descartados", read="READMEs leídos", judge="juez", best="El mejor",
            free="Mejor gratis sin GPU", rising="Promesa nueva", cols="| # | Repo | Puntos | Nivel | ⭐ | Licencia | Cambió | Qué es | Juez | Avisos |",
            tiers=("Usar ya", "Adaptar", "Estudiar"), days="d", queries="Búsquedas", saved="Guardado",
            w=dict(nolic="⚠️ sin licencia clara", copyleft="ℹ️ copyleft", nc="⚠️ no comercial", gpu="🎮 necesita GPU",
                   paid="💳 API de pago", agent="🤖 hecho para agentes", new="🆕 muy nuevo", hot="🔥 en tendencia"),
            blocked="⛔ No funcionan donde estás HOY", because="porque usa", partial="⚠️ funciona sin",
            loses="pero pierde parte de lo que hace", was_blocked="estaba apartado el", now_ok="ya no está bloqueado aquí",
            verified_ok="verificado: {b} ya funciona aquí, sus repos vuelven al ranking",
            verified_bad="verificado: {b} sigue bloqueado aquí", where="Lugar"),
 "pt": dict(title="Melhores repos para", cand="candidatos", drop="descartados", read="READMEs lidos", judge="juiz", best="O melhor",
            free="Melhor grátis sem GPU", rising="Promessa nova", cols="| # | Repo | Pontos | Nível | ⭐ | Licença | Atualizado | O que é | Juiz | Avisos |",
            tiers=("Usar já", "Adaptar", "Estudar"), days="d", queries="Buscas", saved="Salvo",
            w=dict(nolic="⚠️ sem licença clara", copyleft="ℹ️ copyleft", nc="⚠️ não comercial", gpu="🎮 precisa de GPU",
                   paid="💳 API paga", agent="🤖 feito para agentes", new="🆕 muito novo", hot="🔥 em alta"),
            blocked="⛔ Não funcionam onde você está HOJE", because="porque usa", partial="⚠️ funciona sem",
            loses="mas perde parte do que faz", was_blocked="foi separado em", now_ok="não está mais bloqueado aqui",
            verified_ok="verificado: {b} já funciona aqui, os repos voltam ao ranking",
            verified_bad="verificado: {b} continua bloqueado aqui", where="Lugar"),
}


def words(t):
    return [w for w in re.findall(r"[\w.+#-]{2,}", (t or "").lower()) if w not in STOP]


def days(date):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(date.replace("Z", "+00:00"))).days


def load(path, default):
    try:
        return json.loads(Path(path).read_text())
    except Exception:  # noqa: BLE001
        return default


def guess_lang(text):
    t = f" {text.lower()} "
    if re.search(r"[一-鿿]", t): return "zh"
    if re.search(r"[぀-ヿ]", t): return "ja"
    if re.search(r"[Ѐ-ӿ]", t): return "ru"
    if any(w in t for w in (" fazer ", " quero ", "ção", " vídeos ", " com ", " não ", "ões")): return "pt"
    if any(w in t for w in (" hacer ", " quiero ", " para ", " con ", " que ", " en ", " el ", " la ", "ñ", "ción", "á", "é", "í", "ó", "ú")): return "es"
    return "en"


# ---------- Gemini (optional) ----------
def _gemini_key():
    if os.environ.get("GEMINI_API_KEY"):
        return os.environ["GEMINI_API_KEY"]
    env = Path.home() / ".config/watch/.env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GEMINI_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"')
    return "proxy-injected"   # some sandboxes inject the key through a proxy


def gemini_json(prompt):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}],
                       "generationConfig": {"responseMimeType": "application/json"}}).encode()
    for model in os.environ.get("REPOSOMMELIER_MODELS", "gemini-3-flash-preview,gemini-flash-latest").split(","):
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent",
                                     body, {**UA, "Content-Type": "application/json", "x-goog-api-key": _gemini_key()})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.loads(r.read())
            return json.loads(res["candidates"][0]["content"]["parts"][0]["text"])
        except Exception:  # noqa: BLE001
            continue
    return None


def plan_queries(need):
    base = words(need)
    extra = [s for w in base for s in SYN.get(w, [])]
    dic = [x for x in dict.fromkeys([" ".join(extra[:2]), " ".join(extra[1:3])]) if x.strip()]
    g = gemini_json("Turn this need (it may be in any language) into GitHub repository-search queries. GitHub requires EVERY "
                    "word to appear in name/description/README, so each query must be ONLY 2-3 concrete, popular English words "
                    "that a real repo would contain (library and tool names: three.js, remotion, blender, ffmpeg, whisper, "
                    "claude code, mcp...), never abstract phrases. Return JSON {\"lang\": ISO 639-1 code of the need, "
                    "\"queries\": [6 strings], \"keywords\": [6-10 English words a great repo for this would mention]}. Need: " + need)
    if g and g.get("queries"):
        return list(dict.fromkeys(g["queries"][:6] + dic))[:8], g.get("keywords", []) + extra, "gemini", g.get("lang")
    return dic or [" ".join(base[:3])], extra, "dictionary", None


# ---------- GitHub (read-only) ----------
def search(q):
    CACHE.mkdir(parents=True, exist_ok=True)
    f = CACHE / (re.sub(r"[^a-z0-9]+", "_", q.lower())[:80] + ".json")
    if f.exists() and time.time() - f.stat().st_mtime < 86400:
        return json.loads(f.read_text())
    r = subprocess.run(["gh", "api", "-X", "GET", "search/repositories", "-f", f"q={q}", "-f", "per_page=40"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        print(f"  (search failed: {q}: {r.stderr.strip()[:100]})", file=sys.stderr)
        return []
    items = json.loads(r.stdout).get("items", [])
    f.write_text(json.dumps(items))
    return items


def readme(repo):
    for name in ("README.md", "readme.md", "README.MD", "README.rst", "README"):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                    f"https://raw.githubusercontent.com/{repo}/HEAD/{name}", headers=UA), timeout=20) as r:
                return r.read(200_000).decode("utf-8", "ignore")
        except Exception:  # noqa: BLE001
            continue
    return ""


def readme_signals(txt, terms):
    t = txt.lower()
    has = lambda *ws: any(w in t for w in ws)  # noqa: E731
    s = {"install": has("pip install", "npm install", "npx ", "uv ", "docker run", "brew install", "## install", "cargo install"),
         "demo": has(".gif", ".mp4", ".webm", "demo", "screenshot", "gallery"),
         "gpu": has("requires a gpu", "gpu required", "requires cuda", "cuda is required", "nvidia gpu with", "minimum vram", "a100", "h100")
                and not has("cpu only", "no gpu", "on cpu", "cpu mode", "runs on cpu", "device cpu", "cpu inference", "cpu and gpu", "cpu or gpu"),
         "paid": has("openai_api_key", "api key required", "paid plan", "subscription", "credits") and not has("free", "open source"),
         "tests": has("pytest", "npm test", "vitest", "jest", "## test", "actions/workflows"),
         "agent": has("claude code", "skill.md", "mcp", "agent skill", "codex")}
    w = words(txt[:60_000]); total = max(1, len(w))
    s["readme_relevance"] = round(min(1.0, sum(min(1.0, w.count(x) / total * 400) for x in terms) / max(1, len(terms))), 3)
    return s


# ---------- news: what people are talking about (Hacker News, Lobsters, dev.to) ----------
GH_RE = re.compile(r"github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
NOT_REPOS = {"orgs", "topics", "features", "sponsors", "settings", "marketplace", "about", "trending", "collections", "apps", "login"}


def _get_json(url):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def _repo_from(text):
    for o, n in GH_RE.findall(text or ""):
        n = re.sub(r"\.git$", "", n).rstrip(".")
        if o.lower() not in NOT_REPOS and n:
            return f"{o}/{n}"
    return None


NEWS_HITS = []   # every news item read (also the ones that point to Hugging Face, blogs...)
NEWS_TERMS = set()   # words that make a news item relevant to the current need


def relevant(h):
    hay = (h.get("title", "") + " " + h.get("url", "")).lower()
    return not NEWS_TERMS or any(re.search(rf"(?<![a-z0-9]){re.escape(t)}(?![a-z0-9])", hay) for t in NEWS_TERMS)


def news_mentions(topics, days=120):
    """Repos mentioned in recent news/forums about the topics. Returns {owner/repo: [mentions]}."""
    found = {}
    since = int(time.time()) - days * 86400
    for q in topics:
        url = ("https://hn.algolia.com/api/v1/search?tags=story&hitsPerPage=50&numericFilters=created_at_i>" + str(since)
               + "&query=" + urllib.parse.quote(q))
        for h in (_get_json(url) or {}).get("hits", []):
            if not relevant({"title": h.get("title") or "", "url": h.get("url") or ""}):
                continue
            NEWS_HITS.append({"source": "Hacker News", "title": h.get("title") or "", "url": h.get("url") or "",
                              "points": h.get("points") or 0, "date": (h.get("created_at") or "")[:10],
                              "link": f"https://news.ycombinator.com/item?id={h.get('objectID')}"})
            repo = _repo_from(h.get("url")) or _repo_from(h.get("story_text"))
            if repo:
                found.setdefault(repo, []).append({"source": "Hacker News", "title": h.get("title"), "points": h.get("points") or 0,
                                                   "date": (h.get("created_at") or "")[:10],
                                                   "link": f"https://news.ycombinator.com/item?id={h.get('objectID')}"})
        time.sleep(0.5)
    return found


def trending_news(days=7):
    """Repos of the moment: GitHub links on Hacker News (last days) and Lobsters' hottest."""
    found = {}
    since = int(time.time()) - days * 86400
    for page in range(3):
        d = _get_json(f"https://hn.algolia.com/api/v1/search?query=github.com&restrictSearchableAttributes=url&tags=story"
                      f"&hitsPerPage=100&page={page}&numericFilters=created_at_i>{since}") or {}
        for h in d.get("hits", []):
            repo = _repo_from(h.get("url"))
            if repo:
                found.setdefault(repo, []).append({"source": "Hacker News", "title": h.get("title"), "points": h.get("points") or 0,
                                                   "date": (h.get("created_at") or "")[:10],
                                                   "link": f"https://news.ycombinator.com/item?id={h.get('objectID')}"})
    # github.com/trending blocks servers: its legitimate substitute is the official search API
    # (new repos of the period, sorted by stars).
    since_date = datetime.fromtimestamp(since, timezone.utc).strftime("%Y-%m-%d")
    for r in search(f"created:>{since_date} stars:>50")[:40]:
        found.setdefault(r["full_name"], []).append({"source": "GitHub (official search, substitute for Trending)",
                                                      "title": r.get("description") or r["full_name"], "points": r["stargazers_count"],
                                                      "date": r["created_at"][:10], "link": r["html_url"]})
    for h in _get_json("https://lobste.rs/hottest.json") or []:
        repo = _repo_from(h.get("url"))
        if repo:
            found.setdefault(repo, []).append({"source": "Lobsters", "title": h.get("title"), "points": h.get("score") or 0,
                                               "date": (h.get("created_at") or "")[:10], "link": h.get("short_id_url")})
    for a in _get_json("https://dev.to/api/articles?tag=opensource&top=7&per_page=60") or []:
        repo = _repo_from(a.get("url")) or _repo_from(a.get("description"))
        if repo:
            found.setdefault(repo, []).append({"source": "dev.to", "title": a.get("title"), "points": a.get("positive_reactions_count") or 0,
                                               "date": (a.get("published_at") or "")[:10], "link": a.get("url")})
    return found


# ---------- social: X and Reddit (where most repos get shared) ----------
# Both block anonymous servers. Allowed ways, each optional and with YOUR key (never scraping, never cookies):
#   FIRECRAWL_API_KEY  web search that indexes X and Reddit posts (site:x.com / site:reddit.com)
#   BRAVE_API_KEY      Brave Search API (free tier), same idea
#   REDDIT_CLIENT_ID + REDDIT_CLIENT_SECRET   official Reddit API (free "script" app for personal use)
#   X_BEARER_TOKEN     official X API (recent search needs a paid tier)
def _post_json(url, data, headers):
    try:
        req = urllib.request.Request(url, json.dumps(data).encode(), {**UA, "Content-Type": "application/json", **headers})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def _social_hit(source, title, url, text, date=""):
    item = {"source": source, "title": (title or "")[:160], "url": url or "", "points": 20, "date": date, "link": url or ""}
    NEWS_HITS.append(item)
    repo = _repo_from(text) or _repo_from(url)
    return repo, {k: item[k] for k in ("source", "title", "points", "date", "link")}


def social_mentions(topics, days=30):
    found, used = {}, []
    tbs = "qdr:m" if days <= 31 else "qdr:y"
    fk, bk = os.environ.get("FIRECRAWL_API_KEY"), os.environ.get("BRAVE_API_KEY")
    for q in topics[:3]:
        query = f"{q} github (site:x.com OR site:reddit.com)"
        rows = []
        if fk:
            d = _post_json("https://api.firecrawl.dev/v2/search", {"query": query, "limit": 15, "tbs": tbs},
                           {"Authorization": f"Bearer {fk}"}) or {}
            rows = [(w.get("title"), w.get("url"), (w.get("title") or "") + " " + (w.get("description") or ""))
                    for w in (d.get("data") or {}).get("web", [])]
            used.append("Firecrawl")
        elif bk:
            try:
                req = urllib.request.Request("https://api.search.brave.com/res/v1/web/search?count=20&freshness=pm&q="
                                             + urllib.parse.quote(query), headers={**UA, "X-Subscription-Token": bk})
                with urllib.request.urlopen(req, timeout=30) as r:
                    d = json.loads(r.read())
                rows = [(w.get("title"), w.get("url"), (w.get("title") or "") + " " + (w.get("description") or ""))
                        for w in (d.get("web") or {}).get("results", [])]
                used.append("Brave")
            except Exception:  # noqa: BLE001
                pass
        for title, url, text in rows:
            src = "X" if "x.com/" in (url or "") or "twitter.com/" in (url or "") else "Reddit" if "reddit.com/" in (url or "") else None
            if not src or not relevant({"title": text, "url": url or ""}):
                continue
            repo, m = _social_hit(src, title, url, text)
            if repo:
                found.setdefault(repo, []).append(m)
    rid, rsec = os.environ.get("REDDIT_CLIENT_ID"), os.environ.get("REDDIT_CLIENT_SECRET")
    if rid and rsec:
        try:
            import base64
            req = urllib.request.Request("https://www.reddit.com/api/v1/access_token", b"grant_type=client_credentials",
                                         {**UA, "Authorization": "Basic " + base64.b64encode(f"{rid}:{rsec}".encode()).decode()})
            with urllib.request.urlopen(req, timeout=30) as r:
                tok = json.loads(r.read())["access_token"]
            for q in topics[:3]:
                req = urllib.request.Request("https://oauth.reddit.com/search?sort=top&t=month&limit=50&q=" + urllib.parse.quote(q + " github"),
                                             headers={**UA, "Authorization": f"Bearer {tok}"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    for c in json.loads(r.read())["data"]["children"]:
                        p_ = c["data"]
                        text = (p_.get("title") or "") + " " + (p_.get("url") or "") + " " + (p_.get("selftext") or "")[:2000]
                        if not relevant({"title": text, "url": ""}): continue
                        repo, m = _social_hit("Reddit", p_.get("title"), "https://www.reddit.com" + p_.get("permalink", ""), text,
                                              datetime.fromtimestamp(p_.get("created_utc", 0), timezone.utc).strftime("%Y-%m-%d"))
                        m["points"] = p_.get("score") or 0
                        if repo: found.setdefault(repo, []).append(m)
            used.append("Reddit API")
        except Exception:  # noqa: BLE001
            pass
    xb = os.environ.get("X_BEARER_TOKEN")
    if xb:
        for q in topics[:2]:
            d = _get_json_auth("https://api.x.com/2/tweets/search/recent?max_results=50&tweet.fields=public_metrics,created_at,entities&query="
                               + urllib.parse.quote(f"{q} github.com -is:retweet"), xb)
            for t in (d or {}).get("data", []):
                urls = " ".join(u.get("expanded_url", "") for u in (t.get("entities") or {}).get("urls", []))
                repo, m = _social_hit("X", t.get("text"), f"https://x.com/i/status/{t['id']}", t.get("text", "") + " " + urls,
                                      (t.get("created_at") or "")[:10])
                m["points"] = sum((t.get("public_metrics") or {}).get(k, 0) for k in ("like_count", "retweet_count"))
                if repo: found.setdefault(repo, []).append(m)
        used.append("X API")
    return found, used


def _get_json_auth(url, token):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={**UA, "Authorization": f"Bearer {token}"}), timeout=30) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def lookup_repos(names):
    """GitHub metadata for repos found in the news (through the search API: repo:owner/name)."""
    out = []
    for i in range(0, len(names), 5):
        q = " ".join(f"repo:{n}" for n in names[i:i + 5])
        out += search(q)
        time.sleep(2.2)
    return out


def match_by_name(cand_names):
    """A news item mentions a repo if it links to github.com/owner/name, or its URL/title contains owner/name or a
    distinctive repo name (5+ chars, e.g. 'tiny-voca' on huggingface.co/n4ze3m/tiny-voca)."""
    out = {}
    for n in cand_names:
        owner, name = n.lower().split("/", 1)
        for h in NEWS_HITS:
            hay = (h["url"] + " " + h["title"]).lower()
            generic = all(t in NEWS_TERMS or t in STOP for t in re.split(r"[-_.]", name) if t)
            if f"{owner}/{name}" in hay or (len(name) >= 5 and not generic and re.search(rf"(?<![a-z0-9]){re.escape(name)}(?![a-z0-9])", hay)):
                m = {k: h[k] for k in ("source", "title", "points", "date", "link")}
                if m not in out.setdefault(n, []):
                    out[n].append(m)
    return out


def buzz(mentions):
    pts = sum(m["points"] for m in mentions)
    return min(1.0, math.log10(pts + 1) / 3)          # ~1000 points = max


# ---------- blockers: a filter for TODAY and THIS place, never a blacklist ----------
# Each blocker: words that show the repo needs it, and words that show it can work without it.
BLOCKERS = {
    "yt-dlp": (("yt-dlp", "youtube-dl", "yt_dlp"), ("without yt-dlp", "yt-dlp is optional", "optional: yt-dlp", "if yt-dlp is unavailable", "transcripts never require", "fallback")),
    "gpu": (("requires a gpu", "gpu required", "requires cuda", "cuda is required", "minimum vram", "nvidia gpu with"), ("cpu only", "runs on cpu", "on cpu", "cpu mode", "cpu or gpu", "cpu and gpu", "device cpu", "cpu inference")),
    "paid": (("openai_api_key", "api key required", "paid plan", "subscription required"), ("free tier", "local model", "offline")),
    "cookies": (("cookies-from-browser", "--cookies", "browser cookies", "cookies_from_browser"),
                ("optional", "if you need", "for private", "age-restricted", "members-only", "login-walled", "")),   # cookies are almost always an option: warn, do not set aside
    "docker": (("docker run", "docker compose", "docker-compose"), ("without docker", "pip install", "npm install")),
    "windows-only": (("windows only", "only works on windows"), ()),
    "mac-only": (("macos only", "only works on macos", "apple silicon only"), ()),
}


def check_blockers(txt, blockers):
    """Returns (hard, soft): blockers the repo NEEDS, and blockers it uses but can work without."""
    t, hard, soft = txt.lower(), [], []
    for b in blockers:
        needs, alt = BLOCKERS.get(b, ((b.lower(),), ()))
        if any(w in t for w in needs):
            (soft if (b == "cookies" or any(w in t for w in alt if w)) else hard).append(b)
    return hard, soft


def verify_blocker(b):
    """Tests whether a blocker is still real HERE, once, without bypassing anything. None = cannot be tested."""
    if b == "yt-dlp":
        import shutil, tempfile
        if not shutil.which("yt-dlp"):
            return None
        d = tempfile.mkdtemp()
        r = subprocess.run(["yt-dlp", "-q", "--no-warnings", "-f", "worst", "--download-sections", "*0-2", "-o", f"{d}/t.%(ext)s",
                            "https://www.youtube.com/watch?v=jNQXAC9IVRw"], capture_output=True, text=True, timeout=120)
        ok = r.returncode == 0 and any(Path(d).iterdir())
        shutil.rmtree(d, ignore_errors=True)
        return ok
    if b == "gpu":
        import shutil
        return bool(shutil.which("nvidia-smi")) and subprocess.run(["nvidia-smi"], capture_output=True).returncode == 0
    if b == "docker":
        import shutil
        return bool(shutil.which("docker"))
    return None


# Plan B for a blocker: a LEGITIMATE substitute that gives the same result another allowed way.
# Never proxies, cookies, captcha solvers or anything that tricks a site into letting you in (that is bypassing a block).
SUBSTITUTES = {
    "gpu": {"how": {"en": "use a CPU port of the same model (ONNX / C++), or rent a GPU per second only for that step",
                    "es": "usa una versión para CPU del mismo modelo (ONNX / C++), o renta una GPU por segundo solo para ese paso"},
            "search": ["{name} cpu", "{name} onnx", "{name} cpp"]},
    "paid": {"how": {"en": "swap the paid API for a free local model or a free tier", "es": "cambia la API de pago por un modelo local gratis o una capa gratuita"},
             "search": ["{name} local", "{name} ollama", "{name} offline"]},
    "docker": {"how": {"en": "install it natively (pip / npm) instead of Docker", "es": "instálalo directo (pip / npm) en vez de Docker"},
               "search": ["{name} pip", "{name} npm"]},
    "yt-dlp": {"how": {"en": "keep the repo and give it the video another allowed way: a file you upload, or run that step on a computer at home",
                       "es": "conserva el repo y dale el video por otro camino permitido: un archivo que tú subas, o corre ese paso en una computadora de tu casa"},
               "search": []},
    "cookies": {"how": {"en": "no substitute: using browser cookies to get past a site's bot check is bypassing a block",
                        "es": "sin sustituto: usar cookies del navegador para pasar el «no eres un bot» es saltarse un bloqueo"},
                "search": []},
}


def plan_b(blocked_rows, lang, limit=6):
    """For each blocked repo, a legitimate way to still use it, plus substitute repos when a search makes sense."""
    out = []
    for b in blocked_rows[:limit]:
        name = b["repo"].split("/")[1]
        name = re.sub(r"(?i)[-_]?(fastapi|webui|mcp|server|cli|app|studio)$", "", name) or name
        # the model/tool it is built on is a better search key than the repo name (e.g. "F5-TTS", "Qwen3-TTS", "kokoro")
        generic = re.compile(r"(?i)^(zero-shot|real-time|open-source|web-?ui|text-to-\w+|speech-to-\w+|end-to-end|state-of-the-art|"
                             r"multi-\w+|\d+[bkm]-?(parameter|param)s?|llm-based|\w+-based|gradio-\w+|high-\w+|low-\w+|one-click)$")
        bases = [t for t in re.findall(r"[A-Za-z][\w.]*\d[\w.-]*|[A-Za-z]+-[A-Za-z0-9]+", b.get("description", ""))
                 if len(t) >= 3 and t.lower() not in STOP and not generic.match(t)][:2] + [name]
        steps = []
        for blk in b["uses"]:
            sub = SUBSTITUTES.get(blk)
            if not sub:
                steps.append({"blocker": blk, "how": "-", "candidates": []}); continue
            cands = []
            for base, q in ([(base, sub["search"][i % len(sub["search"])].format(name=base)) for i, base in enumerate(bases[:2])]
                            if sub["search"] else []):
                for r in search(q)[:8]:
                    hay = (r["full_name"] + " " + (r.get("description") or "")).lower()
                    if base.lower().split("-")[0] not in hay:      # a substitute must be about the same model/tool
                        continue
                    if r["full_name"] != b["repo"] and not reject(r) and r["full_name"] not in [c["repo"] for c in cands]:
                        cands.append({"repo": r["full_name"], "url": r["html_url"], "stars": r["stargazers_count"],
                                      "description": (r.get("description") or "")[:100]})
                time.sleep(2.2)
            steps.append({"blocker": blk, "how": sub["how"].get(lang, sub["how"]["en"]),
                          "candidates": sorted(cands, key=lambda c: -c["stars"])[:2]})
        out.append({"repo": b["repo"], "steps": steps})
    return out


# ---------- scoring ----------
def reject(r):
    if r.get("archived"): return "archived"
    if r.get("fork"): return "fork"
    if "awesome" in r["full_name"].lower(): return "awesome list"
    if not r.get("language"): return "no code"
    if not r.get("description"): return "no description"
    if days(r["pushed_at"]) > 540: return "dead"
    if r["stargazers_count"] < 5 and days(r["created_at"]) > 180: return "toy"
    return None


def score(r, terms, sig, judge, verdicts):
    text = set(words(r["full_name"].replace("/", " ").replace("-", " ") + " " + (r.get("description") or "") + " "
                     + " ".join(r.get("topics") or [])))
    meta = sum(1 for t in terms if t in text or any(t in w for w in text)) / max(1, len(terms))
    rel = 0.6 * meta + 0.4 * sig.get("readme_relevance", meta) if sig else meta
    pop = min(1, math.log10(r["stargazers_count"] + 1) / 4.5)
    act = max(0, 1 - days(r["pushed_at"]) / 365)
    health = (0.4 * sig.get("install", 0) + 0.3 * sig.get("demo", 0) + 0.3 * sig.get("tests", 0)) if sig else 0.3
    lic = ((r.get("license") or {}).get("spdx_id") or "").lower()
    plic = 1 if lic in PERMISSIVE else 0.6 if lic in COPYLEFT else 0.2 if lic and lic != "noassertion" else 0
    pj = (judge["score"] / 10) if judge else rel
    return round(35 * rel + 15 * pj + 15 * pop + 15 * act + 10 * health + 10 * plic + verdicts.get(r["full_name"], {}).get("shift", 0)), lic


def warnings(r, lic, s, w):
    a = []
    if not lic or lic == "noassertion": a.append(w["nolic"])
    elif lic in COPYLEFT: a.append(w["copyleft"])
    elif "nc" in lic: a.append(w["nc"])
    if s.get("gpu"): a.append(w["gpu"])
    if s.get("paid"): a.append(w["paid"])
    if s.get("agent"): a.append(w["agent"])
    age = max(1, days(r["created_at"]))
    if age < 60: a.append(w["new"])
    if r["stargazers_count"] / age > 20: a.append(f"{w['hot']} ({round(r['stargazers_count'] / age)}⭐/{L['en']['days']})")
    if age < 30 and r["stargazers_count"] / age > 40:
        a.append("⚠️ stars grew very fast: sometimes fake (star farms) or malware bait, check it carefully")
    return a


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("need", nargs="?", help="what you want to do, in any language")
    ap.add_argument("--queries", nargs="+", help="your own GitHub queries (skips the automatic ones)")
    ap.add_argument("--top", type=int, default=15)
    ap.add_argument("--lang", help="output language (en, es, pt...; default: the language of the need)")
    ap.add_argument("--profile", default=str(DATA / "profile.json"), help="JSON with who you are, your hardware and rules")
    ap.add_argument("--no-judge", action="store_true", help="skip the Gemini judge")
    ap.add_argument("--cpu", action="store_true", help="only repos that do not need a GPU")
    ap.add_argument("--free", action="store_true", help="only repos that do not need a paid API")
    ap.add_argument("--commercial", action="store_true", help="only permissive licenses (MIT, Apache, BSD...)")
    ap.add_argument("--where", help="named place profile: data/profiles/<name>.json (e.g. cloud, laptop)")
    ap.add_argument("--blockers", nargs="+", default=[], help="what does NOT work where you are today: yt-dlp gpu paid cookies docker windows-only mac-only (or any word)")
    ap.add_argument("--verify", action="store_true", help="test each blocker first; if it works now, it is dropped")
    ap.add_argument("--news", action="store_true", help="also look in the news (Hacker News, Lobsters, dev.to) for repos people talk about")
    ap.add_argument("--trending", action="store_true", help="repos of the moment (last 7 days of news), checked against your profile")
    ap.add_argument("--days", type=int, default=120, help="how far back to read the news (default 120; --trending uses 7)")
    ap.add_argument("--md", help="save the table as Markdown")
    ap.add_argument("--json", action="store_true", help="machine-readable output for agents")
    ap.add_argument("--verdict", nargs="+", metavar=("REPO", "good|bad"))
    ap.add_argument("--history", action="store_true")
    a = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)
    index = load(INDEX, {"searches": [], "verdicts": {}})

    if a.verdict:
        repo, v = a.verdict[0], (a.verdict[1] if len(a.verdict) > 1 else "good").lower()
        good = v in ("good", "bueno", "bom", "👍")
        index["verdicts"][repo] = {"verdict": "good" if good else "bad", "note": " ".join(a.verdict[2:]),
                                   "shift": 8 if good else -15, "date": f"{datetime.now():%Y-%m-%d}"}
        INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1)); print(f"Saved: {repo} = {index['verdicts'][repo]['verdict']}"); return
    only_trending = a.trending and not a.need
    if only_trending:
        a.need = "the best and most talked-about new open-source repos of the moment"
    if a.history or not a.need:
        print(json.dumps(index, ensure_ascii=False, indent=1)); return

    if a.where:
        own, ex = DATA / "profiles" / f"{a.where}.json", HERE / "profiles" / f"{a.where}.json"
        a.profile = str(own if own.exists() else ex)
    prof_data = load(a.profile, {}) if a.profile else {}
    blockers = list(dict.fromkeys([b.lower() for b in a.blockers] + [b.lower() for b in prof_data.get("blockers", [])]))
    queries, keys, origin, glang = ((a.queries, [], "yours", None) if a.queries else
                                    ([], [], "news only", None) if only_trending else plan_queries(a.need))
    lang = (a.lang or glang or guess_lang(a.need)).lower()[:2]
    T = L.get(lang, L["en"])
    notes = []
    if a.verify:
        for b in list(blockers):
            ok = verify_blocker(b)
            if ok is True:
                blockers.remove(b); notes.append(T["verified_ok"].format(b=b))
            elif ok is False:
                notes.append(T["verified_bad"].format(b=b))
    terms = list(dict.fromkeys(words(a.need + " " + " ".join(queries) + " " + " ".join(keys))))
    print(f"{T['queries']} ({origin}): {queries}", file=sys.stderr)
    cand, dropped = {}, {}
    for i, q in enumerate(queries):
        if i: time.sleep(2.2)
        for r in search(q):
            n = r["full_name"]
            if n in cand or n in dropped: continue
            why = reject(r)
            (dropped.__setitem__(n, why) if why else cand.__setitem__(n, r))
    mentions = {}
    GENERIC = {"open", "source", "fast", "free", "english", "model", "models", "tool", "best", "new", "simple", "local",
               "python", "code", "library", "app", "web", "api", "github", "repo", "easy", "cpu", "gpu", "real", "time"}
    NEWS_TERMS.update(t for t in words(" ".join(queries) + " " + " ".join(keys)) if len(t) >= 3 and t not in GENERIC)
    if a.news or a.trending:
        mentions = trending_news(min(a.days, 7) if a.trending and not a.news else a.days) if a.trending else news_mentions(queries[:4], a.days)
        social, used = social_mentions(queries or [a.need], a.days)
        for k, v in social.items():
            mentions.setdefault(k, []).extend(v)
        notes.append(("X/Reddit: " + ", ".join(used)) if used else
                     {"es": "X/Reddit: sin acceso (bloquean servidores). Para leerlos, pon FIRECRAWL_API_KEY o BRAVE_API_KEY, o las claves oficiales de Reddit/X",
                      "pt": "X/Reddit: sem acesso (bloqueiam servidores). Defina FIRECRAWL_API_KEY ou BRAVE_API_KEY, ou as chaves oficiais"}.get(
                         lang, "X/Reddit: no access (they block servers). Set FIRECRAWL_API_KEY or BRAVE_API_KEY, or the official Reddit/X keys"))
        top_news = sorted(mentions, key=lambda n: -sum(m["points"] for m in mentions[n]))[:25]
        known = {n.lower() for n in cand} | {n.lower() for n in dropped}
        for r in lookup_repos([n for n in top_news if n.lower() not in known]):
            if r["full_name"] in cand or r["full_name"] in dropped: continue
            why = reject(r)
            (dropped.__setitem__(r["full_name"], why) if why else cand.__setitem__(r["full_name"], r))
        low = {k.lower(): v for k, v in mentions.items()}
        by_name = match_by_name(list(cand))
        mentions = {n: low.get(n.lower(), []) + [m for m in by_name.get(n, []) if m not in low.get(n.lower(), [])]
                    for n in cand if n.lower() in low or n in by_name}
    first = sorted(cand.values(), key=lambda r: -(score(r, terms, None, None, index["verdicts"])[0]
                                                  + 40 * buzz(mentions.get(r["full_name"], []))))[:25]
    sig = {}
    for r in first:
        txt = readme(r["full_name"])
        sig[r["full_name"]] = dict(readme_signals(txt, terms), _text=txt[:200_000])
    judge = {}
    if not a.no_judge and first:
        top10 = sorted(first, key=lambda r: -score(r, terms, sig[r["full_name"]], None, index["verdicts"])[0])[:10]
        prof = dict(prof_data, blockers_today=blockers) if blockers else prof_data
        g = gemini_json("You choose GitHub repos for ONE specific person. Need: «" + a.need + "». "
                        + (f"Their profile (hardware, rules, what they already have): {json.dumps(prof, ensure_ascii=False)}. " if prof else "")
                        + "Rate 0-10 how well each repo works as the base for THIS need and THIS person (not its fame; lower the "
                        "score if it does not fit their hardware, costs money or duplicates what they have). Write each reason as one "
                        f"short sentence in the language with ISO code '{lang}'. Return JSON {{\"repos\": [{{\"repo\": \"owner/name\", "
                        "\"score\": 0-10, \"reason\": \"...\"}]}.\n" + "\n".join(f"- {r['full_name']}: {r.get('description')}" for r in top10))
        for x in (g or {}).get("repos", []):
            if isinstance(x, dict) and x.get("repo") in sig:
                judge[x["repo"]] = {"score": float(x.get("score", 5)), "reason": x.get("reason", "")}
    rows, blocked = [], []
    texts = {}
    prev = {}
    for h in index.get("blocked", []):
        prev.setdefault(h["repo"], h)
    for r in first:
        s = sig[r["full_name"]]
        hard, soft = check_blockers(texts.get(r["full_name"], "") or s.get("_text", ""), blockers) if blockers else ([], [])
        if hard:
            blocked.append({"repo": r["full_name"], "url": r["html_url"], "uses": hard, "stars": r["stargazers_count"],
                            "description": (r.get("description") or "")[:120]})
            continue
        pts, lic = score(r, terms, s, judge.get(r["full_name"]), index["verdicts"])
        if (a.cpu and s.get("gpu")) or (a.free and s.get("paid")) or (a.commercial and lic not in PERMISSIVE):
            continue
        if r["full_name"] in mentions:
            pts += round(8 * buzz(mentions[r["full_name"]]))
        pts = max(0, min(100, pts))
        rows.append({"repo": r["full_name"], "url": r["html_url"], "score": pts,
                     "tier": T["tiers"][0] if pts >= 70 else T["tiers"][1] if pts >= 55 else T["tiers"][2],
                     "stars": r["stargazers_count"], "language": r.get("language"), "license": lic or "none",
                     "updated_days_ago": days(r["pushed_at"]), "description": (r.get("description") or "")[:150],
                     "judge": judge.get(r["full_name"]), "warnings": warnings(r, lic, s, T["w"]),
                     "verdict": index["verdicts"].get(r["full_name"], {}).get("verdict"), "signals": {k: v for k, v in s.items() if k != "_text"}})
        if r["full_name"] in mentions:
            ms = sorted(mentions[r["full_name"]], key=lambda m: -m["points"])
            rows[-1]["news"] = ms[:3]
            rows[-1]["warnings"].append(f"📰 {ms[0]['source']} {ms[0]['points']} pts ({ms[0]['date']})")
        if soft:
            rows[-1]["warnings"].append(f"{T['partial']} {', '.join(soft)}, {T['loses']}"
                                        + (" (" + {"es": "no actives su opción de cookies", "pt": "não ative a opção de cookies"}.get(lang, "do not turn on its cookies option") + ")" if "cookies" in soft else ""))
        if r["full_name"] in prev and not hard:
            rows[-1]["warnings"].append(f"ℹ️ {T['was_blocked']} {prev[r['full_name']]['date']} ({', '.join(prev[r['full_name']]['uses'])}); {T['now_ok']}")
    rows.sort(key=lambda x: -x["score"]); rows = rows[:a.top]
    picks = {"best": rows[0]["repo"] if rows else None,
             "best_free_cpu": next((x["repo"] for x in rows if not x["signals"]["gpu"] and not x["signals"]["paid"]
                                    and x["license"] in PERMISSIVE), None),
             "rising": next((x["repo"] for x in rows if any(v.startswith(("🆕", "🔥")) for v in x["warnings"])), None)}
    plans = plan_b(blocked, lang) if blocked else []
    hoy = f"{datetime.now():%Y-%m-%d}"
    index["searches"].append({"date": f"{datetime.now():%Y-%m-%d %H:%M}", "need": a.need, "lang": lang, "queries": queries,
                              "where": a.where, "blockers": blockers, "top": [x["repo"] for x in rows[:5]], "picks": picks})
    index.setdefault("blocked", [])
    for b in blocked:
        index["blocked"].insert(0, {"date": hoy, "repo": b["repo"], "uses": b["uses"], "where": a.where or "-"})
    index["blocked"] = index["blocked"][:500]
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    if a.json:
        print(json.dumps({"need": a.need, "lang": lang, "candidates": len(cand) + len(dropped), "dropped": len(dropped),
                          "picks": picks, "ranking": rows,
                          "blockers": blockers, "notes": notes, "blocked_today": blocked, "plan_b": plans,
                          "news_outside_github": sorted(NEWS_HITS, key=lambda h: -h["points"])[:15]}, ensure_ascii=False, indent=1)); return
    out = [f"# {T['title']}: {a.need}", f"{len(cand) + len(dropped)} {T['cand']} · {len(dropped)} {T['drop']} · "
           f"{len(first)} {T['read']} · {T['judge']}: {'Gemini' if judge else '—'} · {datetime.now():%Y-%m-%d}", "",
           f"**{T['best']}:** {picks['best'] or '—'} · **{T['free']}:** {picks['best_free_cpu'] or '—'} · **{T['rising']}:** {picks['rising'] or '—'}", "",
           T["cols"], "|---|---|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate(rows, 1):
        j = f"{x['judge']['score']:.0f}/10 {x['judge']['reason']}" if x["judge"] else ""
        out.append(f"| {i} | [{x['repo']}]({x['url']}) | {x['score']} | {x['tier']} | {x['stars']} | {x['license']} | "
                   f"{x['updated_days_ago']} {T['days']} | {x['description'].replace('|', '/')} | {j.replace('|', '/')} | {' '.join(x['warnings'])} |")
    if notes:
        out[2:2] = [" · ".join(notes), ""]
    linked = {m["link"] for ms in mentions.values() for m in ms}
    other = sorted([h for h in NEWS_HITS if h["link"] not in linked and h["points"] >= 5], key=lambda h: -h["points"])[:10]
    if other:
        out += ["", "## 📰 " + {"es": "También en las noticias (fuera de GitHub o sin repo claro)", "pt": "Também nas notícias (fora do GitHub)"}.get(lang, "Also in the news (outside GitHub or no clear repo)")]
        out += [f"- {h['points']} pts · {h['date']} · [{h['title']}]({h['url'] or h['link']}) ([HN]({h['link']}))" for h in other]
    if blocked:
        out += ["", f"## {T['blocked']}" + (f" ({T['where']}: {a.where})" if a.where else "")]
        out += [f"- [{b['repo']}]({b['url']}) ({b['stars']}⭐) — {T['because']} **{', '.join(b['uses'])}** — {b['description'].replace('|', '/')}" for b in blocked]
    if plans:
        out += ["", "## 🔁 " + {"es": "Plan B: cómo usarlos de todas formas (solo caminos permitidos)",
                                 "pt": "Plano B: como usá-los mesmo assim (só caminhos permitidos)"}.get(lang, "Plan B: how to use them anyway (allowed ways only)")]
        for pl in plans:
            for st in pl["steps"]:
                alt = "; ".join(f"[{c['repo']}]({c['url']}) ({c['stars']}⭐)" for c in st["candidates"])
                out.append(f"- **{pl['repo']}** · {st['blocker']}: {st['how']}" + (f" → {alt}" if alt else ""))
    text = "\n".join(out)
    if a.md: Path(a.md).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
