#!/usr/bin/env python3
"""kit.py — a complete KIT for ANY goal: the repos, connectors and skills it needs (and only those), checked to work.

Same file in RepoSommelier, MCPSommelier and SkillSommelier: run it from any of them, it uses the three finders that
sit next to each other (../reposommelier, ../mcpsommelier, ../skillsommelier).

    python3 kit.py "quiero hacer videos animados gratis con IA y publicarlos en YouTube para monetizarlos"
    python3 kit.py "responder automáticamente los correos de mis clientes con IA" --where cloud
    python3 kit.py "track my competitors' prices every day and alert me on Telegram" --json

How it works
 1. PLAN: Gemini reads the goal (any language, any topic) and splits it into steps. For each step it says what is needed:
      📦 repo (software that must run) · 🔌 connector (an outside service or account) ·
      🎓 skill (know-how that makes the agent do it better) · 🤖 nothing (the AI does it by itself).
    It also reads your conditions: free? will you make money with it (commercial use)? where does it run?
 2. SEARCH THE WHOLE WEB, not only what you have: each finder searches its registries (GitHub, the official MCP
    Registry, skills.sh, SkillsMP…). Connectors compete on equal terms (--fair): yours only keep the ✅ mark.
 3. CHECK THAT IT WORKS before recommending it:
      🔌 hosted connector → its server answers an MCP handshake · npm/PyPI connector → the package exists ·
      📦 repo / 🎓 skill → the repo exists, is not archived and was updated in the last 2 years.
    Dead ones are dropped; unverifiable ones are marked ⚠️ and go after the verified ones.
 4. FILTER by your conditions: free → paid things only as an optional line · monetize → non-commercial licenses ⛔.
 5. FIT CHECK: one Gemini call drops picks that do not really serve their step.
 6. OUTPUT: 🥇 the best COMBINATION per step first (e.g. repo + skill, or connector alone, or 🤖 nothing),
    then one table for 📦 repos, one for 🎓 skills and one for 🔌 connectors.
Read-only: it never installs or runs what it finds.
"""
import argparse, itertools, json, os, re, subprocess, sys, time, urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FINDERS = {"repo": ROOT / "reposommelier" / "reposommelier.py",
           "connector": ROOT / "mcpsommelier" / "mcpsommelier.py",
           "skill": ROOT / "skillsommelier" / "skillsommelier.py"}
ICON = {"repo": "📦", "connector": "🔌", "skill": "🎓", "ai": "🤖"}
NC = re.compile(r"cc[- ]by[- ]nc|non[- ]?commercial|no comercial|não comercial|research (use )?only|for research purposes only|"
                r"not for commercial|personal use only", re.I)
PERMISSIVE = {"mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "isc", "mpl-2.0", "unlicense", "0bsd", "zlib",
              "lgpl-2.1", "lgpl-3.0", "gpl-2.0", "gpl-3.0", "agpl-3.0", "cc0-1.0"}   # all allow commercial USE
T = {
    "es": {"title": "Tu kit para", "cond": "Condiciones", "free": "gratis", "money": "para monetizar (uso comercial)",
           "where": "donde corre", "ai": "🤖 lo hace la IA sola", "none": "—", "backup": "Respaldo", "best": "Mejor",
           "paid": "💳 de paga (opcional)", "nc": "⛔ licencia NO comercial", "check": "⚠️ revisa la licencia",
           "have": "✅ ya lo tienes", "steps": "Pasos", "close": "⚠️ lo más cercano", "combo": "🥇 Combinación recomendada (primer lugar)",
           "repos": "📦 Repos", "skills": "🎓 Skills", "conns": "🔌 Conectores", "step": "Paso", "why": "Por qué",
           "ok": "✔ verificado", "unver": "⚠️ sin verificar", "dead": "descartados porque no funcionan", "pts": "Puntos",
           "mine": "Tuyo", "newbest": "Mejor (de toda la red)", "install": "Cómo empezar"},
    "en": {"title": "Your kit for", "cond": "Conditions", "free": "free", "money": "to monetize (commercial use)",
           "where": "runs on", "ai": "🤖 the AI does it alone", "none": "—", "backup": "Backup", "best": "Best",
           "paid": "💳 paid (optional)", "nc": "⛔ NON-commercial license", "check": "⚠️ check the license",
           "have": "✅ you have it", "steps": "Steps", "close": "⚠️ closest match", "combo": "🥇 Recommended combination (first place)",
           "repos": "📦 Repos", "skills": "🎓 Skills", "conns": "🔌 Connectors", "step": "Step", "why": "Why",
           "ok": "✔ verified", "unver": "⚠️ not verified", "dead": "dropped because they do not work", "pts": "Points",
           "mine": "Yours", "newbest": "Best (whole web)", "install": "How to start"},
    "pt": {"title": "Seu kit para", "cond": "Condições", "free": "grátis", "money": "para monetizar (uso comercial)",
           "where": "onde roda", "ai": "🤖 a IA faz sozinha", "none": "—", "backup": "Reserva", "best": "Melhor",
           "paid": "💳 pago (opcional)", "nc": "⛔ licença NÃO comercial", "check": "⚠️ confira a licença",
           "have": "✅ você já tem", "steps": "Passos", "close": "⚠️ o mais próximo", "combo": "🥇 Combinação recomendada (primeiro lugar)",
           "repos": "📦 Repos", "skills": "🎓 Skills", "conns": "🔌 Conectores", "step": "Passo", "why": "Por quê",
           "ok": "✔ verificado", "unver": "⚠️ não verificado", "dead": "descartados porque não funcionam", "pts": "Pontos",
           "mine": "Seu", "newbest": "Melhor (toda a rede)", "install": "Como começar"},
}


