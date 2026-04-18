# Hermes v2026.4.13 -> X-LINK Execution Plan

## Purpose

This document turns the Hermes Agent release on April 13, 2026 into a practical X-LINK adoption plan.

We are specifically evaluating and planning around three release features:

- Local Web Dashboard
- `watch_patterns` background process monitoring
- Pluggable Context Engine

Source release:

- [Hermes Agent v0.9.0 / v2026.4.13](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.4.13)


## Current X-LINK Position

X-LINK already has the right ingredients, but too many of them are still custom and loosely coupled:

- Hermes operator planning lives in [tools/hermes_operator.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\hermes_operator.py)
- Hermes memory and lessons live in [tools/hermes_memory.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\hermes_memory.py)
- Hub transport and API routing live in [tools/synapse_bridge.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\synapse_bridge.py)
- The Hub shell is still a large custom frontend spread across:
  - [hub/index.html](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\index.html)
  - [hub/app.js](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\app.js)
  - [hub/style.css](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\style.css)

This means:

- Hermes is becoming the brain
- X-LINK is still hand-building too much of the cockpit
- long-running jobs still rely heavily on polling and ad hoc status JSON
- context is custom and useful, but not yet a formal swappable engine


## 1. Local Web Dashboard

### What Hermes adds

The Hermes release adds a local browser dashboard for:

- settings
- sessions
- skills
- gateway management

This matters because X-LINK is currently carrying too much UI burden by itself.

### X-LINK problem it solves

Our current Hub still has three recurring UI issues:

- too much surface area on one page
- too much custom state glue in `hub/app.js`
- not enough clear separation between operator workspace, run inspection, and system management

### Recommendation

Do not replace X-LINK Hub wholesale with the Hermes dashboard.

Instead:

- keep X-LINK as the founder/operator cockpit
- treat the Hermes local dashboard as a management sub-surface
- either embed it in a dedicated `Hermes Admin` workspace or mirror its concepts in X-LINK

### Best X-LINK use

Use the Hermes dashboard pattern for:

- Hermes profile and gateway status
- skills browsing
- session inspection
- model/provider controls
- debugging and backup/import utilities

Leave these in X-LINK:

- Mission Theater / run inspector
- SuperHero Lab
- X-Agent Eval
- Usage Auditor
- Archive Intel

### Concrete phase

#### Phase A

- Add a dedicated `Hermes Admin` workspace in the Hub
- Move low-level runtime controls out of Home
- Make Home only show:
  - latest mission
  - latest eval
  - system alerts
  - next best action

#### Phase B

- Mirror Hermes dashboard concepts into X-LINK:
  - sessions
  - skills
  - memory
  - provider health
- stop overloading the Home screen with infrastructure details

### File landing zones

- UI integration shell:
  - [hub/index.html](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\index.html)
  - [hub/app.js](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\app.js)
  - [hub/style.css](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\style.css)
- runtime data exposure:
  - [tools/synapse_bridge.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\synapse_bridge.py)


## 2. `watch_patterns` Background Process Monitoring

### What Hermes adds

Hermes now supports `watch_patterns`, which watches background process output for events and errors without polling.

### X-LINK problem it solves

This is directly relevant to one of our most painful current issues:

- evals or archive runs appear stuck
- progress files do not update clearly enough
- the UI sometimes looks frozen even when work is actually happening

We already saw this in X-Agent Eval:

- the process was progressing
- but the session telemetry made it look hung

### Recommendation

Adopt the `watch_patterns` model aggressively for X-LINK long-running jobs.

This should replace parts of the current JSON-status-only approach used for:

- X-Agent Eval
- SuperHero Lab
- archive runs
- briefing generation
- usage audits

### Best X-LINK use

For every long-running subprocess, define event patterns such as:

- `starting`
- `completed`
- `error`
- `waiting for founder`
- `saved file`
- `report generated`
- `batch summary written`
- `approval required`

Then stream those events into:

- mission history
- run inspector timeline
- live status badges
- intervention popups

### Concrete phase

#### Phase A

- Add a lightweight watcher abstraction in Python
- attach it to:
  - archive subprocess launches
  - eval subprocess launches
  - SH Lab launches

#### Phase B

