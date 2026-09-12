"""
util.py: small pure helpers shared across the runner package.

No Kubernetes or I/O dependencies here, so these are trivially testable.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

NAN = float("nan")


def event_epoch(obj: Any) -> float | None:
    """Best-effort wall-clock epoch (UTC seconds) of a Kubernetes Event.

    Events carry several time fields and not all are always set: the newer
    `eventTime` (microsecond precision), the legacy `lastTimestamp` and
    `firstTimestamp` (second precision), and `metadata.creationTimestamp`. The
    most recent available one is returned so a repeated (aggregated) event is
    dated by its latest occurrence, not its first. Returns None if none parse,
    so the caller can choose to keep the event rather than drop it blindly.
    """
    candidates = [
        get(obj, "eventTime"),
        get(obj, "lastTimestamp"),
        get(obj, "firstTimestamp"),
        get(obj, "metadata", "creationTimestamp"),
    ]
    epochs = [e for e in (_parse_k8s_time(c) for c in candidates) if e is not None]
    return max(epochs) if epochs else None


def _parse_k8s_time(value: Any) -> float | None:
    """Parse a Kubernetes RFC3339 timestamp (or a datetime) to epoch seconds."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    # Normalise trailing Z and truncate over-long fractional seconds that
    # datetime.fromisoformat (pre-3.11 tolerance) may reject.
    text = text.replace("Z", "+00:00")
    m = re.match(r"(.*\.\d{6})\d*([+-]\d\d:\d\d)?$", text)
    if m:
        text = m.group(1) + (m.group(2) or "")
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def is_num(x: float) -> bool:
    """True unless x is NaN (NaN is the only value not equal to itself)."""
    return x == x


def rnd(x: float, ndigits: int = 4) -> float:
    """Round, but leave NaN untouched so 'unseen' stays distinguishable."""
    return round(x, ndigits) if is_num(x) else NAN


def get(obj: Any, *path: str) -> Any:
    """Nested lookup that works on plain dicts and openapi model objects alike.

    Watch streams may hand back either, depending on the call, so a uniform
    accessor avoids scattering isinstance checks through the recorder.
    """
    cur = obj
    for key in path:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(key)
        else:
            cur = getattr(cur, snake(key), None)
    return cur


def snake(camel: str) -> str:
    """camelCase -> snake_case, for translating JSON keys to model attributes."""
    out = []
    for ch in camel:
        if ch.isupper():
            out.append("_")
            out.append(ch.lower())
        else:
            out.append(ch)
    return "".join(out)


def count_nodes(message: str, marker: str) -> int:
    """Sum the node count of every reason segment containing `marker`.

    kube-scheduler's diagnosis message has the shape:
      "<avail>/<total> nodes are available: <N1> <reason1>, <N2> <reason2>[...].
       [no new claims to deallocate, ]preemption: <same shape restated>"

    Segments are comma-separated "<count> <reason text>" pairs following the
    "nodes are available:" prefix. Not every reason text contains the literal
    "node(s)" — a custom plugin's own message (e.g. WallFilter's
    "c_wall violated: ...") has no such prefix, unlike built-in plugins (e.g.
    "node(s) had untolerated taint") — so segments are split on commas and
    matched by the caller-supplied marker, not by assuming "node(s)" appears.

    The trailing "preemption: ..." section restates the same reasons for the
    preemption diagnostic and would double-count if included, so it is
    dropped.
    """
    body = message.split(" nodes are available:", 1)
    body = body[1] if len(body) > 1 else message
    body = body.split("preemption:", 1)[0]

    total = 0
    for segment in body.split(","):
        m = re.match(r"\s*(\d+)\s+(.*)", segment, re.DOTALL)
        if not m:
            continue
        count_str, text = m.groups()
        if marker in text:
            total += int(count_str)
    return total


def percentile(sorted_vals: list[float], pct: float) -> float:
    """Linear-interpolation percentile of an already-sorted list."""
    if not sorted_vals:
        return NAN
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    k = (len(sorted_vals) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


def pick(cli_value: Any, scenario_value: Any) -> Any:
    """CLI value wins when provided (not None); otherwise the scenario value."""
    return cli_value if cli_value is not None else scenario_value


def log(step: str, message: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {step:<10} {message}", flush=True)
