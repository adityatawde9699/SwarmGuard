"""Provider-independent, opt-in LLM policies.

The adapter contract is deliberately tiny and uses only the standard library.
LLM output is never trusted until it passes :class:`PolicyDecision` validation.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

from .models import Agent, PolicyDecision, Task, TaskContext


class LLMAdapter(Protocol):
    provider: str
    model: str

    def complete(self, prompt: str, *, temperature: float = 0.0,
                 seed: int | None = None) -> str | dict[str, Any]: ...


class Policy(Protocol):
    """Common structural interface implemented by deterministic and LLM policies."""
    def decide(self, agent: Agent, task: Task,
               context: TaskContext | None = None, objective: Any = None) -> Any: ...


@dataclass
class LocalHTTPAdapter:
    """Ollama ``/api/chat`` and OpenAI-compatible ``/v1/chat/completions``."""

    endpoint: str
    model: str
    provider: str = "local-http"
    timeout: float = 30.0

    def complete(self, prompt: str, *, temperature: float = 0.0,
                 seed: int | None = None) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
        }
        if seed is not None:
            payload["seed"] = seed
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode())
        # Ollama and OpenAI response shapes.
        if "message" in body:
            return body["message"]["content"]
        return body["choices"][0]["message"]["content"]


@dataclass
class FakeLLMAdapter:
    """Deterministic adapter used by tests and offline experiments."""

    response: str | dict[str, Any] | PolicyDecision
    provider: str = "fake"
    model: str = "fake-v1"
    calls: int = 0

    def complete(self, prompt: str, *, temperature: float = 0.0,
                 seed: int | None = None) -> str | dict[str, Any]:
        self.calls += 1
        return self.response


class LLMPolicy:
    """A policy implementation consuming only task-local context."""

    def __init__(self, adapter: LLMAdapter, *, temperature: float = 0.0,
                 seed: int | None = None, delegation_targets: list[str] | None = None):
        self.adapter = adapter
        self.temperature = temperature
        self.seed = seed
        self.delegation_targets = delegation_targets or []

    def _prompt(self, agent: Agent, task: Task, context: TaskContext) -> str:
        local = {
            "agent_id": agent.id, "task": task.model_dump(mode="json", exclude={"local_contexts"}),
            "context": context.model_dump(mode="json"),
            "allowed_actions": ["accept", "refuse", "delegate", "complete", "wait"],
        }
        return ("Return JSON only with action, optional target, content and reason. "
                "You are a local task agent; do not infer or request global objective data.\n"
                + json.dumps(local, sort_keys=True, separators=(",", ":")))

    def decide(self, agent: Agent, task: Task,
               context: TaskContext | None = None, objective: Any = None) -> PolicyDecision:
        if context is None:
            context = TaskContext(task_id=task.id, local_goal=task.title)
        prompt = self._prompt(agent, task, context)
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        started = time.perf_counter()
        metadata: dict[str, Any] = {
            "provider": getattr(self.adapter, "provider", "unknown"),
            "model": getattr(self.adapter, "model", "unknown"),
            "temperature": self.temperature, "seed": self.seed,
            "prompt_hash": prompt_hash,
        }
        try:
            raw = self.adapter.complete(prompt, temperature=self.temperature, seed=self.seed)
            if isinstance(raw, PolicyDecision):
                decision = raw
            else:
                if isinstance(raw, str):
                    raw = json.loads(raw)
                if not isinstance(raw, dict):
                    raise ValueError("adapter response must be JSON object")
                decision = PolicyDecision.model_validate(raw)
            if decision.action == "delegate" and not decision.target and self.delegation_targets:
                decision.target = self.delegation_targets[0]
            metadata["latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
            decision.metadata = {**decision.metadata, **metadata}
            return decision
        except Exception as exc:
            metadata.update({"latency_ms": round((time.perf_counter() - started) * 1000, 3),
                             "error": f"{type(exc).__name__}: {exc}"})
            # Failure is safe by default: refusal is explicit and auditable.
            return PolicyDecision(action="refuse", reason="LLM policy failure",
                                  metadata=metadata)


DeterministicPolicy = __import__("swarmguard.models", fromlist=["AgentPolicy"]).AgentPolicy
LLMDecision = PolicyDecision
