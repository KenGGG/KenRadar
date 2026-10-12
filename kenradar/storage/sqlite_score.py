"""One score interpretation shared by list filters and source aggregation."""
import math
import re
from sqlalchemy import case, func


def parse_score(value):
    if isinstance(value, str):
        if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value):
            return None
    elif type(value) not in {int, float}:
        return None
    try:
        number = float(value)
    except (ValueError, OverflowError):
        return None
    return min(5.0, max(1.0, number)) if math.isfinite(number) else None


def score_expression(column):
    return case((func.json_type(column, "$.value_score").in_(("integer", "real", "text")),
                 func.kr_score(func.json_extract(column, "$.value_score"))), else_=None)
