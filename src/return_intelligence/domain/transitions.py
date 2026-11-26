from .enums import RequestState
from .errors import PolicyViolation


_ALLOWED = {
    RequestState.DRAFT: {RequestState.CLASSIFIED},
    RequestState.CLASSIFIED: {RequestState.OPTIONS_READY},
    RequestState.OPTIONS_READY: {
        RequestState.DECISION_RECORDED,
        RequestState.COMPLETED_KEEP,
        RequestState.SERVICE_RESOLUTION,
        RequestState.COMPLETED_SERVICE,
    },
    RequestState.DECISION_RECORDED: {RequestState.AWAITING_PHOTOS, RequestState.COMPLETED_KEEP, RequestState.SERVICE_RESOLUTION},
    RequestState.SERVICE_RESOLUTION: {RequestState.COMPLETED_SERVICE},
    RequestState.AWAITING_PHOTOS: {
        RequestState.RETAKE_REQUIRED,
        RequestState.AWAITING_REVIEW,
        RequestState.READY_TO_ROUTE,
        RequestState.INELIGIBLE_CLOSED,
        RequestState.DEFECT_HOLD,
    },
    RequestState.RETAKE_REQUIRED: {
        RequestState.AWAITING_PHOTOS,
        RequestState.RETAKE_REQUIRED,
        RequestState.AWAITING_REVIEW,
        RequestState.READY_TO_ROUTE,
        RequestState.INELIGIBLE_CLOSED,
        RequestState.DEFECT_HOLD,
    },
    RequestState.AWAITING_REVIEW: {RequestState.READY_TO_ROUTE, RequestState.INELIGIBLE_CLOSED, RequestState.DEFECT_HOLD},
    RequestState.DEFECT_HOLD: {RequestState.READY_TO_ROUTE, RequestState.DEFECT_RESOLVED},
    RequestState.READY_TO_ROUTE: {RequestState.ROUTED, RequestState.ROUTING_BLOCKED},
    RequestState.ROUTING_BLOCKED: {RequestState.ROUTED, RequestState.ROUTING_BLOCKED},
    RequestState.ROUTED: {RequestState.COMPLETED_RETURN, RequestState.AWAITING_ORIGINAL_RETURN},
    RequestState.AWAITING_ORIGINAL_RETURN: {RequestState.COMPLETED_EXCHANGE},
}


def require_transition(current: str | RequestState, target: str | RequestState) -> None:
    current_state, target_state = RequestState(current), RequestState(target)
    if target_state not in _ALLOWED.get(current_state, set()):
        raise PolicyViolation(f"illegal transition {current_state} -> {target_state}")
