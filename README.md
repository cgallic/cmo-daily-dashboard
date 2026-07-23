# cmo-daily-dashboard

A generated, **local, read-only marketing command center**. It turns a small
SQLite store into a single self-contained `index.html` — a daily glance at
**channel health** plus **what to do today**, with zero external dependencies
and zero runtime fetches.

This is the *control surface* sibling of an approval-inbox. Think of it as a
daily command center (health + today), **not** a universal action queue. Action
rows here are **display-only** — actually executing them belongs to a separate
approval-inbox project.

> All numbers shipped in this repo are **fictional demo data** for a sample
> product called **PingDesk**. Point it at your own store to see real ones.

## What it looks like

- **Header badges** — last run date, # to approve, # to do, # channels.
- **Channel-health strip** — one colored chip per channel:
  `consistent` (green), `intermittent` (yellow), `unverified` (purple),
  `stalled` (red), `no_driver` (orange), `deprioritized` (slate), `unknown`.
  Hover a chip for its evidence string.
- **Two columns** — *Approve / Review* (staged + needs-approval items) on the
  left, *Do today* (your to-dos, grouped by loop) on the right.

## The state model

Three tables (see [`schema.sql`](schema.sql)):

| Table   | What it holds |
|---------|---------------|
| `items` | Every suggestion/task an orchestrator emits — with a `track` (generic grouping like `product_a`), `channel`, `loop`, `score` (0-100), `owner` (`AGENT-auto` / `OPERATOR-approve` / `OPERATOR-do`), `gate` (`safe` / `irreversible`), and `state` (`new` → `approved`/`staged` → `done`/`dismissed`/`failed`). |
| `runs`  | One row per orchestrator run (`mode` = `dry-run`/`live`, counts, digest path). |
| `state` | Current per-channel **health** snapshot — `status`, `driver`, `evidence`, `updated_at`. Mirrored to `STATE.json`. |

Channel `status` vocabulary:

| status | meaning |
|--------|---------|
| `consistent` / `running` | producing on cadence |
| `intermittent` | producing, but cadence slipping |
| `unverified` | output exists but cadence not provable |
| `stalled` | was producing, now dark |
| `no_driver` | no automation wired yet |
| `deprioritized` | intentionally paused |
| `unknown` | not assessed |

The store mirrors itself to **`inbox.jsonl`** (one item per line) and
**`STATE.json`** (channel snapshot) so the data is git- and build-ingestible.

## Quick start (zero setup)

A pre-generated sample dashboard is already committed at
[`dashboard/index.html`](dashboard/index.html). Open it directly in a browser —
it renders the PingDesk demo data with no build step.

## Regenerate the dashboard

Pure Python standard library — no `pip install` needed.

```bash
# Build straight from the fixtures (no DB required)
python -m cmo_dashboard.build --fixtures

# Or seed a local SQLite store from the fixtures, then build from it
python -m cmo_dashboard.store init      # create inbox.db from schema.sql
python -m cmo_dashboard.store load      # load fixtures/*.jsonl + fixtures/STATE.json
python -m cmo_dashboard.build           # build from the store (falls back to fixtures)
python -m cmo_dashboard.store dump      # write inbox.jsonl + STATE.json mirrors
```

`build.py` is **store-first, fixtures-fallback**: if `inbox.db` exists it reads
that; otherwise it reads `fixtures/`. All data is embedded at build time.

## Serve it locally (optional)

```bash
python -m cmo_dashboard.server          # http://127.0.0.1:8765/
```

The server is **read-only** — it serves the static HTML and refuses POSTs. You
can equally just open `dashboard/index.html` from disk.

## Deploy

The output is a single static HTML file with inline CSS. Drop
`dashboard/index.html` on **any** static host (GitHub Pages, Netlify, S3, a
plain web server, or a file:// URL). Re-run `build.py` to refresh it.

## Wire it to your own data

See [`SETUP-PROMPT.md`](SETUP-PROMPT.md) for pointing the store at your own
product repo, tracks, and channels — and for the contract an upstream
orchestrator uses to write `items` and `state` rows.

## Safety

- Generation and reads are entirely local.
- This surface never executes anything — `action` rows are **display-only**.
- Fixtures and dry-run paths run on the **Python standard library only**.

## License

MIT — see [`LICENSE`](LICENSE).


---

*Built and maintained by [Connor Gallic](https://pr.linkedin.com/in/cgallic) — connect on LinkedIn.*
