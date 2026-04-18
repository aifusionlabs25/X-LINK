# Hermes-Owned MEL 2.0 Architecture

## Purpose

This document defines how Hermes should take over MEL / X-LINK SH Lab testing without turning the harness into a self-reinforcing black box.

The goal is to make testing:

- more realistic
- more adaptive
- more commercially relevant
- more organized over time

while preserving:

- benchmark stability
- score comparability
- reviewer independence
- operator trust


## Decision Summary

Hermes should become the **test orchestrator and adaptive scenario architect** for MEL 2.0.

Hermes should **not** become the uncontrolled author, runner, and judge of the same test loop.

The operating model should be:

1. Hermes proposes and organizes scenarios.
2. The harness executes them.
3. A separate scoring layer evaluates them.
4. A frozen benchmark pack remains in rotation for longitudinal comparison.
5. Promotion of Hermes-generated scenarios into canonical packs requires explicit review.


## Why Change

Recent X-LINK testing has exposed a structural mismatch between:

- live Amy performance in Anam
- MEL / X-LINK Hub performance under the current harness

The likely issue is not simply that Amy is weak.

The stronger hypothesis is that the current harness:

- overweights rigid text-only interaction
- flattens pacing and pause realism
- over-penalizes safe boundary language repetition
- compresses conversations into adversarial edge-case exchanges too quickly
- blends stress testing and live-quality scoring into one number

That makes MEL useful for finding brittleness, but less reliable as a pure proxy for real human sales quality.

Hermes can help here because Hermes is already positioned as the operator brain that can:

- interpret recent failures
- vary scenario posture and intent
- maintain memory across batches
- organize missions and job families
- produce structured operational artifacts


## Core Principle

MEL 2.0 should separate **adaptivity** from **authority**.

Hermes can make the system smarter.

Hermes should not be allowed to silently redefine what "good" means.


## Role of Hermes

Hermes should own the following functions:

- scenario ideation
- batch composition
- scenario classification
- test lane assignment
- session orchestration
- post-run synthesis
- failure clustering
- candidate scenario promotion proposals

Hermes should not unilaterally own:

- final score authority
- canonical benchmark replacement
- rubric mutation
- pass/fail threshold changes


## Proposed System Model

### 1. Scenario Layer

Hermes creates scenario specs in a structured format.

Each scenario should include:

- scenario id
- family
- lane
- target agent
- target persona
- user intent
- emotional posture
- commercial objective
- realism level
- pressure level
- guardrail focus
- expected conversation mode
- allowed variability notes

Example lane families:

- discovery
- objection handling
- scheduling / next-step conversion
- credibility / trust repair
- compliance pressure
- hostile or skeptical buyer
- ambiguous buyer intent
- multi-turn persistence

Example realism levels:

- live-like
- mixed
- red-team


## 2. Pack System

MEL 2.0 should use three pack classes.

### Core Pack

Frozen benchmark scenarios used for score stability.

Properties:

- fixed wording or tightly bounded wording
- minimal rotation
- used for longitudinal trend lines
- cannot be changed by Hermes without explicit promotion workflow

### Adaptive Pack

Hermes-generated scenarios based on:

- recent failure clusters
- new business needs
- repeated live-session patterns
- role-specific drift

Properties:

- dynamic
- exploratory
- high discovery value
- tracked separately from the Core Pack

### Red Team Pack

Stress-heavy scenarios used to expose brittleness.

Properties:

- intentionally sharp
- high pressure
- often unrealistic in concentration
- should not be mistaken for live-performance proxy


## 3. Scoring Model

The scoring system should stop collapsing everything into one blended number.

MEL 2.0 should report at least three score families.

### Live Realism Score

Measures:

- naturalness
- trust
- warmth
- pacing feel
- believable next-step handling
- conversational recovery

### Stress Reliability Score

Measures:

- consistency under pressure
- resistance to fabrication
- ability to preserve boundaries cleanly
- robustness across repeated objections

### Compliance Safety Score

Measures:

- refusal quality
- anti-fabrication behavior
- boundary integrity
- safe escalation behavior

Optional fourth score family:

### Commercial Progression Score

Measures:

- discovery quality
- forward movement
- conversion momentum
- handling of hesitation
- quality of next-step setup


## 4. Separation of Duties

This is the most important control in the system.

### Hermes

Responsible for:

- generating adaptive scenarios
- assigning packs
- planning batches
- clustering failures
- summarizing operational lessons

### Harness Executor

Responsible for:

- running sessions
- capturing transcripts
- logging timing and turn metadata
- storing structured artifacts

### Reviewer / Judge Layer

Responsible for:

- scoring against fixed rubrics
- reporting category-level outcomes
- staying blind to whether a scenario came from Hermes or from the canonical library where possible

### Human Review

Responsible for:

- promoting adaptive scenarios into Core Packs
- approving rubric changes
- validating score interpretation against live sessions


## 5. Main Dangers

### Evaluation Drift

If Hermes continually changes the test distribution, score history becomes noisy and hard to compare.

Mitigation:

- preserve a frozen Core Pack
- report pack type in every run
- separate adaptive score dashboards from benchmark score dashboards

### Judge Contamination

If Hermes creates the test and also influences the scoring logic, the harness can gradually grade on its own curve.

Mitigation:

