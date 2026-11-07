"""Strict envelope validation against contracts/Shared_Protocol.json.

Only checks structure and numeric semantics (no NaN/Infinity, probabilities in [0,1]).
It does not judge statistical content: Research owns that.
"""
import json
import math
import os

_PROTO_PATH = os.path.join(os.path.dirname(__file__), "..", "contracts", "Shared_Protocol.json")
with open(_PROTO_PATH, encoding="utf-8") as _f:
    PROTOCOL = json.load(_f)

PROTOCOL_VERSION = PROTOCOL["protocol_version"]
REQUIRED = PROTOCOL["required_envelopes"]
DECISION_STATES = set(PROTOCOL["decision_states"])
DATA_MODES = set(PROTOCOL["data_modes"])
CHANNELS = set(PROTOCOL["claim_channels"])

PROBABILITY_FIELDS = {"forecast_probability"}


class ContractError(ValueError):
    pass


def _reject_constant(name):
    raise ContractError(f"non-finite JSON constant {name} is not allowed")


def loads_strict(text):
    """json.loads that rejects NaN / Infinity / -Infinity."""
    return json.loads(text, parse_constant=_reject_constant)


def _walk_numbers(obj, path="$"):
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            raise ContractError(f"{path}: non-finite number")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk_numbers(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            _walk_numbers(v, f"{path}[{i}]")


def validate_envelope(name, obj):
    if name not in REQUIRED:
        raise ContractError(f"unknown envelope {name}")
    if not isinstance(obj, dict):
        raise ContractError(f"{name}: must be an object")
    missing = [k for k in REQUIRED[name] if k not in obj]
    if missing:
        raise ContractError(f"{name}: missing fields {missing}")
    _walk_numbers(obj)
    for f in PROBABILITY_FIELDS & obj.keys():
        v = obj[f]
        if v is not None and not (isinstance(v, (int, float)) and 0 <= v <= 1):
            raise ContractError(f"{name}.{f}: probability must be in [0,1]")
    if "protocol_version" in obj and obj["protocol_version"] != PROTOCOL_VERSION:
        raise ContractError(f"{name}: protocol_version must be {PROTOCOL_VERSION}")
    if "data_mode" in obj and obj["data_mode"] not in DATA_MODES:
        raise ContractError(f"{name}: unknown data_mode {obj['data_mode']!r}")
    if "decision" in obj and obj["decision"] not in DECISION_STATES:
        raise ContractError(f"{name}: unknown decision {obj['decision']!r}")
    return True
