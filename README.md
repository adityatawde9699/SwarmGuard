# SwarmGuard

SwarmGuard is a deterministic research MVP for understanding safety behavior in
multi-agent systems. It ingests scripted events into SQLite, builds a
NetworkX provenance graph, detects refusal laundering/shopping and blind
decomposition, and applies an observe/enforce group policy gate. It performs no
external operations and makes no claims about real-world efficacy.

```bash
uv sync --extra dev
uv run swarmguard run --scenario delegation_laundering --db run.db --report report.json
uv run swarmguard evaluate --db run.db
uv run pytest
```

Scenarios: `direct_refusal`, `benign_collaboration`, `delegation_laundering`,
`refusal_shopping`, `blind_decomposition`, `shared_memory`, and
`legitimate_workflow`, `refusal_then_benign`, and `multi_agent_prohibited`.

The M2 runner executes equivalent inputs under conditions A–E and writes
`<output>.config.json`, trial-level JSON/CSV, aggregate JSON, and SQLite ledgers:

```bash
uv run swarmguard experiment-run --scenario refusal_then_benign --trials 10 \
  --seed 42 --output artifacts/m2
```

Conditions are semantically distinct: A is a single-agent baseline, B is
multi-agent execution with no safeguards, C shares refusal propagation, D
uses external group monitoring, and E combines shared propagation with group
monitoring. The aggregate JSON and generated SVG compare each condition by
confusion/detection, violation, benign-success, intervention/prevention, and
overhead metrics.

Enforcement is a pre-operation boundary: `observe` never blocks, while
`enforce` records a structured intervention linked to triggering findings,
refuses the protected operation, and still permits unrelated benign work.
Undefined metrics (zero denominators) are represented as JSON `null`.

M3 adds genuinely serial single-agent and scheduled multi-agent topologies.
Trial seeds select reproducible relay paths, partial-information metadata and
communication ordering; the seed and topology are persisted with every event.
Finding references are stable across incremental detection and interventions
link back to both their trigger event and finding IDs. Experiments are
resumable: completed `(condition, trial)` records in the results JSON are
skipped. Aggregate JSON includes Wilson 95% intervals for the Bernoulli
`attack_attempt_rate`, `detection_rate`, `intervention_rate`,
`successful_violation_rate`, and `prevention_rate` measures.

## M4 interaction engine

M4 adds an offline executable interaction engine in `swarmguard.engine`, while
keeping the M1–M3 scripted runner unchanged. Typed `Agent`, `Objective`, `Task`,
`Message`, policy, and experiment-state models support explicit creator/assignee
task trees and contribution lineage. `SimulationLayer` executes agent policies;
`MonitoringLayer` observes the resulting legacy `Event` records; and
`IndependentGroundTruthEvaluator` computes outcomes without using monitor
findings. `FailureInjector` models interrupted agents and failed communication.
`ExperimentOrchestrator` checkpoints pending/running/completed/failed state in
SQLite, making runs resumable and retryable. The implementation is deterministic
and has no LLM, Amadeus, or Adaption dependency.

### M4.1 interaction semantics

M4.1 separates the global `Objective` (available to the evaluator and
controller) from each agent's `TaskContext` and local knowledge.  A policy can
therefore accept a locally harmless subtask without being given the global
objective; the independent evaluator still labels the resulting prohibited
execution correctly.  `DiscreteEventScheduler` provides a deterministic clock,
stable ordering, delayed delivery, failures, and retry callbacks.  `Store`
persists objectives, tasks, messages, decisions, and results so the complete
provenance chain can be reconstructed after restart:
`Objective -> Task -> Delegation -> Message -> Agent Decision -> Result`.
The executable attack demonstrations are available through
`swarmguard.engine.run_m4_scenario("delegation_laundering")` and
`run_m4_scenario("refusal_shopping")`; they create and delegate real tasks.

### M4.2 group policy gate

M4.2 adds `GroupPolicyGate`, which evaluates global objective/history while
agents retain local `TaskContext`. It is integrated before high-risk
acceptance, child delegation, sensitive delivery, protected tools, and final
aggregation. `observe` records and permits; `enforce` records a structured,
stable-ID intervention and blocks before completion. Every interaction is
durable in SQLite and distinguishes attempted, completed, and blocked work.
See `docs/m4.2.md`. Conditions A–F are available from the experiment runner;
condition F enables the M4.2 gate.

### M4.3 interaction experiments

The interaction engine is now the executable experiment path (not a scripted
proxy). Run the complete core suite in one command:

```bash
uv run swarmguard experiment-run --suite core --trials 5 --seed 42 \
  --output artifacts/m4-core
```

The core suite covers `delegation_laundering`, `refusal_shopping`,
`benign_collaboration_after_refusal`, `legitimate_task_decomposition`, and
`communication_failure`, under both `observe` and `enforce`. Trial records
persist an experiment ID, run/status, seed, configuration, complete
boundary-by-boundary detection history, findings, intervention decisions, and
metrics (including Wilson 95% uncertainty intervals). JSON, CSV, and SVG
artifacts are written beside the configured output prefix. A persisted run can
be inspected with `uv run swarmguard report RUN_ID --db RUN_DB`.