- keep scenario generation and scoring logic separate
- version rubrics independently
- prevent automatic rubric rewrites from Hermes outputs

### Overfitting to Recent Failures

Hermes may keep focusing on the latest visible weakness and distort the scenario mix.

Mitigation:

- enforce family quotas per batch
- require scenario diversity constraints
- maintain a balanced rotation schedule

### Reinforcing Existing Blind Spots

If Hermes learns only from MEL outputs, it may amplify MEL's current over-harnessed style.

Mitigation:

- ingest live-session review signals from Anam and manual review
- explicitly tag "live-better-than-harness" findings
- create a realism correction layer in scenario planning

### Operational Complexity

Adaptive systems become harder to debug when multiple moving parts shift at once.

Mitigation:

- version scenario specs
- version pack composition
- version rubrics
- store batch manifests
- store Hermes rationale for scenario creation


## 6. Governance Rules

Hermes should be allowed to create unlimited candidate scenarios.

Hermes should not be allowed to:

- overwrite the Core Pack automatically
- delete canonical scenarios automatically
- change pass thresholds automatically
- alter scoring categories automatically
- hide scenario provenance

Every scenario should carry provenance:

- `source: canonical`
- `source: hermes_adaptive`
- `source: human_curated`
- `source: promoted_from_adaptive`

Every batch should carry:

- pack class
- scenario manifest
- rubric version
- review mode
- realism label


## 7. Suggested Artifact Model

Hermes-generated scenario specs should live in a structured folder model such as:

- `vault/mel/scenarios/core/`
- `vault/mel/scenarios/adaptive/`
- `vault/mel/scenarios/red_team/`
- `vault/mel/batches/`
- `vault/mel/reviews/`
- `vault/mel/promotions/`

Each scenario file should contain:

- metadata
- scenario brief
- user simulation guidance
- realism constraints
- scoring hints for reviewers
- provenance and version history

Each batch manifest should contain:

- batch id
- creation source
- target agent
- included scenarios
- scenario families
- rationale for inclusion
- scoring rubric version


## 8. Hermes Workflow Inside MEL 2.0

### Step A: Observe

Hermes reads:

- recent MEL failures
- live-session notes
- category drift
- agent-specific regression patterns

### Step B: Generate

Hermes proposes:

- new adaptive scenarios
- revised scenario families
- new pack composition for exploratory runs

### Step C: Organize

Hermes groups scenarios by:

- lane
- pressure level
- realism type
- business objective
- risk focus

### Step D: Execute

The harness runs the selected batch.

### Step E: Score

The reviewer layer scores the run using the current rubric version.

### Step F: Learn

Hermes summarizes:

- repeated failure patterns
- likely harness artifacts
- likely real agent weaknesses
- which scenarios deserve promotion review

### Step G: Promote

Human approval decides whether adaptive scenarios should join the Core Pack.


## 9. What Hermes Should Improve Immediately

Hermes would likely add the most value in these areas first:

- generating more organic discovery scenarios
- modeling skepticism without instant hostility
- varying user patience and trust levels
- adding pacing-aware prompts for user simulation
- separating realistic buyer hesitation from red-team interrogation
- clustering failures by conversational pattern instead of only category score

This should help MEL stop treating every conversation like a compressed cross-examination.


## 10. Recommended Rollout

### Phase 1: Hermes as Scenario Architect

Add Hermes-generated adaptive scenarios, but keep current scoring and current Core Pack intact.

Success criteria:

- adaptive scenarios are clearly useful
- no loss of score comparability
- scenario provenance is visible

### Phase 2: Hermes as Batch Orchestrator

Let Hermes decide which mix of Core, Adaptive, and Red Team scenarios should run for a target agent.

Success criteria:

- better coverage
- better organization
- fewer repetitive tests

### Phase 3: Multi-Score MEL Dashboard

Split reporting into:

- Live Realism
- Stress Reliability
- Compliance Safety
- Commercial Progression

Success criteria:

- clearer interpretation
- less confusion between live quality and harness toughness

### Phase 4: Promotion Workflow

Allow Hermes to nominate scenarios for Core Pack promotion.

Success criteria:

- benchmark library evolves
- longitudinal stability remains intact


## 11. Recommendation

Proceed with a **Hermes-owned MEL 2.0**, but define ownership carefully:

- Hermes owns adaptation
- the harness owns execution
- reviewers own scoring
- humans own benchmark governance

That is the safest high-upside version of this idea.

The wrong version would be letting Hermes silently become:

- test author
- batch selector
- scorer
- rubric editor
- benchmark curator

all at once.

That would create a powerful system, but not a trustworthy one.


## 12. Practical Next Build

The next implementation slice should be small and testable:

1. Add a Hermes scenario spec generator that outputs structured adaptive scenarios.
2. Add batch manifests that label every scenario by pack class and provenance.
3. Keep the current MEL scoring logic intact for the first pass.
4. Add dashboard labeling so operators can tell whether a score came from Core, Adaptive, or Red Team runs.
5. Compare Hermes adaptive runs against live Anam observations before changing canonical benchmarks.


## Final Position

Let Hermes loose inside a fenced yard.

That means:

- broad creative authority
- narrow scoring authority
- zero silent benchmark authority

If implemented this way, Hermes should make SH Lab smarter, more realistic, and more useful without sacrificing trust in the system.
