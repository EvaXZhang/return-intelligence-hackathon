# ReMatch AWS architecture mapping

## Interaction path

```text
Streamlit or React
  │ HTTPS
  ▼
Amazon API Gateway
  ▼
Strands agent on AWS Lambda ───── optional: Bedrock AgentCore Runtime
  │              │
  │              └── Amazon Bedrock multimodal model
  ▼
Seven deterministic Lambda tool APIs
  ├── check_return
  ├── grade_condition
  ├── find_buyers
  ├── calculate_offer
  ├── send_offer
  ├── approve_inspection
  └── route_item
      │
      ├── DynamoDB: return, offer, idempotency, and checkpoint state
      ├── S3: approved photos and synthetic artifacts
      └── CloudWatch: calls, reason codes, checks, latency, errors, approvals
```

## Implemented now versus production extension

| Capability | Prototype now | Production extension |
|---|---|---|
| Experience | Polished local Streamlit app | React or hosted Streamlit behind authenticated APIs |
| Orchestration | Resumable state machine; deterministic Demo plus Strands with seven registered schemas and a state-permission validator | Strands on Lambda; optional AgentCore for managed runtime features |
| Model | Lazy, configurable Bedrock boundary | Enabled multimodal model selected per region, evaluated and monitored |
| Tools | Seven typed deterministic local adapters | One independently permissioned Lambda/API per tool |
| State | Streamlit session + synthetic JSON | DynamoDB with conditional updates and idempotency keys |
| Photos | Optional in-memory upload | Encrypted S3 prefix, short retention, malware/content controls |
| Audit | Append-only-style structured events in session | CloudWatch plus durable, access-controlled audit records |
| Entry/security | Local process | API Gateway, auth, throttling, WAF as appropriate, least-privilege IAM |

No infrastructure is provisioned by the prototype. AgentCore is optional and not a delivery dependency.

## Trust boundaries

1. **UI boundary:** validate file type/size and associate uploads with synthetic or authorized return IDs.
2. **Agent boundary:** send only minimum synthetic/authorized context. Never include raw source files, full buyer records, names, emails, protected traits, or private chain-of-thought.
3. **Tool boundary:** every model-proposed action is schema-validated before execution. Policy, consent, ranking inputs, and price floor live in deterministic code.
4. **Human boundary:** the AI condition grade is preliminary; store staff alone selects the final A/B/C grade. Low confidence or conflicting evidence pauses the flow for staff review.
5. **Fallback boundary:** no profitable eligible buyer means outlet/liquidation, not a forced match or floor waiver.

## Service responsibilities

- **Amazon Bedrock:** interpret allowed image evidence and propose bounded structured decisions. Model ID and region remain environment-configurable.
- **Strands Agents SDK:** manage the single agent loop and allowed tool selection; preserve resumable checkpoints and re-plan after external events.
- **AWS Lambda:** host the orchestrator and deterministic ALDO API adapters. Assign narrow IAM permissions per function.
- **Amazon API Gateway:** expose authenticated, throttled endpoints to the UI.
- **Amazon S3:** hold authorized photos and explicitly synthetic artifacts under encryption and lifecycle policies.
- **Amazon DynamoDB:** persist return, inspection, candidate, offer, route, and idempotency state.
- **Amazon CloudWatch:** measure tool latency/errors and record structured reason codes, guardrail outcomes, and staff grade events.
- **Bedrock AgentCore Runtime (optional):** provide a managed runtime path if its operational benefits justify adoption after the pilot.

## Pilot-to-production sequence

1. Shadow-test grades and buyer ranking on consented, de-identified pilot cases; humans make all final condition decisions.
2. Calibrate confidence, grade overrides, price assumptions, and operational costs.
3. Move tool contracts to Lambda and state to DynamoDB; add idempotency, IAM, auth, retention, and observability.
4. Enable limited staff-assisted offers with rollback and outlet/liquidation fallback paths.
5. Expand only after recovery, acceptance, override, fairness, and error metrics meet agreed thresholds.
