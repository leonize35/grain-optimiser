"""Generated arrivals from the site's demand profiles (prototype method, extended to grades and several days).

Per activity with daily volume > 0, for each simulated day:
- arrivals follow a Poisson process whose rate is constant within each clock hour and proportional to that hour's
  profile weight, over opening hours [open, close); the rates are scaled so the expected total equals
  `daily` x `demand_factor`. As in the prototype, the gap is redrawn at each hour boundary (memoryless);
- each truck's commodity (from `mix`), payload (triangular `payload` tonnes, kept to the kilogram) and, for graded
  commodities, grade (from `grade_mix`) come from the truck's own random stream.
The opening queue (`initial.queue`) arrives at opening on day 1.

Streams: arrival times use (seed, "arrivals", activity, day); a truck's attributes use
(seed, "truck", activity, day, index). The equipment layout plays no part, so every scenario of an experiment sees
the same trucks for the same seed (common random numbers).
"""
from decimal import Decimal

from ..config.schema import ActivityDemand, SiteConfig
from ..sim.random_streams import Stream, exponential, pick_weighted, triangular
from ..sim.time import MS_PER_DAY, MS_PER_MINUTE, m
from .scripted import ScriptedTruck

ACTIVITIES = ("unload", "load", "weigh")
PREFIX = {"unload": "U", "load": "L", "weigh": "W"}


def _minutes(hours: float) -> float:
    return float(Decimal(str(hours)) * 60)


def _attributes(site: SiteConfig, act: str, d: ActivityDemand, stream: Stream) -> tuple[str | None, int | None, str | None]:
    if act == "weigh":
        return None, None, None
    commodity = pick_weighted(stream.uniform(), d.mix)
    low, mode, high = d.payload
    kg = round(triangular(stream.uniform(), low, mode, high) * 1000)
    grade = None
    graded = next((c.grades for c in site.commodities if c.id == commodity and c.grades), None)
    u_grade = stream.uniform()  # always drawn, so adding grades later does not shift other draws
    if graded:
        mix = d.grade_mix.get(commodity)
        if mix:
            grade = pick_weighted(u_grade, mix)
        elif act == "unload" and site.grade_segregation != "none":
            raise ValueError(f"No grade mix for {commodity}; the site keeps its grades apart")
        # a loading order without a grade mix takes any grade of the commodity
    return commodity, kg, grade


def _sampling(seed: int, d, truck_id: str) -> bool | None:
    """Sampler access: one draw per truck from its own stream (identical across layouts); None without a share."""
    if d.sampling_share is None:
        return None
    return Stream(seed, "sampling", truck_id).uniform() < d.sampling_share


def generate_arrivals(site: SiteConfig, seed: int, days: int = 1, demand_factor: float = 1.0) -> list[ScriptedTruck]:
    trucks: list[ScriptedTruck] = []
    open_min, close_min = _minutes(site.hours.open), _minutes(site.hours.close)
    for act in ACTIVITIES:
        d = getattr(site.demand, act)
        if d is None or not d.daily > 0:
            continue
        profile = d.profile if d.profile and len(d.profile) == 24 else [1.0] * 24
        # hour h overlaps opening hours for `share` of an hour
        slices = []
        for h in range(24):
            start, end = max(h * 60, open_min), min((h + 1) * 60, close_min)
            if end > start and profile[h] > 0:
                slices.append((start, end, profile[h]))
        weight = sum(w * (end - start) / 60 for start, end, w in slices)
        if weight <= 0:
            continue
        for day in range(days):
            times = Stream(seed, "arrivals", act, day + 1)
            index = 0
            for start, end, w in slices:
                per_minute = d.daily * demand_factor * w / weight / 60
                t = start
                while True:
                    t += exponential(times.uniform(), per_minute)
                    if t >= end:
                        break
                    index += 1
                    commodity, kg, grade = _attributes(site, act, d, Stream(seed, "truck", act, day + 1, index))
                    arrive = day * MS_PER_DAY + round(t * MS_PER_MINUTE)
                    tid = f"{PREFIX[act]}{day + 1}-{index:03d}"
                    trucks.append(ScriptedTruck(tid, act, arrive, commodity, kg, False, grade, _sampling(seed, d, tid)))
        for n in range(1, getattr(site.initial.queue, act) + 1):
            commodity, kg, grade = _attributes(site, act, d, Stream(seed, "backlog", act, n))
            tid = f"{PREFIX[act]}B-{n:02d}"
            trucks.append(ScriptedTruck(tid, act, m(Decimal(str(open_min))), commodity, kg, True, grade,
                                        _sampling(seed, d, tid)))
    order = {a: i for i, a in enumerate(ACTIVITIES)}
    trucks.sort(key=lambda t: (t.arrive_ms, not t.backlog, order[t.activity], t.id))
    return trucks
