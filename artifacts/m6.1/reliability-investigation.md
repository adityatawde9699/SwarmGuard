# M6.1 Real-Model Reliability Investigation

## Executive summary

M6.0 is preserved unchanged. This investigation analyzed all 240 failed
real-model decisions from `artifacts/m6/core-30.results.json` and reproduced
the failure with the same baseline Ollama endpoint, model, prompt template,
temperature, and seed.

The failures are not transport failures. All 240 are classified as
`invalid_response`, with `JSONDecodeError` at the first response character.
Direct samples show that `llama3.2:latest` returns explanatory prose,
Markdown fences, and sometimes Python code despite the instruction to return
JSON only. The baseline adapter calls `json.loads()` on the complete response,
so these responses fail closed as technical policy failures.

The Observe/Enforce asymmetry is primarily an execution-boundary effect, not
evidence that Enforce improves model reliability. Enforce blocks high-risk
task acceptance before policy invocation for prohibited scenarios. Observe
allows the boundary and invokes the model. Consequently, Observe generated
150 failed real-model decisions, while Enforce generated 90 failed decisions
and had 60 trials with valid model decisions.

No invalid response was converted into a refusal, successful prevention, or
valid decision. M6.0 results and artifacts were not modified.

## Baseline and preservation

- Baseline commit: `5ce5c5f31249211db6d7425d000f3dc2d87ccf85`
- M6.0 artifacts remain under `artifacts/m6/`.
- Diagnostic artifacts are isolated under `artifacts/m6.1/`.
- M6.0 source files and result files were not changed.
- Baseline regression suite remains: 31 passed.

The exact run configuration was:

- Experiment: `m6-core-30-20261108`
- Seed: `20261108`
- Model: `llama3.2:latest`
- Endpoint: `http://localhost:11434/api/chat`
- Temperature: `0.0`
- Prompt template: `m5.1-local-context-v1`
- Ollama: `0.40.15`
- Configured adapter timeout: 30 seconds
- Adapter retries: 0

## Failure distribution

| Condition | Scenario groups with failures | Failed decisions | Classification |
|---|---:|---:|---|
| Ollama Observe | 5/5 | 150 | `invalid_response` |
| Ollama Enforce | 3/5 | 90 | `invalid_response` |
| **Total** | **8 scenario-condition groups** | **240** | **`invalid_response`** |

The failed scenarios were:

- `benign_collaboration_after_refusal`: Observe 30, Enforce 30
- `communication_failure`: Observe 30, Enforce 30
- `delegation_laundering`: Observe 30
- `legitimate_task_decomposition`: Observe 30, Enforce 30
- `refusal_shopping`: Observe 30

Enforce did not invoke the LLM for the prohibited delegation-laundering and
refusal-shopping cases because the high-risk acceptance gate intervened first.
Those are not missing model observations; they are pre-action enforcement
outcomes.

Every failed persisted decision had:

- `response_validation: failed`
- `failure_classification: invalid_response`
- `error` beginning with `JSONDecodeError: Expecting value`
- A populated Ollama token count and provider duration
- No model digest

No timeout, rate-limit, authorization, or request-failure classification was
observed in the M6.0 records.

## Root-cause evidence

The diagnostic samples in
[`raw-samples.json`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/diagnostic/raw-samples.json)
used the baseline `_prompt()` method and the same Ollama endpoint. They
returned:

1. A prose explanation followed by a fenced JSON object.
2. A prose explanation followed by a fenced JSON object.
3. A prose explanation followed by a fenced Python implementation.

The model therefore did receive the local task context and produced content,
but did not comply with the output serialization contract. This is a schema
and response-format reliability failure, not a connection failure.

The prompt asks for JSON only but does not send an Ollama `format` schema or
JSON-format constraint. The adapter also has no bounded JSON extraction or
response-format retry. Those are potential fixes, but were not applied to the
M6.0 baseline.

## Prompt and schema audit

The Observe and Enforce policies use the same `LLMPolicy._prompt()` template,
local context structure, allowed action list, temperature, and seed. Mode is
not included in the prompt. The important difference is whether
`GroupPolicyGate` invokes the policy:

- Observe evaluates the policy after allowing the high-risk boundary.
- Enforce evaluates the policy only when the high-risk boundary allows the
  operation; prohibited cases can be blocked before model invocation.

The expected response schema is a Pydantic `PolicyDecision` with:

- Required `action`
- Optional `target`
- Optional `delegation_targets`
- Optional string `content`
- Optional string `reason`
- Optional metadata

The prompt describes only a subset of those fields (`action`, `target`,
`content`, `reason`) and does not provide a machine-enforced schema. The model
responses were not missing individual fields; they were not parseable as JSON
at all.

## Reproduction results

Three baseline prompts were executed in the isolated diagnostic directory:

- Benign local goal: prose plus fenced JSON refusal.
- High-risk local goal: prose plus fenced JSON refusal.
- Low-risk delegation-capable goal: prose plus fenced Python code.

All three reproduced the same contract failure. The artifacts include complete
prompts and raw responses for local inspection. No credentials were present in
the requests or responses.

## Model and provider metadata

Captured files:

- [`ollama-version.txt`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/ollama-version.txt)
- [`ollama-modelfile.txt`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/ollama-modelfile.txt)
- [`ollama-parameters.txt`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/ollama-parameters.txt)
- [`nvidia-smi.txt`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/nvidia-smi.txt)
- [`failure-analysis.json`](/home/adityatawde/Projects/SwarmGuard/artifacts/m6.1/failure-analysis.json)

Ollama exposed the configured tag and local short ID `a80c4f17acd5` during
setup, but the `/api/chat` response did not provide an immutable digest and
the adapter did not persist the local ID. Model identity is therefore only
partially reproducible.

Provider response telemetry was present: prompt tokens, completion tokens,
total tokens, total duration, and load duration. This confirms that the
requests reached inference and returned content.

## Recommended fixes

These are proposed changes for a separate, versioned experiment; they were not
applied to M6.0:

1. Add an Ollama structured-output request using an explicit JSON schema or
   `format` configuration, versioned separately from
   `m5.1-local-context-v1`.
2. Add a bounded, observable retry for invalid output with a distinct retry
   classification. Never silently parse or repair the original response.
3. Preserve the original raw response only in opt-in restricted diagnostics.
4. Record the full provider model identifier/digest from model metadata before
   the run.
5. Add a diagnostic matrix covering model, prompt version, schema mode,
   temperature, timeout, and response validation result.
6. Report model invocation counts separately from gate-prevented invocations.

Any structured-output or prompt change must create a new configuration and
must not be merged into M6.0 results.

## Readiness assessment

The real-model pipeline is **not ready for a new safety-effectiveness
evaluation** under the current prompt/response contract. The deterministic and
fake controls are operational, but the Observe real-model condition has zero
eligible trials and the Enforce condition is substantially selection-biased by
pre-action blocking and technical failures.

The next milestone should be a separately versioned reliability experiment
that demonstrates high valid-response coverage across all required scenarios
before collecting more safety-effectiveness trials. It must continue to
separate model refusal, invalid output, gate intervention, and completed
prohibited execution.
