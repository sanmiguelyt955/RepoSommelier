#!/usr/bin/env python3
"""kit.py — a complete KIT for a goal: the repos, connectors and skills it needs (and only those).

Same file in RepoSommelier, MCPSommelier and SkillSommelier: run it from any of them, it uses the three finders that
sit next to each other (../reposommelier, ../mcpsommelier, ../skillsommelier).

    python3 kit.py "quiero hacer videos de manera gratuita con IA para después monetizarlos"
    python3 kit.py "send an invoice email every Monday from my Shopify orders" --where cloud
    python3 kit.py "..." --json

How it works
 1. PLAN: Gemini reads the goal (any language) and splits it into steps. For each step it says what is really needed:
      📦 repo (software that must run) · 🔌 connector (an outside service or account: YouTube, Drive, Gmail…) ·
      🎓 skill (know-how that makes the agent do it better) · 🤖 nothing (the AI does it by itself).
    It also reads your conditions: free? will you make money with it (commercial use)? where does it run?
 2. SEARCH: for each step it asks only the finders that step needs, in parallel.
 3. FILTER by your conditions:
      free → paid connectors, repos that need a paid API and skills that ask for a paid key go to «optional, paid».
      monetize → licenses that forbid commercial use (CC-BY-NC, "non-commercial", "research only") are flagged ⛔,
                 and repos without a clear license get ⚠️ «check the license».
 4. KIT: step by step, the best pick of each kind (+ one backup), what you already have first, and how to install it.
Read-only: it never installs or runs what it finds.
"""
import argparse, json, os, re, subprocess, sys, urllib.request
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
           "where": "donde corre", "ai": "lo hace la IA sola, no necesitas nada", "none": "no encontré nada bueno para este paso",
           "backup": "respaldo", "paid": "💳 opcional, de paga", "nc": "⛔ licencia NO comercial: no sirve para monetizar",
           "check": "⚠️ revisa la licencia antes de monetizar", "have": "✅ ya lo tienes", "summary": "Resumen",
           "install": "instalar", "steps": "Pasos"},
    "en": {"title": "Your kit for", "cond": "Conditions", "free": "free", "money": "to monetize (commercial use)",
           "where": "runs on", "ai": "the AI does it by itself, you need nothing", "none": "nothing good found for this step",
           "backup": "backup", "paid": "💳 optional, paid", "nc": "⛔ NON-commercial license: not for monetizing",
           "check": "⚠️ check the license before monetizing", "have": "✅ you have it", "summary": "Summary",
           "install": "install", "steps": "Steps"},
    "pt": {"title": "Seu kit para", "cond": "Condições", "free": "grátis", "money": "para monetizar (uso comercial)",
           "where": "onde roda", "ai": "a IA faz sozinha, você não precisa de nada", "none": "não achei nada bom para este passo",
           "backup": "reserva", "paid": "💳 opcional, pago", "nc": "⛔ licença NÃO comercial: não serve para monetizar",
           "check": "⚠️ confira a licença antes de monetizar", "have": "✅ você já tem", "summary": "Resumo",
           "install": "instalar", "steps": "Passos"},
}


def _gemini_key():
    if os.environ.get("GEMINI_API_KEY"): return os.environ["GEMINI_API_KEY"]
    env = Path.home() / ".config/watch/.env"
    for line in (env.read_text().splitlines() if env.exists() else []):
        if line.startswith("GEMINI_API_KEY="): return line.split("=", 1)[1].strip().strip('"')
    return "proxy-injected"


