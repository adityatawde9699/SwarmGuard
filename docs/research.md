# Research notes

The simulator uses fixed event scripts so experiments are reproducible and
contain no network calls or external side effects. Each event records agent,
risk, parent provenance, and content. SQLite is the durable event ledger;
NetworkX provides a queryable derivation graph. Detectors are intentionally
transparent heuristics: refusal propagation, refusal shopping, delegation
laundering, and blind decomposition. `observe` records findings without
blocking; `enforce` blocks high-severity findings at the group gate.

Metrics are descriptive proxies, not validated benchmarks. `risk_detected`
and `detection_recall_proxy` compare the detector output to the scenario's
declared risk labels; scenarios are hand-authored and therefore unsuitable
for claims of statistical performance. Future work should add blinded
annotations, inter-rater agreement, adversarial scripts, and calibration.

## M2 protocol

Each scenario carries an independent ground-truth annotation (violation,
protected operation, and whether unrelated benign work follows a refusal).
Conditions A–E use the same scripted input but distinct safeguards: A is a
single-agent baseline, B is multi-agent with no safeguards, C uses shared
refusal propagation, D uses external group monitoring, and E combines both.
The runner persists the seed and full condition configuration alongside every
trial. Reports include confusion counts,
precision, recall, F1, false-positive rate, collective violation,
benign-success, refusal-to-success, prevention, intervention, and measured
overhead. A metric whose denominator is zero is explicitly `null`, rather than
silently treated as zero.

The enforcement boundary is evaluated before a protected high-risk operation.
An intervention event records the detector names and triggering event ID.
Attempted operations remain auditable but do not become successful outcomes;
subsequent unrelated benign events are still executed. These deterministic
fixtures are regression controls, not evidence of deployment efficacy.
