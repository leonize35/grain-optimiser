"""Book inventory (R) and reconciliation explanations (docs/STOCK_ADJUSTMENTS.md).

The book ledger holds recorded quantities per bin. It has no reference to bins or any physical state, so nothing
done to the book can change physical grain. Physical events are *posted* to it by the engine; book corrections are
applied to it only. Each difference between book and physical stock that the engine knows a reason for is recorded
as an explanation, so the reconciliation can show what remains unexplained.
"""
from dataclasses import dataclass, field

COMPONENTS = ("administrative", "survey_based", "unposted_loss")


@dataclass
class BookPosting:
    time: int
    bin: str
    kg: int  # signed
    source: str  # transfer or load id, loss id, or correction id


@dataclass
class BookLedger:
    opening: dict[str, int]
    balance: dict[str, int] = field(init=False)
    postings: list[BookPosting] = field(default_factory=list)
    explained: dict[str, dict[str, int]] = field(init=False)  # bin -> component -> kg

    def __post_init__(self) -> None:
        self.balance = dict(self.opening)
        self.explained = {b: {c: 0 for c in COMPONENTS} for b in self.opening}

    def post(self, time: int, bin_id: str, kg: int, source: str) -> None:
        self.balance[bin_id] += kg
        self.postings.append(BookPosting(time, bin_id, kg, source))

    def explain(self, bin_id: str, component: str, kg: int) -> None:
        if component not in COMPONENTS:
            raise ValueError(f"Unknown reconciliation component {component}")
        self.explained[bin_id][component] += kg
