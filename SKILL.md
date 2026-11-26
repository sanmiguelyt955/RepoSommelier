---
name: reposommelier
description: Find the best GitHub repos for a need (any language), ranked for the user's hardware, rules and license needs. Use BEFORE building something from scratch, or when the user asks "is there a repo/library/tool for X", "best repo to do X", "what should I use to X".
---

# RepoSommelier skill

1. Write the need in one sentence, in the user's language. Add hard filters when the user implies them:
   `--cpu` (no GPU), `--free` (no paid API), `--commercial` (they want to make money).
2. Pass where it will run: `--where cloud|laptop` (or `--blockers yt-dlp gpu ...`) and `--verify`.
   Run `python3 reposommelier.py "<need>" --json --top 10` (needs `gh` logged in; `GEMINI_API_KEY` optional).
3. Read `notes` (verified blockers), `blocked_today` (set aside, with reasons; never present them as recommended), `picks` and, for the top 3, `judge.reason`, `license`, `warnings` and `signals`.
4. Answer in the user's language: the top 3 with one line each (what it is, why it fits, warnings), then the 3 picks.
   Say clearly if a license is non-commercial, copyleft or missing.
5. Never clone, install or run a recommended repo without the user's OK, and read its code first.
6. When the user says a repo worked (or failed), record it: `python3 reposommelier.py --verdict owner/repo good|bad "note"`.
