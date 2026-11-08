import json
import sqlite3
from pathlib import Path
from .models import Event, RunReport, ExperimentState, Objective, Task, Message, TaskContext

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, scenario TEXT NOT NULL, mode TEXT NOT NULL,
 started_at TEXT NOT NULL, report_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL, timestamp TEXT NOT NULL,
 agent_id TEXT NOT NULL, parent_event_id TEXT, kind TEXT NOT NULL,
 content TEXT NOT NULL, risk TEXT NOT NULL, metadata_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_run ON events(run_id);
CREATE TABLE IF NOT EXISTS findings (
 id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
 finding_ref TEXT,
 detector TEXT NOT NULL, severity TEXT NOT NULL, event_ids_json TEXT NOT NULL,
 explanation TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interventions (
 intervention_id TEXT PRIMARY KEY, run_id TEXT NOT NULL,
 event_id TEXT NOT NULL, finding_refs_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS experiment_states (
 id TEXT PRIMARY KEY, status TEXT NOT NULL, attempt INTEGER NOT NULL,
 error TEXT, checkpoint INTEGER NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS objectives (id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (id TEXT PRIMARY KEY, objective_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (id TEXT PRIMARY KEY, task_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS decisions (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, agent_id TEXT NOT NULL,
 action TEXT NOT NULL, context_json TEXT NOT NULL, created_at TEXT NOT NULL
 ,metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS results (
 id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, payload TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trial_manifests (
 run_id TEXT PRIMARY KEY, payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS interactions (
 interaction_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, agent_id TEXT,
 task_id TEXT, action TEXT NOT NULL, mode TEXT NOT NULL, allowed INTEGER NOT NULL,
 attempted INTEGER NOT NULL, completed INTEGER NOT NULL, timestamp TEXT NOT NULL,
 finding_ids_json TEXT NOT NULL, payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_interactions_run ON interactions(run_id);
"""

class Store:
    def __init__(self, path: str | Path = "swarmguard.db"):
        self.path = str(path)
        self.con = sqlite3.connect(self.path)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        # M2 ledgers remain readable; these columns are additive.
        cols = {r[1] for r in self.con.execute("PRAGMA table_info(events)")}
        if "task_id" not in cols: self.con.execute("ALTER TABLE events ADD COLUMN task_id TEXT")
        if "message_id" not in cols: self.con.execute("ALTER TABLE events ADD COLUMN message_id TEXT")
        if "provenance_json" not in cols: self.con.execute("ALTER TABLE events ADD COLUMN provenance_json TEXT")
        if "finding_ref" not in {r[1] for r in self.con.execute("PRAGMA table_info(findings)")}: self.con.execute("ALTER TABLE findings ADD COLUMN finding_ref TEXT")
        if "metadata_json" not in {r[1] for r in self.con.execute("PRAGMA table_info(decisions)")}: self.con.execute("ALTER TABLE decisions ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'")
        self.con.commit()

    def start_run(self, run_id: str, scenario: str, mode: str) -> None:
        self.con.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, datetime('now'), NULL)", (run_id, scenario, mode))
        self.con.commit()

    def add_event(self, event: Event) -> None:
        self.con.execute("INSERT INTO events(id,run_id,timestamp,agent_id,parent_event_id,kind,content,risk,metadata_json,task_id,message_id,provenance_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (event.id, event.run_id, event.timestamp.isoformat(), event.agent_id,
             event.parent_event_id, event.kind,              event.content, event.risk, json.dumps(event.metadata), event.task_id, event.message_id,
             json.dumps(event.provenance)))
        self.con.commit()

    def events(self, run_id: str) -> list[Event]:
        rows = self.con.execute("SELECT * FROM events WHERE run_id=? ORDER BY timestamp, rowid", (run_id,)).fetchall()
        return [Event(id=r["id"], run_id=r["run_id"], timestamp=r["timestamp"], agent_id=r["agent_id"],
                      parent_event_id=r["parent_event_id"], kind=r["kind"], content=r["content"],
                      risk=r["risk"], metadata=json.loads(r["metadata_json"]),
                      task_id=r["task_id"], message_id=r["message_id"],
                      provenance=json.loads(r["provenance_json"] or "[]")) for r in rows]

    def query_events(self, run_id: str, *, agent_id: str | None = None,
                     kind: str | None = None) -> list[Event]:
        """Query the ledger without exposing raw SQLite rows to callers."""
        clauses, args = ["run_id=?"], [run_id]
        if agent_id:
            clauses.append("agent_id=?"); args.append(agent_id)
        if kind:
            clauses.append("kind=?"); args.append(kind)
        rows = self.con.execute(
            f"SELECT * FROM events WHERE {' AND '.join(clauses)} ORDER BY timestamp, rowid", args
        ).fetchall()
        return [Event(id=r["id"], run_id=r["run_id"], timestamp=r["timestamp"], agent_id=r["agent_id"],
                      parent_event_id=r["parent_event_id"], kind=r["kind"], content=r["content"],
                      risk=r["risk"], metadata=json.loads(r["metadata_json"]),
                      task_id=r["task_id"], message_id=r["message_id"],
                      provenance=json.loads(r["provenance_json"] or "[]")) for r in rows]

    def lineage(self, run_id: str) -> dict[str, list[str]]:
        """Return parent/message provenance for audit and report consumers."""
        return {e.id: [x for x in (e.parent_event_id, *e.provenance) if x]
                for e in self.events(run_id)}

    def save_report(self, report: RunReport) -> None:
        self.con.execute("UPDATE runs SET report_json=? WHERE run_id=?", (report.model_dump_json(), report.run_id))
        for f in report.findings:
            self.con.execute("INSERT INTO findings(run_id,finding_ref,detector,severity,event_ids_json,explanation) VALUES(?,?,?,?,?,?)",
                             (report.run_id, f.id, f.detector, f.severity, json.dumps(f.event_ids), f.explanation))
        for iid, refs in report.intervention_refs.items():
            event_id = report.intervention_refs[iid][0] if refs else ""
            self.con.execute("INSERT OR REPLACE INTO interventions VALUES(?,?,?,?)",
                             (iid, report.run_id, event_id, json.dumps(refs)))
        self.con.commit()

    def save_experiment_state(self, state: ExperimentState) -> None:
        """Persist a checkpoint so an interrupted experiment can be resumed."""
        self.con.execute(
            "INSERT OR REPLACE INTO experiment_states VALUES (?,?,?,?,?,?)",
            (state.id, state.status, state.attempt, state.error, state.checkpoint,
             state.updated_at.isoformat()))
        self.con.commit()

    def experiment_state(self, state_id: str) -> ExperimentState | None:
        row = self.con.execute("SELECT * FROM experiment_states WHERE id=?",
                               (state_id,)).fetchone()
        if row is None:
            return None
        return ExperimentState(id=row["id"], status=row["status"], attempt=row["attempt"],
                               error=row["error"], checkpoint=row["checkpoint"],
                               updated_at=row["updated_at"])

    def close(self) -> None:
        self.con.close()

    def save_interaction(self, interaction: dict) -> None:
        """Append a durable, auditable gate decision (including blocked attempts)."""
        self.con.execute(
            "INSERT OR REPLACE INTO interactions VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (interaction["interaction_id"], interaction.get("run_id", "m4"),
             interaction.get("agent_id"), interaction.get("task_id"),
             interaction["action"], interaction["mode"], int(interaction["allowed"]),
             int(interaction.get("attempted", True)), int(interaction.get("completed", False)),
             interaction["timestamp"], json.dumps(interaction.get("finding_ids", [])),
             json.dumps(interaction.get("payload", {}))))
        self.con.commit()

    def interactions(self, run_id: str | None = None) -> list[dict]:
        sql = "SELECT * FROM interactions"
        args: tuple = ()
        if run_id is not None:
            sql += " WHERE run_id=?"; args = (run_id,)
        sql += " ORDER BY timestamp, rowid"
        return [dict(r) | {"finding_ids": json.loads(r["finding_ids_json"]),
                           "payload": json.loads(r["payload_json"])}
                for r in self.con.execute(sql, args).fetchall()]

    # M4.1 append-only interaction ledger. Payloads retain forward-compatible
    # model fields and allow complete reconstruction after a process restart.
    def save_objective(self, objective: Objective) -> None:
        self.con.execute("INSERT OR REPLACE INTO objectives VALUES (?,?)",
                         (objective.id, objective.model_dump_json()))
        self.con.commit()

    def save_task(self, task: Task) -> None:
        self.con.execute("INSERT OR REPLACE INTO tasks VALUES (?,?,?)",
                         (task.id, task.objective_id, task.model_dump_json()))
        self.con.commit()

    def save_message(self, message: Message) -> None:
        self.con.execute("INSERT OR REPLACE INTO messages VALUES (?,?,?)",
                         (message.id, message.task_id, message.model_dump_json()))
        self.con.commit()

    def save_decision(self, task_id: str, agent_id: str, action: str,
                      context: TaskContext, metadata: dict | None = None) -> None:
        self.con.execute(
            "INSERT INTO decisions(task_id,agent_id,action,context_json,created_at,metadata_json) VALUES(?,?,?,?,datetime('now'),?)",
            (task_id, agent_id, action, context.model_dump_json(),
             json.dumps(metadata or {}, sort_keys=True)))
        self.con.commit()

    def save_result(self, task_id: str, result: object) -> None:
        payload = result.model_dump_json() if hasattr(result, "model_dump_json") else json.dumps(result)
        self.con.execute("INSERT INTO results(task_id,payload,created_at) VALUES(?,?,datetime('now'))",
                         (task_id, payload))
        self.con.commit()

    def save_trial_manifest(self, run_id: str, manifest: dict) -> None:
        self.con.execute(
            "INSERT OR REPLACE INTO trial_manifests(run_id,payload,created_at) "
            "VALUES(?,?,datetime('now'))",
            (run_id, json.dumps(manifest, sort_keys=True)),
        )
        self.con.commit()

    def trial_manifest(self, run_id: str) -> dict | None:
        row = self.con.execute(
            "SELECT payload FROM trial_manifests WHERE run_id=?", (run_id,)
        ).fetchone()
        return json.loads(row["payload"]) if row else None

    def interaction_provenance(self) -> dict:
        """Return the durable Objective→Task→Message→Decision→Result chain."""
        return {
             "objectives": [json.loads(r[0]) for r in self.con.execute("SELECT payload FROM objectives ORDER BY rowid")],
             "tasks": [json.loads(r[0]) for r in self.con.execute("SELECT payload FROM tasks ORDER BY rowid")],
             "messages": [json.loads(r[0]) for r in self.con.execute("SELECT payload FROM messages ORDER BY rowid")],
             "decisions": [dict(r) for r in self.con.execute("SELECT * FROM decisions ORDER BY id")],
             "results": [dict(r) for r in self.con.execute("SELECT * FROM results ORDER BY id")]}
