import json

from swarmguard.engine import SimulationEngine
from swarmguard.experiment import M52_CONDITIONS, experiment
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
