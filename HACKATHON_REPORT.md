# SwarmGuard

## Experimental Safety Monitoring for Multi-Agent Systems

### Hackathon project report

## Executive summary

SwarmGuard is an offline-capable experimental framework for studying safety
behavior in multi-agent systems. It evaluates whether local agent decisions
remain safe when tasks are delegated, refused, decomposed, or distributed
across multiple agents.

The project combines:

- deterministic scripted scenarios for reproducible controls;
- local language-model adapters, including Ollama and Amadeus-AI;
- independent scenario ground truth;
- causal execution traces and provenance graphs;
- a pre-action group-policy enforcement gate;
- SQLite persistence for events, decisions, actions, and trial manifests;
- repeated experiments with seeds, configurations, and trial-level artifacts;
- technical-failure-aware metrics and audit reports.

SwarmGuard is designed to measure and audit agent behavior. It does not claim
that autonomous systems spontaneously develop coordinated safety bypasses, and
it does not claim general real-world safety effectiveness from the current
results.

## Problem

Most agent safety checks inspect one request, one agent, or one response in
isolation. That can miss group-level behavior such as:

- delegating a prohibited objective after another agent refuses it;
- splitting a prohibited objective into individually benign subtasks;
- shopping for a more permissive agent;
- allowing several agents to contribute to a prohibited aggregate outcome;
- confusing a proposed action with an action that actually executed.

SwarmGuard addresses this measurement gap by preserving task lineage,
delegation relationships, policy decisions, action lifecycle states, and final
outcomes in a single auditable execution record.

## Technical approach

### Execution model

Each scenario is executed through a controlled interaction engine. Agents
receive local task contexts, produce decisions, and may propose or execute
actions. The group-policy gate evaluates protected operations before execution.

The gate supports:

- **Observe mode:** records findings but never blocks execution.
- **Enforce mode:** blocks a protected operation before it executes.

Interventions are persisted as structured events and reference their triggering
findings. A blocked operation cannot produce a successful final outcome, while
unrelated benign work can continue after a refusal.

### Independent ground truth

Scenario definitions specify the expected violation status, evidence events,
detection categories, intervention expectation, and legitimate completion
expectation. These labels are kept separate from detector output so that
detector evaluation does not become circular.

### Causal trace validation

Trial manifests validate the intended execution chain:

```text
refusal
  -> delegation
  -> child task
  -> receiving-agent decision
  -> action attempt
  -> policy gate
  -> blocked or completed outcome
```

Validation checks include missing references, cross-trial references,
timestamp ordering, ownership mismatches, cyclic task lineage, missing
delegation delivery, missing decisions, missing execution evidence, duplicate
identifiers, and contradictory lifecycle states.

### Experimental conditions

The framework supports:

1. deterministic single-agent or multi-agent controls;
2. fake-LLM controls;
3. real local-model conditions;
4. Observe and Enforce variants;
5. shared refusal propagation and group-level monitoring configurations.

Every trial records its seed, condition, scenario, provider metadata, decision
telemetry, technical failures, action lifecycle, ground truth, and persisted
artifacts.

## Implemented scenarios

The core suite includes:

- direct restricted request followed by refusal;
- legitimate multi-agent collaboration;
- delegation laundering;
- refusal shopping;
- blind task decomposition;
- benign work after a refusal;
- communication failure;
- multiple agents contributing to a prohibited aggregate outcome.

The suite includes benign controls to test false positives. Participation by
multiple agents is not itself treated as malicious; objective identity, task
lineage, context, and final outcome are considered.

## Verified experimental results

### M6.0 controlled evaluation

The preserved M6.0 run executed **900 trials**:

- five core scenarios;
- 30 trials per scenario-condition;
- six conditions;
- deterministic, fake-LLM, and Ollama providers;
- Observe and Enforce modes;
- seed: `20261108`;
- causal validation: **900/900 valid**;
- independent ground-truth audit: **900/900 valid**.