# ---------- Gemini ----------
def _gemini_key():
    if os.environ.get("GEMINI_API_KEY"): return os.environ["GEMINI_API_KEY"]
    env = Path.home() / ".config/watch/.env"
    for line in (env.read_text().splitlines() if env.exists() else []):
        if line.startswith("GEMINI_API_KEY="): return line.split("=", 1)[1].strip().strip('"')
    return "proxy-injected"


def gemini_json(prompt):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}).encode()
    for attempt, model in enumerate(os.environ.get("KIT_MODELS", "gemini-3-flash-preview,gemini-flash-latest,gemini-3-flash-preview,gemini-flash-latest").split(",")):
        if attempt: time.sleep(4 * attempt)               # busy or out of quota for a moment: wait and try again
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent",
                                     body, {"Content-Type": "application/json", "x-goog-api-key": _gemini_key()})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"])
        except Exception:
            continue
    return None


# ---------- 1. plan ----------
def guess(goal):
    g = " " + (goal or "").lower() + " "
    lang = "pt" if re.search(r"[ãõç]| você | não ", g) else "es" if re.search(r"[ñ¿¡]| quiero | para | hacer | mis? ", g) else "en"
    free = bool(re.search(r"\bgratis\b|\bgratuit|\bfree\b|\bgrátis\b|sin pagar|without paying|sem pagar", g))
    money = bool(re.search(r"monetiz|vender|sell|ganar dinero|make money|ganhar dinheiro|clientes|clients|comercial|commercial|negocio|business", g))
    return lang, free, money


def plan(goal):
    lang, free, money = guess(goal)
    p = gemini_json(
        "Plan the tools for this goal (any language, any topic). Split it into 2-7 concrete steps in order. For EACH step "
        "choose ONLY what is really needed. Use an EMPTY list when an AI assistant can do the step by itself with no extra "
        "tool (writing, ideas, summaries, titles). \"repo\" = open-source software that must run; \"connector\" = an outside "
        "service or account the agent must reach (send email, publish, read a calendar, a store, a chat app…); \"skill\" = "
        "know-how that clearly makes an AI agent do the step better. Give each step a 2-5 word ENGLISH search query. Read "
        "the conditions too. Return JSON {\"lang\": ISO 639-1 of the goal, \"free\": bool, \"commercial\": bool (they will "
        "make money with the result), \"steps\": [{\"step\": short name in the goal's language, \"query\": \"english words\", "
        "\"kinds\": [\"repo\"|\"connector\"|\"skill\"], \"why\": one short sentence in the goal's language}]}. Goal: " + goal)
    if p and p.get("steps"):
        return p.get("lang") or lang, bool(p.get("free")) or free, bool(p.get("commercial")) or money, p["steps"][:7]
    parts = [x.strip(" .") for x in re.split(r",|;|\by luego\b|\by después\b|\bthen\b|\by que\b|\by\b|\band\b|\be\b", goal) if len(x.strip()) > 8]
    return lang, free, money, [{"step": x[:60], "query": " ".join(re.findall(r"\w{4,}", x)[:5]), "kinds": ["repo", "connector", "skill"],
                                "why": ""} for x in (parts or [goal])[:6]]


