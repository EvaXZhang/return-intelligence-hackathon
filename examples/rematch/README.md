# ReMatch

**Agentic return-to-resale: every eligible return, matched to its next buyer.** A presentation-ready prototype for the McGill BSRM × ALDO Retail Gen AI Hackathon.

ReMatch uses one resumable agent to check a return, provisionally grade condition, rank opted-in demand, calculate a guarded offer, react to rejection or a staff grade change, and route the item. Policy, price floors, consent, and fairness remain deterministic. The AI grade is always preliminary; store staff alone selects the final A/B/C condition grade.

## Quick start (macOS / zsh)

Prerequisite: Python 3.11 or newer.

```zsh
cd examples/rematch
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
REMATCH_MODE=demo PYTHONPATH=src .venv/bin/python -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8502
```

Demo mode makes no AWS call.

## Run with real Amazon Bedrock

Run this command from `examples/rematch` after creating the environment above. AWS mode uses the standard AWS credential chain and a model enabled in the selected region. The verified hackathon configuration is:

```zsh
REMATCH_MODE=aws AWS_REGION=us-east-1 BEDROCK_MODEL_ID=amazon.nova-lite-v1:0 PYTHONPATH=src .venv/bin/python -m streamlit run streamlit_app.py --server.headless=true --server.address=127.0.0.1 --server.port=8502 --browser.gatherUsageStats=false
```

Open `http://127.0.0.1:8502`. The Strands agent and Bedrock model are created lazily. Seven schema-constrained tools are registered. The model selects a state-permitted action, while deterministic adapters enforce policy, consent, matching, pricing, and routing. `approve_inspection` is human-only: the model cannot finalize or change the grade. AWS errors are shown explicitly and never silently fall back to Demo mode.

Configuration defaults are documented in `.env.example`. Never store access keys in project files.

## What the prototype implements

- A deterministic Demo orchestrator and a credential-gated Strands/Bedrock orchestrator sharing one typed state contract.
- Seven mock ALDO tools: `check_return`, `grade_condition`, `find_buyers`, `calculate_offer`, `send_offer`, `approve_inspection`, and `route_item`.
- Policy checks for order/SKU, return window, returnable flag, and final sale.
- Preliminary condition evidence/confidence and mandatory staff selection of the final A/B/C grade.
- A low-confidence/conflicting-evidence branch that pauses before matching for staff review.
- At least three pseudonymous, opted-in candidates ranked using product, wear, price, and proximity only.
- Deterministic price floor, safe outlet/liquidation fallback, reason codes, and append-only-style audit events.
- Dynamic first-buyer decline → re-plan → second-buyer acceptance.
- Staff B→C change → automatic $78 re-price and Buyer Cedar re-match.
- A warm Streamlit story across Overview, Live Agent Demo, Economics / Impact, Responsible AI, and AWS Architecture.

## Illustrative unit economics

For the rehearsed B-grade $120 return: $102 resale − $7 cleaning − $5 routing = **$90 net recovery**, versus a **$30 liquidation** baseline: **+$60 incremental** and **3.0× recovery**. These are illustrative assumptions, not a forecast. Customer refund cost is common to resale and liquidation, so it is excluded from the differential comparison.

## Privacy boundary

`data/synthetic_demo.json` is hand-authored and explicitly synthetic. It has pseudonymous buyer labels and no names, emails, source IDs, protected traits, or copied records. The app never imports the parent workspace's source datasets.

Only selected synthetic context and an optional user-uploaded shoe photo may cross the Bedrock boundary in AWS mode. Raw CSV/XLSX/DOCX files, real PII, customer names/emails, and exact source records must never be sent to Bedrock. Uploads remain in memory in this local prototype.

## AWS production mapping

```text
Streamlit / React UI
  → API Gateway
  → Strands agent on Lambda (or optional Bedrock AgentCore Runtime)
  → Amazon Bedrock
  ↘ seven deterministic Lambda tool APIs
      ↘ DynamoDB state + S3 photos/synthetic artifacts + CloudWatch audit/metrics
```

See `docs/aws-architecture.md`. The project contains no deployment scripts and creates no AWS resources.

## 3–4 minute click-by-click demo

1. **Overview:** state the thesis and point to the illustrative ~3× recovery.
2. In **Live Agent Demo**, select AWS or Demo and click **Run to next checkpoint**. Narrate policy eligibility, preliminary Bedrock/preset B evidence, opted-in candidates, and deterministic economics.
3. At **Staff checkpoint**, choose the final A, B, or C grade and click **Record final grade and unlock agent**. Explain that AI can propose a grade but only staff finalizes it.
4. Click **Next agent action** to show Buyer Juniper decline, dynamic re-planning, Buyer Maple acceptance, and routing.
5. Reset and change B→C to show automatic $78 re-pricing and Buyer Cedar re-matching.
6. Show the uncertainty and no-profitable-buyer branches in Demo mode if time permits.
7. Open an activity event to show sanitized data and reason codes—not chain-of-thought.
8. Close on Responsible AI and AWS Architecture.

**Fallback plan:** keep Demo mode available; it requires no network or AWS credentials. If AWS reports a credential/model error, select Demo and continue with identical deterministic business controls.

## Validation commands

```zsh
REMATCH_MODE=demo PYTHONPATH=src .venv/bin/python scripts/smoke_scenario.py
REMATCH_MODE=demo PYTHONPATH=src .venv/bin/python scripts/smoke_streamlit.py
```

## Troubleshooting

- `ModuleNotFoundError`: run from `examples/rematch` with `PYTHONPATH=src` and `.venv/bin/python`.
- Port in use: add `--server.port 8502`.
- AWS credentials: run `aws sts get-caller-identity`; if needed, authenticate with `aws login`.
- AWS model error: confirm `BEDROCK_MODEL_ID` is enabled in `AWS_REGION`.
- Staff grade did not advance: use **Reset scenario**, run to the checkpoint, choose A/B/C, and click **Record final grade and unlock agent**.
- No buyer remains: this is a guarded outcome; the agent chooses outlet/liquidation instead of going below the price floor.

The 8-minute presentation structure is in `docs/pitch-outline.md`.
