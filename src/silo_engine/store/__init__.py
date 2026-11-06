"""Configuration store: versioned site configurations, history, diff and scenario overlays
(docs/PLATFORM_GAP_ANALYSIS.md step 7, gap G10). Separate from the simulation core.

Layout under the store root (default: outside the repository, see `default_store_root`):
    <site id>/versions/0001.json, 0002.json, ...   immutable; the store numbers versions
    <site id>/history.json                         version, note, configuration hash, parent, time, report summary
    <site id>/scenarios/<name>.json                base version + overlay operations (the base is never edited)

A configuration must be readable (schema) to be saved; one that cannot run yet is saved as a draft and its
pre-run report summary is recorded. Nothing here interprets site data: it stores what the user saves.
"""
import copy
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from ..config import load_site_config
from ..config.report import prerun_report
from ..config.schema import config_hash

_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class StoreError(ValueError):
    pass


class StoreNotFound(StoreError):
    """A site, version or scenario that is not in the store."""


def default_store_root() -> Path:
    """`SILO_STORE` if set, else a folder in the user's home: never inside the (public) repository."""
    return Path(os.environ.get("SILO_STORE") or Path.home() / ".silo-optimiser" / "store")


def _safe(name: str, what: str) -> str:
    if not isinstance(name, str) or not _SAFE.match(name) or ".." in name:
        raise StoreError(f"The {what} '{name}' cannot be used as a folder name; use letters, digits, '-', '_' or '.'.")
    return name


@dataclass(frozen=True)
class SavedVersion:
    site_id: str
    version: int
    config_hash: str
    report: dict


