"""Equipment catalogue for the silo builder: what each equipment type is called, which fields it has (with units and
whether the validator requires them) and which types it may feed grain into. Presentation metadata only; the
connection rules and labels are the validator's own (`validation.ALLOWED_CONNECTIONS`, `EQUIPMENT_LABEL`), so a
user interface reading this never carries its own copy of engine rules.

Field kinds: number, integer, triangular ([min, most likely, max]), commodities (list of commodity ids), choice
(`options`), activities (list of truck activities).
"""
from .validation import ACTIVITY_LABEL, ALLOWED_CONNECTIONS, EQUIPMENT_LABEL


def _f(name, label, kind, unit=None, required=False, options=None, help=None):
    out = {"name": name, "label": label, "kind": kind, "unit": unit, "required": required}
    if options is not None:
        out["options"] = options
    if help is not None:
        out["help"] = help
    return out


_STATION = [
    _f("cap", "Trucks at once", "integer", "trucks", True),
    _f("time", "Time per truck", "triangular", "min", True, help="minimum, most likely, maximum"),
    _f("activities", "Serves", "activities", help="leave empty to serve every truck activity"),
]
FIELDS = {
    "sampler": _STATION + [_f("pass_through", "Drive-through time (no sample)", "triangular", "min")],
    "grader": _STATION + [_f("reject", "Rejection probability", "number", "0-1")],
    "weighbridge": _STATION + [_f("moves", "Weighs", "choice", options=["in", "out", "both"],
                                  help="in: weighs trucks in; out: weighs trucks out; both")],
    "hopper": [
        _f("capT", "Pit capacity", "number", "t", True),
        _f("rate", "Discharge rate", "number", "t/h", True),
        _f("tip", "Tipping time", "triangular", "min", True, help="minimum, most likely, maximum"),
        _f("commodities", "Accepts", "commodities"),
        _f("tip_admission", "A truck may tip when", "choice", options=["full_load_space", "empty_pit"]),
    ],
    "conveyor": [
        _f("rate", "Transfer rate", "number", "t/h", True),
        _f("changeover", "Changeover time", "number", "min"),
        _f("max_concurrent_feeds", "Streams at once", "integer", "streams"),
        _f("clear_minutes", "Emptying time after the last grain", "number", "min"),
    ],
    "elevator": [
        _f("rate", "Transfer rate", "number", "t/h", True),
        _f("changeover", "Changeover time", "number", "min"),
        _f("max_concurrent_feeds", "Streams at once", "integer", "streams"),
        _f("clear_minutes", "Emptying time after the last grain", "number", "min"),
    ],
    "bin": [
        _f("capT", "Capacity", "number", "t", True),
        _f("commodities", "May store", "commodities", required=True),
        _f("inv", "Opening stock", "number", "t"),
        _f("invCommodity", "Opening stock commodity", "commodity"),
    ],
    "loadpoint": [
        _f("rate", "Loading rate", "number", "t/h", True),
        _f("setup", "Setup time per truck", "triangular", "min"),
    ],
}


def catalogue() -> dict:
    return {
        "equipment_types": {t: {"label": EQUIPMENT_LABEL[t], "connects_to": list(ALLOWED_CONNECTIONS[t]),
                                "fields": FIELDS[t]} for t in EQUIPMENT_LABEL},
        "activities": [{"id": a, "label": label} for a, label in ACTIVITY_LABEL.items()],
    }
