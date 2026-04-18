# Hermes Atlas -> X-LINK Hub Adoption Blueprint

## Purpose

This document answers one practical question:

Can anything from the Hermes Atlas ecosystem replace the current X-LINK Hub dashboard/UI experience and improve the overall product direction?

Short answer: yes.

The strongest path is not to copy one project whole-cloth. It is to combine:

- a Hermes-native workspace model
- a mission-control inspection model
- a skills/tools registry model
- a calmer operator-console UI shell

That combination is a much better fit for X-LINK than the current single-page "everything at once" dashboard.


## Current X-LINK Hub Reality

The current Hub is strong on ambition but weak on composure.

Observed characteristics from the current implementation:

- One oversized page in `hub/index.html`
- Heavy client logic concentrated in `hub/app.js`
- Many simultaneous surfaces competing for attention:
  - Hermes Console
  - Mission Theater
  - SuperHero Lab
  - X-Agent Eval
  - Usage Auditor
  - Research
  - Briefing
  - Archive
- Legacy persona/UI concepts still mixed into the architecture
- Mission state exists, but result visibility and run inspection are still harder than they should be

This means the Hub currently behaves more like a feature collage than a coherent operator cockpit.


## Best Atlas Candidates

### 1. `hermes-workspace`

Role for X-LINK:

- Primary UI replacement pattern
- Best source for workspace layout and Hermes-native interaction model

Why it fits:

- It treats Hermes as the engine, not a sidekick
- It is built around workspaces, not one giant dashboard
- It aligns with the desired "Hub as the face of Hermes" direction

What to borrow:

- Workspace shell
- Left-rail navigation model
- Context-aware center pane
- Inspector/detail side panels
- Memory/skills visibility as first-class product surfaces

What not to copy blindly:

- Any generic developer-centric assumptions that do not fit founder/operator workflows
- Any UI patterns that prioritize chat over mission state


### 2. `mission-control`

Role for X-LINK:

- Mission execution and run-inspection replacement pattern
- Best source for "what is happening right now?" clarity

Why it fits:

- X-LINK needs better inspection of jobs, evals, artifacts, blockers, and approvals
- User pain is not lack of features; it is lack of visibility and interpretability

What to borrow:

- Run inspector layout
- Status rail for active jobs
- Artifact/result panels
- Per-run detail view
- Better approval and governance framing

What not to copy blindly:

- Anything that over-indexes on infra/admin dashboards instead of operator workflows


### 3. `hermes-agent` / NousResearch Hermes core patterns

Role for X-LINK:

- Backend architecture replacement guidance
- Best source for the "single operator brain" model

Why it fits:

- Validates the move away from Sloane as a required orchestration layer
- Aligns with memory, skills, multi-channel, scheduling, and multi-step execution

What to borrow:

- Hermes-first execution mindset
- Skills and memory as native surfaces
- Multi-channel access as transport, not identity
- More direct operator-to-engine interaction

What not to copy blindly:

- Any broad open-ended autonomy without X-LINK policy controls


### 4. `awesome-hermes-agent`

Role for X-LINK:

- Discovery index, not a direct replacement

Why it fits:

- Useful as an ecosystem map for future integrations
- Helps identify best-in-class plugins, memory systems, workspaces, and orchestration projects

What to borrow:

- Reference map for later phases
- Candidate shortlists for skills, memory, agent coordination, and UI modules

What not to copy blindly:

- Random ecosystem experimentation without a platform architecture


### 5. `openclaw-to-hermes`

Role for X-LINK:

- Migration framing reference

Why it fits:

- Mirrors the current tension in X-LINK:
  - old persona/tool orchestration surface
  - new Hermes-native direction

What to borrow:

- Migration mindset
- How to normalize legacy workflows under a Hermes-native execution model

What not to copy blindly:

- Any migration assumptions specific to OpenClaw internals rather than X-LINK


## Recommendation

### Best replacement strategy

Do not replace the Hub with one Atlas project.

Instead, rebuild X-LINK around this stack:

- UI shell inspiration: `hermes-workspace`
- run inspector inspiration: `mission-control`
- backend model inspiration: `hermes-agent`
- ecosystem discovery source: `awesome-hermes-agent`
- migration framing: `openclaw-to-hermes`


## Proposed Future Product Shape

### X-LINK becomes:

- Hermes-native operator cockpit
- Mission and eval control surface
- Workspace-based execution UI
- Optional persona skins only

### Sloane becomes:

- optional voice mode
- optional comms skin
- not an orchestration dependency


## New Information Architecture

### 1. Home becomes a true command overview

Home should only show:

