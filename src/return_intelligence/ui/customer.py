from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from ..agents.visual import VisualConditionAssessmentAgent
from ..db.fixtures import SCENARIOS
from ..domain.errors import DomainError
from ..services.customer_copy import choice_label, option_label
from .components import state_badge


_REQUIRED_ANGLES = ("front", "left", "right")
METHOD_LABELS = {
    "DROPOFF": "Drop off at a nearby store · FREE (recommended)",
    "SHIP": "Ship with a prepaid label · $9",
}
# Customer-facing names of the simulated photo fixtures. They describe the photos only, never a
# confidence or the expected outcome; the fixture keys stay internal and staff control the review path.
PHOTO_SCENARIO_LABELS = {
    "eligible_a_95": "Clean unworn pair",
    "eligible_75": "Minor handling marks",
    "eligible_a_90": "Clean pair with slight glare on one photo",
    "worn_ineligible": "Visible wear",
    "worn_low_confidence": "Light try-on creasing",
    "suspected_defect": "Sole edge separating",
    "defect_low_confidence": "Small gap near the sole edge",
    "unclear": "Blurry or incomplete photos",
}


def _email_expander(view):
    messages = view.get("messages") or []
    if not messages:
        return
    with st.expander("Sent to your email (simulated)"):
        for message in messages:
            st.markdown(f"**To:** {message['recipient']}  \n**Subject:** {message['subject']}")
            st.text(message["body"])


def _resolution_path(recommendation):
    path = recommendation.get("resolution_path")
    if path:
        return path
    # Legacy recommendations have no stored path; a service choice marks the old service flow.
    return "SERVICE" if "SERVICE_RESOLUTION" in recommendation.get("choices", ()) else "NORMAL"


def _options_ready(supervisor, view):
    recommendation = view["recommendation"]
    path = _resolution_path(recommendation)
    st.subheader("Personalized response")
    st.info(recommendation["explanation"])
    _email_expander(view)
    st.subheader("Available choices")
    options = {
        f"{option_label(option)} · {option['available']} available": option["option_id"]
        for option in recommendation["options"]
    }
    choices = list(recommendation["choices"])
    preferred = recommendation.get("recommended_action")

    def label(choice):
        text = choice_label(choice, path)
        return f"{text} (recommended)" if choice == preferred else text

    decision = st.radio(
        "Resolution",
        choices,
        index=choices.index(preferred) if preferred in choices else 0,
        format_func=label,
        horizontal=True,
        key=f"decision_{view['return_id']}_{view['version']}",
    )
    option_id = None
    if decision in {"EXCHANGE", "REFUND"} and path == "NORMAL":
        st.info("Return the original pair at a nearby store — FREE (recommended). Prefer to mail it? Prepaid label $9.")
    elif path in ("MISSING_ITEM", "OUT_OF_STOCK"):
        st.info("No return needed.")
    if decision in {"EXCHANGE", "RESHIP"}:
        selector = "Verified in-stock exchange" if decision == "EXCHANGE" else "Verified in-stock item to ship"
        option_id = options.get(st.selectbox(selector, list(options))) if options else None
    if st.button("Save decision"):
        try:
            supervisor.record_decision(view["return_id"], decision, option_id)
            st.rerun()
        except (DomainError, ValueError) as exc:
            st.error(str(exc))


def _service_text(view):
    resolution = json.loads(view["service_resolution_json"]) if view.get("service_resolution_json") else {}
    if resolution.get("resolution") == "RESHIP":
        item = resolution.get("item") or {}
        return (
            f"Reship recorded: {item.get('sku', '')} · size {item.get('size', '')} · {item.get('color', '')} "
            "(simulated) — no return needed."
        )
    if resolution.get("resolution") == "REFUND_NOT_RECEIVED":
        return "Refund recorded for the item you didn't receive (simulated). No photos or return are needed."
    return "Service resolution recorded. No photos or return label are needed for this request."


def _defect_resolved_text(view):
    resolution = json.loads(view["service_resolution_json"]) if view.get("service_resolution_json") else {}
    if resolution.get("resolution") == "CONFIRMED_DEFECT_REPLACEMENT":
        item = resolution.get("replacement") or {}
        return (
            "Our team confirmed a product defect. Your replacement "
            f"{item.get('sku', '')} · size {item.get('size', '')} · {item.get('color', '')} "
            "has been released (simulated) — no return needed."
        )
    return "Our team confirmed a product defect. A refund has been recorded (simulated) — no return needed."


