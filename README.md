# Return Intelligence

Return Intelligence is a Streamlit prototype from a second-place McGill BSRM × ALDO Retail GenAI Hackathon project. It uses a Strands Supervisor and six Amazon Bedrock specialists to help process shoe returns, recommend exchanges, and flag unusual complaint patterns. Python rules control policy, inventory, routing, and staff review.

This repository includes the updated Return Intelligence prototype and [ReMatch](examples/rematch/README.md), a separate return-to-resale demo. The demos use synthetic orders, products, customers, and inventory. The main app seeds its own SQLite database.

## Run the offline demo

From the repository root, create a Python 3.11+ environment and install the project:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
```

Launch the app in simulated mode:

```bash
AI_BACKEND=simulated AWS_INTEGRATION_ENABLED=false DEPLOYMENT_ENABLED=false DEMO_SEASON=WINTER \
  python -m streamlit run app.py --server.address=127.0.0.1 --server.port=8504
```

Open <http://127.0.0.1:8504>. [The demo walkthrough](DEMO.md) covers the Customer Portal, Staff Dashboard, and multi-agent activity timeline. Use **Reset synthetic demo → Reset and reseed** to restart a rehearsal.

## Run with Amazon Bedrock

Use AWS credentials from the standard credential chain and a Bedrock model enabled for your account and region. The model and region below are the prototype's example settings.

```bash
AI_BACKEND=bedrock AWS_INTEGRATION_ENABLED=true DEPLOYMENT_ENABLED=false \
  AWS_REGION=us-east-1 BEDROCK_MODEL_ID=amazon.nova-lite-v1:0 DEMO_SEASON=WINTER \
  python -m streamlit run app.py --server.address=127.0.0.1 --server.port=8504
