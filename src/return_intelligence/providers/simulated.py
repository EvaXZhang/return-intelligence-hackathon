from __future__ import annotations


class SimulatedAIProvider:
    provider_kind = "simulated"
    display_label = "SIMULATED AI OUTPUT — deterministic local rules"
    is_live = False

    def classify_reason(self, text):
        return {"normalized": text.casefold(), "provider_kind": self.provider_kind}

    def compose_recommendation(self, facts):
        preferred = facts.get("preferred_action")
        options = facts.get("verified_inventory_options") or ()
        if preferred == "EXCHANGE" and options:
            sizes = sorted({str(option["size"]) for option in options}, key=lambda value: (len(value), value))
            return (
                "Clearly simulated recommendation: we found verified in-stock pairs "
                f"(size {', '.join(sizes)}), so we recommend an exchange. You get the right fit or colour "
                "without waiting for a refund. A valid refund remains available."
            )
        if preferred == "RESHIP" and options:
            if facts.get("resolution_path") == "MISSING_ITEM":
                lead = "we can reship the missing item from verified local stock"
            else:
                lead = "the ordered pair is unavailable, but we can ship a similar in-stock style in your size"
            return (
                f"Clearly simulated recommendation: {lead}. No return is needed. "
                "A valid refund remains available."
            )
        return "Clearly simulated recommendation based only on verified local synthetic inventory. A valid refund remains available."

    def assess_visual_evidence(self, fixture_key, images=None):
        return {"fixture_key": fixture_key, "simulated": True}

    def explain_alert(self, facts):
        return "Suspected pattern—investigation recommended; this is not a confirmed manufacturing defect."

    def explain_route(self, facts):
        return "Simulated explanation of the deterministic condition × seasonality matrix and destination score."

    def compose_fulfillment_instructions(self, facts):
        mode = facts.get("fulfillment_mode") or "SHIP"
        store = facts.get("customer_return_store") or {}
        name = store.get("name") or "your nearby return store"
        where = f"{name}, {store['address']}" if store.get("address") else name
        if mode == "DROPOFF":
            method = f"Bring the shoes to {where}. Store drop-off is FREE."
        else:
            method = (
                f"Ship the shoes to {where} with the prepaid label ($9). "
                "Prefer not to pay? Drop-off at this store is FREE."
            )
        return f"{method} This artifact is a local demo and is not valid for shipping."