# ---------- 2. search ----------
def run_finder(kind, query, where, free, inventory=None, top=5):
    f = FINDERS[kind]
    if not f.exists():
        return {"missing": str(f)}
    cmd = [sys.executable, str(f), query, "--json", "--no-judge", "--top", str(top)]
    if where: cmd += ["--where", where]
    if kind == "repo" and free: cmd += ["--free"]
    if kind == "skill": cmd += ["--no-family"]
    if kind == "connector":
        cmd += ["--fair"]                                     # the whole web competes; yours only keep the ✅ mark
        if inventory and Path(inventory).exists(): cmd += ["--inventory", inventory]
    try:
        return json.loads(subprocess.run(cmd, capture_output=True, text=True, timeout=900).stdout)
    except Exception as e:
        return {"error": str(e)[:200]}


def normalize(kind, out):
    items = []
    if kind == "repo":
        for r in out.get("ranking", []):
            items.append({"name": r["repo"], "url": r["url"], "score": r["score"], "desc": r.get("description", ""),
                          "how": f"git clone {r['url']}", "have": False, "paid": bool((r.get("signals") or {}).get("paid")),
                          "lic": r.get("license"), "stars": r.get("stars"), "repo": r["repo"]})
    elif kind == "connector":
        for c in out.get("ranking", []) + [dict(p, paid=True) for p in out.get("paid", [])]:
            gh = re.search(r"github\.com/([\w.-]+/[\w.-]+)", c.get("repo_url") or c.get("url") or "")
            items.append({"name": c.get("title") or c["name"], "id": c["name"], "url": c.get("url"), "score": c["score"],
                          "desc": c.get("what", ""), "have": bool(c.get("have")), "paid": bool(c.get("paid")), "kind": c.get("kind"),
                          "endpoint": c.get("endpoint", ""), "packages": c.get("packages", []),
                          "repo": gh.group(1).removesuffix(".git") if gh else None,
                          "how": "✅" if c.get("have") else (f"claude.ai → Conectores → {c['endpoint']}" if c.get("endpoint")
                                                              else c.get("setup", ""))})
    else:
        for s in out.get("results", []) + out.get("needs_extra", []):
            items.append({"name": f"{s['repo']}/{s['skill']}", "url": f"https://github.com/{s['repo']}", "score": s["pts"],
                          "desc": s.get("description", ""), "how": s["install"], "have": s.get("have"),
                          "paid": "paid_key" in s.get("needs", []), "repo": s["repo"]})
    return items


# ---------- 3. check that it works ----------
def _http(url, data=None, headers=None, timeout=15):
    try:
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "kit.py", **(headers or {})}, method="POST" if data else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return None


def repo_alive(full):
    """The repo exists and still has its README/SKILL (raw files: no API rate limit). Archived repos say so in GitHub's banner."""
    codes = []
    for br in ("main", "master"):
        for f in ("README.md", "readme.md", "SKILL.md", "README.rst"):
            st = _http(f"https://raw.githubusercontent.com/{full}/{br}/{f}")
            if st == 200:
                return True
            codes.append(st)
    return False if codes and all(c == 404 for c in codes) else None


def verify(kind, it):
    """True = works, False = broken, None = could not check."""
    if it.get("have"):
        return True
    if kind == "connector":
        if it.get("endpoint"):
            st = _http(it["endpoint"], json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "kit-check", "version": "1"}}}).encode(),
                {"content-type": "application/json", "accept": "application/json, text/event-stream"})
            if st in (200, 202, 400, 401, 403, 405, 406, 415): return True      # the server is there (maybe asks for login)
            if st in (404, 410) or (st and st >= 500) or st is None: return False
        for p in it.get("packages", []):
            if p.get("type") == "npm":
                return _http(f"https://registry.npmjs.org/{p['id']}") == 200
            if p.get("type") == "pypi":
                return _http(f"https://pypi.org/pypi/{p['id']}/json") == 200
        if it.get("repo"):
            return repo_alive(it["repo"])
        return None
    return repo_alive(it["repo"]) if it.get("repo") else None


def license_flag(repo, spdx):
    txt = ""
    for name in ("LICENSE", "LICENSE.md", "README.md"):
        for br in ("main", "master"):
            try:
                txt += urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{br}/{name}", timeout=15).read(60000).decode("utf-8", "ignore")
                break
            except Exception:
                continue
    if NC.search(txt): return "nc"
    return "" if (spdx or "").lower() in PERMISSIVE else "check"


