# 🍷 RepoSommelier

**The smart GitHub repo finder for humans and AI agents.** Tell it what you want to build — in **any language** — and it pours you the **best repos for your need**, ranked best to worst, with the reasons, the license truth and the warnings that matter.

> A sommelier doesn't pour the most expensive wine. It pours the best one for *your* dish, *your* taste and *your* budget.

[Leer en español](README.es.md)

```bash
python3 reposommelier.py "make 3D animated shorts with code"
python3 reposommelier.py "transcribir audio en español" --cpu --free --commercial
python3 reposommelier.py "用代码生成游戏音效" --json          # any language in, answers in that language
python3 reposommelier.py --verdict owner/repo good "worked great"   # teach it
```

## Why not just GitHub search (or asking an LLM)?
| | GitHub search | Asking an LLM | **RepoSommelier** |
|---|---|---|---|
| Live data (today's repos) | ✅ | ❌ (training cutoff) | ✅ |
| Understands a need in any language | ❌ | ✅ | ✅ |
| Drops dead, toy, fork and "awesome" repos | ❌ | ❌ | ✅ |
| Reads each README (install? demo? GPU? paid API?) | ❌ | ❌ | ✅ |
| Fits **your** hardware, rules and what you already have | ❌ | partly | ✅ (`profile.json`) |
| Warns about non-commercial / copyleft / missing licenses | ❌ | rarely | ✅ |
| Learns from your verdicts | ❌ | ❌ | ✅ |
| JSON for agents | ✅ | ❌ | ✅ |

## How it works
1. **Understands** the need in any language and writes 6 short GitHub queries with real tool names (Gemini; falls back to a synonym dictionary). GitHub needs every word to match, so queries stay 2-3 concrete words.
2. **Searches** GitHub (official API through `gh`, 24 h cache).
3. **Drops** archived repos, forks, "awesome" lists, repos with no code or description, dead repos (>18 months) and toys.
4. **Reads the README** of the top 25: install steps, demo, GPU requirement, paid API, tests, agent-ready, and how much it talks about your task.
5. **Judge** (optional, Gemini): rates 0-10 how well each of the top 10 fits your need **and your profile**, with a one-line reason in your language.
6. **Scores** 0-100 = relevance 35 + judge 15 + popularity 15 + activity 15 + health 10 + license 10 + your verdicts.
7. **Returns** the ranking with tiers (**Use now** ≥70 · **Adapt** 55-69 · **Study** <55), warnings (🎮 GPU, 💳 paid API, ⚠️ non-commercial, 🆕 new, 🔥 trending, 🤖 agent-ready) and 3 picks: best overall, best free & CPU-friendly, rising newcomer.

## Setup
- Python 3.9+ (standard library only) and the GitHub CLI `gh`, logged in (`gh auth login`).
- Optional: `GEMINI_API_KEY` (free from Google AI Studio). Without it there is no judge and queries come from a dictionary.
- Optional: copy `data/profile.example.json` to `data/profile.json` and describe yourself.
- Data folder: `data/` (or `REPOSOMMELIER_DATA`): `index.json` keeps searches and verdicts.

## For AI agents
See [`SKILL.md`](SKILL.md). Use `--json` and read `picks` and `ranking[].warnings` before recommending anything.

## Safety
Read-only. It only reads public GitHub search results and READMEs; it never clones, installs or runs what it finds. A high score is not a security review: always read a repo's code before using it.

## License
MIT © 2026 sanmiguelyt955
