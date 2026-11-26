# Tests and Current Limitations

The pytest suite runs with `AI_BACKEND=simulated` and makes no AWS calls. Live provider code is tested only with fakes (`tests/fakes.py`). It currently reports **206 passed** (1 ReportLab deprecation warning):

```zsh
AI_BACKEND=simulated AWS_INTEGRATION_ENABLED=false DEPLOYMENT_ENABLED=false PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
```

The v2 test modules are `test_migrations.py`, `test_seasonality_clock.py`, `test_reason_classifier.py`, `test_resolution_paths.py`, `test_customer_copy.py`, `test_confidence_gate.py`, `test_bedrock_provider_contract.py`, `test_staff_authority.py`, `test_early_warning_v2.py`, `test_kpis.py` and `test_ui_surfaces.py` (Streamlit AppTest). The separate `scripts/smoke_bedrock_*.py` make real, paid Bedrock calls and are not part of the suite.

Current limitations:

- The photo confidence is the LLM's self-reported value (or a fixed fixture value in simulated mode). It is not statistically calibrated: fine for the demo, not for production. The staff Force 95% / Force 75% override exists only for demos.
- Early warning counts a sales period in full when it overlaps the 90-day window; periods are not prorated.
- A database created before v2 keeps its old rows and timestamps. Legacy alerts and requests still render, but a **Reset and reseed** is recommended before a rehearsal.
- `SYN-STORE-2` becomes a drop-off store only on a fresh or reset database, because seeding never updates existing rows.
- If every eligible store is full, the request is `ROUTING_BLOCKED`; there is no further fallback.
- Customer emails are mock records in `customer_messages`; nothing is sent.
- There is no authentication for customers or staff, and the staff ID is free text. Run it as a local demo only.
- Three practical photos (Front, Left, Right, at least 320×240) are required. Only an unusable specific photo should trigger a retake.
- Inventory, destinations and reservations are synthetic local snapshots. Logistics and refunds are not executed; PDFs and QR tokens are local demos.
- There is no fraud or tax logic, production geocoding or cloud durability.
- Live mode uses the local AWS credential chain and incurs Bedrock inference charges. No AWS infrastructure is provisioned.
