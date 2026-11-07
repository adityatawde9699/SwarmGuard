from swarmguard.sim import run
from swarmguard.db import Store
from swarmguard.experiment import experiment

def test_enforce_blocks_laundering(tmp_path):
    report = run("delegation_laundering", str(tmp_path / "x.db"), "enforce")
    assert not report.decision.allowed
    assert any(f.detector == "delegation_laundering" for f in report.findings)

def test_observe_does_not_block(tmp_path):
    report = run("direct_refusal", str(tmp_path / "x.db"), "observe")
    assert report.decision.allowed and report.events == 2

def test_events_persist(tmp_path):
    path = str(tmp_path / "x.db")
    report = run("benign_collaboration", path)
    store = Store(path)
    assert len(store.events(report.run_id)) == 3
    store.close()

def test_enforcement_intervenes_before_operation_and_recovers(tmp_path):
    report = run("refusal_then_benign", str(tmp_path / "x.db"), "enforce")
    assert report.outcome == "blocked" and report.interventions
    assert report.metrics["prevention"] == 1
    store = Store(str(tmp_path / "x.db"))
    events = store.events(report.run_id)
    assert any(e.kind == "intervention" for e in events)
    assert any("Summarize" in e.content for e in events)  # recovery is possible
    store.close()

def test_observe_never_intervenes_and_collective_control(tmp_path):
    observed = run("multi_agent_prohibited", str(tmp_path / "o.db"), "observe")
    assert observed.decision.allowed and not observed.interventions
    enforced = run("multi_agent_prohibited", str(tmp_path / "e.db"), "enforce")
    assert enforced.metrics["collective_violation"] == 1
    assert enforced.metrics["intervention"] == 1

def test_experiment_conditions_are_named_and_distinct(tmp_path):
    result = experiment("multi_agent_prohibited", trials=1, seed=3,
                        output=str(tmp_path / "m2"))
    names = [result["config"]["conditions"][c]["name"] for c in "ABCDE"]
    assert names == ["single-agent baseline", "multi-agent no safeguards",
                     "shared refusal propagation", "external group monitoring",
                     "shared propagation plus group monitoring"]
    assert result["comparisons"]["A"]["recall"] == 0
    assert result["comparisons"]["C"]["recall"] == 1
    assert result["comparisons"]["D"]["prevention"] == 1
    assert (tmp_path / "m2.svg").exists()
