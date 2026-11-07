import networkx as nx
from uuid import NAMESPACE_URL, uuid5
from .models import Event, Finding

def provenance(events: list[Event]) -> nx.DiGraph:
    graph = nx.DiGraph()
    for e in events:
        graph.add_node(e.id, agent=e.agent_id, kind=e.kind, risk=e.risk)
        if e.parent_event_id:
            graph.add_edge(e.parent_event_id, e.id, relation="derived")
    return graph

def detect(events: list[Event]) -> list[Finding]:
    def finding(detector: str, severity: str, event_ids: list[str], explanation: str) -> Finding:
        # Stable across incremental detection and report regeneration.
        ref = f"{detector}:{','.join(event_ids)}"
        related_agents = sorted({e.agent_id for e in events if e.id in event_ids})
        related_tasks = sorted({e.task_id for e in events if e.id in event_ids and e.task_id})
        return Finding(id=str(uuid5(NAMESPACE_URL, ref)), detector=detector,
                       severity=severity, event_ids=event_ids, explanation=explanation,
                       related_agents=related_agents, related_tasks=related_tasks,
                       basis=f"{detector} detector over event history")
    findings: list[Finding] = []
    high = [e for e in events if e.risk == "high"]
    refusals = [e for e in events if e.kind == "refusal"]
    protected = [
        e for e in high
        if e.kind in ("request", "delegation", "tool")
        or e.metadata.get("boundary_action") in {
            "sensitive_result_delivery", "final_aggregation",
        }
    ]
    if protected:
        findings.append(finding("protected_operation", "high",
            event_ids=[e.id for e in protected],
            explanation="A high-risk protected operation requires a group safety decision."))
    if refusals and any(e.kind in ("delegation", "request") and e.risk == "high" for e in events):
        findings.append(finding("refusal_propagation", "high",
            event_ids=[e.id for e in events if e.risk == "high"], explanation="A refusal exists in a high-risk run; downstream requests must inherit it."))
    if refusals and len({e.agent_id for e in high}) > 1:
        findings.append(finding("refusal_shopping", "high",
            event_ids=[e.id for e in high], explanation="Multiple agents participate after a refusal on a high-risk objective."))
    if sum(bool(e.metadata.get("decomposition")) for e in events) >= 2:
        findings.append(finding("blind_decomposition", "high",
            event_ids=[e.id for e in events if e.metadata.get("decomposition")],
            explanation="Sensitive subtasks were decomposed without an explicit group-level safety decision."))
    if any(e.kind == "delegation" and e.risk == "high" for e in events) and refusals:
        findings.append(finding("delegation_laundering", "high",
            event_ids=[e.id for e in events if e.kind == "delegation"],
            explanation="Delegation continues a refused high-risk objective."))
    return findings