def _live_photo_form(supervisor, view):
    st.subheader("Live Bedrock visual assessment")
    st.write("Upload just three practical photos: Front, Left, and Right. JPEG/PNG/WebP, minimum 320×240.")
    st.caption("Normal room lighting, mild reflections, partial background objects, and casual phone photos are acceptable. No sole, back, or packaging photo is required.")
    uploads: dict[str, bytes] = {}
    columns = st.columns(3)
    for index, angle in enumerate(_REQUIRED_ANGLES):
        with columns[index]:
            uploaded = st.file_uploader(
                angle.title(),
                type=["jpg", "jpeg", "png", "webp"],
                key=f"photo_{view['return_id']}_{angle}",
            )
            if uploaded:
                uploads[angle] = uploaded.getvalue()
    st.caption(
        "Bedrock evaluates these three photos for practical sufficiency, visible evidence, eligibility, and a preliminary grade. "
        "A team member may confirm the result before you get return instructions."
    )
    ready = all(angle in uploads for angle in _REQUIRED_ANGLES)
    if st.button("Analyze 3 photos with Amazon Bedrock", type="primary", disabled=not ready):
        try:
            supervisor.submit_photos(
                view["return_id"],
                "live_upload",
                angles=tuple(uploads),
                uploads=uploads,
            )
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
    if not ready:
        missing = [angle.title() for angle in _REQUIRED_ANGLES if angle not in uploads]
        st.info("Still required: " + ", ".join(missing))


def _simulated_photo_form(supervisor, view):
    fixture = st.selectbox(
        "Synthetic photo scenario",
        list(VisualConditionAssessmentAgent.fixtures),
        format_func=PHOTO_SCENARIO_LABELS.get,
    )
    st.caption("Simulated mode uses three deterministic Front/Left/Right scenario fixtures.")
    if st.button("Submit 3 synthetic photos"):
        try:
            supervisor.submit_photos(view["return_id"], fixture)
            st.rerun()
        except DomainError as exc:
            st.error(str(exc))


def _exchange_summary(view):
    exchange = view.get("exchange")
    if view.get("current_decision") != "EXCHANGE" or not exchange:
        return
    status = exchange.get("exchange_status", "RESERVED_PENDING_ORIGINAL_RETURN")
    st.subheader("Your exchange")
    columns = st.columns(4)
    columns[0].metric("Replacement SKU", exchange["sku"])
    columns[1].metric("Size", exchange["size"])
    columns[2].metric("Color", exchange["color"])
    columns[3].metric("Status", status.replace("_", " ").title())
    if status == "RESERVED_PENDING_ORIGINAL_RETURN":
        st.info("Replacement inventory is reserved in this local demo. Complete the original-shoe return steps below; the replacement releases after the original return is received.")
    elif status == "REPLACEMENT_RELEASED_DEMO":
        st.success("The replacement has been released for simulated fulfillment. No real order or carrier shipment was created.")


