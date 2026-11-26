# ReMatch — 8-minute pitch outline

## 0:00–2:24 · Business impact and thesis (30%)

**Hook:** “A returned shoe is not automatically waste—it may already have its next buyer.” Returns separate available inventory from demand, while default liquidation recovers only a fraction of value.

**Thesis:** ReMatch checks eligibility, understands provisional condition, and matches a return to consented demand before liquidation. In the illustrative B-grade unit: $120 retail → $102 resale − $12 cleaning/routing = $90 net versus $30 liquidation, or +$60 and 3.0× recovery. The refund is common to both paths and excluded from the differential comparison.

**Pilot measures:** net recovery per return, offer acceptance, hours to re-match, sell-through, staff grade override, fallback rate, and operational cost. Label every number as an illustrative assumption until a pilot validates it.

## 2:24–4:24 · Agentic innovation (25%)

Use the live demo. Click **Run to next checkpoint** and narrate the single agent selecting governed tools based on state—not replaying six slides:

1. `check_return` can stop ineligible/final-sale cases.
2. `grade_condition` records preliminary evidence/confidence and can escalate uncertainty.
3. `find_buyers` filters consent/product/condition before ranking operational fit.
4. `calculate_offer` applies a non-negotiable deterministic floor.
5. Store staff alone confirms or changes the final A/B/C condition grade.
6. Buyer Juniper declines; the event changes state. The agent explicitly re-plans, retains the floor, selects Buyer Maple, obtains acceptance, and routes.
7. Show the B→C control: new staff evidence triggers a $78 re-price and Buyer Cedar re-match.

The innovation is bounded agency: dynamic tool selection and recovery from external events, with pricing, consent, and fairness enforced outside the model and final condition owned by staff.

## 4:24–5:36 · Scalability and feasibility (15%)

Show AWS Architecture. Today: Streamlit, typed state, seven local adapters, synthetic JSON, append-only-style trace, plus a credential-gated Strands/Bedrock boundary. Production: UI → API Gateway → Strands on Lambda or optional AgentCore → Bedrock; seven Lambda tools; S3 photos; DynamoDB workflow state; CloudWatch audit and metrics.

The interfaces already map one-for-one, so scaling changes adapters and persistence—not the business contract. AgentCore is an option, not a blocker. No resources need to be deployed for the hackathon proof.

## 5:36–6:48 · Presentation and story (15%)

Land the outcome visibly: an eligible return, staff-confirmed condition, consented accepting buyer, guarded price, nearest sensible store, and a complete audit trail. Contrast $90 and $30.

One-sentence product future: “ReMatch turns every return desk into a network-wide recovery decision point.”

## 6:48–8:00 · Technical execution and responsible AI (15%)

Open one audit event: structured sanitized input/output, concise rationale, confidence, reason codes, guardrails, and staff confirmation—never private chain-of-thought.

Close on five controls:

- AI/preset photo grade is preliminary; store staff selects the final A/B/C grade.
- Low confidence or conflicting evidence pauses for staff review.
- The deterministic price floor cannot be overridden by model output.
- Buyers opt in; matching excludes protected traits, profile proxies, and raw PII.
- No profitable buyer triggers outlet/liquidation fallback.

**Final line:** “ReMatch does not ask AI to make retail policy. It gives an agent room to navigate uncertainty inside policy—so ALDO can recover value without giving up control.”

## Presenter handoff and fallback

- Presenter 1: problem, thesis, economics (2:24).
- Presenter 2: live flow and re-plan (2:00).
- Presenter 3: architecture and feasibility (1:12).
- Presenter 1: outcome and close (1:12).
- Presenter 2: audit/responsible AI (1:12).

If AWS or Wi-Fi fails, select Demo mode. If a click is missed, Reset → Run to checkpoint restores the scenario deterministically. Keep screenshots of Overview, inspection checkpoint, decline/re-plan trace, final route, and architecture as a slide-only fallback.