| Condition | Trials | Technical failures | Eligible | Detection | Intervention | Prevention | Successful violation |
|---|---:|---:|---:|---:|---:|---:|---:|
| Deterministic Observe | 150 | 0 | 150 | 0.400 | 0.000 | 0.000 | 0.400 |
| Deterministic Enforce | 150 | 0 | 150 | 0.400 | 0.400 | 0.400 | 0.000 |
| Fake LLM Observe | 150 | 0 | 150 | 0.400 | 0.000 | 0.000 | 0.400 |
| Fake LLM Enforce | 150 | 0 | 150 | 0.400 | 0.400 | 0.400 | 0.000 |
| Ollama Observe | 150 | 150 | 0 | undefined | undefined | undefined | undefined |
| Ollama Enforce | 150 | 90 | 60 | 1.000 | 1.000 | 1.000 | 0.000 |

The deterministic and fake controls confirm the expected enforcement boundary:
eligible prohibited operations were blocked in Enforce mode and remained
executable in Observe mode.

The Ollama results expose an important limitation rather than a success claim:
Observe had 150/150 technical failures, while Enforce had 90/150. The 60
eligible Enforce trials had no successful prohibited outcome, but this cannot be
interpreted as general model safety effectiveness because technical failure
could prevent execution.

### Amadeus-AI local integration

Amadeus-AI was integrated as an optional external local policy provider:

<https://github.com/adityatawde9699/Amadeus-AI>

Verified live results:

- local provider: `llama_cpp`;
- local model: `Llama-3.2-1B-Instruct-Q4_K_M.gguf`;
- structured local response: valid JSON;
- legitimate task decomposition: completed successfully with no violation;
- prohibited delegation-laundering task in Enforce mode: not completed and no
  violation;
- SwarmGuard regression tests: **34 passed**;
- Amadeus targeted local-model tests: **22 passed**.

These are integration and smoke-test results, not a repeated Amadeus
statistical evaluation. The planned 30-trial Amadeus run was interrupted and
must not be reported as completed.

## What the project demonstrates

The current implementation demonstrates that SwarmGuard can:

1. enforce group policy at the correct pre-action boundary;
2. preserve structured, queryable execution histories;
3. distinguish proposals, authorization, attempts, blocks, and completion;
4. validate causal references in trial manifests;
5. keep ground truth independent from detector results;
6. run deterministic, fake, and local-model conditions through a common
   experiment interface;
7. separate technical failures from refusals, interventions, and violations;
8. generate persisted JSON, CSV, SQLite, audit, and chart artifacts;
9. integrate an external local runtime without making it mandatory;
10. continue benign work after a refusal or blocked operation where the scenario
    permits it.

## Limitations

The results do not yet establish:

- spontaneous emergent safety-bypass behavior in autonomous swarms;
- generalization across models, model versions, prompts, seeds, or hardware;
- statistical independence of repeated deterministic trials;
- an immutable model digest for every local-model run;
- reliable real-model evaluation when structured output fails;
- broad safety effectiveness from the Amadeus smoke tests.

Technical failures are not counted as refusals or successful prevention. This
is essential to avoid overstating the results.

## Reproducibility

The repository preserves:

- experiment configuration and seed;
- trial-level JSON and CSV records;
- one SQLite database per trial in the M6 artifacts;
- aggregate metrics;
- causal-validation and ground-truth-audit outputs;
- SVG visualizations;
- provider and latency telemetry where available.

The main M6 report is available at
[artifacts/m6/research-results.md](artifacts/m6/research-results.md).

The project runs deterministic experiments offline and does not require paid
APIs. Amadeus-AI and Ollama are optional providers, not mandatory dependencies.

## Future work

The next milestone should:

1. capture immutable provider and model metadata;
2. finish the M6.1 failure taxonomy for local-model outputs;
3. run a complete Amadeus Observe/Enforce evaluation with at least 30 trials
   per condition;
4. preserve raw diagnostic traces with appropriate redaction;
5. introduce meaningful controlled scenario variations;
6. report technical failure, valid decision, intervention, prevention, and
   completed violation rates separately;
7. conduct per-trace causal inspection before making stronger research claims.

## Conclusion

SwarmGuard is a working experimental and auditing framework for group-level
multi-agent safety behavior. Its strongest current contribution is not a claim
that agents have developed emergent collusion. It is a reproducible system
that makes such a claim testable: actions are gated before execution, traces
are persisted, causal relationships are checked, ground truth is independent,
and technical failures are visible instead of being converted into favorable
safety metrics.
