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
                   paid="💳 paid API", agent="🤖 agent-ready", new="🆕 new", hot="🔥 trending")),
 "es": dict(title="Mejores repos para", cand="candidatos", drop="descartados", read="READMEs leídos", judge="juez", best="El mejor",
            free="Mejor gratis sin GPU", rising="Promesa nueva", cols="| # | Repo | Puntos | Nivel | ⭐ | Licencia | Cambió | Qué es | Juez | Avisos |",
            tiers=("Usar ya", "Adaptar", "Estudiar"), days="d", queries="Búsquedas", saved="Guardado",
            w=dict(nolic="⚠️ sin licencia clara", copyleft="ℹ️ copyleft", nc="⚠️ no comercial", gpu="🎮 necesita GPU",
                   paid="💳 API de pago", agent="🤖 hecho para agentes", new="🆕 muy nuevo", hot="🔥 en tendencia")),
 "pt": dict(title="Melhores repos para", cand="candidatos", drop="descartados", read="READMEs lidos", judge="juiz", best="O melhor",
            free="Melhor grátis sem GPU", rising="Promessa nova", cols="| # | Repo | Pontos | Nível | ⭐ | Licença | Atualizado | O que é | Juiz | Avisos |",
            tiers=("Usar já", "Adaptar", "Estudar"), days="d", queries="Buscas", saved="Salvo",
            w=dict(nolic="⚠️ sem licença clara", copyleft="ℹ️ copyleft", nc="⚠️ não comercial", gpu="🎮 precisa de GPU",
                   paid="💳 API paga", agent="🤖 feito para agentes", new="🆕 muito novo", hot="🔥 em alta")),
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
    if any(w in t for w in (" hacer ", " quiero ", " para ", " videos ", " con ", " ñ", "ción")): return "es"
    if any(w in t for w in (" fazer ", " quero ", " ção", " vídeos ", " com ")): return "pt"
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
    if a.history or not a.need:
        print(json.dumps(index, ensure_ascii=False, indent=1)); return

    queries, keys, origin, glang = (a.queries, [], "yours", None) if a.queries else plan_queries(a.need)
    lang = (a.lang or glang or guess_lang(a.need)).lower()[:2]
    T = L.get(lang, L["en"])
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
    first = sorted(cand.values(), key=lambda r: -score(r, terms, None, None, index["verdicts"])[0])[:25]
    sig = {r["full_name"]: readme_signals(readme(r["full_name"]), terms) for r in first}
    judge = {}
    if not a.no_judge and first:
        top10 = sorted(first, key=lambda r: -score(r, terms, sig[r["full_name"]], None, index["verdicts"])[0])[:10]
        prof = load(a.profile, {}) if a.profile else {}
        g = gemini_json("You choose GitHub repos for ONE specific person. Need: «" + a.need + "». "
                        + (f"Their profile (hardware, rules, what they already have): {json.dumps(prof, ensure_ascii=False)}. " if prof else "")
                        + "Rate 0-10 how well each repo works as the base for THIS need and THIS person (not its fame; lower the "
                        "score if it does not fit their hardware, costs money or duplicates what they have). Write each reason as one "
                        f"short sentence in the language with ISO code '{lang}'. Return JSON {{\"repos\": [{{\"repo\": \"owner/name\", "
                        "\"score\": 0-10, \"reason\": \"...\"}]}.\n" + "\n".join(f"- {r['full_name']}: {r.get('description')}" for r in top10))
        for x in (g or {}).get("repos", []):
            if isinstance(x, dict) and x.get("repo") in sig:
                judge[x["repo"]] = {"score": float(x.get("score", 5)), "reason": x.get("reason", "")}
    rows = []
    for r in first:
        s = sig[r["full_name"]]
        pts, lic = score(r, terms, s, judge.get(r["full_name"]), index["verdicts"])
        if (a.cpu and s.get("gpu")) or (a.free and s.get("paid")) or (a.commercial and lic not in PERMISSIVE):
            continue
        pts = max(0, min(100, pts))
        rows.append({"repo": r["full_name"], "url": r["html_url"], "score": pts,
                     "tier": T["tiers"][0] if pts >= 70 else T["tiers"][1] if pts >= 55 else T["tiers"][2],
                     "stars": r["stargazers_count"], "language": r.get("language"), "license": lic or "none",
                     "updated_days_ago": days(r["pushed_at"]), "description": (r.get("description") or "")[:150],
                     "judge": judge.get(r["full_name"]), "warnings": warnings(r, lic, s, T["w"]),
                     "verdict": index["verdicts"].get(r["full_name"], {}).get("verdict"), "signals": s})
    rows.sort(key=lambda x: -x["score"]); rows = rows[:a.top]
    picks = {"best": rows[0]["repo"] if rows else None,
             "best_free_cpu": next((x["repo"] for x in rows if not x["signals"]["gpu"] and not x["signals"]["paid"]
                                    and x["license"] in PERMISSIVE), None),
             "rising": next((x["repo"] for x in rows if any(v.startswith(("🆕", "🔥")) for v in x["warnings"])), None)}
    index["searches"].append({"date": f"{datetime.now():%Y-%m-%d %H:%M}", "need": a.need, "lang": lang, "queries": queries,
                              "top": [x["repo"] for x in rows[:5]], "picks": picks})
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1))
    if a.json:
        print(json.dumps({"need": a.need, "lang": lang, "candidates": len(cand) + len(dropped), "dropped": len(dropped),
                          "picks": picks, "ranking": rows}, ensure_ascii=False, indent=1)); return
    out = [f"# {T['title']}: {a.need}", f"{len(cand) + len(dropped)} {T['cand']} · {len(dropped)} {T['drop']} · "
           f"{len(first)} {T['read']} · {T['judge']}: {'Gemini' if judge else '—'} · {datetime.now():%Y-%m-%d}", "",
           f"**{T['best']}:** {picks['best'] or '—'} · **{T['free']}:** {picks['best_free_cpu'] or '—'} · **{T['rising']}:** {picks['rising'] or '—'}", "",
           T["cols"], "|---|---|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate(rows, 1):
        j = f"{x['judge']['score']:.0f}/10 {x['judge']['reason']}" if x["judge"] else ""
        out.append(f"| {i} | [{x['repo']}]({x['url']}) | {x['score']} | {x['tier']} | {x['stars']} | {x['license']} | "
                   f"{x['updated_days_ago']} {T['days']} | {x['description'].replace('|', '/')} | {j.replace('|', '/')} | {' '.join(x['warnings'])} |")
    text = "\n".join(out)
    if a.md: Path(a.md).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
