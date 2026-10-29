# SQUEEZE — Non-Technical Summary

What this project does
- SQUEEZE turns raw football match events (passes, shots, recoveries, etc.) into trustworthy, explainable intelligence and short human-friendly stories.

How data gets into the system
- Events arrive from a live stream (Azure Event Hubs) or from a built-in simulator. Each incoming item is wrapped so the system knows its origin and metadata.

How the system treats facts vs. interpretation
- Observed facts: the raw events recorded from the stream or simulator (who did what, when).
- Computed facts: deterministic calculations derived from events (possession, metrics, and a versioned score called ActionImpact).
- Interpretations: human-facing explanations and narratives produced by an AI provider.
- Deterministic facts always take priority; AI can explain but not change those facts.

Core processing flow (plain steps)
1. Ingestion: unwrap and validate incoming envelopes to create canonical match events.
2. Deterministic processing: a central processor orders events, reconstructs possessions, updates metrics, detects patterns, computes action impacts, and builds causal chains. These steps are rule-based and repeatable.
3. Candidate generation and validation: the system creates structured candidate insights and validates them using deterministic checks.
4. Context assembly for AI: the system builds a compact, bounded context (verified facts, evidence, and impacts) and sends that to AI agents — not the raw event stream.
5. AI reasoning and narrative: the AI (Microsoft Foundry) receives the bounded context and produces explanations, validated narrative language, or other outputs. If AI fails or returns malformed output, the system falls back to deterministic representations.
6. API and products: processed facts, metrics, validated insights, and narratives are exposed through APIs for dashboards, apps, or downstream services.

Special features and guarantees
- ActionImpact: a deterministic, versioned score estimating how an action changed attacking or defensive opportunity, traceable to the exact event.
- Traceability: every insight links back to the exact evidence and original event IDs so a human can follow story → evidence → event.
- AI Gate: AI only gets bounded and verified contexts to ensure explanations are grounded in deterministic facts.
- Observability & safety: health and readiness endpoints let the system report whether external dependencies (Event Hubs, AI provider) are configured and healthy.

Who benefits
- Product teams, analysts, and downstream services that need accurate, explainable match intelligence plus polished narrative text for human readers — with strong guarantees the narrative is grounded in verified facts.

Questions or next steps
- I can produce a one-page stakeholder summary, or a component-by-component plain-English walkthrough showing where the `simulator`, `MatchProcessor`, `AgentOrchestrator`, and API fit. Which would you prefer?

Component-by-component walkthrough (plain English)

- Simulator:
	- What it does: creates realistic match events (passes, shots, recoveries) you can use for development, testing, or load testing when a live feed isn't available.
	- Why it matters: lets teams exercise the system end-to-end without depending on live data.

- Ingestion / Transport Envelope:
	- What it does: receives incoming messages from Event Hubs or the simulator, keeps transport metadata (where the event came from), and converts the message to a canonical `MatchEvent` the core understands.
	- Why it matters: separates delivery details from football facts, so the rest of the system only sees clean, consistent inputs.

- `MatchProcessor` (central deterministic core):
	- What it does: the rule-based brain that orders events, rebuilds who had the ball (possession), updates running statistics, detects patterns (like sustained pressure), computes `ActionImpact` (how much an action changed the game), and chains events into causal stories.
	- Why it matters: produces reliable, repeatable facts and signals that downstream features and AI can trust.

- Domain models and computed facts:
	- What they are: structured representations of events, possessions, sequences, metrics, patterns, and validated claims.
	- Why they matter: provide a consistent language the entire system (and humans) use to reason about a match.

- Candidate generation & deterministic validation:
	- What it does: the system turns detected patterns and metrics into candidate insights (structured claims) and runs deterministic checks to verify them before any AI sees them.
	- Why it matters: prevents AI from building narratives on unverified or invented claims.

- Agent context assembly (`AgentContextBuilder`):
	- What it does: gathers only the needed, verified facts, evidence links, and impacts into a compact context for AI, filtering out irrelevant detail.
	- Why it matters: keeps AI focused, reduces cost and risk, and enforces the rule that AI only sees validated information.

- Agent orchestration and gateway (`AgentOrchestrator` / `AgentGateway`):
	- What it does: sends the bounded context to the AI provider (Microsoft Foundry), receives structured responses, captures traces, and ensures responses are validated and safe.
	- Why it matters: gives AI a controlled, auditable path so human-facing language is grounded and traceable.

- Microsoft Foundry (AI provider):
	- What it does: generates narrative explanations, audience-tailored wording, or validation checks over the supplied, bounded context.
	- Why it matters: produces readable stories and explanations without touching the raw deterministic facts.

- Insight/Story assembly and traceability:
	- What it does: combines deterministic evidence, agent output, and validation records into an `Insight` or `Story` object that links back to the exact events and calculations.
	- Why it matters: makes every narrative auditable — you can trace a sentence back to the exact play and numeric factors that support it.

- Services and infrastructure (API, repositories, streaming, observability):
	- What they do: store and expose processed facts, serve APIs for dashboards and clients, publish or consume event streams, and provide health, readiness, and logging so operators know the system status.
	- Why they matter: turn internal intelligence into usable products and keep the system observable and manageable in production.

- Testing, evaluation, and `evals`:
	- What they do: provide fixtures, scenario runners, and test suites to verify deterministic logic and to run end-to-end checks including the simulator and AI integration (where possible).
	- Why they matter: ensure changes don't break traceability, metrics, or the guarantees the system promises.

- Safety and fallback behavior:
	- What it does: when an external dependency (Event Hubs or AI provider) is unavailable or returns invalid output, the system reports the condition and falls back to deterministic representations rather than pretending AI succeeded.
	- Why it matters: preserves trust — stakeholders always see what is verifiably true even when AI or cloud services are down.

End-to-end example (in plain terms)
- A simulated or live pass event arrives. The ingestion layer unwraps it and turns it into a canonical `MatchEvent`.
- `MatchProcessor` updates possession, computes the pass's `ActionImpact`, and identifies nearby events that together form a suspicious pattern.
- The system bundles the validated evidence and the best supporting impacts into a compact context, then sends it to the AI agent.
- AI returns a short explanation; the system validates the response (format, required fields) and attaches the AI text to the deterministic evidence so reviewers can follow the trail.
- The API exposes both the raw, computed facts and the AI-generated narrative, with links so a user can inspect the exact events and calculations behind the story.

