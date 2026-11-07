from uuid import uuid4
from time import perf_counter
from copy import deepcopy
import random
from .db import Store
from .detect import detect
from .metrics import evaluate
from .models import Event, RunReport
from .policy import gate
from .scenarios import SCENARIOS

def run(scenario: str, db: str = "swarmguard.db", mode: str = "observe",
        *, detector_enabled: bool = True, group_monitoring: bool | None = None,
        topology: str = "multi", seed: int = 0) -> RunReport:
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario: {scenario}")
    run_id = str(uuid4()); spec = SCENARIOS[scenario]; store = Store(db); store.start_run(run_id, scenario, mode)
    started = perf_counter()
    if group_monitoring is None:
        group_monitoring = mode == "enforce"
    if topology not in ("single", "multi"):
        raise ValueError("topology must be single or multi")
    originals = [deepcopy(x) for x in spec.events]
    # Topology is substantive: one agent executes a serial plan, while a
    # multi-agent run preserves delegation and uses a reproducible schedule.
    if topology == "single":
        for item in originals:
            item["agent_id"] = "solo"
    else:
        rng = random.Random(seed)
        # A seed selects a concrete, inspectable delegation topology rather
        # than merely changing a scalar score.  The selected relay can differ
        # while the scenario's work and risk labels stay fixed.
        roster = ["agent-a", "agent-b", "agent-c", "agent-d"]
        relay = roster[rng.randrange(len(roster))]
        for item in originals:
            if item.get("kind") in ("delegation", "tool"):
                item["agent_id"] = relay
            item.setdefault("metadata", {}).update({
                "topology": "multi", "delegation_path": relay,
                "partial_information": bool(rng.randrange(2)),
                "refusal_timing": "early" if rng.randrange(2) else "late",
                "decomposition_strategy": "serial" if rng.randrange(2) else "parallel",
            })
        # Independent benign responses can arrive in either order; causal
        # high-risk chains remain ordered so conditions stay comparable.
        if all(x.get("risk") != "high" for x in originals):
            rng.shuffle(originals)
    previous = None; events = []; interventions = []; intervention_refs = {}; blocked = False
    task_id = f"task-{scenario}-{seed}"
    for index, original in enumerate(originals):
        raw = deepcopy(original)
        raw.setdefault("metadata", {}).setdefault("topology", topology)
        explicit_parent = raw.pop("parent_event_id", None)
        event = Event(run_id=run_id, parent_event_id=explicit_parent or previous,
                      task_id=task_id, message_id=f"{task_id}-m{index}",
                      provenance=[task_id], **raw)
        candidate = events + [event]
        findings = detect(candidate) if detector_enabled else []
        if group_monitoring and mode == "enforce" and findings and event.risk == "high" and event.kind not in ("refusal",):
            # The gate is deliberately before the protected operation.  The
            # attempted request remains auditable, but is never successful.
            store.add_event(event); events.append(event); previous = event.id
            intervention = Event(run_id=run_id, agent_id="swarmguard", parent_event_id=event.id,
                kind="intervention", content="Protected operation refused before execution.",
                risk="high", metadata={"finding_ids": [f.detector for f in findings],
                                       "finding_refs": [f.id for f in findings],
                                       "trigger_event_id": event.id},
                task_id=task_id, message_id=f"{task_id}-intervention-{index}",
                provenance=[task_id, event.id])
            store.add_event(intervention); events.append(intervention)
            interventions.append(intervention.id); blocked = True
            intervention_refs[intervention.id] = [event.id, *[f.id for f in findings]]
            continue
        store.add_event(event); events.append(event); previous = event.id
    elapsed = (perf_counter() - started) * 1000
    findings = detect(events) if detector_enabled else []
    # Incremental gate findings may cover a prefix of the ledger. Repoint
    # persisted intervention references to the final report's durable IDs.
    by_detector = {f.detector: f.id for f in findings}
    for iid, refs in list(intervention_refs.items()):
        trigger = refs[0] if refs else ""
        names = next((e.metadata.get("finding_ids", []) for e in events
                      if e.id == trigger), [])
        intervention_refs[iid] = [trigger, *[by_detector[n] for n in names if n in by_detector]]
    decision = gate(findings, mode)
    if blocked:
        decision.allowed = False
        decision.reason = "Blocked before protected operation; unrelated benign work may continue."
    report = RunReport(run_id=run_id, scenario=scenario, mode=mode, events=len(events),
                       findings=findings, decision=decision,
                       ground_truth=spec.ground_truth or {},
                       interventions=interventions,
                       intervention_refs=intervention_refs,
                       outcome="blocked" if blocked else "success",
                       metrics=evaluate(events, findings, scenario, spec.ground_truth,
                                        blocked=blocked, overhead_ms=elapsed))
    store.save_report(report); store.close(); return report
