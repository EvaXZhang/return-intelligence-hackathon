from .enums import DestinationType, EligibilityState, Grade
from .errors import PolicyViolation


def route_type(condition: Grade | str | EligibilityState, seasonality_flag: int) -> DestinationType:
    if seasonality_flag not in (0, 1): raise PolicyViolation("seasonality must be 0 or 1")
    value = condition.value if hasattr(condition, "value") else str(condition)
    matrix = {
        ("A",0): DestinationType.RETAIL_STORE, ("A",1): DestinationType.OUTLET,
        ("B",0): DestinationType.OUTLET, ("B",1): DestinationType.OUTLET,
        ("C",0): DestinationType.COMPANY_WAREHOUSE, ("C",1): DestinationType.COMPANY_WAREHOUSE,
        ("WORN_INELIGIBLE",0): DestinationType.REJECT, ("WORN_INELIGIBLE",1): DestinationType.REJECT,
    }
    if value == "SUSPECTED_DEFECT": raise PolicyViolation("suspected defects require investigation hold")
    try: return matrix[(value, seasonality_flag)]
    except KeyError as exc: raise PolicyViolation("unsupported condition for routing") from exc
