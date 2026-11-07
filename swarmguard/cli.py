import json
import typer
from rich import print
from .scenarios import SCENARIOS
from .sim import run
from .db import Store
from .experiment import experiment

app = typer.Typer(help="Deterministic multi-agent monitoring research MVP.")

@app.command()
def scenarios(engine: str | None = typer.Option(
    None, "--engine", help="List scenarios for the legacy or interaction engine"
)):
    if engine not in (None, "legacy", "interaction"):
        raise typer.BadParameter("engine must be legacy or interaction")
    if engine == "interaction":
        from .experiment import M4_SCENARIOS
        for name in sorted(M4_SCENARIOS):
            print(f"[bold]{name}[/bold]: executable interaction scenario")
        return
    for s in SCENARIOS.values(): print(f"[bold]{s.name}[/bold]: {s.description}")

@app.command("run")
def run_scenario(scenario: str = typer.Option("direct_refusal", "--scenario"),
                 db: str = typer.Option("swarmguard.db", "--db"),
                 mode: str = typer.Option("observe", "--mode"),
                 report: str | None = typer.Option(None, "--report")):
    result = run(scenario, db, mode)
    text = result.model_dump_json(indent=2)
    if report: open(report, "w", encoding="utf-8").write(text)
    print(text)

@app.command("llm-run")
def llm_run(scenario: str = typer.Option("legitimate_task_decomposition", "--scenario"),
            db: str = typer.Option("swarmguard-llm.db", "--db"),
            mode: str = typer.Option("enforce", "--mode"),
            provider: str = typer.Option("fake", "--provider"),
            endpoint: str | None = typer.Option(None, "--endpoint"),
            model: str = typer.Option("llama3.2", "--model"),
            temperature: float = typer.Option(0.0, "--temperature"),
            seed: int | None = typer.Option(0, "--seed"),
            fake_action: str = typer.Option("complete", "--fake-action"),
            api_key_env: str | None = typer.Option(None, "--api-key-env")):
    """Run an opt-in LLM policy; fake is the offline default."""
    from .llm import (FakeLLMAdapter, LLMPolicy, OllamaAdapter,
                      OpenAICompatibleAdapter)
    from .experiment import M4_SCENARIOS
    if scenario not in M4_SCENARIOS:
        raise typer.BadParameter("unknown interaction scenario")
    # Keep CLI offline by default and reuse the executable scenario factory.
    if fake_action not in {"accept", "refuse", "delegate", "complete", "wait"}:
        raise typer.BadParameter("fake-action must be accept, refuse, delegate, complete, or wait")
    if provider == "fake":
        adapter = FakeLLMAdapter({"action": fake_action, "content": "offline decision"})
    elif provider == "ollama":
        adapter = OllamaAdapter(endpoint=endpoint or "http://localhost:11434/api/chat",
                                model=model)
    elif provider in {"openai", "openai-compatible"}:
        adapter = OpenAICompatibleAdapter(
            endpoint=endpoint or "http://localhost:11434/v1/chat/completions",
            model=model, api_key_env=api_key_env)
    else:
        raise typer.BadParameter("provider must be fake, ollama, or openai-compatible")
    result = __import__("swarmguard.engine", fromlist=["run_m4_scenario"]).run_m4_scenario(
        scenario, store=Store(db), mode=mode,
        policy_factory=lambda: LLMPolicy(adapter, temperature=temperature, seed=seed))
    print(json.dumps({"scenario": scenario, "provider": provider, "model": model,
                      "result": str(result.get("ground_truth", {}))}, indent=2))

@app.command()
def evaluate(db: str = typer.Option("swarmguard.db", "--db")):
    store = Store(db)
    rows = store.con.execute("SELECT scenario, mode, report_json FROM runs WHERE report_json IS NOT NULL").fetchall()
    if not rows: print("No reports found."); return
    reports = [json.loads(r["report_json"]) for r in rows]
    print(json.dumps({"runs": len(reports), "average_events": sum(r["events"] for r in reports)/len(reports),
                      "runs_with_findings": sum(bool(r["findings"]) for r in reports)}, indent=2))

@app.command()
def chart(db: str = typer.Option("swarmguard.db", "--db"),
          output: str = typer.Option("report.svg", "--output")):
    """Write a dependency-free SVG chart from persisted run data."""
    store = Store(db)
    rows = store.con.execute(
        "SELECT scenario, COUNT(*) AS n FROM runs GROUP BY scenario ORDER BY scenario"
    ).fetchall()
    width, bar, height = 720, 42, 80 + 55 * max(1, len(rows))
    maximum = max([r["n"] for r in rows] or [1])
    labels = []
    for i, row in enumerate(rows):
        y = 55 + i * 55
        w = int(560 * row["n"] / maximum)
        labels.append(f'<text x="20" y="{y}" font-size="14">{row["scenario"]}</text>'
                      f'<rect x="180" y="{y-16}" width="{w}" height="22" fill="#356cb5"/>'
                      f'<text x="{190+w}" y="{y}" font-size="13">{row["n"]}</text>')
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">' + "".join(labels) + "</svg>"
    open(output, "w", encoding="utf-8").write(svg)
    print(f"Wrote {output} from {len(rows)} persisted scenarios.")

@app.command()
def experiment_run(scenario: str = typer.Option("delegation_laundering", "--scenario"),
                   trials: int = typer.Option(5, "--trials"),
                   seed: int = typer.Option(0, "--seed"),
                   output: str = typer.Option("experiment", "--output"),
                   engine: str = typer.Option("legacy", "--engine"),
                   agent_policy: str = typer.Option("deterministic", "--agent-policy"),
                   provider: str = typer.Option("fake", "--provider"),
                   model: str = typer.Option("llama3.2", "--model"),
                   endpoint: str | None = typer.Option(None, "--endpoint"),
                   temperature: float = typer.Option(0.0, "--temperature"),
                   suite: str | None = typer.Option(None, "--suite",
                                                     help="core runs all M4 interaction scenarios")):
    """Run interaction-engine scenarios and persist all experiment artifacts."""
    if engine not in ("legacy", "interaction"):
        raise typer.BadParameter("engine must be legacy or interaction")
    if engine == "interaction" and suite is None and scenario not in {
        "delegation_laundering", "refusal_shopping",
        "benign_collaboration_after_refusal", "legitimate_task_decomposition",
        "communication_failure",
    }:
        raise typer.BadParameter("unknown interaction scenario")
    if engine == "interaction" and suite is None:
        suite = None
    if agent_policy not in {"deterministic", "llm"}:
        raise typer.BadParameter("agent-policy must be deterministic or llm")
    result = experiment(scenario, trials, seed, output, suite=suite,
                        config={"agent_policy": agent_policy, "provider": provider,
                                "model": model, "endpoint": endpoint,
                                "temperature": temperature})
    print(json.dumps({"experiment_id": result.get("experiment_id"),
                      "conditions": list(result["aggregate"]),
                      "trials": len(result["trials"]), "output": output}, indent=2))

@app.command()
def report(run_id: str = typer.Argument(..., help="Persisted run/experiment ID"),
           db: str = typer.Option("swarmguard.db", "--db")):
    """Print a persisted report by run ID."""
    store = Store(db)
    row = store.con.execute("SELECT report_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
    if row and row["report_json"]:
        print(row["report_json"])
        store.close()
        return
    state = store.experiment_state(run_id)
    if state:
        print(json.dumps(state.model_dump(), default=str, indent=2))
    else:
        print(json.dumps({"error": "run ID not found", "run_id": run_id}, indent=2))
    store.close()

if __name__ == "__main__":
    app()
