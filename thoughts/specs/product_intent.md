# Product Intent

## Status

- active

## Why this exists

- `nanobot` exists to give a technical user a lightweight, channel-connected personal assistant that can operate across chat surfaces, local automation, and coding workflows without the tax of a large assistant platform.
- This repository is the control plane for that experience: it owns channel delivery, session continuity, reminders, recurring tasks, tool use, and extensibility.
- ACP support exists so `nanobot` can become a first-class gateway to external coding agents such as OpenCode while preserving nanobot's native strengths instead of replacing them.

## Users and jobs-to-be-done

- Primary user: a technical founder or power user who wants one lightweight assistant to operate across Telegram and other channels, local repositories, recurring reminders, and coding-agent delegation.
- Core jobs:
  - chat with an assistant from existing communication surfaces
  - schedule reminders and recurring autonomous tasks
  - route coding or research work to the right agent backend
  - preserve session context and continue work later
  - configure behavior without adopting a heavyweight platform
- Most important pain points to remove:
  - fragmented toolchains for chat, scheduling, and coding agents
  - fragile PTY scraping or one-off shell glue for agent delegation
  - loss of context across sessions or restarts
  - automation that cannot safely run unattended

## Desired outcomes

- Outcome 1: `nanobot` can route conversations and scheduled tasks through either its local loop or a first-class ACP-backed external agent session.
- Outcome 2: scheduled reminders and recurring jobs remain a native capability even when work is delegated to ACP agents.
- Outcome 3: external agent support is configurable, provider-agnostic, and does not require adopting a monolithic assistant platform.

## Experience principles

- Principle 1: Lightweight control plane, not heavyweight platform.
- Principle 2: Channels and automation are first-class, not afterthoughts.
- Principle 3: External agent delegation must feel native, observable, and resumable.
- Principle 4: Unattended automation must be policy-driven and safe by default.
- Principle 5: Configuration should be explicit and composable rather than hidden in provider-specific assumptions.

## Boundaries and non-goals

- `nanobot` is not trying to replace every external coding agent with one built-in agent loop.
- ACP support should not force users into a single provider ecosystem.
- The repo should not claim full platform features that do not exist in repo truth, such as imaginary build or e2e systems.
- Acceptance tests may support a real OpenCode backend, but the core test suite should remain hermetic.

## Quality and trust bar

- Reliability: session resume, restart recovery, and scheduled execution must be treated as core behavior.
- Security: filesystem and terminal access must respect workspace boundaries and explicit permission policy.
- Data integrity: scheduled jobs, session bindings, and external runtime metadata must persist safely across restarts.
- Observability: streamed agent progress, permission requests, and final results should be visible to the user through normal channel flows.

## How plans must use this document

- Every plan under `thoughts/plans/` must include a `Product intent alignment` section.
- Plans must cite which desired outcomes and experience principles they advance.
- If a plan conflicts with this intent, update this file first or log an explicit deviation before execution.

## Change log

- 2026-03-09: Created initial product intent to support quality-gated ACP planning and parallel execution.
