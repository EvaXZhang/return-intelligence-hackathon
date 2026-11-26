# Architecture

`app.py` is a local Streamlit frontend over a modular Python application with SQLite persistence. `SupervisorService` owns workflow state and deterministic gates. In live mode, `BedrockProvider` creates a real Strands Supervisor and six specialist Strands Agents backed by `amazon.nova-lite-v1:0` in `us-east-1`.

## Live execution

```text
Customer / Staff Streamlit UI
            |
      SupervisorService -------- SQLite / local uploads / demo artifacts
            |
      BedrockProvider
            |
   Strands Supervisor Agent
      |     |     |     |     |     |
   Reason Retain Alert Visual Route Fulfillment specialist Agents
            |
     Amazon Bedrock Nova Lite
```

The Strands Supervisor exposes six specialist delegation tools. For each deterministic workflow state, only the matching tool is authorized. The specialist produces structured output; Python validates and persists it. Model conversation history is cleared between workflow stages because durable state belongs in SQLite, preventing cross-request contamination.

## Deterministic authority

Bedrock provides language/vision intelligence but cannot modify:

- return eligibility and worn/ineligible separation (worn is never Grade C);
- manufacturing-defect hold and its staff resolution (confirmed defects are never routed or resold);
- inventory filtering, the exchange-first recommended action (passed as `preferred_action`) and the fulfillment path;
- customer decision rights (a valid refund is always offered);
- the photo gate: at or above 0.85 on the AI's self-reported confidence skips review, while below 0.85 (or missing/invalid confidence) goes to staff, with a staff-only demo override (Force 95% / Force 75%) stored in `demo_settings`;
- condition × seasonality route type, which is only a system suggestion: staff record the final destination in `staff_destination_decisions`;
- the customer return store (nearest eligible store, drop-off FREE, mail-in $9) and the customer-safe copy guard;
- destination capacity and scoring;
- early-warning thresholds, window, dedupe and alert status (OPEN → INVESTIGATING → CLOSED, staff only);
- fulfillment gates.

The route matrix remains A+0 retail, A+1 outlet, B+0/1 outlet, C+0/1 company warehouse, and Worn+0/1 reject. Defects stop before matrix evaluation. Candidate score weights are distance 25%, transport cost 20%, capacity 20%, inventory/load fit 15%, and demand 20%, with deterministic ID tie-breaks. Customers always return to the nearest eligible store; the internal destination is never shown to them.

## Early warning

`EarlyWarningAgent` evaluates every label of a request at two levels over the 90 days ending on the business clock: SKU + size (baseline: the same SKU's other sizes) and series = `products.model_id` (baseline: other models in the same `similar_group`). The rule in `domain/early_warning_rules.py` (at least 5 complaints, 20 units, 15% rate, 2× lift; without a comparable baseline, count + units + rate only) is shared with the local Lambda-style handler. An active alert with the same fingerprint is updated without a new AI call; an alert closed in the same window is not re-raised. Product/series flags are derived from active alerts and never stored. KPIs come from `services/kpis.py`.

## Data and services

SQLite uses foreign keys, WAL, busy timeout, write transactions, optimistic versions, normalized complaint/decision/review/route/artifact tables, and append-only activity triggers. v2 tables (`customer_messages`, `staff_destination_decisions`, `alert_status_events`, `demo_settings`) are appended to `schema.sql`, and new nullable columns are added by `db/migrations.py` on every boot, so older databases upgrade in place. Photos are validated and stored locally before the selected uploaded bytes are sent to Bedrock vision. Logistics artifacts stay local and are marked `DEMO / NOT VALID FOR SHIPPING`.

No Lambda, S3, DynamoDB, IAM, API Gateway, or hosting resource is created. Lambda-compatible pure Python handlers remain available for later deployment after company authorization.
