# campaign-data-platform — first task: Windsor pull → normalize → endpoint

Vertical slice of Waves 0–1 (Google Ads only, campaign level), stopping at a **local endpoint**
that stands in for Snowflake RAW. When the sandbox Windsor key arrives you run the live demo;
when the Snowflake creds arrive, only the final sink changes (endpoint → keyed `MERGE`).

## Status
| Step | State |
|---|---|
| 0 Scaffold | ✅ done |
| 1 Look at the data | ⏳ needs sandbox key — run `spikes/peek.py`, fill `spikes/out/discovery_notes.md` |
| 2 Windsor client + tests | ✅ done, tests green |
| 3 Normalize + tests | ✅ done, tests green |
| 4 Endpoint + glue | ✅ done |
| 5 Live end-to-end demo | ⏳ needs sandbox key |
| 6 Show the owner | ⏳ after Step 5 |
| 7 Swap to Snowflake | later (creds handover) |

## Setup
```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -v            # Steps 2 & 3 proven without touching the live API
cp .env.example .env # then paste the sandbox key into .env
```

## Live demo (once .env has the sandbox key)
```bash
# Terminal 1
. .venv/bin/activate && uvicorn demo.endpoint:app --reload
# Terminal 2
. .venv/bin/activate && python demo/run_pull.py
curl localhost:8000/count
```
Quick sanity check without the server: in `run_pull.py` swap the POST for
`json.dump(payload, open("demo/out.json","w"), indent=2)` and open the file.

## Before you run the live pull
Do Step 1 first, then reconcile the **left-hand keys** of `FIELD_MAP` in
`src/etl/normalize.py` with the confirmed names in `spikes/out/discovery_notes.md`.
The placeholders marked `# <- confirm` are guesses until the snapshot proves them.

## Guardrails (from the task doc)
- Sandbox workspace / non-production accounts only (§14-3).
- Secrets in `.env` only, never committed; never log a full Windsor URL (key is in the query string).
- Local `git` only; do not push to any external host.

## Deviations from the task doc (deliberate, minimal)
1. **`.env.example` committed instead of a real `.env`.** The task lists creating `.env`, but
   `.env` is git-ignored and holds the key — committing it violates the guardrail. `.env.example`
   is the committed template; `cp .env.example .env` and paste the key.
2. **`run_pull.py` reads `ENDPOINT_URL` with a default**, not a bare `os.environ[...]`.
   `pydantic-settings` loads `.env` into `WindsorSettings` but does **not** export `ENDPOINT_URL`
   into `os.environ`, so the original bare lookup would `KeyError` at demo time. The default
   matches the endpoint (`http://localhost:8000/ingest`) and an env var still overrides it.

## GitHub Codespaces (dev convenience — remove when the repo moves to OVH)
`.devcontainer/devcontainer.json` makes a Codespace boot with Python 3.12 and run
`pip install -e ".[dev]"` automatically. In a Codespace you can **skip the venv step** —
the container already isolates you. Once it's built, just run `pytest -v`.
Create the key file inside the Codespace (`cp .env.example .env`, paste the sandbox key)
or use a Codespaces secret. Never commit `.env`. Keep the GitHub repo **private**; the code's
real home is the self-hosted OVH git host (constraint C1).
