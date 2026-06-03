"""cmo-daily-dashboard — portable command-center store.

SQLite-backed (Python stdlib only) store for Suggestions + Tasks ("items"),
per-channel health "state", and one row per "run". Mirrored to inbox.jsonl and
STATE.json so the inbox is git- and static-build-ingestible.

Read/dry-run safe: this module only reads/writes the local DB and mirror files.
It performs NO live actions of any kind. (Execution belongs to a separate
approval-inbox project; here, action rows are display-only.)

Usage:
    from cmo_dashboard.store import InboxStore
    s = InboxStore()                       # opens/creates ./inbox.db
    rid = s.start_run(mode="dry-run")
    s.add_item({
        "type": "suggestion", "track": "product_a", "loop": "revenue_leads",
        "channel": "leads", "title": "Leads down WoW (demo data)",
        "body": "20 leads (7d) vs 29 prior (demo data); drop in organic.",
        "evidence": {"leads_7d": 20, "prior_7d": 29, "_note": "demo data"},
        "score": 80, "owner": "OPERATOR-do", "gate": "safe",
    }, run_id=rid)
    s.finish_run(rid)
    s.export_jsonl(); s.export_state_json()

CLI:
    python -m cmo_dashboard.store init   # create the DB from schema.sql
    python -m cmo_dashboard.store load   # load fixtures/*.jsonl + fixtures/STATE.json
    python -m cmo_dashboard.store dump   # write inbox.jsonl + STATE.json from the DB
    python -m cmo_dashboard.store show   # print a quick summary
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from uuid import uuid4

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DB_PATH = ROOT / "inbox.db"
SCHEMA_PATH = ROOT / "schema.sql"
JSONL_PATH = ROOT / "inbox.jsonl"
STATE_JSON_PATH = ROOT / "STATE.json"
FIXTURES = ROOT / "fixtures"

_JSON_FIELDS = ("evidence", "action", "result")  # stored as TEXT, surfaced as objects


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class InboxStore:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        schema = SCHEMA_PATH.read_text(encoding="utf-8")
        self.conn.executescript(schema)
        self.conn.commit()

    # ---- items -----------------------------------------------------------
    def add_item(self, item: dict[str, Any], run_id: str | None = None) -> str:
        """Insert a suggestion/task. Returns its id.

        Honors dedup_key: if an item with the same dedup_key already exists,
        the existing id is returned and nothing is inserted (idempotent runs).
        """
        item = dict(item)
        dedup = item.get("dedup_key")
        if dedup:
            existing = self.conn.execute(
                "SELECT id FROM items WHERE dedup_key = ?", (dedup,)
            ).fetchone()
            if existing:
                return existing["id"]
            # Base-key match: same logical item from a prior day that is still active.
            # dedup_key convention = "{date}:{loop}:{channel}:{tag}" — strip the date.
            base = ":".join(dedup.split(":")[1:])
            if base:
                existing = self.conn.execute(
                    "SELECT id FROM items WHERE dedup_key LIKE ? "
                    "AND state NOT IN ('done','dismissed')",
                    (f"%:{base}",),
                ).fetchone()
                if existing:
                    return existing["id"]

        created = item.get("created_at") or _now()
        item_id = item.get("id") or self._gen_id(created, item.get("loop", "item"), dedup)
        cols = {
            "id": item_id,
            "created_at": created,
            "run_id": run_id or item.get("run_id"),
            "type": item["type"],
            "track": item["track"],
            "channel": item.get("channel"),
            "loop": item["loop"],
            "title": item["title"],
            "body": item.get("body"),
            "evidence": _dump(item.get("evidence")),
            "score": int(item.get("score", 50)),
            "owner": item.get("owner", "AGENT-auto"),
            "gate": item.get("gate", "safe"),
            "state": item.get("state", "new"),
            "action": _dump(item.get("action")),
            "result": _dump(item.get("result")),
            "acted_at": item.get("acted_at"),
            "dedup_key": dedup,
        }
        placeholders = ",".join("?" for _ in cols)
        self.conn.execute(
            f"INSERT INTO items ({','.join(cols)}) VALUES ({placeholders})",
            tuple(cols.values()),
        )
        self.conn.commit()
        return item_id

    def update_item(self, item_id: str, **fields: Any) -> None:
        if not fields:
            return
        for f in _JSON_FIELDS:
            if f in fields:
                fields[f] = _dump(fields[f])
        sets = ",".join(f"{k} = ?" for k in fields)
        self.conn.execute(
            f"UPDATE items SET {sets} WHERE id = ?", (*fields.values(), item_id)
        )
        self.conn.commit()

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _row_to_item(row) if row else None

    def query_items(self, **filters: Any) -> list[dict[str, Any]]:
        limit = filters.pop("limit", None)
        order = filters.pop("order_by", "score DESC, created_at DESC")
        clause = " AND ".join(f"{k} = ?" for k in filters) if filters else "1=1"
        sql = f"SELECT * FROM items WHERE {clause} ORDER BY {order}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = self.conn.execute(sql, tuple(filters.values())).fetchall()
        return [_row_to_item(r) for r in rows]

    # ---- runs ------------------------------------------------------------
    def start_run(self, run_id: str | None = None, mode: str = "dry-run",
                  loops_run: Iterable[str] | None = None) -> str:
        run_id = run_id or _now()
        self.conn.execute(
            "INSERT OR REPLACE INTO runs (id, started_at, mode, loops_run) VALUES (?,?,?,?)",
            (run_id, _now(), mode, _dump(list(loops_run) if loops_run else None)),
        )
        self.conn.commit()
        return run_id

    def finish_run(self, run_id: str, counts: dict | None = None,
                   digest_path: str | None = None, notes: str | None = None) -> None:
        self.conn.execute(
            "UPDATE runs SET finished_at=?, counts=?, digest_path=?, notes=? WHERE id=?",
            (_now(), _dump(counts), digest_path, notes, run_id),
        )
        self.conn.commit()

    def last_run(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT id, mode FROM runs ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else {"id": "-", "mode": "-"}

    # ---- channel state ---------------------------------------------------
    def set_state(self, channel: str, status: str, track: str | None = None,
                  driver: str | None = None, evidence: str | None = None) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO state (channel, track, status, driver, evidence, updated_at)"
            " VALUES (?,?,?,?,?,?)",
            (channel, track, status, driver, evidence, _now()),
        )
        self.conn.commit()

    def get_states(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM state ORDER BY channel").fetchall()
        return [dict(r) for r in rows]

    # ---- mirrors ---------------------------------------------------------
    def export_jsonl(self, path: Path | str = JSONL_PATH) -> Path:
        path = Path(path)
        items = self.query_items(order_by="created_at ASC")
        with path.open("w", encoding="utf-8") as fh:
            for it in items:
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
        return path

    def export_state_json(self, path: Path | str = STATE_JSON_PATH) -> Path:
        """Merge the state table into STATE.json, preserving top-level keys
        (e.g. tracks) and any channels the DB hasn't touched. Never clobbers a
        hand-seeded structure."""
        path = Path(path)
        payload: dict[str, Any] = {}
        if path.exists():
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
        payload.setdefault("channels", {})
        for s in self.get_states():
            payload["channels"][s["channel"]] = {
                k: v for k, v in s.items() if k != "channel"
            }
        payload["as_of"] = _now()
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    # ---- fixtures --------------------------------------------------------
    def load_fixtures(self, jsonl: Path | str = FIXTURES / "inbox.jsonl",
                      state_json: Path | str = FIXTURES / "STATE.json") -> dict[str, int]:
        """Seed the DB from the fictional demo fixtures. Idempotent-ish: items
        are added with INSERT OR IGNORE semantics on primary key."""
        n_items = 0
        jsonl = Path(jsonl)
        if jsonl.exists():
            for line in jsonl.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                it = json.loads(line)
                try:
                    self.add_item(it)
                    n_items += 1
                except sqlite3.IntegrityError:
                    pass
        n_chan = 0
        state_json = Path(state_json)
        if state_json.exists():
            payload = json.loads(state_json.read_text(encoding="utf-8"))
            for ch, s in (payload.get("channels") or {}).items():
                self.set_state(
                    ch, s.get("status", "unknown"),
                    track=s.get("track"), driver=s.get("driver"),
                    evidence=s.get("evidence"),
                )
                n_chan += 1
        # Seed one demo run so the dashboard badge has a date.
        rid = self.start_run(mode="dry-run", loops_run=["revenue_leads", "traffic_seo"])
        self.finish_run(rid, counts={"items": n_items})
        return {"items": n_items, "channels": n_chan}

    def summary(self) -> dict[str, Any]:
        c = self.conn.execute
        return {
            "items": c("SELECT COUNT(*) FROM items").fetchone()[0],
            "suggestions": c("SELECT COUNT(*) FROM items WHERE type='suggestion'").fetchone()[0],
            "tasks": c("SELECT COUNT(*) FROM items WHERE type='task'").fetchone()[0],
            "needs_approval": c("SELECT COUNT(*) FROM items WHERE owner='OPERATOR-approve' AND state IN ('new','staged')").fetchone()[0],
            "todo": c("SELECT COUNT(*) FROM items WHERE owner='OPERATOR-do' AND state='new'").fetchone()[0],
            "staged": c("SELECT COUNT(*) FROM items WHERE state='staged'").fetchone()[0],
            "channels": c("SELECT COUNT(*) FROM state").fetchone()[0],
            "runs": c("SELECT COUNT(*) FROM runs").fetchone()[0],
        }

    @staticmethod
    def _gen_id(created: str, loop: str, dedup: str | None = None) -> str:
        if dedup:
            return re.sub(r"[^A-Za-z0-9]+", "-", dedup).strip("-")
        stamp = created.replace(":", "").replace("-", "").replace("+0000", "").replace("T", "-")
        return f"{loop}-{stamp}-{uuid4().hex[:6]}"


def _dump(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def _row_to_item(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    for f in _JSON_FIELDS:
        if d.get(f):
            try:
                d[f] = json.loads(d[f])
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "show"
    s = InboxStore()
    if cmd == "init":
        print(f"inbox.db ready at {s.db_path}")
    elif cmd == "load":
        print("loaded fixtures:", json.dumps(s.load_fixtures()))
    elif cmd == "dump":
        print("wrote", s.export_jsonl())
        print("wrote", s.export_state_json())
    elif cmd == "show":
        print(json.dumps(s.summary(), indent=2))
    else:
        print(f"unknown command: {cmd}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