- replace vague polling states with event-driven status
- show a real mission/event timeline in the Hub
- use event matches to trigger intervention prompts instead of broad polling checks

### File landing zones

- subprocess launch and API layer:
  - [tools/synapse_bridge.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\synapse_bridge.py)
- eval/job process wrappers:
  - [tools/xagent_eval/tool.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\xagent_eval\tool.py)
  - [tools/run_eval.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\run_eval.py)
  - [tools/great_archivist.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\great_archivist.py)
- frontend event rendering:
  - [hub/app.js](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\hub\app.js)

### Expected payoff

- less false “hung” behavior
- more truthful runtime visibility
- easier stop/resume logic later
- much better mission inspector UI


## 3. Pluggable Context Engine

### What Hermes adds

Hermes now supports a pluggable context engine via `hermes plugins`.

That means context selection becomes a formal extension point instead of hard-coded core behavior.

### X-LINK problem it solves

We already have a custom context/memory layer, but it is still hand-wired:

- lesson trust logic
- mission recall
- recent actions
- rollback checkpoint memory
- operational brief building

All of that is useful, but it is still local code rather than a formal engine boundary.

### Recommendation

Turn X-LINK memory into a Hermes-native context provider rather than continuing to bolt context onto prompts and routing manually.

### Best X-LINK use

Use the context engine slot for three X-LINK-specific context tiers:

#### Tier 1: operational now

- latest active mission
- latest eval/archive status
- approval blockers
- recent operator actions

#### Tier 2: trusted lessons

- only evidence-backed lessons
- MEL pending packets
- batch summaries
- eval scorecards

#### Tier 3: reusable patterns

- previous successful mission shapes
- archive workflows
- operator command patterns

### Concrete phase

#### Phase A

- Extract current context-building logic behind a formal interface:
  - `build_context(turn_request, mission_state, memory_snapshot) -> context_payload`
- keep current behavior but move it behind one entrypoint

#### Phase B

- Split context policy into plugins/modes:
  - `ops_now`
  - `trusted_eval_memory`
  - `archive_research`
  - `minimal_direct`

#### Phase C

- allow per-workspace context mode selection:
  - Hermes Console uses `ops_now`
  - SH Lab / X-Agent Eval uses `trusted_eval_memory`
  - Archive Intel uses `archive_research`

### File landing zones

- current context/memory source:
  - [tools/hermes_memory.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\hermes_memory.py)
- planner/orchestrator entrypoint:
  - [tools/hermes_operator.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\hermes_operator.py)
- bridge/runtime injection path:
  - [tools/synapse_bridge.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\synapse_bridge.py)
  - [tools/sloane_runtime.py](C:\AI Fusion Labs\X AGENTS\REPOS\X-LINK\tools\sloane_runtime.py)

### Expected payoff

- cleaner separation of memory policy from orchestration
- less prompt overgrowth
- easier future self-learning pipeline
- more trustworthy “Hermes remembers what matters” behavior


## Recommended Sequence

### Step 1

Adopt the `watch_patterns` idea first.

Why:

- it solves an active pain immediately
- it improves trust in long-running operations
- it makes the Hub feel more alive without a full rewrite

### Step 2

Formalize the context engine boundary.

Why:

- Hermes is already the brain
- this is the cleanest way to stop hard-wiring memory everywhere
- it sets up better future learning and archive reuse

### Step 3

Use the Hermes dashboard model to simplify the Hub.

Why:

- UI should come after the underlying system truth is stronger
- cleaner eventing and context will make a better dashboard possible


## Recommended Deliverables

### Deliverable 1

`docs/hermes_watch_patterns_design.md`

Contents:

- event taxonomy
- process watcher architecture
- Hub rendering model
- stop/resume hooks

### Deliverable 2

`tools/hermes_context_engine.py`

Contents:

- formal context builder interface
- context mode selection
- bridge/runtime integration

### Deliverable 3

`docs/hermes_dashboard_replatform_plan.md`

Contents:

- current Hub vs Hermes dashboard capability map
- keep/replace decisions
- staged UI migration plan


## Recommendation in One Sentence

Yes, we should adopt all three release ideas, but in this order:

- `watch_patterns` first for operational truth
- pluggable context next for cleaner Hermes memory
- dashboard patterns last for a calmer, more useful Hub
