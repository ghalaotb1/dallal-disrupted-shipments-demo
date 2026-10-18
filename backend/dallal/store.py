"""Durable operational store (SQLite, WAL). One consistent state for runs, inquiries, messages, plans, approvals and the audit feed.

The same schema runs on a Postgres-compatible store later; everything is JSON-in-columns on purpose so the API contracts do not
depend on the engine. Idempotency is a database property here: `webhook_events.event_key` is UNIQUE, so a duplicate delivery of
the same WhatsApp event (Meta retries for up to 7 days) cannot be processed twice, even across processes.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(run_id TEXT PRIMARY KEY, subject_id TEXT, status TEXT, engine TEXT, scenario_id TEXT, origin TEXT, bundle_json TEXT, checkpoint_json TEXT,
  run_json TEXT, created_at REAL, updated_at REAL);
CREATE INDEX IF NOT EXISTS runs_subject ON runs(subject_id, updated_at);
CREATE TABLE IF NOT EXISTS inquiries(inquiry_id TEXT PRIMARY KEY, run_id TEXT, spec_id TEXT, target TEXT, scope TEXT, recipient_hash TEXT, recipient_ref TEXT, delivery_mode TEXT,
  status TEXT, asked_real REAL, deadline_real REAL, answered_real REAL, outcome TEXT, question TEXT, answers_json TEXT, payload_json TEXT, subject_id TEXT);
CREATE INDEX IF NOT EXISTS inq_status ON inquiries(status, deadline_real);
CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY AUTOINCREMENT, inquiry_id TEXT, direction TEXT, provider TEXT, wamid TEXT, mode TEXT, status TEXT, kind TEXT, body_json TEXT, created_at REAL);
CREATE UNIQUE INDEX IF NOT EXISTS msg_wamid ON messages(direction, wamid) WHERE wamid IS NOT NULL;
CREATE TABLE IF NOT EXISTS webhook_events(event_key TEXT PRIMARY KEY, received_at REAL, kind TEXT);
CREATE TABLE IF NOT EXISTS timeline(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, kind TEXT, subject_id TEXT, run_id TEXT, payload_json TEXT);
CREATE TABLE IF NOT EXISTS plans(plan_id TEXT PRIMARY KEY, scope TEXT, status TEXT, plan_json TEXT, created_at REAL, decided_by TEXT, decided_at REAL);
CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, tbl TEXT, row_json TEXT);
CREATE TABLE IF NOT EXISTS optouts(recipient_hash TEXT PRIMARY KEY, ts REAL);
"""


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript(SCHEMA)
        self.lock = threading.RLock()

    # ── generic helpers ──
    def q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def x(self, sql: str, args: tuple = ()) -> sqlite3.Cursor:
        with self.lock:
            return self.db.execute(sql, args)

    # ── runs ──
    def save_run(self, run_id: str, subject_id: str, status: str, engine: str, scenario_id: str | None, origin: str | None, bundle: str | None, checkpoint: dict | None, run: dict) -> None:
        now = time.time()
        with self.lock:
            existing = self.db.execute("SELECT created_at, bundle_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
            created = existing["created_at"] if existing else now
            bundle = bundle if bundle is not None else (existing["bundle_json"] if existing else None)
            self.db.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?,?,?)", (run_id, subject_id, status, engine, scenario_id, origin, bundle,
                            json.dumps(checkpoint, default=str) if checkpoint else None, json.dumps(run, default=str), created, now))

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        r = self.q("SELECT * FROM runs WHERE run_id=?", (run_id,))
        if not r:
            return None
        d = dict(r[0])
        d["run"] = json.loads(d.pop("run_json"))
        ck = d.pop("checkpoint_json")
        d["checkpoint"] = json.loads(ck) if ck else None
        return d

    def list_runs(self, subject_id: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.q("SELECT run_id, subject_id, status, engine, scenario_id, origin, created_at, updated_at, run_json FROM runs " + ("WHERE subject_id=? " if subject_id else "")
                      + "ORDER BY updated_at DESC LIMIT ?", ((subject_id, limit) if subject_id else (limit,)))
        out = []
        for r in rows:
            d = dict(r)
            d["run"] = json.loads(d.pop("run_json"))
            out.append(d)
        return out

    # ── inquiries & messages ──
    def save_inquiry(self, **f: Any) -> None:
        cols = ",".join(f)
        with self.lock:
            self.db.execute(f"INSERT OR REPLACE INTO inquiries({cols}) VALUES({','.join('?' * len(f))})", tuple(json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in f.values()))

    def update_inquiry(self, inquiry_id: str, **f: Any) -> None:
        sets = ",".join(f"{k}=?" for k in f)
        with self.lock:
            self.db.execute(f"UPDATE inquiries SET {sets} WHERE inquiry_id=?", (*[json.dumps(v, default=str) if isinstance(v, (dict, list)) else v for v in f.values()], inquiry_id))

    def get_inquiry(self, inquiry_id: str) -> dict[str, Any] | None:
        r = self.q("SELECT * FROM inquiries WHERE inquiry_id=?", (inquiry_id,))
        return dict(r[0]) if r else None

    def inquiries_for(self, *, run_id: str | None = None, subject_id: str | None = None, status: str | None = None) -> list[dict[str, Any]]:
        where, args = [], []
        for col, v in (("run_id", run_id), ("subject_id", subject_id), ("status", status)):
            if v is not None:
                where.append(f"{col}=?")
                args.append(v)
        return [dict(r) for r in self.q("SELECT * FROM inquiries" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY asked_real", tuple(args))]

    def pending_for_recipient(self, recipient_ref: str) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q("SELECT * FROM inquiries WHERE recipient_ref=? AND status='awaiting' ORDER BY asked_real DESC", (recipient_ref,))]

    def overdue(self, now: float) -> list[dict[str, Any]]:
        return [dict(r) for r in self.q("SELECT * FROM inquiries WHERE status='awaiting' AND deadline_real<=?", (now,))]

    def reset_demo(self) -> dict[str, int]:
        """Wipe runs, inquiries, messages, plans, ledger and opt-outs so a demonstration replays from the same starting point.
        The audit timeline is kept (ids keep increasing) so connected browsers do not miss or replay events."""
        counts: dict[str, int] = {}
        with self.lock:
            for table in ("messages", "inquiries", "runs", "plans", "ledger", "optouts", "webhook_events"):
                counts[table] = self.db.execute(f"DELETE FROM {table}").rowcount  # noqa: S608 - fixed table names
        return counts

    def backup(self, dest: str | Path) -> str:
        """Consistent online snapshot (SQLite backup API; safe while the service is writing)."""
        import sqlite3 as _sq

        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        out = _sq.connect(str(dest))
        try:
            with self.lock:
                self.db.backup(out)
        finally:
            out.close()
        return str(dest)

    def held_message(self, inquiry_id: str) -> dict[str, Any] | None:
        for m in self.messages_for(inquiry_id):
            if m["direction"] == "out" and m["status"] == "held_for_approval":
                return m
        return None

    def finalize_message(self, message_id: int, wamid: str | None, status: str, body: dict) -> None:
        self.x("UPDATE messages SET wamid=?, status=?, body_json=? WHERE id=?", (wamid, status, json.dumps(body, default=str), message_id))

    def add_message(self, inquiry_id: str | None, direction: str, provider: str, wamid: str | None, mode: str, status: str, kind: str, body: dict) -> bool:
        """Returns False if this (direction, wamid) was already stored - a duplicate."""
        try:
            with self.lock:
                self.db.execute("INSERT INTO messages(inquiry_id,direction,provider,wamid,mode,status,kind,body_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                                (inquiry_id, direction, provider, wamid, mode, status, kind, json.dumps(body, default=str), time.time()))
            return True
        except sqlite3.IntegrityError:
            return False

    def set_message_status(self, wamid: str, status: str) -> list[dict[str, Any]]:
        order = {"queued": 0, "sandbox_accepted": 1, "accepted": 1, "sent": 2, "sandbox_sent": 2, "delivered": 3, "sandbox_delivered": 3, "read": 4, "sandbox_read": 4}
        rows = self.q("SELECT * FROM messages WHERE direction='out' AND wamid=?", (wamid,))
        if not rows:
            return []
        cur = rows[0]["status"]
        if status == "failed" or order.get(status, 0) >= order.get(cur, 0):  # statuses can arrive out of order: never move backwards
            self.x("UPDATE messages SET status=? WHERE direction='out' AND wamid=?", (status, wamid))
        return [dict(r) for r in self.q("SELECT * FROM messages WHERE direction='out' AND wamid=?", (wamid,))]

    def messages_for(self, inquiry_id: str) -> list[dict[str, Any]]:
        out = []
        for r in self.q("SELECT * FROM messages WHERE inquiry_id=? ORDER BY id", (inquiry_id,)):
            d = dict(r)
            d["body"] = json.loads(d.pop("body_json"))
            out.append(d)
        return out

    def seen_event(self, key: str, kind: str) -> bool:
        """Atomically record a webhook event; True if it was ALREADY seen (i.e. a duplicate)."""
        try:
            with self.lock:
                self.db.execute("INSERT INTO webhook_events VALUES(?,?,?)", (key, time.time(), kind))
            return False
        except sqlite3.IntegrityError:
            return True

    # ── timeline (audit feed) ──
    def emit(self, kind: str, subject_id: str | None, run_id: str | None, payload: dict[str, Any]) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO timeline(ts,kind,subject_id,run_id,payload_json) VALUES(?,?,?,?,?)", (time.time(), kind, subject_id, run_id, json.dumps(payload, default=str)))
            return int(cur.lastrowid or 0)

    def timeline(self, after: int = 0, limit: int = 200, subject_id: str | None = None) -> list[dict[str, Any]]:
        rows = self.q("SELECT * FROM timeline WHERE id>? " + ("AND subject_id=? " if subject_id else "") + "ORDER BY id LIMIT ?", ((after, subject_id, limit) if subject_id else (after, limit)))
        return [{**{k: r[k] for k in ("id", "ts", "kind", "subject_id", "run_id")}, "payload": json.loads(r["payload_json"])} for r in rows]

    # ── opt-outs, plans, ledger ──
    def opt_out(self, recipient_hash: str) -> None:
        self.x("INSERT OR REPLACE INTO optouts VALUES(?,?)", (recipient_hash, time.time()))

    def is_opted_out(self, recipient_hash: str) -> bool:
        return bool(self.q("SELECT 1 FROM optouts WHERE recipient_hash=?", (recipient_hash,)))

    def save_plan(self, plan_id: str, scope: str, status: str, plan: dict, decided_by: str | None = None) -> None:
        now = time.time()
        with self.lock:
            old = self.db.execute("SELECT created_at FROM plans WHERE plan_id=?", (plan_id,)).fetchone()
            self.db.execute("INSERT OR REPLACE INTO plans VALUES(?,?,?,?,?,?,?)", (plan_id, scope, status, json.dumps(plan, default=str), old["created_at"] if old else now, decided_by, now if decided_by else None))

    def get_plan(self, plan_id: str) -> dict[str, Any] | None:
        r = self.q("SELECT * FROM plans WHERE plan_id=?", (plan_id,))
        if not r:
            return None
        d = dict(r[0])
        d["plan"] = json.loads(d.pop("plan_json"))
        return d

    def list_plans(self) -> list[dict[str, Any]]:
        out = []
        for r in self.q("SELECT * FROM plans ORDER BY created_at DESC"):
            d = dict(r)
            d["plan"] = json.loads(d.pop("plan_json"))
            out.append(d)
        return out

    def ledger_add(self, table: str, row: dict[str, Any]) -> None:
        self.x("INSERT INTO ledger(ts,tbl,row_json) VALUES(?,?,?)", (time.time(), table, json.dumps(row, default=str)))

    def ledger(self, limit: int = 500) -> list[dict[str, Any]]:
        return [{"id": r["id"], "ts": r["ts"], "table": r["tbl"], **json.loads(r["row_json"])} for r in self.q("SELECT * FROM ledger ORDER BY id DESC LIMIT ?", (limit,))]
