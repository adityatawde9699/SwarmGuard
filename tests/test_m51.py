import json

import pytest

from swarmguard.db import Store
from swarmguard.engine import SimulationEngine
from swarmguard.llm import (
    FakeLLMAdapter,
    LLMPolicy,
    OllamaAdapter,
    OpenAICompatibleAdapter,
)
from swarmguard.models import Agent, AgentPolicy, Objective, Task, TaskContext


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


def test_ollama_request_disables_streaming_and_uses_options(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return _Response({
            "model": "llama3.2:latest",
            "message": {"content": '{"action":"complete"}'},
            "prompt_eval_count": 11,
            "eval_count": 7,
            "total_duration": 1234,
        })

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    result = OllamaAdapter(timeout=4).complete("prompt", temperature=.2, seed=9)
    assert json.loads(result)["action"] == "complete"
    assert captured["body"]["stream"] is False
    assert captured["body"]["options"] == {"temperature": .2, "seed": 9}
    assert captured["timeout"] == 4
    adapter = OllamaAdapter()
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: _Response({
        "model": "llama3.2:latest", "message": {"content": "{}"},
        "prompt_eval_count": 11, "eval_count": 7,
    }))
    adapter.complete("prompt")
    assert adapter.last_metadata["total_tokens"] == 18
    assert adapter.last_metadata["model_revision"] == "llama3.2:latest"


def test_openai_compatible_request_and_response(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.data)
        return _Response({
            "system_fingerprint": "local-revision",
            "choices": [{"message": {"content": '{"action":"refuse"}'}}],
            "usage": {"prompt_tokens": 13, "completion_tokens": 5, "total_tokens": 18},
        })

    monkeypatch.setenv("TEST_API_KEY", "secret")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    adapter = OpenAICompatibleAdapter(api_key_env="TEST_API_KEY")
    result = adapter.complete("prompt")
    assert json.loads(result)["action"] == "refuse"
    assert captured["headers"]["Authorization"] == "Bearer secret"
    assert captured["body"]["messages"][0]["content"] == "prompt"
    assert adapter.last_metadata["total_tokens"] == 18
    assert adapter.last_metadata["model_revision"] == "local-revision"


def test_fake_adapter_is_agent_specific_and_records_requests():
    adapter = FakeLLMAdapter(
        responses={("a", "task-a"): [{"action": "complete"}, {"action": "wait"}]},
    )
    policy = LLMPolicy(adapter)
    objective = Objective(name="safe", description="safe")
    task = Task(objective_id=objective.id, title="local", creator_id="a", id="task-a")
    context = TaskContext(task_id=task.id, local_goal="local")
    assert policy.decide(Agent(id="a"), task, context).action == "complete"
    assert policy.decide(Agent(id="a"), task, context).action == "wait"
    assert len(adapter.calls) == 2


def test_malformed_and_failed_requests_fail_closed_with_distinct_metadata():
    objective = Objective(name="safe", description="safe")
    task = Task(objective_id=objective.id, title="local", creator_id="a")
    malformed = LLMPolicy(FakeLLMAdapter(response="{bad"))
    failed = LLMPolicy(FakeLLMAdapter(response={"action": "complete"}, failures=1))
    malformed_result = malformed.decide(Agent(id="a"), task)
    failed_result = failed.decide(Agent(id="a"), task)
    assert malformed_result.action == failed_result.action == "refuse"
    assert malformed_result.metadata["response_validation"] == "failed"
    assert malformed_result.metadata["failure_classification"] == "invalid_response"
    assert failed_result.metadata["error"].startswith("LLMRequestError")


def test_global_objective_is_not_in_prompt_when_context_is_missing():
    objective = Objective(name="hidden", description="DO NOT LEAK THIS", prohibited=True)
    adapter = FakeLLMAdapter(response={"action": "complete"})
    policy = LLMPolicy(adapter)
    task = Task(objective_id=objective.id, title="local task", creator_id="agent")
    policy.decide(Agent(id="agent"), task, objective=objective)
    prompt = adapter.calls[0]["prompt"]
    assert objective.description not in prompt
    assert str(objective.prohibited) not in prompt
    assert objective.id not in prompt


def test_unknown_delegation_target_is_rejected_before_task_creation():
    objective = Objective(name="safe", description="safe")
    policy = LLMPolicy(FakeLLMAdapter(response={
        "action": "delegate", "target": "missing",
    }))
    engine = SimulationEngine([Agent(id="lead", policy=policy)], objective)
    root = engine.add_task(Task(objective_id=objective.id, title="safe",
                                creator_id="lead", assignee_id="lead"))
    engine.run(root)
    assert root.status == "refused"
    assert len(engine.tasks) == 1
    assert any(e.metadata.get("authorization") == "rejected" for e in engine.events)


def test_llm_decision_persists_metadata_and_gate_remains_authoritative(tmp_path):
    objective = Objective(name="safe", description="safe")
    adapter = FakeLLMAdapter(response={"action": "complete", "content": "secret"})
    policy = LLMPolicy(adapter, seed=3)
    store = Store(tmp_path / "m51.db")
    engine = SimulationEngine([Agent(id="lead", policy=policy)], objective,
                              store=store, mode="enforce")
    task = engine.add_task(Task(objective_id=objective.id, title="local",
                                creator_id="lead", assignee_id="lead",
                                local_contexts={"lead": TaskContext(
                                    task_id="x", local_goal="harmless formatting")}))
    engine.run(task)
    row = store.con.execute("SELECT metadata_json FROM decisions").fetchone()
    assert row is not None
    metadata = json.loads(row[0])
    assert metadata["provider"] == "fake"
    assert metadata["prompt_template_version"]
    assert task.status == "completed"
    store.close()


def test_deterministic_policy_returns_validated_decision():
    objective = Objective(name="safe", description="safe")
    agent = Agent(id="a", policy=AgentPolicy())
    task = Task(objective_id=objective.id, title="safe", creator_id="a")
    assert agent.decide(task, context=TaskContext(task_id=task.id,
                                                  local_goal="safe")).action == "complete"