- active mission
- latest eval result
- top system alerts
- quick launch actions
- one short "next best action" panel

Remove from the default home surface:

- deep telemetry walls
- large dashboard grids
- long descriptive cards
- multiple overlapping mission and chat regions


### 2. Hermes Console becomes its own workspace

Hermes Console should become:

- center-pane conversation with Hermes
- optional right-side inspector for:
  - tool calls
  - memory hits
  - artifacts
  - mission bindings

Key change:

- stop treating chat as a popup/docked afterthought
- make it a first-class workspace


### 3. Mission Theater becomes a run inspector

Instead of a decorative strip, Mission Theater should become:

- latest run card
- active step rail
- result summary
- transcript access
- artifact links
- approvals and blockers
- rollback checkpoint visibility

This is where `mission-control` patterns are most useful.


### 4. SuperHero Lab and X-Agent Eval become dedicated lanes

These should not compete visually with home operations.

Each gets:

- clear run form
- live run status
- latest completed result
- direct links to:
  - transcript
  - batch summary
  - review packet
  - pending recommendation


### 5. Usage Auditor becomes a proper module

Usage Auditor should evolve from "some cards in the Hub" into:

- subscription registry view
- audit snapshots
- renewal pipeline
- invoice/email-assisted ingestion
- explicit yes/no card lookup results

This module should not be visually tangled into the main operator home.


## What We Should Replace First

### Replace now

- Current single-page dashboard composition
- Popup/docked-feeling chat interaction model
- Mission visibility model that hides real artifacts
- Home surface clutter and duplicated state surfaces

### Keep for now

- Existing backend routes where practical
- Existing MEL and eval engines
- Existing mission/job data flow, while the UI is re-skinned
- Existing Hub launch points

### Remove or demote over time

- Sloane-first wording and architecture
- legacy "assistant theater" responses where direct system truth is better
- one-page dashboard density


## Phased Adoption Plan

### Phase A: UX replacement shell

Goal:

- Replace the current home/dashboard shell without breaking features

Build:

- new left rail
- center workspace router
- right inspector rail
- compact home surface

Result:

- immediate reduction in clutter
- easier mental model


### Phase B: Mission Control layer

Goal:

- Make test runs, jobs, and artifacts readable

Build:

- dedicated run inspector
- "latest run" panel
- artifact drawer
- approval state card
- mission timeline with real step state

Result:

- easier trust and verification
- much better post-run workflow


### Phase C: Hermes-native console

Goal:

- Make direct operator interaction feel like Hermes, not a legacy persona wrapper

Build:

- Hermes Console workspace
- tool/action transcript panel
- memory context panel
- action result rendering

Result:

- less confusion about what Hermes actually did
- more confidence in operator mode


### Phase D: Skills + memory visibility

Goal:

- Surface Hermes capabilities instead of hiding them

Build:

- skills registry panel
- recent operational memory
- reusable patterns / lessons browser
- mission-linked evidence panel

Result:

- X-LINK becomes a real operator platform rather than a mysterious prompt shell


### Phase E: Sloane retirement

Goal:

- Make Sloane optional or remove her entirely

Build:

- persona toggle only if needed
- all default labeling and flows become Hermes-native

Result:

- simpler architecture
- fewer translation problems
- less "assistant theater"


## What Success Looks Like

The future X-LINK Hub should make the following easy:

- launch a test
- see what is running
- inspect the latest result
- ask Hermes what happened
- approve or reject next steps
- review artifacts without hunting through the filesystem
- move between mission work, eval work, and audits without UI chaos

If the user cannot tell within a few seconds:

- what ran
- what passed
- what failed
- where to open the evidence
- what Hermes recommends next

then the UI still is not good enough.


## Recommended Build Priority

### Highest-value immediate build

1. Replace the current home shell with a true workspace layout
2. Build a dedicated latest-run / mission inspector
3. Convert Direct Line into a real Hermes Console workspace

### Second wave

4. Rebuild Usage Auditor as its own module
5. Add skills/memory inspector
6. Add artifact explorer shortcuts

### Final cleanup

7. Remove remaining Sloane-first wording and assumptions
8. Make Hermes the only default operator identity


## Final Answer

Yes, Atlas contains resources that can materially replace and improve the current X-LINK dashboard/UI experience.

But the best move is not "swap in one repo."

The best move is to use Atlas as a blueprint source:

- `hermes-workspace` for the shell
- `mission-control` for run/result visibility
- `hermes-agent` for the backend/operator model

That combination is strong enough to replace the current Hub direction and better aligned with the long-term goal of retiring Sloane as a required system layer.