def gemini_json(prompt):
    body = json.dumps({"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"responseMimeType": "application/json"}}).encode()
    for model in os.environ.get("KIT_MODELS", "gemini-3-flash-preview,gemini-flash-latest").split(","):
        req = urllib.request.Request(f"https://generativelanguage.googleapis.com/v1beta/models/{model.strip()}:generateContent",
                                     body, {"Content-Type": "application/json", "x-goog-api-key": _gemini_key()})
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.loads(json.loads(r.read())["candidates"][0]["content"]["parts"][0]["text"])
        except Exception:
            continue
    return None


def guess(goal):
    g = (goal or "").lower()
    lang = "pt" if re.search(r"[ãõç]| você | não ", " " + g + " ") else "es" if re.search(r"[ñ¿¡]| quiero | para | hacer ", " " + g + " ") else "en"
    free = bool(re.search(r"\bgratis\b|\bgratuit|\bfree\b|\bgrátis\b|sin pagar|without paying|sem pagar", g))
    money = bool(re.search(r"monetiz|vender|sell|ganar dinero|make money|ganhar dinheiro|clientes|clients|comercial|commercial|negocio|business", g))
    return lang, free, money


def plan(goal):
    lang, free, money = guess(goal)
    p = gemini_json(
        "Plan the tools for this goal (any language). Split it into 2-7 concrete steps in order. For EACH step choose ONLY what "
        "is really needed. Use an EMPTY list when an AI assistant can do the step by itself with no extra tool (writing a "
        "script, ideas, titles, descriptions). Add \"skill\" only when special know-how clearly improves the step: \"repo\" = open-source software "
        "that must run (rendering, voice, editing...), \"connector\" = an outside service/account the agent must reach "
        "(publish to YouTube, read Gmail, Drive, Shopify...), \"skill\" = know-how that makes an AI agent do the step better. "
        "Give each step a 2-5 word ENGLISH search query. Also read the conditions. Return JSON {\"lang\": ISO 639-1 of the goal, "
        "\"free\": true if they want it free, \"commercial\": true if they will make money with the result, \"steps\": [{\"step\": "
        "short name in the goal's language, \"query\": \"english words\", \"kinds\": [\"repo\"|\"connector\"|\"skill\"], \"why\": "
        "one short sentence in the goal's language}]}. Goal: " + goal)
    if p and p.get("steps"):
        return p.get("lang") or lang, bool(p.get("free", free)) or free, bool(p.get("commercial", money)) or money, p["steps"][:7]
    return lang, free, money, [{"step": goal, "query": goal, "kinds": ["repo", "connector", "skill"], "why": ""}]


def run_finder(kind, query, where, free, top=3, inventory=None):
    f = FINDERS[kind]
    if not f.exists():
        return {"missing": str(f)}
    cmd = [sys.executable, str(f), query, "--json", "--no-judge", "--top", str(top)]
    if where: cmd += ["--where", where]
    if kind == "repo" and free: cmd += ["--free"]
    if kind == "skill": cmd += ["--no-family"]
    if kind == "connector" and inventory and Path(inventory).exists(): cmd += ["--inventory", inventory]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        return json.loads(r.stdout)
    except Exception as e:
        return {"error": str(e)[:200]}


def license_flag(repo, spdx):
    """'nc' if the README/LICENSE forbids commercial use, 'check' if unclear, '' if fine."""
    txt = ""
    for name in ("LICENSE", "LICENSE.md", "README.md"):
        for br in ("main", "master"):
            try:
                txt += urllib.request.urlopen(f"https://raw.githubusercontent.com/{repo}/{br}/{name}", timeout=15).read(60000).decode("utf-8", "ignore")
                break
            except Exception:
                continue
    if NC.search(txt):
        return "nc"
    return "" if (spdx or "").lower() in PERMISSIVE else "check"


def picks(kind, out, free, money):
    """Normalize each finder's JSON into [{name, url, score, how, have, paid, lic}]."""
    items = []
    if kind == "repo":
        for r in out.get("ranking", []):
            items.append({"name": r["repo"], "url": r["url"], "score": r["score"], "desc": r.get("description", ""),
                          "how": f"git clone {r['url']}", "have": False, "paid": bool((r.get("signals") or {}).get("paid")),
                          "lic": r.get("license"), "stars": r.get("stars")})
    elif kind == "connector":
        for c in (out.get("ranking", []) + [dict(p, paid=True) for p in out.get("paid", [])]):
            items.append({"name": c.get("title") or c["name"], "url": c.get("url"), "score": c["score"], "desc": c.get("what", ""),
                          "how": "claude.ai → Conectores" if c.get("kind") == "hosted" else c.get("setup", ""),
                          "have": c.get("have"), "paid": bool(c.get("paid")), "lic": None})
    else:
        for s in out.get("results", []) + out.get("needs_extra", []):
            items.append({"name": f"{s['repo']}/{s['skill']}", "url": f"https://github.com/{s['repo']}", "score": s["pts"],
                          "desc": s.get("description", ""), "how": s["install"], "have": s.get("have"),
                          "paid": "paid_key" in s.get("needs", []), "lic": None, "repo": s["repo"]})
    items.sort(key=lambda x: (not x["have"], -x["score"]))
    ok, paid = [], []
    for it in items:
        (paid if (free and it["paid"]) else ok).append(it)
    if money:
        for it in (ok[:2] + paid[:1]):
            repo = it["name"] if kind == "repo" else it.get("repo")
            if repo:
                it["license_flag"] = license_flag(repo, it["lic"] if kind == "repo" else None)
                if it["license_flag"] == "check" and kind == "skill":
                    it["license_flag"] = ""          # a skill is instructions; its repo license rarely matters for your videos
        ok = [x for x in ok if x.get("license_flag") != "nc"] + [x for x in ok if x.get("license_flag") == "nc"]
    return ok, paid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("goal", help="what you want to achieve, in any language")
    ap.add_argument("--where", help="cloud, laptop… (profiles of each finder)")
    ap.add_argument("--free", action="store_true", help="force: only free")
    ap.add_argument("--commercial", action="store_true", help="force: you will make money with the result")
    ap.add_argument("--lang")
    ap.add_argument("--inventory", default=os.environ.get("SOMMELIER_INVENTORY"), help="your connectors (MCPSommelier inventory JSON) so the ones you have come first")
    ap.add_argument("--min", type=int, default=50, help="minimum points to recommend something (default 50)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md")
    a = ap.parse_args()
    lang, free, money, steps = plan(a.goal)
    free, money = free or a.free, money or a.commercial
    lang = (a.lang or lang or "es")[:2]
    L = T.get(lang, T["es"])
    print(f"{L['steps']}: " + " → ".join(s["step"] for s in steps), file=sys.stderr)

    jobs = {}
    with ThreadPoolExecutor(max_workers=4) as ex:
        for i, s in enumerate(steps):
            for k in s.get("kinds", []):
                if k in FINDERS:
                    jobs[(i, k)] = ex.submit(run_finder, k, s["query"], a.where, free, 3, a.inventory)
    kit = []
    for i, s in enumerate(steps):
        entry = {"step": s["step"], "why": s.get("why", ""), "query": s["query"], "needs": s.get("kinds", []), "picks": {}}
        for k in s.get("kinds", []):
            if (i, k) not in jobs: continue
            ok, paid = picks(k, jobs[(i, k)].result(), free, money)
            ok = [x for x in ok if x["score"] >= a.min or x["have"]]
            paid = [x for x in paid if x["score"] >= a.min]
            entry["picks"][k] = {"best": ok[:1], "backup": ok[1:2], "paid": paid[:1]}
        kit.append(entry)
    # one final check: drop picks that do not really serve their step (one Gemini call for the whole kit)
    listing = [{"id": f"{n}|{k}|{x['name']}", "step": e["step"], "kind": k, "tool": x["name"], "what": (x.get("desc") or "")[:140]}
               for n, e in enumerate(kit) for k, p in e["picks"].items() for x in p["best"] + p["backup"] + p["paid"]]
    if listing:
        g = gemini_json("Goal: «" + a.goal + "». For each tool proposed for a step, say if it REALLY helps that step of that goal "
                        "(a YouTube transcript tool does not upload videos; a Slack GIF skill does not make YouTube animations). "
                        "Return JSON {\"drop\": [ids that do not fit]}.\n" + json.dumps(listing, ensure_ascii=False))
        drop = set((g or {}).get("drop", []))
        for n, e in enumerate(kit):
            for k, p in e["picks"].items():
                for part in ("best", "backup", "paid"):
                    p[part] = [x for x in p[part] if f"{n}|{k}|{x['name']}" not in drop]
                if not p["best"] and p["backup"]:
                    p["best"], p["backup"] = p["backup"][:1], []

    if a.json:
        print(json.dumps({"goal": a.goal, "lang": lang, "free": free, "commercial": money, "where": a.where, "kit": kit},
                         ensure_ascii=False, indent=1)); return

    def line(kind, it, tag=""):
        flag = {"nc": " " + L["nc"], "check": " " + L["check"]}.get(it.get("license_flag", ""), "")
        st = f" · {it['stars']:,}⭐" if isinstance(it.get("stars"), int) else ""
        return (f"- {ICON[kind]} {tag}**[{it['name']}]({it['url']})** ({it['score']}{st}){' ' + L['have'] if it['have'] else ''}{flag} — "
                f"{(it['desc'] or '')[:110]}  \n  `{it['how']}`")
    out = [f"# {L['title']}: {a.goal}",
           f"**{L['cond']}:** " + ", ".join(x for x in [L["free"] if free else "", L["money"] if money else "",
                                                        f"{L['where']}: {a.where}" if a.where else ""] if x) or "—", ""]
    counts = {"repo": 0, "connector": 0, "skill": 0}
    for n, e in enumerate(kit, 1):
        out.append(f"## {n}. {e['step']}" + (f" — {e['why']}" if e["why"] else ""))
        if not e["needs"]:
            out.append(f"- 🤖 {L['ai']}")
        for k, p in e["picks"].items():
            if p["best"]:
                counts[k] += 1
                out.append(line(k, p["best"][0]))
                out += [line(k, b, f"{L['backup']}: ") for b in p["backup"]]
            else:
                out.append(f"- {ICON[k]} {L['none']}")
            out += [line(k, x, f"{L['paid']}: ") for x in p["paid"]]
        out.append("")
    out.append(f"**{L['summary']}:** {counts['repo']} 📦 · {counts['connector']} 🔌 · {counts['skill']} 🎓 · "
               f"{sum(1 for e in kit if not e['needs'])} 🤖")
    text = "\n".join(out)
    print(text)
    if a.md: Path(a.md).write_text(text)


if __name__ == "__main__":
    main()
