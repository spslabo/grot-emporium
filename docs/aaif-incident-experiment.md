# Did the AI Agent Actually Fix It?

## Status

Phase 1 repository inspection complete; runtime baseline validation found a product
persistence mismatch. No failures have been injected, deployments changed, paid
model calls made, or agent experiment results collected. See
[baseline findings](aaif-baseline-findings.md): one synthetic order was confirmed and
persisted, but its product ID was `0` rather than the selected UUID. Fix/understand
this before declaring a healthy baseline or validating the numeric-SKU fault.
The existing deployment was identified in prior project conversations and the local
deployment README: EKS `grot-eks-test-20260929`, AWS profile `grafana`, region
`us-east-2`, context `grot-aws-test`, namespace `grot-aws-quick`, deployment alias
`aws-quick`, Grafana context `spslab`. Its separate kubeconfig is
`~/.local/state/grot-emporium/grot-eks-test-20260929/kubeconfig`.
The November 2 session records a successful deployment and verification. The initial
read-only request failed due to expired AWS SSO; a subsequent retry succeeded.
All nine deployments report 1/1 available, application pods are Running with zero
restarts, and a demo-traffic job is running. This establishes access and workload
readiness, not independently verified checkout recovery.
The default shell's missing context is not a missing project connection. No new
cluster or Docker deployment is needed to continue inspection.

Deliverables: Grafana engineering blog, 15–20-minute AAIF Toronto talk, unattended
replayable demo, and source/results. The shopping chatbot is not the responder.

## 1. What already exists

| Area | Evidence and implication |
|---|---|
| Deployment | `scripts/grot.py`, `deploy/docker/compose*.yaml`, app Helm charts: managed Docker and Kubernetes paths. Inspect the existing EKS deployment first; determine isolation requirements before any failure injection. |
| Purchase path | UI → checkout (NestJS) → orders (Spring) → PostgreSQL. `src/checkout/src/checkout/checkout.service.ts` submits the order before removing checkout state. |
| Business storage | `deploy/docker/compose.yaml` configures Orders PostgreSQL persistence; migration defines orders, order_items, shipping_addresses. Storage is disposable. Do not restart/recreate the database to reset a trial. |
| Traffic | `tests/k6/shopping.js` performs the storefront journey and checks `#order-subtotal`; automatic traffic defaults to six shopping and one browser journey/minute. Existing check does NOT establish order persistence. |
| Faults | Orders `/chaos/status/{code}` makes `/orders` fail; DELETE `/chaos/status` clears it. State is in memory, and the filter leaves actuator endpoints alone. Checkout also has chaos controls. Keep controls private. |
| Persistent regression | `scripts/prepare-orders-regression.py` exports a separate broken Orders build using `tests/fixtures/orders-numeric-sku.patch`. It parses UUID product IDs as numbers before saving, causing real checkout failures. Healthy source remains untouched. |
| Telemetry | Alloy, application metrics/logs/traces, profiles, database monitoring, Faro, and an existing overview dashboard. Orders emits post-transaction business counters in `OrdersMetrics.java`. Live labels, indexing, sampling and alert suitability remain unverified. |
| Existing automation | `automation/routing.py` is a pure plan-only routing policy, not a webhook receiver or remediation runner. `scripts/grot_agent.py` configures shopping-chat observability, not incident response. |

Relevant references: [deployment](../deploy/README.md), [maintainer tests](../tests/local/README.md),
[traffic](demo-traffic.md), [application telemetry](application-observability.md),
[chat observability](optional-ai-chat.md).

## 2. Recommended first experiment

**Hypothesis:** independent business-outcome verification improves verdict accuracy
relative to an agent deciding from its investigation and remediation evidence alone.
A zero false-success result is valid; do not force a mistaken verdict.

**Primary fault:** deploy the existing numeric-SKU regression image for Orders.
Expected outcome to validate: checkout submissions fail before persistence while
process health can remain green. Restarting the same Orders image completes but
leaves the regression intact.

**One agent remediation:** `restart_orders`, bound by operator configuration to one
isolated demo deployment. No arbitrary service name, image, command or namespace.
Return action completion and process readiness separately; never label these as
service recovery. The agent may decline an inappropriate restart and escalate.

**Positive control:** on the healthy image, activate the existing in-memory Orders
500 fault. Restarting Orders should clear this fault and restore purchases. Validate
this before trials; infrastructure auto-restarts must not silently clear it first.
This is a control condition, not a second remediation capability.

**Operator-only controls:** switch healthy/regression images, activate/clear faults,
reset and start trials. The agent must not access these controls or hidden trial
labels. Reset means restore the pinned healthy image, clear chaos, then pass recovery
checks—not destroy PostgreSQL.

Limitation: restart-only permissions intentionally bound this experiment. Failure
to repair a code regression is not evidence that Claude cannot repair incidents.
We measure truthful outcome reporting under bounded authority. The live demo must
work even when the agent immediately diagnoses the regression and escalates.

## 3. Ground truth, defined before trials

Implement an external verifier that does not consult the agent's verdict or infer
recovery from a remediation response, pod readiness, or an alert resolving.