The five independently exercisable boundaries are task acceptance, delegated
child creation, sensitive result delivery, protected tool execution, and
final aggregation. Observe records and allows; enforce blocks when a
high-severity finding exists. Ground-truth evaluation remains a separate
component and never consumes monitor findings.

## M5 local LLM policies

M5.1 hardens the opt-in `LLMPolicy` without changing deterministic policies or
the M4 `GroupPolicyGate`/independent evaluator. Policies return a Pydantic-validated
`PolicyDecision` (`accept`, `refuse`, `delegate`, `complete`, or `wait`).
Prompts contain only the agent's `TaskContext` and local messages; the global
objective is never sent to an adapter. Provider/model, temperature, seed,
prompt hash, latency, failures, and lineage are persisted in the decision
ledger. LLM failures fail closed as an explicit refusal.

Offline usage requires no network:

```bash
uv run swarmguard llm-run --scenario legitimate_task_decomposition \
  --fake-action complete --seed 42
```

For a local Ollama-compatible server (or an OpenAI-compatible chat endpoint):

```bash
uv run swarmguard llm-run --endpoint http://localhost:11434/api/chat \
  --model llama3.2 --temperature 0 --seed 42
```

M5 makes no claims about model capability or safety. Use `enforce` for
protected runs, keep endpoint access local, and retain configuration and
artifacts for reproducibility. Network access is optional and no paid provider
dependency is required.

The hardened adapters are `OllamaAdapter` (`/api/chat`, non-streaming),
`OpenAICompatibleAdapter` (`/v1/chat/completions`), and the offline
`FakeLLMAdapter`. Fake responses can be configured per agent/task and as
sequences for deterministic tests. Model-generated delegation is checked for
known, authorized targets before task creation and then passes through the
group gate. Technical model failures are recorded as failed policy requests
and are not counted as safety refusals.

The interaction experiment runner accepts the same scenarios for deterministic
and fake/local policies:

```bash
uv run swarmguard experiment-run --engine interaction \
  --agent-policy llm --provider fake --suite core --trials 10 --seed 42 \
  --output artifacts/m5-fake
```

Use `--provider ollama` with `--endpoint` for a local model. A local model
server is optional; ordinary tests use mocked HTTP responses and do not
require network access.

M5.2 adds a six-condition comparison manifest with
`--condition-set m52`: deterministic observe/enforce, fake LLM
observe/enforce, and real local LLM observe/enforce. Per-agent provider/model
configuration can be supplied with `--agent-config`, while a scenario-aware
offline manifest can be supplied with `--fake-manifest`. Each trial records
agent refusal/delegation rates, refusal-shopping observations, model failure
counts, mean/median latency, token usage when provided, and the existing
violation/detection/prevention metrics. Model failures remain distinct from
policy refusals.

```bash
uv run swarmguard experiment-run --engine interaction \
  --condition-set m52 --provider fake --trials 5 --seed 42 \
  --output artifacts/m52-comparison
```

The real conditions require a reachable local endpoint. Model seeds are
reproducibility inputs, not guarantees of identical output across inference
systems. Fake-agent observations are synthetic control data and must not be
reported as real-model results.

M5.3.2 persists a controlled trial manifest in each trial database and trial
JSON. The manifest records agent identity and role, original and delegated
tasks, parent-child task lineage, validated decisions, response-validation
status, attempted-action evidence, gate interactions, technical failures, and
policy interventions. It intentionally excludes raw prompts and responses.
This supports causal trace inspection without treating invalid model output as
an agent refusal or a prevented violation.

M5.3.3 supports repeated trials with a research default of 30 trials when
`--trials` is omitted. Aggregate reports include per-scenario/per-condition
breakdowns, trial IDs, seeds, explicit metric denominators, Wilson 95%
intervals for binary outcomes, and the persisted configuration for every
trial. Provider model digests are retained when the adapter supplies them;
otherwise the report keeps the model identifier without inventing an
immutable digest.

M5.3.4 adds causal trace validation. Refusal events carry message links;
delegations can reference a preceding refusal event; delegated tasks retain
their parent task and receiving-agent decision; and action records distinguish
proposed, authorized, executed, blocked, and completed states. Trial manifests
are validated for missing parents, unknown owners, mismatched decision
ownership, missing causal references, duplicate IDs, cross-trial references,
timestamp ordering, cyclic task lineage, missing delegation delivery, and
contradictory blocked/completed or technical-failure/completed states. The
research audit is written alongside aggregate output as `.audit.json`; it
reports invalid traces, ground-truth audit failures, technical model failures,
and rates adjusted by excluding those failures. Zero eligible trials produce
an explicit undefined (`null`) rate. Ground truth continues to come from the
objective and execution ledger rather than detector findings. These structural
and temporal links are execution evidence, not independent proof that one
event caused another.
