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

## Blockers: what does not work where you are TODAY
Some repos are great but cannot run in your place (e.g. a cloud machine where YouTube blocks `yt-dlp`, or a laptop without a GPU).
```bash
python3 reposommelier.py "watch YouTube videos" --where cloud --verify      # place profile + test the blockers first
python3 reposommelier.py "..." --blockers yt-dlp gpu cookies
```
- **Never deletes**: blocked repos go to a second list, *"⛔ Does not work where you are TODAY"*, with the reason.
- **Per search, per place**: blockers come from `--blockers` or a place profile (`profiles/cloud.json`, `profiles/laptop.json`, or your own in `data/profiles/`). Next search starts fresh.
- **Soft blockers**: if a repo uses something but can work without it, it stays in the ranking with a warning.
- **`--verify`** tests each blocker once, without bypassing anything (e.g. a 2-second `yt-dlp` test on a public video, `nvidia-smi` for GPU). If it works now, the blocker is dropped and you are told.
- **History** keeps the date and reason; when a repo set aside before is usable now, it says so.
Known blockers: `yt-dlp`, `gpu`, `paid`, `cookies`, `docker`, `windows-only`, `mac-only` (any other word is matched in the README).

## News and repos of the moment
```bash
python3 reposommelier.py "text to speech on CPU" --news      # also reads what people talk about (last 120 days)
python3 reposommelier.py --trending                           # repos of the moment (last 7 days), checked against your profile
```
- Sources: Hacker News, Lobsters and dev.to, plus the official GitHub search as the substitute for github.com/trending
  (which blocks servers). Reddit also blocks servers and is not used.
- A news item counts for a repo when it links to it or names it (distinctive names only). Relevant news about projects
  outside GitHub (Hugging Face, blogs) is listed in its own section.
- **X and Reddit** (where most repos get shared) block anonymous servers. RepoSommelier reads them only through allowed
  ways, each optional with your own key: `FIRECRAWL_API_KEY` or `BRAVE_API_KEY` (web search that indexes public posts),
  `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` (official Reddit API, free personal "script" app), `X_BEARER_TOKEN`
  (official X API; recent search needs a paid tier). Without keys it tells you so; it never scrapes or uses cookies. In sandboxes where a proxy injects the key, set the variable to a placeholder (e.g. `FIRECRAWL_API_KEY=proxy-injected`).
- Repos with suspiciously fast stars are flagged: star farms and malware bait exist.

## Plan B: legitimate substitutes for what is blocked
When a repo is set aside by a blocker, RepoSommelier proposes how to still use it, **only through allowed ways**:
| Blocker | Plan B |
|---|---|
| `gpu` | a CPU port of the same model (ONNX / C++), searched by the model it is built on (e.g. F5-TTS → F5-TTS-ONNX), or rent a GPU per second |
| `paid` | a free local model or free tier |
| `docker` | a native install (pip / npm) |
| `yt-dlp` | keep the repo, feed it a file you upload or run that step on a computer at home |
| `cookies` | no substitute: getting past a bot check with browser cookies is bypassing a block (repos where cookies are optional stay, with a warning) |
It never suggests proxies, cookie tricks, captcha solvers or anything that tricks a site into letting you in.

## Hunt mode: keep searching until something works where you are
```bash
python3 hunt.py "watch YouTube videos (frames + audio) from a link" --where cloud \
    --works-if "gemini" "file_uri|filedata|fileuri" "youtube" --rounds 5
```
- Round after round it adds new queries and reads **more sources**: GitHub repo search, **GitHub code search** (finds repos by
  what their code really does, not by what the README promises), npm, Hugging Face Spaces, Hacker News stories **and comments**,
  Lobsters, dev.to, and X/Reddit with a key.
- `--works-if`: the evidence that a repo solves the need **without** your blockers (each group is "a|b|c"; all groups must match).
  Without it, Gemini proposes the evidence.
- It stops as soon as enough repos work; if none does, it hunts **connectors** with MCPSommelier.
- **Several targets at once** with `--want label=group;group;!excluded` (e.g. one target *with* Gemini and one *without*:
  `--want "gemini=gemini;file_uri|filedata;youtube" --want "no-gemini=youtube;transcript|storyboard;!gemini"`). It keeps going
  until every target has `--min-found` results.
- **Real tests win**: `--tested owner/repo works "note"` (or `fails`) records what you actually tried; tested repos float up or
  sink in later hunts and are marked 🧪.
- Real example: watching YouTube in a cloud sandbox where `yt-dlp` is blocked. Four rounds of plain search found nothing;
  code search found 41 repos that send the YouTube link straight to Gemini (no download), e.g. `aigentive/youtube-gemini-mcp`.

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