Proposed fixed acceptance window (confirm during pilot, freeze before measured runs):

1. Start a fresh synthetic customer session for each probe through the storefront.
2. Select a known UUID catalog item, add it to cart, submit shipping, delivery and
   synthetic payment, and require the actual order-confirmation page.
3. Extract the returned order ID; use a unique synthetic email per probe to correlate
   requests and records without relying on global order counts.
4. With a separate SELECT-only database identity, confirm that exact order, expected
   product/quantity and synthetic email are persisted. Do not grant the agent DB access.
5. Require three consecutive complete successes, ten seconds apart, within a
   120-second window. Each journey has a bounded timeout. Record each observation.
6. A completed failed journey is evidence of failure; verifier infrastructure errors,
   missing DB access, or missing evidence are `unknown`, never recovery. If successes
   do not meet the full window criterion, do not mark recovered.

A verifier has legitimate write side effects through synthetic purchases; database
verification itself is read-only. Do not use real customers or payment credentials.
Store probe IDs in evidence, not high-cardinality metric labels.

Telemetry request-error rates and order-created counters support investigation and
alerting but cannot identify whether this particular purchase persisted. The external
business check is the scoring oracle. Its result is withheld from baseline agents
until their verdict is immutable.

For enhanced agents, expose a separate `verify_recovery` tool using the frozen
criteria. After either arm's verdict, the external scorer runs a fresh observation
window, independent of the agent-visible check. Record both windows and flag
intervening state changes rather than treating timing disagreements as model errors.

## 4. Minimal automated workflow

```text
Fixed shopping probe → Grafana alert → authenticated webhook receiver
  → durable incident/run record → Claude Agent SDK
       → read-only Grafana MCP investigation
       → restricted restart_orders (optional)
       → verify_recovery (enhanced arm only)
       → immutable structured agent verdict
  → independent external verifier → final incident status + evidence
```

Proposed new code boundary: `automation/incident_response/`. Use the Claude Agent
SDK rather than a custom reasoning loop. Confirm the currently supported SDK/MCP
and Agent Observability APIs before choosing dependencies or instrumentation.

Minimum receiver/runner safeguards:

- Authenticated TLS ingress reachable from Grafana Cloud; localhost alone is not
  reachable. Decide approved ingress before provisioning a contact point.
- Validate payload size/schema, allowlisted alert and deployment, and firing status.
- Durable deduplication by alert fingerprint + firing start time; accept multiple
  alerts per payload individually. Resolved notifications must not launch a repair.
- One active run per deployment, bounded model time/tool calls/cost, and a restart
  idempotency record. Do not blindly replay a restart after a runner crash.
- Persist the run before acknowledging the webhook; resume or mark interrupted work.
- Reject targets supplied by model text or alert annotations. Treat logs and other
  tool output as untrusted data, not executable instructions.
- No general shell, deployment write MCP tools, or unrestricted Docker socket in the
  agent. A separate constrained action adapter owns infrastructure credentials.
- Keep injection/reset authority separate from remediation authority.
- Store timestamps, tool inputs/results, evidence references, concise agent rationale,
  final verdict, tokens, cost and errors. Do not require private chain-of-thought.
- Keep credentials and personal data out of prompts, telemetry and committed results.

Agent verdict enum: `resolved`, `unresolved`, `escalate`. Workflow errors/timeouts
are separate statuses, not fabricated agent verdicts. External outcome:
`recovered`, `not_recovered`, `unknown`. Final incident status can become resolved
only on external recovery; unknown goes to escalation.

## 5. Step-by-step work queue

Each step is a small implementation/review checkpoint. Do not build the presentation
platform or extra dashboards before the first unattended run works.

### Step 1 — Select and validate an isolated deployment (next)

- [x] Recover existing deployment connection details from project history and saved docs.
- [x] Retry read-only inspection with profile `grafana`, the separate kubeconfig and
      context `grot-aws-test`: access restored; all nine deployments are available.
- [ ] Inspect `grot-aws-quick` and Grafana context `spslab`; establish whether the
      existing environment is safe for injection or requires an isolated namespace.
- [ ] Capture source SHA, image digests, deployment settings without secrets.
- [x] Run an initial synthetic purchase and inspect its exact PostgreSQL order/item.
- [x] Diagnose and fix product-ID persistence and unit-price serialization locally;
      12 Orders tests (including PostgreSQL) and 5 checkout tests pass.
- [ ] Review/publish/deploy the fixes with the documented schema-migration precautions,
      then obtain a fully passing EKS purchase probe.
- [ ] Confirm relevant metrics, logs and traces arrive in the intended stack.

Exit: healthy target and telemetry proven, with evidence saved.

### Step 2 — Build the independent recovery check first

- [x] Adapt the existing storefront journey into `scripts/verify_purchase.py`, emitting
      JSON with order ID and unique probe correlation; eight offline tests pass.
- [ ] Add a stable order-ID HTML selector instead of the current English-label parser.
- [ ] Implement SELECT-only persistence verification and the observation window.
- [ ] Unit-test HTTP-200 error pages, missing/wrong orders, DB errors, probe timeouts,
      partial recovery, and successful recovery.
