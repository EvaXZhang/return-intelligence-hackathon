# Live AI Verification

Verified on October 15, 2026 using the existing AWS CLI login credential chain in `us-east-1` and `amazon.nova-lite-v1:0`. This live evidence predates v2 and was not re-run for this copy; the v2 provider changes (model confidence, preferred action, customer-safe prompts, early-warning levels) are covered by offline fake-runtime tests only.

## Real Strands / Bedrock results (pre-v2)
- One Strands Supervisor delegated successfully to all six unique specialist Agents.
- Return Reason Agent classified “too small and tight” as `Wrong Size` with `size_direction=too_small`.
- Retention Agent produced customer guidance constrained to the supplied in-stock option and preserved Refund as a separate valid choice.
- Early Warning Agent explained deterministic metrics: 5 complaints / 25 units, 20% rate, 1% baseline, and 20× lift, with investigation language rather than a confirmed-defect claim.
- Visual Agent received the required Front, Left, and Right image content blocks. It correctly rejected synthetic illustrations as insufficient real shoe evidence, requested practical replacement views, and assigned no A/B/C.
- Routing Agent explained a destination already locked by Python's mandatory condition × seasonality matrix.
- Fulfillment Agent produced instructions for a locally generated artifact marked `DEMO / NOT VALID FOR SHIPPING`.
- A real `SupervisorService` application flow persisted live classification/recommendation output, an Exchange decision, an early-warning alert, and multi-agent activity to a temporary SQLite database.
- The LIVE Streamlit UI constructed successfully without triggering inference merely from page rendering.
No Lambda, S3, DynamoDB, IAM, API Gateway, App Runner, or other AWS resource was created, modified, or deleted. Only user-authorized Bedrock inference was used.

## Deterministic validation (current v2 copy)
- `206 passed`, `0 failed` in the local pytest suite (1 ReportLab deprecation warning).
- The tests use `AI_BACKEND=simulated` and fakes for the Bedrock provider, so they incur no inference charges.

## Live launch (this copy, port 8504)
```zsh
AI_BACKEND=bedrock AWS_INTEGRATION_ENABLED=true DEPLOYMENT_ENABLED=false AWS_REGION=us-east-1 BEDROCK_MODEL_ID=amazon.nova-lite-v1:0 DEMO_SEASON=WINTER python -m streamlit run app.py --server.headless=true --server.port=8504 --browser.gatherUsageStats=false
```
No artificial `maxTokens` limit is configured. Structured schemas and business validation still constrain fields for safety and correctness.