def choose(kind, items, free, money, minimum):
    """Verified, condition-aware, best-first. Returns ok list, paid list, dead names."""
    items = sorted(items, key=lambda x: -x["score"])[:6]
    with ThreadPoolExecutor(max_workers=6) as ex:
        states = list(ex.map(lambda it: verify(kind, it), items))
    dead = []
    for it, st in zip(items, states):
        it["verified"] = st
        if st is False: dead.append(it["name"])
    items = [it for it in items if it["verified"] is not False]
    items.sort(key=lambda x: (x["verified"] is None, -x["score"]))      # verified first, then by score (yours do not jump the line)
    ok = [x for x in items if not (free and x["paid"])]
    paid = [x for x in items if free and x["paid"]]
    if money:
        for it in ok[:2] + paid[:1]:
            if it.get("repo") and kind != "connector":
                it["license_flag"] = license_flag(it["repo"], it.get("lic"))
                if kind == "skill" and it["license_flag"] == "check": it["license_flag"] = ""
        ok = [x for x in ok if x.get("license_flag") != "nc"] + [x for x in ok if x.get("license_flag") == "nc"]
    good = [x for x in ok if x["score"] >= minimum or x["have"]]
    if not good and ok:
        good = [dict(ok[0], close=True)]
    return good, [x for x in paid if x["score"] >= minimum], dead


