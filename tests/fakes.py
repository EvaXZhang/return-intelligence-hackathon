"""Offline fakes for live-provider code paths. Nothing here calls AWS or Bedrock."""
from __future__ import annotations

from return_intelligence.providers.bedrock import BedrockProvider

_DEFAULT_REASON = {
    "categories": ["Wrong Size"],
    "details": {"size_direction": "too_small"},
    "customer_summary": "The shoe is too small.",
}
_DEFAULT_VISUAL = {
    "evidence_sufficient": True,
    "eligibility_state": "ELIGIBLE_UNWORN",
    "preliminary_grade": "A",
    "evidence": ["clean soles"],
    "retakes": [],
    "uncertainty": [],
}


class FakeLiveProvider:
    """Scriptable live provider. Defaults match the original tests/test_ai_provider_wiring.py fake."""

    provider_kind = "fake_live"
    display_label = "FAKE LIVE PROVIDER"
    is_live = True

    def __init__(self, *, visual=None, recommendation=None, fulfillment=None, reason=None):
        self.calls = []
        self.facts = {}
        self.visual = dict(_DEFAULT_VISUAL if visual is None else visual)
        self.recommendation = "Live explanation constrained to verified options." if recommendation is None else recommendation
        self.fulfillment = "Demo instructions only." if fulfillment is None else fulfillment
        self.reason = dict(_DEFAULT_REASON if reason is None else reason)

    def classify_reason(self, text):
        self.calls.append("reason")
        return dict(self.reason)

    def compose_recommendation(self, facts):
        self.calls.append("retention")
        self.facts["retention"] = facts
        assert all(option["available"] > 0 for option in facts["verified_inventory_options"])
        return self.recommendation

    def assess_visual_evidence(self, fixture_key, images=None):
        self.calls.append("visual")
        assert images
        return dict(self.visual)

    def explain_alert(self, facts):
        self.calls.append("early_warning")
        return "Suspected size pattern with investigation steps."

    def explain_route(self, facts):
        self.calls.append("routing")
        return f"Explained locked {facts['destination_type']} route."

    def compose_fulfillment_instructions(self, facts):
        self.calls.append("fulfillment")
        self.facts["fulfillment"] = facts
        return self.fulfillment


class FakeRuntime:
    """Stands in for StrandsMultiAgentRuntime: records (key, prompt), returns output_model(**outputs[key])."""

    def __init__(self, outputs):
        self.outputs = outputs
        self.prompts = []
        self.delegation_history = []

    def run(self, key, prompt, output_model):
        self.prompts.append((key, prompt))
        self.delegation_history.append({"supervisor": "Supervisor", "specialist": key})
        return output_model(**self.outputs[key])


def make_fake_bedrock_provider(outputs):
    """Real BedrockProvider methods over a FakeRuntime. Built with __new__ so __init__ (and AWS) never runs."""
    provider = BedrockProvider.__new__(BedrockProvider)
    provider.config = None
    provider._model_id = "fake-model"
    provider._runtime = FakeRuntime(outputs)
    return provider
