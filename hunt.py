#!/usr/bin/env python3
"""hunt.py — keep searching, round after round, until a repo (first) or a connector (second) that WORKS WHERE YOU ARE
shows up. Uses every source RepoSommelier knows plus more:

  GitHub repo search · GitHub CODE search (finds repos by what their code really does) · npm · PyPI · Hugging Face Spaces
  · Hacker News stories and comments · Lobsters · dev.to · X and Reddit (with a key: FIRECRAWL_API_KEY / BRAVE_API_KEY)

    python3 hunt.py "watch YouTube videos (frames + audio) from a link" --where cloud \\
        --works-if "gemini" "file_uri|filedata|fileuri|file_data" --rounds 5
    python3 hunt.py "transcribe audio on CPU" --works-if "whisper|parakeet" "cpu"

--works-if: evidence groups that ALL must appear in the README or code (each group is "a|b|c" = any of them).
Without it, Gemini proposes the evidence from your need and blockers (fallback: the need's own keywords).
A candidate WORKS when it has the evidence and no hard blocker for your place (--where / --blockers).
Each round adds new queries (Gemini variants, synonyms, code patterns) and stops as soon as something works, or after
--rounds. If no repo works, it hunts connectors with MCPSommelier (if installed next to this repo or in --mcpsommelier).
Read-only: it never clones, installs or runs what it finds; X/Reddit searches spend your Firecrawl/Brave credits.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import reposommelier as rs  # noqa: E402

CODE_EXT = "language:python OR language:typescript OR language:javascript"


def evidence_groups(need, blockers, given):
    if given:
        return [[w.strip().lower() for w in g.split("|") if w.strip()] for g in given]
    g = rs.gemini_json("A repo must solve this need AND work under these blockers (things NOT available): " + json.dumps(blockers)
                       + ". Need: " + need + ". Give the concrete words that would appear in its README or code to prove it "
                       "solves the need WITHOUT the blocked things. Return JSON {\"groups\": [[synonyms...], ...]} with 2-3 groups; "
                       "every group must be matched (any synonym). Lowercase, short technical words (library, API or field names).")
    if g and g.get("groups"):
        return [[w.lower() for w in grp if w] for grp in g["groups"] if grp]
    return [[w] for w in rs.words(need)[:3]]


def has_evidence(text, groups):
    """Every positive group must match (any synonym); a group written "!word" must NOT appear."""
    t = text.lower()
    pos = [g for g in groups if not g[0].startswith("!")]
    neg = [w[1:] for g in groups if g[0].startswith("!") for w in g]
    return all(any(w in t for w in grp) for grp in pos) and not any(re.search(rf"(?<![a-z0-9]){re.escape(n)}", t) for n in neg)


def parse_want(spec):
    """'no-gemini=youtube;storyboard|transcript;!gemini' -> ('no-gemini', [['youtube'], ['storyboard', 'transcript'], ['!gemini']])"""
    label, _, body = spec.partition("=")
    groups = []
    for part in body.split(";"):
        part = part.strip()
        if not part: continue
        if part.startswith("!"):
            groups.append(["!" + w.strip().lower() for w in part[1:].split("|")])
        else:
            groups.append([w.strip().lower() for w in part.split("|") if w.strip()])
    return label.strip(), groups


def gh(path, **params):
    args = ["gh", "api", "-X", "GET", path] + sum([["-f", f"{k}={v}"] for k, v in params.items()], [])
    r = subprocess.run(args, capture_output=True, text=True, timeout=60)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else {}


def code_search(groups):
    """Repos whose CODE contains the evidence (one term of each positive group; "!" groups are checked on the README)."""
    groups = [g for g in groups if not g[0].startswith("!")]
    q = " ".join(f'"{grp[0]}"' if " " in grp[0] else grp[0] for grp in groups[:3])
    d = gh("search/code", q=q, per_page="50")
    out = {}
    for it in d.get("items", []):
        out.setdefault(it["repository"]["full_name"], []).append(it.get("path", ""))
    return out


def npm_search(q):
    d = rs._get_json("https://registry.npmjs.org/-/v1/search?size=25&text=" + urllib.parse.quote(q)) or {}
    out = []
    for o in d.get("objects", []):
        p = o.get("package", {})
        repo = rs._repo_from((p.get("links") or {}).get("repository", "")) or rs._repo_from((p.get("links") or {}).get("homepage", ""))
        if repo:
            out.append((repo, f"npm: {p.get('name')} — {p.get('description', '')}"))
    return out


def hf_spaces(q):
    d = rs._get_json("https://huggingface.co/api/spaces?limit=20&full=false&search=" + urllib.parse.quote(q)) or []
    return [{"id": s.get("id"), "likes": s.get("likes", 0), "url": f"https://huggingface.co/spaces/{s.get('id')}"} for s in d]


def hn_comments(q, days=180):
    since = int(time.time()) - days * 86400
    d = rs._get_json(f"https://hn.algolia.com/api/v1/search?tags=comment&hitsPerPage=50&numericFilters=created_at_i>{since}&query="
                     + urllib.parse.quote(q)) or {}
    out = []
    for h in d.get("hits", []):
        repo = rs._repo_from(h.get("comment_text"))
        if repo:
            out.append((repo, f"HN comment: {(h.get('story_title') or '')[:80]}"))
    return out


def variants(need, round_no, used):
    g = rs.gemini_json(f"Round {round_no} of a search for GitHub repos. Need: {need}. Already tried: {json.dumps(used)}. Give 4 NEW short "
                       "GitHub search queries (2-3 concrete words, different angles, tool/library names) not tried yet. JSON {\"queries\": [...]}")
    if g and g.get("queries"):
        return [q for q in g["queries"] if q not in used][:4]
    base = rs.words(need)
    pool = [" ".join(base[i:i + 2]) for i in range(len(base))] + [f"{w} mcp" for w in base] + [f"{w} skill" for w in base]
    return [q for q in pool if q not in used][round_no * 3:(round_no + 1) * 3] or [q for q in pool if q not in used][:3]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("need", nargs="?")
    ap.add_argument("--tested", nargs="+", metavar=("REPO", "works|fails"),
                    help='record a real test: --tested owner/repo works "note" (it then floats up or sinks in later hunts)')
    ap.add_argument("--works-if", nargs="+", help='evidence groups, e.g. "gemini" "file_uri|filedata"')
    ap.add_argument("--want", action="append", default=[],
                    help='several targets at once: label=group;group;!excluded (repeat). E.g. '
                         '--want "gemini=gemini;file_uri|filedata;youtube" --want "no-gemini=youtube;transcript|storyboard;!gemini"')
    ap.add_argument("--where", default="cloud")
    ap.add_argument("--blockers", nargs="+", default=[])
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--min-found", type=int, default=1)
    ap.add_argument("--queries", nargs="+", default=[])
    ap.add_argument("--mcpsommelier", default=str(Path(__file__).resolve().parent.parent / "mcpsommelier" / "mcpsommelier.py"))
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    if a.tested:
        idx = rs.load(rs.INDEX, {"searches": [], "verdicts": {}})
        res = "works" if (a.tested[1] if len(a.tested) > 1 else "works").lower() in ("works", "funciona", "ok", "good") else "fails"
        idx.setdefault("tested", {})[a.tested[0]] = {"result": res, "note": " ".join(a.tested[2:]), "where": a.where,
                                                     "date": time.strftime("%Y-%m-%d")}
        rs.DATA.mkdir(parents=True, exist_ok=True); rs.INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=1))
        print(f"Recorded: {a.tested[0]} {res}"); return
    if not a.need:
        ap.error("need is required")
    prof = rs.load(rs.HERE / "profiles" / f"{a.where}.json", {}) if a.where else {}
    blockers = list(dict.fromkeys([b.lower() for b in a.blockers] + prof.get("blockers", [])))
    notes = []
    for b in list(blockers):                       # test each blocker once, without bypassing anything
        ok = rs.verify_blocker(b)
        if ok is True:
            blockers.remove(b); notes.append(f"{b}: works here now")
        elif ok is False:
            notes.append(f"{b}: still blocked here")
    targets = [parse_want(w) for w in a.want] or [("main", evidence_groups(a.need, blockers, a.works_if))]
    groups = targets[0][1]
    print(f"Targets: {targets} · blockers: {blockers} · {'; '.join(notes)}", file=sys.stderr)
    seen, found, near, log, used = set(), [], [], [], list(a.queries)
    rs.NEWS_TERMS.update(w for _, gs in targets for grp in gs for w in grp if len(w) >= 3 and not w.startswith("!"))
    need_per = {lab: a.min_found for lab, _ in targets}
    for rnd in range(a.rounds):
        qs = (a.queries if rnd == 0 and a.queries else []) or variants(a.need, rnd, used)
        used += qs
        cands = {}
        def add(repo, why):
            if repo and repo not in seen:
                cands.setdefault(repo, []).append(why)
        for q in qs:                                                            # 1. GitHub repo search
            for r in rs.search(q):
                if not rs.reject(r): add(r["full_name"], f"GitHub search: {q}")
            for repo, why in npm_search(q): add(repo, why)                     # 2. npm
            for repo, why in hn_comments(q): add(repo, why)                    # 3. HN comments
            time.sleep(2.0)
        for lab, gs in targets:                                                # 4. GitHub code search (what the code does)
            pos = [g for g in gs if not g[0].startswith("!")]
            gg = [[g[rnd % len(g)]] + g for g in pos]                         # another synonym each round
            for repo, paths in code_search(gg).items():
                add(repo, f"code[{lab}]: {', '.join(paths[:2])}")
        news = rs.news_mentions(qs[:2], 180)                                   # 5. HN stories
        social, _ = rs.social_mentions(qs[:1], 60)                             # 6. X / Reddit (if a key exists)
        for repo in list(news) + list(social): add(repo, "news")
        spaces = hf_spaces(qs[0]) if qs else []                                # 7. Hugging Face Spaces (apps, not repos)
        checked = 0
        order = sorted(cands.items(), key=lambda kv: (not any(w.startswith("code") for w in kv[1]), -len(kv[1])))
        for repo, whys in order[:60]:
            seen.add(repo)
            txt = rs.readme(repo)
            if not txt:
                continue
            checked += 1
            hard, soft = rs.check_blockers(txt, blockers)
            for lab, gs in targets:
                code_hit = any(w.startswith(f"code[{lab}]") for w in whys)
                negs = [g for g in gs if g[0].startswith("!")]
                ev = (has_evidence(txt, gs) or (code_hit and has_evidence(txt, negs))) if negs else (has_evidence(txt, gs) or code_hit)
                item = {"repo": repo, "url": f"https://github.com/{repo}", "found_by": whys[:3], "soft_blockers": soft,
                        "round": rnd + 1, "target": lab}
                if ev and not hard:
                    found.append(item)
                elif ev and hard:
                    near.append({**item, "blocked_by": hard})
        log.append({"round": rnd + 1, "queries": qs, "candidates": len(cands), "readmes": checked, "found_total": len(found),
                    "spaces": [s["id"] for s in spaces[:5]]})
        print(f"round {rnd + 1}: {len(cands)} candidates, {checked} READMEs, {len(found)} work here", file=sys.stderr)
        counts = {lab: sum(1 for f in found if f["target"] == lab) for lab, _ in targets}
        print(f"   per target: {counts}", file=sys.stderr)
        if all(counts[lab] >= need_per[lab] for lab in counts):
            break
    # rank what works with RepoSommelier's metadata (stars, activity, license)
    for f in found:
        meta = (rs.search(f"repo:{f['repo']}") or [{}])[0]
        f.update(stars=meta.get("stargazers_count", 0), license=((meta.get("license") or {}).get("spdx_id") or "none").lower(),
                 updated_days=rs.days(meta["pushed_at"]) if meta.get("pushed_at") else None, description=(meta.get("description") or "")[:140])
    terms = [w for w in rs.words(a.need) if len(w) >= 4]
    def fit(f):   # relevance first (description + files where the evidence was found), then a little popularity
        hay = (f.get("description", "") + " " + " ".join(f["found_by"]) + " " + f["repo"]).lower()
        return sum(1 for t in terms if t in hay) / max(1, len(terms)) + min(0.3, (f.get("stars") or 0) / 5000)
    for f in found:
        f["fit"] = round(fit(f), 2)
    tested = rs.load(rs.INDEX, {}).get("tested", {})
    for f in found:
        t = tested.get(f["repo"])
        if t:
            f["tested"] = t
            f["fit"] += 1.0 if t["result"] == "works" else -1.0            # real tests beat any guess
    found = [f for f in found if f["fit"] >= 0.15 or f.get("tested")] or found
    found.sort(key=lambda f: (f["target"], -f["fit"]))
    connectors = None
    if not found and Path(a.mcpsommelier).exists():
        r = subprocess.run([sys.executable, a.mcpsommelier, a.need, "--where", a.where, "--json", "--top", "8"],
                           capture_output=True, text=True, timeout=1200)
        try:
            connectors = json.loads(r.stdout)
        except Exception:  # noqa: BLE001
            connectors = None
    res = {"need": a.need, "evidence": groups, "blockers": blockers, "notes": notes, "rounds": log,
           "works_here": found, "would_work_but_blocked": near[:10], "connectors": connectors}
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=1)); return
    print(f"# Hunt: {a.need}\n")
    print(f"Evidence: {groups} · blockers: {blockers} · {'; '.join(notes)}\n")
    for l in log:
        print(f"- round {l['round']}: {l['candidates']} candidates, {l['readmes']} READMEs, {l['found_total']} working · queries: {l['queries']}")
    print("\n## ✅ Works here\n" + ("\n".join(f"- [{f['target']}] [{f['repo']}]({f['url']}) ({f.get('stars', 0)}⭐, {f.get('license')}) — {f.get('description', '')} · found by: {'; '.join(f['found_by'])}"
                                       + (f" · ⚠️ without {', '.join(f['soft_blockers'])}" if f["soft_blockers"] else "")
                                       + (f" · 🧪 tested here: {f['tested']['result']} ({f['tested']['date']})" if f.get("tested") else "") for f in found) or "- nothing yet"))
    if near:
        print("\n## ⛔ Would work, but blocked here\n" + "\n".join(f"- [{n['repo']}]({n['url']}) — {', '.join(n['blocked_by'])}" for n in near[:10]))
    if connectors:
        print("\n## 🔌 Connectors (no repo worked)\n" + "\n".join(f"- {c['title']} ({c['score']})" for c in connectors.get("ranking", [])[:6]))


if __name__ == "__main__":
    main()
