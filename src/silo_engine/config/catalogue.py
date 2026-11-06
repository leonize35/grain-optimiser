"""Equipment catalogue for the silo builder: what each equipment type is called, which fields it has (with units and
whether the validator requires them) and which types it may feed grain into. Presentation metadata only; the
connection rules and labels are the validator's own (`validation.ALLOWED_CONNECTIONS`, `EQUIPMENT_LABEL`), so a
user interface reading this never carries its own copy of engine rules.

Field kinds: number, integer, triangular ([min, most likely, max]), commodities (list of commodity ids), choice
(`options`), activities (list of truck activities).
"""
import typing

from .rules_validation import CONDITIONS, PLACE_STEPS
from .schema import (EndOfDay, LabourRequirement, QueueGroupName, QueuePolicyName, SiteConfig, TruckStep,
                     UnloadingLabour)
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


# Truck process vocabulary (slice 9b). Ids are the engine's TruckStep values; labels are presentation only.
STEP_INFO = {
    "sample": ("Sampling", "sampler", "A sample is taken; it is graded off the truck."),
    "grade": ("Wait for grading result", "grader", "The truck waits where it is until its sample has been graded."),
    "weigh_in": ("Weigh in", "weighbridge", None),
    "tip": ("Unload at a hopper", "hopper", None),
    "load": ("Load at a load point", "loadpoint", None),
    "weigh_out": ("Weigh out", "weighbridge", None),
}
CONDITION_LABEL = {"graded": "its sample has been graded"}
DEADLOCK_LABEL = {
    "reserve_next_space": "A truck starts a service only when a place in the next waiting area is reserved (prevents gridlock)",
    "detect_only": "No reservation of the next place; a gridlock stops the run and is reported",
}


# Labour, operating rules and demand vocabulary (slice 9c): ids are the engine's literals.
QUEUE_GROUP_LABEL = {"sample": "Sampling queue", "grade": "Grading queue", "weigh": "Weighbridge queue",
                     "tip": "Hopper queue", "intake": "Grain intake (pit to bin)", "move": "Moving between areas",
                     "load": "Loading queue"}
POLICY_LABEL = {"strict_fifo": "Strict first come, first served: nobody may pass a waiting earlier truck",
                "feasible_first": "First come, first served among those that can go: a truck may pass an earlier one that cannot"}
EOD_LABEL = {"carry_over": "stay and continue the next day", "turned_away": "are sent away",
             "queue_for_next_day": "wait at the gate for the next day"}
HELD_LABEL = {"whole_task": "throughout the task", "start_only": "only to start it"}
ALLOCATION_LABEL = {"oldest_task_first": "Oldest waiting task first (any task that fits)",
                    "strict_order": "Strict order: no task starts while an older one waits",
                    "started_trucks_first": "Trucks already at a hopper first"}


def _lit(model, name) -> list[str]:
    return list(typing.get_args(model.model_fields[name].annotation))


def _activity_steps(activity: str) -> list[str]:
    """Steps a truck of this activity can have (the validator refuses tipping for non-receiving trucks and loading
    for non-loading trucks)."""
    steps = list(typing.get_args(TruckStep))
    return [s for s in steps if not (s == "tip" and activity != "unload") and not (s == "load" and activity != "load")]


def catalogue() -> dict:
    return {
        "equipment_types": {t: {"label": EQUIPMENT_LABEL[t], "connects_to": list(ALLOWED_CONNECTIONS[t]),
                                "fields": FIELDS[t]} for t in EQUIPMENT_LABEL},
        "activities": [{"id": a, "label": label} for a, label in ACTIVITY_LABEL.items()],
        "truck_steps": [{"id": s, "label": STEP_INFO[s][0], "station": STEP_INFO[s][1], "help": STEP_INFO[s][2]}
                        for s in typing.get_args(TruckStep)],
        "activity_steps": {a: _activity_steps(a) for a in ACTIVITY_LABEL},
        "release_conditions": [{"id": c, "label": CONDITION_LABEL.get(c, c)} for c in CONDITIONS if c != "service_done"],
        "place_steps": list(PLACE_STEPS),
        "deadlock_prevention": [{"id": d, "label": DEADLOCK_LABEL[d]}
                                for d in typing.get_args(SiteConfig.model_fields["deadlock_prevention"].annotation)],
        "queue_groups": [{"id": g, "label": QUEUE_GROUP_LABEL[g]} for g in typing.get_args(QueueGroupName)],
        "queue_policies": [{"id": p, "label": POLICY_LABEL[p]} for p in typing.get_args(QueuePolicyName)],
        "end_of_day": {k: [{"id": o, "label": EOD_LABEL[o]} for o in _lit(EndOfDay, k)]
                       for k in ("unfinished_trucks", "late_arrivals")},
        "labour": {"steps": _lit(LabourRequirement, "step"),
                   "held": [{"id": h, "label": HELD_LABEL[h]} for h in _lit(LabourRequirement, "held")],
                   "allocation": [{"id": a, "label": ALLOCATION_LABEL[a]} for a in _lit(UnloadingLabour, "allocation")]},
    }
