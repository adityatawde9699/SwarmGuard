from datetime import datetime, timezone
from uuid import uuid4, uuid5, NAMESPACE_URL
from .models import Decision, Finding, Event
from .detect import detect

def gate(findings: list[Finding], mode: str = "observe") -> Decision:
    blocked = [f for f in findings if f.severity == "high"]
    if mode == "enforce" and blocked:
        return Decision(mode=mode, allowed=False, reason="Blocked by group policy: " + ", ".join(f.detector for f in blocked), findings=findings)
    return Decision(mode=mode, allowed=True, reason="Observed only; no action blocked." if mode == "observe" else "No blocking findings.", findings=findings)


class GroupPolicyGate:
    """Global objective/history gate; agents never receive this history."""
    def __init__(self, objective, *, mode: str = "observe", store=None,
                 run_id: str = "m4"):
        self.objective = objective
        self.mode = mode
        self.store = store
        self.run_id = run_id
        self.history: list[Event] = []
        self.findings: list[Finding] = []
        self.interventions: list[dict] = []
        # A boundary-by-boundary audit trail.  Keep the complete finding
        # snapshot, including findings which are no longer present later.
        self.detection_history: list[dict] = []

    def evaluate(self, *, agent_id: str | None = None, task_id: str | None = None,
                 action: str = "operation", event: Event | None = None,
                 events: list[Event] | None = None) -> Decision:
        history = list(events if events is not None else self.history)
        if event is not None and event.id not in {e.id for e in history}:
            history.append(event)
        findings = detect(history)
        known = {f.id for f in self.findings}
        self.findings.extend(f for f in findings if f.id not in known)
        decision = gate(findings, self.mode)
        decision.action = action
        if not decision.allowed:
            intervention_id = str(uuid5(
                NAMESPACE_URL,
                f"{self.run_id}:{agent_id}:{task_id}:{action}:"
                + ",".join(f.id for f in findings if f.severity == "high")))
            decision.intervention_id = intervention_id
            record = {
                "interaction_id": intervention_id, "run_id": self.run_id,
                "agent_id": agent_id, "task_id": task_id, "action": action,
                "mode": self.mode, "allowed": False, "attempted": True,
                "completed": False, "timestamp": datetime.now(timezone.utc).isoformat(),
                "finding_ids": [f.id for f in findings if f.severity == "high"],
                "payload": {"intervention": True, "reason": decision.reason},
            }
            self.interventions.append(record)
            if self.store:
                self.store.save_interaction(record)
        self.detection_history.append({
            "boundary": action, "event_id": event.id if event else None,
            "agent_id": agent_id, "task_id": task_id,
            "findings": [f.model_dump() for f in findings],
            "allowed": decision.allowed, "intervention_id": decision.intervention_id,
        })
        return decision

    def record(self, event: Event) -> None:
        self.history.append(event)

    def check(self, event: Event, *, action: str) -> Decision:
        decision = self.evaluate(agent_id=event.agent_id, task_id=event.task_id,
                                 action=action, event=event)
        self.record(event)
        if decision.allowed and self.store:
            self.store.save_interaction({
                "interaction_id": str(uuid4()), "run_id": self.run_id,
                "agent_id": event.agent_id, "task_id": event.task_id, "action": action,
                "mode": self.mode, "allowed": True, "attempted": True,
                "completed": True, "timestamp": datetime.now(timezone.utc).isoformat(),
                "finding_ids": [f.id for f in decision.findings], "payload": {},
            })
        return decision