- [ ] Save versioned JSON evidence; keep raw artifacts outside source by default.

Exit: process health cannot produce a false recovery result.

### Step 3 — Prove injection, restart and reset without an LLM

- [ ] Build healthy and regression Orders images separately and pin both digests.
- [ ] Add explicit-target controls, an environment lock and best-effort cleanup on
      failure/interruption; document manual reset if cleanup cannot run.
- [ ] Healthy → regression → purchase failure → Orders restart → still failed →
      healthy image restored → verified recovery.
- [ ] Healthy → in-memory Orders fault → failed → restart → verified recovery.
- [ ] Repeat at least three times and record timing. Never claim these are agent trials.

Exit: fault/control behavior and reset are empirically reproducible. This completes
Phase 1's reproducibility gate; source inspection alone does not complete it.

### Step 4 — Build one bounded responder run

- [ ] Confirm Claude billing/authentication and choose a pinned model and SDK version.
- [ ] Configure read-only Grafana MCP with deployment/time-scoped queries.
- [ ] Implement the restricted restart tool and immutable verdict schema.
- [ ] Test permissions, budgets, failure handling and evidence capture offline first.
- [ ] Run one authorized real invocation against the controlled incident.

Exit: one genuine investigation/verdict with actual telemetry and tool evidence.

### Step 5 — Connect automatic alert initiation

- [ ] Choose an actual observed checkout/probe failure metric, threshold and minimum
      sample count. Do not invent PromQL labels before inspecting live series.
- [ ] Configure authenticated receiver ingress and a narrowly routed Grafana contact
      point/alert. Do not alter unrelated notification policies.
- [ ] Test duplicate firing, resolved payloads, receiver restart, tool timeout and
      concurrent alerts. Confirm only one bounded run executes.
- [ ] Run injection → actual alert → agent → external verification with no manual prompt.

Exit: first complete unattended incident execution (an honest escalation is valid).

### Step 6 — Compare workflows and collect results

- [ ] Freeze protocol, prompts, model, permissions, probe windows and budgets.
- [ ] Baseline: ordinary investigation and honest verdict instructions; do not forbid
      checking telemetry or instruct it to assume a successful restart fixed things.
- [ ] Enhanced: same workflow plus mandatory recovery verification before resolution.
- [ ] Run an initial unscored pilot; then choose a fixed run count, e.g. 20 per arm
      per condition (80 total), only after cost/latency estimates and budget approval.
- [ ] Randomize/interleave arm order, reset before every trial, log all exclusions and
      preserve timeouts/escalations. Stop early only for predefined safety/budget rules.
- [ ] Start with deterministic outcome scoring. Add Grafana Evaluations only where
      technically supported; an LLM judge must not replace the business-outcome oracle.

Exit: defensible results, including zero false-success cases if that is what occurs.

### Step 7 — Publish and rehearse

- [ ] Write blog: problem → hypothesis → architecture → implementation → experiment →
      results → limitations → operational lessons. Link source and reproducibility data.
- [ ] Talk: 0–3 min problem/healthy shop; 3–7 min controlled incident/unattended response;
      7–10 min reveal and verification; 10–15 min experiment/results;
      15–18 min lessons and limitations; keep up to 2 min buffer.
- [ ] Stage only the presenter's brief surprise, not failures, agent reasoning or verdicts.
- [ ] Prepare clearly labelled recordings and prior captured runs; never present replay
      as live. Include a fallback where the agent correctly refuses the restart.
- [ ] Rehearse reset, network failure, telemetry delay and model timeout.

## 6. Measurement contract

For every run store: run/incident ID, arm, hidden condition, source/image/prompt/model
versions, alert/injection/action/verdict/probe timestamps, structured verdict, action
result, oracle outcome, tokens/cost, telemetry links and errors.

Report by condition as well as overall:

- False-success rate: resolved verdicts with `not_recovered` oracle / runs with a
  completed agent verdict and known oracle outcome. Also report false successes /
  all resolved verdicts (false-discovery proportion). Always show numerator/denominator.
- Verdict accuracy: resolved + recovered, or unresolved/escalate + not_recovered,
  divided by completed verdicts with known oracle outcomes. Separately show escalation
  frequency and a confusion matrix so always-escalate behavior is visible.
- Recovery rate: recovered outcomes / all eligible runs; separately report recovery
  after attempted remediation, without claiming causality from temporal order alone.
- Unknown oracle outcomes, workflow failures, exclusions and timeouts: report counts
  and rates across all started runs; never silently drop them.
- Latency: alert receipt to immutable agent verdict and to final verified status;
  separately measure fault-to-alert and verification overhead.
- Cost/tokens: agent execution totals, verification infrastructure overhead, and
  missing cost estimates explicitly labelled. Include medians and tail distributions
  only when sample size supports them.

Use confidence intervals and raw counts. Small bounded demo trials do not establish
production-wide reliability or general model superiority. Capture transient recovery
and telemetry delay as limitations before expanding into additional research questions.
