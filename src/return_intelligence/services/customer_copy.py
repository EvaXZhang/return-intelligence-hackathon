"""Customer-facing copy: internal-term guard, mock solution email and deterministic fallbacks.

Customers never learn where a returned pair finally goes, so every AI-written customer text passes
through customer_safe(), which swaps in a deterministic template whenever an internal term appears.
This module has no package-level dependencies so agents can import it lazily without import cycles.
"""
from __future__ import annotations

FORBIDDEN_CUSTOMER_TERMS = (
    "outlet",
    "warehouse",
    "secondary market",
    "second-hand",
    "second hand",
    "secondhand",
    "recycl",
    "resale",
    "liquidat",
    "syn-outlet",
    "syn-wh",
    "company_warehouse",
    "retail_store",
    "routing",
    "internal destination",
    "final destination",
)

RETURN_METHOD_NOTE = (
    "Returning the original pair? Drop it off at a nearby store — it's FREE and the quickest option. "
    "Prefer to mail it? A prepaid label costs $9."
)
SIMULATED_EMAIL_FOOTER = "This is a simulated message for a synthetic demo; nothing was actually sent."

_CHOICE_LABELS = {
    "EXCHANGE": "Exchange for an in-stock pair",
    "KEEP": "Keep the shoes (no refund)",
    "REFUND": "Return for a refund",
    "SERVICE_RESOLUTION": "Service resolution",
}


def is_customer_safe(text) -> bool:
    folded = str(text or "").casefold()
    return not any(term in folded for term in FORBIDDEN_CUSTOMER_TERMS)


def customer_safe(text, fallback: str) -> str:
    """Return text unchanged when it is customer-safe, otherwise the deterministic fallback."""
    value = str(text or "").strip()
    return value if value and is_customer_safe(value) else fallback


def recipient_for(order_id: str) -> str:
    return f"customer-{str(order_id).strip().lower()}@example.test"


def choice_label(choice: str, resolution_path: str | None = None) -> str:
    if choice == "RESHIP":
        return "Reship the missing item" if resolution_path == "MISSING_ITEM" else "Ship a similar in-stock style instead"
    return _CHOICE_LABELS.get(choice, choice)


def option_label(option: dict) -> str:
    return f"{option['sku']} · size {option['size']} · {option['color']}"


def fallback_recommendation_text(preferred_action: str | None = None) -> str:
    lead = {
        "EXCHANGE": "We found in-stock pairs that should fit your needs, so an exchange is our recommended next step.",
        "RESHIP": "We can send you an in-stock pair right away, and no return is needed.",
    }.get(preferred_action or "", "Thanks for telling us what went wrong. Your available choices are listed below.")
    return f"{lead} A refund remains available if you prefer."


def fallback_fulfillment_text(mode: str | None, store_name: str | None, store_address: str | None) -> str:
    store = store_name or "your nearby return store"
    where = f"{store}, {store_address}" if store_address else store
    if mode == "DROPOFF":
        method = f"Bring the shoes to {where}. Store drop-off is FREE."
    else:
        method = (
            f"Ship the shoes to {where} with the prepaid label ($9). "
            "Prefer not to pay? Drop-off at this store is FREE."
        )
    return f"{method} This artifact is a local demo and is not valid for shipping."


def compose_solution_email(return_id: str, order_id: str, classification: dict, recommendation: dict) -> tuple[str, str]:
    """Build the (subject, body) of the mock solution email sent after the reason is classified."""
    path = recommendation.get("resolution_path") or "NORMAL"
    choices = list(recommendation.get("choices") or ())
    explanation = customer_safe(
        recommendation.get("explanation"),
        fallback_recommendation_text(recommendation.get("recommended_action")),
    )
    subject = f"Your return request {return_id}: options for order {order_id}"
    lines = [f"Hello, thanks for contacting us about order {order_id}."]
    categories = [str(getattr(value, "value", value)) for value in (classification or {}).get("categories") or ()]
    if categories:
        lines.append(f"What we understood: {', '.join(categories)}.")
    lines += ["", explanation]
    options = recommendation.get("options") or ()
    if options:
        lines += ["", "In-stock options for you:"]
        lines += [f"- {option_label(option)}" for option in options]
    if choices:
        lines += ["", "Your available choices:"]
        lines += [f"- {choice_label(choice, path)}" for choice in choices]
    if path == "NORMAL" and ("EXCHANGE" in choices or "REFUND" in choices):
        lines += ["", RETURN_METHOD_NOTE]
    lines += ["", SIMULATED_EMAIL_FOOTER]
    return subject, "\n".join(lines)