class ConfigStore:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else default_store_root()

    # ---- versions ----
    def save(self, raw: dict, note: str = "") -> SavedVersion:
        site_id = _safe(raw.get("id"), "site id")
        history = self.history(site_id) if (self.root / site_id / "history.json").exists() else []
        n = (history[-1]["version"] if history else 0) + 1
        cfg = copy.deepcopy(raw)
        cfg["version"] = n
        site = load_site_config(copy.deepcopy(cfg))  # raises ConfigSchemaError for an unreadable configuration
        rep = prerun_report(site).as_dict()
        summary = {k: rep[k] for k in ("ok", "errors", "warnings", "notes")}
        h = config_hash(site)
        self._write_version(site_id, n, cfg)
        history.append({"version": n, "note": note, "config_hash": h, "parent": n - 1 if n > 1 else None,
                        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"), "report": summary})
        self._write_json(self.root / site_id / "history.json", history)
        return SavedVersion(site_id, n, h, summary)

    def _write_version(self, site_id: str, n: int, cfg: dict) -> None:
        path = self.root / site_id / "versions" / f"{n:04d}.json"
        if path.exists():
            raise StoreError(f"Version {n} of {site_id} already exists; versions are never overwritten.")
        self._write_json(path, cfg)

    def load(self, site_id: str, version: int | None = None) -> dict:
        _safe(site_id, "site id")
        history = self.history(site_id)
        n = version if version is not None else history[-1]["version"]
        path = self.root / site_id / "versions" / f"{n:04d}.json"
        if not path.exists():
            raise StoreNotFound(f"{site_id} has no version {n}.")
        return json.loads(path.read_text(encoding="utf-8"))

    def history(self, site_id: str) -> list[dict]:
        path = self.root / _safe(site_id, "site id") / "history.json"
        if not path.exists():
            raise StoreNotFound(f"No saved configuration for {site_id}.")
        return json.loads(path.read_text(encoding="utf-8"))

    def list_sites(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(p.name for p in self.root.iterdir() if (p / "history.json").exists())

    # ---- scenarios ----
    def save_scenario(self, site_id: str, name: str, base_version: int, ops: list[dict], note: str = "") -> dict:
        config = apply_overlay(self.load(site_id, base_version), ops)
        load_site_config(copy.deepcopy(config))
        record = {"name": _safe(name, "scenario name"), "base_version": base_version, "ops": ops, "note": note}
        self._write_json(self.root / site_id / "scenarios" / f"{name}.json", record)
        return record

    def load_scenario(self, site_id: str, name: str) -> dict:
        path = self.root / _safe(site_id, "site id") / "scenarios" / f"{_safe(name, 'scenario name')}.json"
        if not path.exists():
            raise StoreNotFound(f"{site_id} has no scenario {name}.")
        record = json.loads(path.read_text(encoding="utf-8"))
        return {**record, "config": apply_overlay(self.load(site_id, record["base_version"]), record["ops"])}

    def list_scenarios(self, site_id: str) -> list[str]:
        folder = self.root / _safe(site_id, "site id") / "scenarios"
        return sorted(p.stem for p in folder.glob("*.json")) if folder.exists() else []

    @staticmethod
    def _write_json(path: Path, data) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)


# ---- overlays (scenarios as changes to a base; the base is never edited) ----
def apply_overlay(base: dict, ops: list[dict]) -> dict:
    cfg = copy.deepcopy(base)
    eq = cfg.setdefault("equipment", [])
    edges = cfg.setdefault("edges", [])

    def find(eid):
        item = next((e for e in eq if e.get("id") == eid), None)
        if item is None:
            raise StoreError(f"The configuration has no equipment {eid}.")
        return item
    for op in ops:
        kind = op.get("op")
        if kind == "set":
            keys = op["path"].split(".")
            node = cfg
            for i, k in enumerate(keys[:-1]):
                if not isinstance(node, dict) or k not in node or not isinstance(node[k], dict):
                    raise StoreError(f"The configuration has no field {'.'.join(keys[:i + 1])}.")
                node = node[k]
            node[keys[-1]] = copy.deepcopy(op["value"])
        elif kind == "add_equipment":
            if any(e.get("id") == op["item"]["id"] for e in eq):
                raise StoreError(f"The configuration already has equipment {op['item']['id']}.")
            eq.append(copy.deepcopy(op["item"]))
        elif kind == "remove_equipment":
            item = find(op["id"])
            eq.remove(item)
            edges[:] = [e for e in edges if op["id"] not in e]  # its connections go with it
        elif kind == "update_equipment":
            find(op["id"]).update(copy.deepcopy(op["fields"]))
        elif kind == "add_edge":
            edge = list(op["edge"])
            if edge in [list(e) for e in edges]:
                raise StoreError(f"The configuration already has edge {edge[0]} -> {edge[1]}.")
            edges.append(edge)
        elif kind == "remove_edge":
            edge = list(op["edge"])
            match = [e for e in edges if list(e) == edge]
            if not match:
                raise StoreError(f"The configuration has no edge {edge[0]} -> {edge[1]}.")
            edges.remove(match[0])
        else:
            raise StoreError(f"unknown overlay operation {kind}")
    return cfg


# ---- diff ----
def _field_changes(where: str, a, b, prefix: str = "") -> list[dict]:
    out = []
    for k in list(a) + [k for k in b if k not in a]:
        x, y = a.get(k), b.get(k)
        if isinstance(x, dict) and isinstance(y, dict):
            out += _field_changes(where, x, y, f"{prefix}{k}.")
        elif x != y:
            out.append({"kind": "changed", "where": where, "field": f"{prefix}{k}", "from": x, "to": y})
    return out


def diff_configs(a: dict, b: dict) -> list[dict]:
    """What changed from configuration a to b: equipment by id, connections, then other sections by field.
    The store's version number is ignored."""
    out = []
    ea = {e["id"]: e for e in a.get("equipment", [])}
    eb = {e["id"]: e for e in b.get("equipment", [])}
    for eid, item in eb.items():
        if eid in ea:
            out += _field_changes(f"equipment {eid}", ea[eid], item)
        else:
            out.append({"kind": "added", "where": f"equipment {eid}"})
    out += [{"kind": "removed", "where": f"equipment {eid}"} for eid in ea if eid not in eb]
    sa = [list(e) for e in a.get("edges", [])]
    sb = [list(e) for e in b.get("edges", [])]
    out += [{"kind": "added", "where": f"edge {x} -> {y}"} for x, y in sb if [x, y] not in sa]
    out += [{"kind": "removed", "where": f"edge {x} -> {y}"} for x, y in sa if [x, y] not in sb]
    for key in sorted((set(a) | set(b)) - {"equipment", "edges", "version"}):
        x, y = a.get(key), b.get(key)
        if x == y:
            continue
        if isinstance(x, dict) and isinstance(y, dict):
            out += _field_changes(key, x, y)
        else:
            out.append({"kind": "changed", "where": key, "from": x, "to": y})
    return out