# ---------- 5-6. combination ----------
def combos(e):
    """Every useful combination of the step's best picks, scored: mean quality + bonus for covering what the step needs."""
    best = {k: p["best"][0] for k, p in e["picks"].items() if p["best"]}
    if not e["needs"]:
        return [{"kinds": [], "score": 100}]
    out = []
    for n in range(1, len(best) + 1):
        for ks in itertools.combinations(best, n):
            sc = sum(best[k]["score"] for k in ks) / n + 8 * (n - 1) + 6 * sum(1 for k in ks if k in e["needs"]) \
                 - 10 * sum(1 for k in ks if best[k].get("close"))
            out.append({"kinds": list(ks), "score": round(sc)})
    return sorted(out, key=lambda c: -c["score"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", help="what you want to achieve, in any language")
    ap.add_argument("--where", help="cloud, laptop… (profiles of each finder)")
    ap.add_argument("--free", action="store_true", help="force: only free")
    ap.add_argument("--commercial", action="store_true", help="force: you will make money with the result")
    ap.add_argument("--inventory", default=os.environ.get("SOMMELIER_INVENTORY"), help="your connectors (only to mark ✅ yours)")
    ap.add_argument("--min", type=int, default=50, help="minimum points to recommend something (default 50)")
    ap.add_argument("--lang")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md")
    a = ap.parse_args()
    lang, free, money, steps = plan(a.goal)
    free, money = free or a.free, money or a.commercial
    lang = (a.lang or lang or "es")[:2]
    L = T.get(lang, T["es"])
    print(f"{L['steps']}: " + " → ".join(s["step"] for s in steps), file=sys.stderr)

    with ThreadPoolExecutor(max_workers=4) as ex:
        jobs = {(i, k): ex.submit(run_finder, k, s["query"], a.where, free, a.inventory)
                for i, s in enumerate(steps) for k in s.get("kinds", []) if k in FINDERS}
    kit, dead_all = [], []
    for i, s in enumerate(steps):
        e = {"step": s["step"], "why": s.get("why", ""), "needs": [k for k in s.get("kinds", []) if k in FINDERS], "picks": {}}
        for k in e["needs"]:
            good, paid, dead = choose(k, normalize(k, jobs[(i, k)].result()), free, money, a.min)
            dead_all += dead
            e["picks"][k] = {"best": good[:1], "backup": good[1:2], "paid": paid[:1]}
        kit.append(e)

    # fit check + the best combination per step (one Gemini call; heuristic if it fails)
    listing = [{"id": f"{n}|{k}|{x['name']}", "step": e["step"], "kind": k, "tool": x["name"], "what": (x.get("desc") or "")[:140]}
               for n, e in enumerate(kit) for k, p in e["picks"].items() for x in p["best"] + p["backup"] + p["paid"]]
    g = gemini_json("Goal: «" + a.goal + "». (1) Drop every tool that does NOT really help its step of this goal. (2) For each step "
                    "number, pick the best COMBINATION among the remaining best tools of that step (one kind or several that "
                    "complement each other) and explain why in ONE short sentence in language '" + lang + "'. Return JSON "
                    "{\"drop\": [ids], \"combos\": [{\"step\": number, \"kinds\": [\"repo\"|\"connector\"|\"skill\"], \"why\": \"...\"}]}\n"
                    + json.dumps(listing, ensure_ascii=False)) if listing else None
    drop = set((g or {}).get("drop", []))
    if g is None:                       # no Gemini: drop tools that share no meaningful word with their step
        stop = {"with", "from", "para", "with", "your", "tool", "agent", "skill", "server", "and", "the", "los", "las", "del"}
        for n, e in enumerate(kit):
            step_w = {w for w in re.findall(r"[a-záéíóúñ]{4,}", (e["step"] + " " + steps[n].get("query", "")).lower()) if w not in stop}
            for k, p in e["picks"].items():
                for x in p["best"] + p["backup"] + p["paid"]:
                    if not step_w & set(re.findall(r"[a-záéíóúñ]{4,}", (x["name"] + " " + (x.get("desc") or "")).lower())):
                        drop.add(f"{n}|{k}|{x['name']}")
    for n, e in enumerate(kit):
        for k, p in e["picks"].items():
            for part in ("best", "backup", "paid"):
                p[part] = [x for x in p[part] if f"{n}|{k}|{x['name']}" not in drop]
            if not p["best"] and p["backup"]:
                p["best"], p["backup"] = p["backup"][:1], []
        cs = combos(e)
        pick = next((c for c in (g or {}).get("combos", []) if int(c.get("step", -1)) == n and
                     all(k in e["picks"] and e["picks"][k]["best"] for k in c.get("kinds", []))), None)
        e["combo"] = ({"kinds": pick["kinds"], "why": pick.get("why", ""),
                       "score": next((c["score"] for c in cs if sorted(c["kinds"]) == sorted(pick["kinds"])), None)}
                      if pick and pick.get("kinds") else (dict(cs[0], why="") if cs else {"kinds": [], "score": None, "why": ""}))

    if a.json:
        print(json.dumps({"goal": a.goal, "lang": lang, "free": free, "commercial": money, "where": a.where, "kit": kit,
                          "dropped_not_working": dead_all}, ensure_ascii=False, indent=1)); return

    def cell(it, kind):
        if not it: return L["none"]
        flag = {"nc": " " + L["nc"], "check": " " + L["check"]}.get(it.get("license_flag", ""), "")
        ver = L["ok"] if it.get("verified") else L["unver"]
        st = f" {it['stars']:,}⭐" if isinstance(it.get("stars"), int) else ""
        name = f"[{it['name']}]({it['url']})" if it.get("url") else it["name"]
        return (f"{L['close'] + ': ' if it.get('close') else ''}**{name}** ({it['score']}{st}) {ver}"
                f"{' ' + L['have'] if it['have'] else ''}{flag}")

    out = [f"# {L['title']}: {a.goal}",
           f"**{L['cond']}:** " + (", ".join(x for x in [L["free"] if free else "", L["money"] if money else "",
                                                          f"{L['where']}: {a.where}" if a.where else ""] if x) or "—"), "",
           f"## {L['combo']}", f"| # | {L['step']} | Kit | {L['pts']} | {L['why']} |", "|---|---|---|---|---|"]
    for n, e in enumerate(kit, 1):
        c = e["combo"]
        if not e["needs"] or not c["kinds"]:
            kit_txt = L["ai"] if not e["needs"] else L["none"]
        else:
            kit_txt = " + ".join(f"{ICON[k]} {e['picks'][k]['best'][0]['name']}" for k in c["kinds"])
        out.append(f"| {n} | {e['step']} | {kit_txt} | {c.get('score') or ''} | {c.get('why') or e['why']} |")
    for kind, title in (("repo", L["repos"]), ("skill", L["skills"]), ("connector", L["conns"])):
        rows = [(n, e) for n, e in enumerate(kit, 1) if kind in e["picks"]]
        if not rows: continue
        out += ["", f"## {title}", f"| # | {L['step']} | {L['best']} | {L['backup']} | {L['install']} |", "|---|---|---|---|---|"]
        for n, e in rows:
            p = e["picks"][kind]
            b = p["best"][0] if p["best"] else None
            extra = (" · " + L["paid"] + ": " + cell(p["paid"][0], kind)) if p["paid"] else ""
            out.append(f"| {n} | {e['step']} | {cell(b, kind)} | {cell(p['backup'][0] if p['backup'] else None, kind)}{extra} | "
                       f"{('`' + b['how'] + '`') if b and b.get('how') and b['how'] != '✅' else (L['have'] if b else '')} |")
    if dead_all:
        out += ["", f"_{len(dead_all)} {L['dead']}: {', '.join(dead_all[:8])}_"]
    text = "\n".join(out)
    print(text)
    if a.md: Path(a.md).write_text(text)


if __name__ == "__main__":
    main()
