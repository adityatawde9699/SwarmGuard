from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field

EventKind = Literal["request", "response", "refusal", "delegation", "memory", "tool", "intervention"]
TaskStatus = Literal["pending", "running", "completed", "failed", "refused", "interrupted"]
MessageKind = Literal["request", "refusal", "delegation", "result"]
AgentAction = Literal["accept", "refuse", "delegate", "complete", "wait"]


class PolicyDecision(BaseModel):
    """Validated, auditable action returned by any agent policy."""
    action: AgentAction
    target: str | None = None
    delegation_targets: list[str] = Field(default_factory=list)
    content: str = ""
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def delegation_target(self) -> str | None:
        return self.target


class Objective(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    risk: Literal["benign", "low", "medium", "high"] = "benign"
    prohibited: bool = False


class AgentPolicy(BaseModel):
    """Deterministic, executable policy used by an Agent at every decision point."""
    refuse_prohibited: bool = True
    max_concurrent_tasks: int = 1
    delegation_targets: list[str] = Field(default_factory=list)

    def decide(self, agent: "Agent", task: "Task", context: "TaskContext | Objective | None" = None,
               objective: Objective | None = None) -> AgentAction:
        # Policies consume only the agent's local view.  The Objective argument
        # is retained for M1-M4 callers, but is no longer consulted when a
        # TaskContext is supplied.
        prohibited = (context.known_prohibited if isinstance(context, TaskContext)
                      else bool(getattr(context, "prohibited", False)))
        if prohibited and self.refuse_prohibited:
            return "refuse"
        if self.delegation_targets:
            return "delegate"
        return "complete"


class AgentState(BaseModel):
    status: Literal["idle", "working", "interrupted", "failed"] = "idle"
    active_task_ids: list[str] = Field(default_factory=list)
    completed_task_ids: list[str] = Field(default_factory=list)


class Agent(BaseModel):
    id: str
    name: str | None = None
    # Kept permissive so third-party/LLM policies can implement the same
    # decide protocol without becoming a required dependency.
    policy: Any = Field(default_factory=AgentPolicy)
    state: AgentState = Field(default_factory=AgentState)
    capabilities: set[str] = Field(default_factory=set)

    def decide(self, task: "Task", objective: Objective | None = None,
               context: "TaskContext | None" = None) -> AgentAction | PolicyDecision:
        return self.policy.decide(self, task, context or objective)


class TaskContext(BaseModel):
    """The deliberately incomplete, agent-local view of a task."""
    task_id: str
    local_goal: str
    known_risk: Literal["unknown", "benign", "low", "medium", "high"] = "unknown"
    known_prohibited: bool = False
    knowledge: dict[str, Any] = Field(default_factory=dict)
    local_messages: list["Message"] = Field(default_factory=list)


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    objective_id: str
    title: str
    creator_id: str
    assignee_id: str | None = None
    parent_task_id: str | None = None
    status: TaskStatus = "pending"
    children: list[str] = Field(default_factory=list)
    contribution_ids: list[str] = Field(default_factory=list)
    output: str | None = None
    local_contexts: dict[str, TaskContext] = Field(default_factory=dict)


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    kind: MessageKind
    sender_id: str
    recipient_id: str
    task_id: str
    content: str
    parent_message_id: str | None = None
    delivered: bool = True
    failure_reason: str | None = None


class ExperimentState(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: Literal["pending", "running", "completed", "failed"] = "pending"
    attempt: int = 0
    error: str | None = None
    checkpoint: int = 0
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Event(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    run_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    agent_id: str
    parent_event_id: str | None = None
    kind: EventKind
    content: str
    risk: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    message_id: str | None = None
    provenance: list[str] = Field(default_factory=list)

class Finding(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    detector: str
    severity: Literal["low", "medium", "high"]
    event_ids: list[str]
    explanation: str
    related_agents: list[str] = Field(default_factory=list)
    related_tasks: list[str] = Field(default_factory=list)
    basis: str | None = None

class Decision(BaseModel):
    mode: Literal["observe", "enforce"]
    allowed: bool
    reason: str
    findings: list[Finding] = Field(default_factory=list)
    intervention_id: str | None = None
    action: str | None = None

class RunReport(BaseModel):
    run_id: str
    scenario: str
    mode: str
    events: int
    findings: list[Finding]
    decision: Decision
    metrics: dict[str, float | None] = Field(default_factory=dict)
    ground_truth: dict[str, Any] = Field(default_factory=dict)
    interventions: list[str] = Field(default_factory=list)
    intervention_refs: dict[str, list[str]] = Field(default_factory=dict)
    outcome: str = "success"
