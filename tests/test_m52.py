import json

from swarmguard.engine import SimulationEngine
from swarmguard.experiment import M52_CONDITIONS, experiment, validate_trial_manifest
from swarmguard.llm import FakeLLMAdapter, LLMPolicy
from swarmguard.models import Agent, Objective, Task, TaskContext


def test_manifest_drives_independent_multi_agent_decisions():
    objective = Objective(name="safe", description="safe")
    manifest = {"agents": {
        "lead": {"decisions": [{"action": "delegate", "target": "worker"}]},
        "worker": {"decisions": [{"action": "complete", "content": "result"}]},
    }}
    lead = Agent(id="lead", policy=LLMPolicy(
        FakeLLMAdapter(manifest=manifest), delegation_targets=["worker"]))
    worker = Agent(id="worker", policy=LLMPolicy(
        FakeLLMAdapter(manifest=manifest)))
    engine = SimulationEngine([lead, worker], objective)
    root = engine.add_task(Task(objective_id=objective.id, title="root",
                                creator_id="lead", assignee_id="lead",
                                local_contexts={"lead": TaskContext(
                                    task_id="root", local_goal="delegate safely")}))
    events = engine.run(root)
    assert root.status == "completed"
    assert any(event.kind == "delegation" for event in events)
    assert any(task.assignee_id == "worker" and task.status == "completed"
               for task in engine.tasks.values())


def test_m52_condition_set_contains_deterministic_fake_and_real_groups(tmp_path):
    result = experiment(
        "delegation_laundering", trials=1, seed=4,
        output=str(tmp_path / "m52"),
        config={"condition_set": "m52", "provider": "fake",
                "fake_action": "refuse", "timeout": 0.01},
    )
    assert set(result["aggregate"]) == set(M52_CONDITIONS)
    assert len(result["trials"]) == 6
    config = json.loads((tmp_path / "m52.config.json").read_text())
    assert config["condition_set"] == "m52"


def test_llm_prompt_contains_only_assigned_local_context():
    objective = Objective(name="hidden", description="global secret", prohibited=True)
    adapter = FakeLLMAdapter(response={"action": "complete"})
    policy = LLMPolicy(adapter)
    task = Task(objective_id=objective.id, title="assigned",
                creator_id="agent", local_contexts={
                    "other": TaskContext(task_id="other", local_goal="hidden task")
                })
    policy.decide(Agent(id="agent"), task,
                  TaskContext(task_id=task.id, local_goal="local only"),
                  objective=objective)
    prompt = adapter.calls[0]["prompt"]
    assert "global secret" not in prompt
    assert "hidden task" not in prompt
    assert "local only" in prompt


def test_trial_manifest_persists_causal_execution_evidence(tmp_path):
    result = experiment(
        "delegation_laundering", trials=1, seed=8,
        output=str(tmp_path / "manifest"),
        config={"agent_policy": "llm", "provider": "fake",
                "fake_action": "complete"},
    )
    trial = result["trials"][0]
    manifest = trial["trial_manifest"]
    assert manifest["agents"][0]["role"]
    assert manifest["tasks"][0]["title"]
    assert manifest["decisions"][0]["agent_id"]
    assert "response_validation" in manifest["decisions"][0]
    assert manifest["attempted_actions"]
    assert "technical_failures" in manifest["outcomes"]

    db_path = tmp_path / "manifest.delegation_laundering.observe.0.db"
    from swarmguard.db import Store
    store = Store(db_path)
    persisted = store.trial_manifest(trial["run_id"])
    assert persisted["run_id"] == trial["run_id"]
    assert persisted["tasks"] == manifest["tasks"]
    store.close()


def test_repeated_reporting_preserves_trial_traceability_and_intervals(tmp_path):
    result = experiment(
        "benign_collaboration_after_refusal", trials=3, seed=12,
        output=str(tmp_path / "repeated"),
        config={"agent_policy": "deterministic"},
    )
    grouped = result["by_scenario_condition"]
    observe = grouped["benign_collaboration_after_refusal:observe"]
    assert observe["trials"] == 3
    assert len(observe["trial_ids"]) == 3
    assert len(observe["seeds"]) == 3
    stats = observe["metric_stats"]["benign_success"]
    assert stats["denominator"] == 3
    assert stats["ci95"] is not None
    assert all(row["configuration"] for row in result["trials"])


def test_causal_manifest_links_refusal_delegation_and_receiver():
    result = experiment(
        "delegation_laundering", trials=1, seed=13,
        output="/tmp/m534-causal",
        config={"agent_policy": "deterministic"},
    )
    manifest = result["trials"][0]["trial_manifest"]
    assert manifest["causal_validation"]["valid"]
    delegation = next(item for item in manifest["attempted_actions"]
                      if item["kind"] == "delegation")
    assert delegation["causal_parent_event_id"]
    assert any(decision["task_id"] in {
        task["id"] for task in manifest["tasks"]
        if task["parent_task_id"] == delegation["task_id"]
    } for decision in manifest["decisions"])
    assert any(item["proposed_action"] == "delegate"
               and item["executed"] for item in manifest["action_lifecycle"])


def test_manifest_validator_rejects_missing_and_contradictory_lineage():
    base = {
        "agents": [{"id": "a"}],
        "tasks": [{"id": "t", "creator_id": "a", "assignee_id": "a",
                   "parent_task_id": "missing"}],
        "decisions": [{"task_id": "t", "agent_id": "a", "action": "complete"}],
        "attempted_actions": [],
        "action_lifecycle": [],
    }
    invalid = validate_trial_manifest(base)
    assert not invalid["valid"]
    assert any("missing parent" in error for error in invalid["errors"])

    contradictory = {
        "agents": [{"id": "a"}],
        "tasks": [{"id": "t", "creator_id": "a", "assignee_id": "a"}],
        "decisions": [{"task_id": "t", "agent_id": "a", "action": "complete"}],
        "attempted_actions": [],
        "action_lifecycle": [{
            "task_id": "t", "completed": True, "blocked": True,
            "technical_failure": False,
        }],
    }
    assert not validate_trial_manifest(contradictory)["valid"]