```

Live mode sends submitted return descriptions and photos to Bedrock and can incur inference charges. Run the demos locally. The app has no authentication, and its emails, refunds, and shipping artifacts are simulations.

## Business clock and season

- `DEMO_CLOCK` sets the business clock. It defaults to `2026-01-15T12:00:00+00:00`, which matches the seeded history. `DEMO_CLOCK=now` (or empty) uses the real UTC date.
- The season comes from the clock month on a Montréal retail calendar: Nov–Mar WINTER, May–Aug SUMMER, Apr/Sep/Oct TRANSITION.
- `DEMO_SEASON=SUMMER|WINTER|TRANSITION` overrides the derived season. Pin `DEMO_SEASON=WINTER` for rehearsals.
- The same clock sets the 90-day early-warning window and stamps new complaint events.

## Customer flow

1. **Reason (multi-label).** The customer describes the problem in natural language (English or Chinese). The Reason agent returns categories (Wrong Size, Wrong Color, Dislike/Preference, Quality Issue, Delayed Shipping, Missing Item/Wrong Item, Other) and fixed detail codes: `size_direction` (too_small/too_large/unspecified), `quality_symptom` (sole_separation, stitching_seam, material_damage, hardware_failure, other_quality) and `fulfillment_issue` (missing_item, wrong_item, out_of_stock, other_fulfillment).
2. **Exchange-first solution.** Deterministic code picks verified in-stock options: other sizes in the needed direction for size problems, other colours for colour problems, similar styles in the customer's size for preference, and a similar-style fallback when the primary list is empty. When options exist, EXCHANGE is the recommended choice and the default. Refund always stays available.
3. **Two copies of the solution.** The customer gets a mock email, stored in `customer_messages` (channel EMAIL, status `MOCK_SENT`, recipient `customer-<order>@example.test`). Nothing is actually sent. The staff copy (`staff_solution_json`) keeps categories, detail codes, path, options, allowed choices and, later, the customer's final decision.
4. **Fulfillment paths.**
   - Missing item: reship the same variant (or a similar in-stock style in the same size), or refund. No photos or label.
   - Out of stock: ship a similar in-stock style in the same size, or refund. No photos or label.
   - Wrong item, or an order that was never delivered: service resolution or refund.
   - Delayed but delivered: the normal flow (exchange/keep/refund).
5. **Photos and grading.** Three photos (front, left, right). The AI decides evidence sufficiency, eligibility (eligible/unworn, worn/ineligible, suspected defect) and a preliminary A/B/C. Worn shoes are never Grade C and are not accepted. A/B/C is a general freshness standard: C means eligible and unworn, just less new.
6. **Return method.** Every grade returns to the nearest eligible store. Store drop-off is **FREE** and recommended. Mailing costs **$9** for every mail-in, exchanges included; the prepaid label is addressed to that store. If the nearest store is full, the next nearest drop-off store is used; if every eligible store is full the request is `ROUTING_BLOCKED`.
7. **Exchange completion.** An exchange reserves the replacement, waits for the original pair, then releases it (`COMPLETED_EXCHANGE`). A reservation is released whenever the exchange cannot go ahead (worn close, confirmed-defect refund).

Customers never see internal destinations: no outlet, warehouse, secondary market, recycling, resale, routing or destination IDs. AI-written customer text and the mock email pass a guard that falls back to a fixed template when an internal term appears.

## Photo confidence gate

- The AI self-reports a confidence between 0 and 1 (simulated fixtures carry a fixed value).
- Confidence at or above 0.85 skips human review. Confidence below 0.85, or missing/invalid confidence, goes to staff. This applies to eligible, worn and suspected-defect results alike. Existing persisted assessments are unchanged; the rule applies to future photo submissions.
- Staff can force the gate for demos in **Staff controls → Demo photo-confidence override (staff only)**: Use AI confidence, Force 95% or Force 75%. The choice is stored in `demo_settings`, so it applies across browser tabs. The customer page never shows a confidence value.
- LLM self-reported confidence is not statistically calibrated. It is fine for this demo, not for production.

## Staff authority

- **Human review:** confirm the AI result, override to A/B/C, mark worn/ineligible, or hold a suspected defect.
- **Defect hold:** resolve as Not a defect (staff grade A/B/C, back to the normal flow) or Confirmed defect. A confirmed defect follows the customer's decision: an exchange with a live reservation gets the replacement released, anything else gets a refund recorded. The request ends in `DEFECT_RESOLVED`; the pair is never routed or resold.
- **Final destination:** the condition × seasonality matrix (A in season → retail store, A off season → outlet, B → outlet, C → company warehouse) and the destination score produce a system suggestion only. Staff record the final destination in **Final destination (staff decision)**; a reason is required when it differs from the suggestion. The latest decision wins, and it never changes the customer flow.
- **AI grading report:** eligibility, grade, gate and AI confidence, source, evidence, uncertainty and a lifecycle block (season, product season profile, in season or off season).

## Early warning

- **Two levels**, evaluated for every label of a request:
  - SKU + size (for example `SYN-RUNNER-100|8`), compared with the same SKU's other sizes.
  - Series = `model_id` (one style across all sizes and colours, for example `SYN-MODEL-RUNNER`), compared with other models in the same `similar_group`.
- **Window:** the 90 days ending on the business clock. Complaints outside it are ignored. Sales periods that overlap the window count in full.
- **Rule:** at least 5 complaints, at least 20 units sold, a rate of at least 15%, and a lift of at least 2× over the baseline. When no comparable baseline exists, the alert rests on the count, units and rate alone, and the card shows "n/a — no comparable baseline".
- **Grouping:** complaints group by category plus fixed detail code, so differently worded AI details land together.
- **Dedupe:** an active alert with the same fingerprint gets its metrics updated, with no new AI call. An alert closed within the same window is not raised again.
- **Status:** OPEN → INVESTIGATING → CLOSED only, through **Start investigation** and **Close alert** on the alert card. Each change is written to `alert_status_events` with the staff ID and an optional note.
- **Flags:** **Product / series flags** are derived from OPEN and INVESTIGATING alerts and disappear when the alert closes. A request whose series is flagged shows a warning in its detail view.
- Every alert is a suspected pattern, not a confirmed defect.

## KPIs

The Staff Dashboard shows Synthetic requests, Open human reviews and Active suspected-pattern alerts (OPEN + INVESTIGATING), then Exchanges, Refunds, Keeps, Exchange rate, Retention rate and Store drop-off share.

- Decided = requests whose current decision is EXCHANGE, KEEP or REFUND. Reships and service cases are not counted.
- Exchange rate = exchanges ÷ decided. Retention rate = (exchanges + keeps) ÷ decided.
- Store drop-off share = drop-off routes ÷ all routes.
- "—" is shown when a denominator is 0.

## Multi-agent execution

Every generative step goes through the Strands Supervisor, which may delegate only to the specialist for the current stage:

1. Return Reason Classification Agent: structured multi-label classification with fixed detail codes.
2. Customer Retention & Recommendation Agent: wording constrained to verified options; follows the deterministic recommended action.
3. Early Warning & Product Issue Detection Agent: explains deterministic metrics, names the level and states when no baseline exists.
4. Visual Condition Assessment Agent: three-photo sufficiency, eligibility, preliminary grade and self-reported confidence.
5. Seasonality & Routing Optimization Agent: explains the locked route as a system suggestion.
6. Fulfillment & Label Generation Agent: customer instructions naming only the return store.

The activity timeline shows public rationale and provider details, never chain-of-thought.

## Persistence and mocked logistics

SQLite stores requests, classifications, recommendations, mock emails, staff copies, complaints, decisions, reservations, assessments, reviews, alerts and their status history, routes, staff destination decisions, artifacts and activity. Schema changes are additive (`db/migrations.py`), so older databases upgrade on boot. Shipping PDFs and drop-off QR confirmations are local files marked `DEMO / NOT VALID FOR SHIPPING`; no carrier is called.

## Tests

The suite uses the simulated provider and makes no AWS calls:

```zsh
AI_BACKEND=simulated AWS_INTEGRATION_ENABLED=false DEPLOYMENT_ENABLED=false PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

Current result: **206 passed** (1 ReportLab deprecation warning).

`scripts/smoke_bedrock_*.py` make real, paid Bedrock calls. Run them only when live charges are authorized.

## Security note

There is no authentication. Anyone who can open the page can use the Staff Dashboard, change the demo override, resolve reviews and close alerts. The staff ID is a free-text field. Run this only as a local demo on your own machine.

See [DEMO.md](DEMO.md), [architecture](docs/architecture.md), [project structure](docs/project-structure.md) and [tests and limitations](docs/test-and-limitations.md).