def render(supervisor):
    runtime = supervisor.runtime_info
    live = bool(runtime["live_ai"])
    st.header("Customer Portal")
    st.caption("All orders, products, locations, and outcomes shown here are synthetic. Customer text and uploaded photos may be sent to Bedrock only in LIVE AI mode.")

    if "return_id" not in st.session_state:
        options = [value["order_id"] for value in SCENARIOS.values() if isinstance(value, dict) and "order_id" in value]
        order = st.selectbox("Synthetic order", options, key="customer_order")
        if st.button("Start return", type="primary"):
            try:
                st.session_state.return_id = supervisor.start_return(order)["return_id"]
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))
        return

    try:
        view = supervisor.get_customer_view(st.session_state.return_id)
    except DomainError:
        st.session_state.pop("return_id", None)
        st.warning("That request no longer exists; start again.")
        return

    st.code(view["return_id"])
    # The internal ROUTING_BLOCKED code is shown to customers in return-store terms.
    state_badge("RETURN_STORE_UNAVAILABLE" if view["state"] == "ROUTING_BLOCKED" else view["state"])
    _exchange_summary(view)

    if view["state"] == "DRAFT":
        reason = st.text_area("Why are you returning these shoes?", key=f"reason_{view['return_id']}")
        button_label = "Ask Bedrock agents to classify and recommend" if live else "Classify reason and show options"
        if st.button(button_label, type="primary"):
            try:
                with st.spinner("Supervisor is coordinating the Reason and Retention agents..."):
                    supervisor.submit_reason(view["return_id"], reason)
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))

    elif view["state"] == "OPTIONS_READY":
        heading = "Structured reason · LIVE Bedrock/Strands" if live else "Structured reason · simulated"
        st.subheader(heading)
        st.json(view["classification"])
        _options_ready(supervisor, view)

    elif view["state"] in ("AWAITING_PHOTOS", "RETAKE_REQUIRED"):
        if view["state"] == "RETAKE_REQUIRED":
            st.warning("One or more of the three photos was not usable. Replace only the photo named below; no grade was assigned.")
            if view.get("latest_assessment") and view["latest_assessment"].get("retakes"):
                for instruction in view["latest_assessment"]["retakes"]:
                    st.write(f"- {instruction}")
        if live:
            _live_photo_form(supervisor, view)
        else:
            _simulated_photo_form(supervisor, view)

    elif view["state"] == "AWAITING_REVIEW":
        st.warning("A team member is confirming the photo check. We'll update this page when it's done.")

    elif view["state"] in ("READY_TO_ROUTE", "ROUTING_BLOCKED"):
        # Free store drop-off is listed first and preselected; available modes stay ("SHIP", "DROPOFF").
        modes = sorted(supervisor.available_fulfillment_modes(view["return_id"]), key=lambda value: value != "DROPOFF")
        mode = st.radio(
            "How would you like to return the shoes?",
            modes,
            index=0,
            format_func=METHOD_LABELS.get,
            horizontal=True,
            key=f"method_{view['return_id']}_{view['version']}",
        )
        if mode == "SHIP":
            st.info("Return shipping fee: $9. Drop-off at a nearby store is FREE.")
        else:
            st.success("Store drop-off fee: FREE")
        if st.button("Confirm return method"):
            try:
                with st.spinner("Preparing your return instructions..."):
                    supervisor.select_fulfillment_mode(view["return_id"], mode)
                    supervisor.route_return(view["return_id"])
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))

    elif view["state"] == "ROUTED":
        st.subheader("Your return store")
        st.success(view.get("return_store_name") or "Nearby eligible store")
        st.write(view.get("return_store_address") or "Store address unavailable")
        if view.get("fulfillment_mode") == "DROPOFF":
            st.success("Bring the shoes to this store · FREE")
        else:
            st.info("Ship the shoes to this store with the prepaid label · $9")
        st.caption("After the store receives the item, our team takes care of the rest.")
        artifact_label = (
            "Generate return label + exchange confirmation"
            if view.get("current_decision") == "EXCHANGE"
            else "Generate demo fulfillment artifact"
        )
        if st.button(artifact_label):
            try:
                with st.spinner("Fulfillment Agent is preparing customer instructions and the local demo artifact..."):
                    supervisor.generate_artifact(view["return_id"])
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))

    elif view["state"] == "AWAITING_ORIGINAL_RETURN":
        st.success("Exchange reserved and return instructions created. The next step is to return the original shoes.")
        st.markdown(f"**Return store:** {view.get('return_store_name')}  ")
        st.write(view.get("return_store_address"))
        for artifact in view["artifacts"]:
            if artifact.get("instructions"):
                st.write(artifact["instructions"])
            path = Path(artifact["local_path"])
            if path.exists():
                st.download_button(
                    "Download return label / drop-off confirmation",
                    path.read_bytes(),
                    path.name,
                    "application/pdf",
                )
        st.warning("Demo checkpoint · In production, the carrier scan or store receipt would trigger the replacement release.")
        if st.button("Simulate original return received → release replacement", type="primary"):
            try:
                supervisor.complete_exchange(view["return_id"])
                st.rerun()
            except DomainError as exc:
                st.error(str(exc))

    elif view["state"] == "COMPLETED_EXCHANGE":
        exchange = view.get("exchange") or {}
        st.success(
            f"Exchange complete · Replacement {exchange.get('sku', '')}, size {exchange.get('size', '')}, "
            f"{exchange.get('color', '')} has been released for simulated fulfillment."
        )
        st.info("This is a complete local exchange simulation. No real replacement order, payment, or carrier shipment was created.")
        st.markdown(f"**Original return store:** {view.get('return_store_name')}  ")
        st.write(view.get("return_store_address"))
        for artifact in view["artifacts"]:
            path = Path(artifact["local_path"])
            if path.exists():
                st.download_button(
                    "Download exchange return confirmation",
                    path.read_bytes(),
                    path.name,
                    "application/pdf",
                )

    elif view["state"] == "COMPLETED_RETURN":
        fee_label = "FREE store drop-off" if view.get("fulfillment_mode") == "DROPOFF" else "$9 prepaid-label shipping"
        st.success(f"Refund return workflow complete using {fee_label}. Logistics remains mocked; LIVE mode used Bedrock only for displayed AI decisions and explanations.")
        st.markdown(f"**Return store:** {view.get('return_store_name')}  ")
        st.write(view.get("return_store_address"))
        for artifact in view["artifacts"]:
            if artifact.get("instructions"):
                st.write(artifact["instructions"])
            path = Path(artifact["local_path"])
            if path.exists():
                st.download_button(
                    "Download DEMO / NOT VALID FOR SHIPPING PDF",
                    path.read_bytes(),
                    path.name,
                    "application/pdf",
                )

    elif view["state"] == "COMPLETED_SERVICE":
        st.success(_service_text(view))
    elif view["state"] == "COMPLETED_KEEP":
        st.success("Keep decision recorded.")
    elif view["state"] == "INELIGIBLE_CLOSED":
        st.error("Worn/used shoes are ineligible for the standard return flow. This is not Grade C.")
        if view.get("current_decision") == "EXCHANGE":
            st.info("Your exchange reservation was cancelled because worn shoes can't be exchanged.")
    elif view["state"] == "DEFECT_RESOLVED":
        st.success(_defect_resolved_text(view))
    elif view["state"] == "DEFECT_HOLD":
        st.warning(
            "Suspected manufacturing defect — our team is taking a closer look. This is not a confirmed defect, "
            "and no return label is needed yet. We'll update this page with next steps."
        )

    if st.button("Leave this request / start another"):
        st.session_state.pop("return_id", None)
        st.rerun()
