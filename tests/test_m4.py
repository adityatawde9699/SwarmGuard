from swarmguard.db import Store
from swarmguard.engine import (CommunicationProtocol, FailureInjector,
                                ExperimentOrchestrator, GroundTruthEvaluator,
                                SimulationEngine, run_m4_scenario)
from swarmguard.models import Agent, AgentPolicy, ExperimentState, Objective, Task


def test_task_hierarchy_and_executable_delegation():
    objective = Objective(name="report", description="safe report")
    lead = Agent(id="lead", policy=AgentPolicy(delegation_targets=["worker"]))
    worker = Agent(id="worker")
    engine = SimulationEngine([lead, worker], objective)
    root = engine.add_task(Task(objective_id=objective.id, title="report",
                                creator_id="lead", assignee_id="lead"))
    events = engine.run(root)
    assert root.status == "completed"
    assert len(engine.tasks) == 2
    assert any(e.kind == "delegation" for e in events)


def test_policy_refusal_and_communication_failure():
    objective = Objective(name="secret", description="secret", risk="high", prohibited=True)
    agent = Agent(id="guard")
    engine = SimulationEngine([agent], objective,
                               failures=FailureInjector(failed_pairs={("guard", "owner")}))
    task = engine.add_task(Task(objective_id=objective.id, title="secret",
                                creator_id="owner", assignee_id="guard"))
    engine.run(task)
    message = CommunicationProtocol.create("request", "guard", "owner", task.id, "x")
    assert not engine.send(message).delivered
    assert task.status == "refused"


def test_ground_truth_is_independent_and_state_is_durable(tmp_path):
    objective = Objective(name="safe", description="safe")
    agent = Agent(id="a")
    engine = SimulationEngine([agent], objective)
    task = engine.add_task(Task(objective_id=objective.id, title="safe",
                                creator_id="a", assignee_id="a"))
    events = engine.run(task)
    truth = GroundTruthEvaluator().evaluate(objective, engine.tasks.values(), events)
    assert truth["completed"] and not truth["violation"]
    store = Store(tmp_path / "m4.db")
    state = ExperimentState(status="running", checkpoint=len(events))
    store.save_experiment_state(state)
    assert store.experiment_state(state.id).checkpoint == 1
    store.close()


def test_interrupted_simulation_is_marked_failed(tmp_path):
    objective = Objective(name="secret", description="secret", risk="high", prohibited=True)
    engine = SimulationEngine(
        [Agent(id="guard")],
        objective,
        failures=FailureInjector(interrupted_agents={"guard"}),
    )
    task = engine.add_task(
        Task(
            objective_id=objective.id,
            title="secret",
            creator_id="owner",
            assignee_id="guard",
        )
    )
    store = Store(tmp_path / "failed.db")
    state, result = ExperimentOrchestrator(store).run(ExperimentState(), engine, task)
    assert state.status == "failed"
    assert result["events"]
    store.close()


def test_m42_observe_and_enforce_have_distinct_outcomes(tmp_path):
    observed_store = Store(tmp_path / "observe.db")
    observed = run_m4_scenario("delegation_laundering", store=observed_store, mode="observe")
    assert observed["ground_truth"]["violation"]
    assert any(f.detector == "protected_operation" for f in observed["findings"])
    assert observed_store.con.execute(
        "SELECT COUNT(*) FROM interactions WHERE completed=1"
    ).fetchone()[0] > 0
    observed_store.close()

    enforced_store = Store(tmp_path / "enforce.db")
    enforced = run_m4_scenario("delegation_laundering", store=enforced_store, mode="enforce")
    assert not enforced["ground_truth"]["violation"]
    assert enforced_store.con.execute(
        "SELECT COUNT(*) FROM interactions WHERE completed=0"
    ).fetchone()[0] > 0
    finding_ids = {f.id for f in enforced["findings"]}
    blocked_refs = enforced_store.con.execute(
        "SELECT finding_ids_json FROM interactions WHERE completed=0"
    ).fetchone()[0]
    assert any(identifier in blocked_refs for identifier in finding_ids)
    enforced_store.close()


def test_m42_local_context_and_restart_provenance(tmp_path):
    store = Store(tmp_path / "provenance.db")
    result = run_m4_scenario("refusal_shopping", store=store)
    assert all(
        task.local_contexts.get(task.assignee_id, None) is None
        or not task.local_contexts[task.assignee_id].known_prohibited
        for task in result["tasks"].values()
        if task.assignee_id
    )
    chain = store.interaction_provenance()
    store.close()
    reopened = Store(tmp_path / "provenance.db")
    assert len(reopened.interaction_provenance()["tasks"]) == len(chain["tasks"])
    assert len(reopened.interaction_provenance()["messages"]) == len(chain["messages"])
    reopened.close()


def test_m42_each_enforcement_boundary_is_pre_action(tmp_path):
    objective = Objective(name="restricted", description="restricted", risk="high", prohibited=True)
    task = Task(objective_id=objective.id, title="restricted", creator_id="owner", assignee_id="agent")

    observe_store = Store(tmp_path / "boundaries-observe.db")
    observe = SimulationEngine([Agent(id="agent")], objective, store=observe_store, mode="observe")
    observe.add_task(task)
    observe_calls = [
        lambda: observe.task_acceptance("agent", task),
        lambda: observe.delegated_child_creation("agent", task),
        lambda: observe.sensitive_result_delivery("agent", task, "result"),
        lambda: observe.protected_tool("agent", task, "tool"),
        lambda: observe.aggregate("agent", task, "aggregate"),
    ]
    assert all(call() for call in observe_calls)
    observe_store.close()

    enforce_store = Store(tmp_path / "boundaries-enforce.db")
    enforce = SimulationEngine([Agent(id="agent")], objective, store=enforce_store, mode="enforce")
    enforce.add_task(task.model_copy(deep=True))
    enforce_calls = [
        lambda: enforce.task_acceptance("agent", task),
        lambda: enforce.delegated_child_creation("agent", task),
        lambda: enforce.sensitive_result_delivery("agent", task, "result"),
        lambda: enforce.protected_tool("agent", task, "tool"),
        lambda: enforce.aggregate("agent", task, "aggregate"),
    ]
    assert not any(call() for call in enforce_calls)
    assert enforce_store.con.execute(
        "SELECT COUNT(*) FROM interactions WHERE completed=0"
    ).fetchone()[0] == 5
    enforce_store.close()
