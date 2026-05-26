"""Per-underlying market-feeling trade gate.

Why this exists:
    The operator (or AI) needs a one-knob way to say "the market is choppy
    today, sit out" or "I'm bearish on NIFTY, don't buy calls." Without this
    gate, a stale Bullish TradingView signal during a Bearish session opens a
    losing position. The gate hard-stops contra-bias entries at the route and
    engine layers; it never blocks exits.

    Per-underlying (NIFTY, BANKNIFTY, FINNIFTY). Values:
        Bullish  → allow CALL entries, BLOCK PUT entries
        Bearish  → allow PUT entries,  BLOCK CALL entries
        Inside   → BLOCK both (range-bound, sit out)
        None     → allow all (no opinion → no filter; fresh-install default)

Three surfaces:

    1. feeling_gate(side, feeling) -> (allow, reason)
       Pure 8-case decision. No I/O. side is 'CALL' or 'PUT'. Exits are filtered
       out by the caller; this helper never sees them.

    2. FeelingState — file-backed state with a threading.Lock around writes.
       Atomic writes via atomic_json. Fail-closed read semantics:
           FileNotFoundError (missing) → fresh install, all None (allow all)
           JSONDecodeError   (corrupt) → fail-closed sentinel
           PermissionError   (denied)  → fail-closed sentinel
       The `is_unreadable` property exposes the fail-closed state for /health
       and for entry routes that must block until recovery.

    3. derive_side / derive_direction — bridge between the route-level
       vocabulary (CALL/PUT) and the engine-level vocabulary (long/short).
       The engine guard takes direction='long'|'short' per the explicit-kwarg
       decision; CALL = long bet, PUT = short bet.

ASCII flow:

    /webhook | /super-order | /conditional-order
              │
              ├── is_exit?  ────────────────────────────────── yes → bypass gate
              │
              ├── store.is_unreadable? ──────── yes → block with status=skipped_by_feeling_unreadable
              │
              ├── feeling = store.get(underlying)
              │
              ├── allow, reason = feeling_gate(side, feeling)
              │
              └── allow? ── no → HTTP 200 skipped_by_feeling + trade_feed SKIPPED row
                       ── yes → engine call (also gated at engine layer with `direction` kwarg)

State file shape (feelings.json):
    {"NIFTY": "Bullish", "BANKNIFTY": null, "FINNIFTY": "Inside"}
"""

from __future__ import annotations

import os
import threading
from typing import Optional, Tuple

from atomic_json import read_json, write_json


# ───────────────────────── constants ─────────────────────────

VALID_FEELINGS = frozenset({"Bullish", "Bearish", "Inside"})
VALID_SIDES = frozenset({"CALL", "PUT"})
VALID_DIRECTIONS = frozenset({"long", "short"})

# Absolute path same as scrip-CSV (commit 8fd39b6 fix for relative-path regression).
_FEELINGS_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "feelings.json"
)


# ───────────────────────── pure helpers ─────────────────────────


def normalize_feeling(raw) -> Optional[str]:
    """Normalize a raw feeling input to the canonical {Bullish,Bearish,Inside} or None.

    Returns None for explicit clears (None/null) or whitespace-only strings.
    Raises ValueError on anything else (typos, 'Neutral', 'Sideways', etc.) so
    the route can surface a 400 instead of silently disabling the gate.
    """
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError(f"feeling must be a string or null, got {type(raw).__name__}")
    s = raw.strip()
    if s == "":
        return None
    s = s.capitalize()
    if s not in VALID_FEELINGS:
        raise ValueError(
            f"feeling must be one of {sorted(VALID_FEELINGS)} or null, got {raw!r}"
        )
    return s


def derive_side(direction: str) -> str:
    """Map engine-level direction ('long'/'short') to gate-level side ('CALL'/'PUT').

    Long bets are CALL options; short bets are PUT options. The engine takes
    `direction` as the explicit kwarg (no fragile symbol parsing); the gate
    helper takes `side` because that's the natural vocabulary for the gating
    rules (Bullish allows CALL, Bearish allows PUT). This shim ties them.

    Raises ValueError on unknown direction so the engine guard fail-closes
    rather than silently defaulting.
    """
    if direction not in VALID_DIRECTIONS:
        raise ValueError(
            f"direction must be one of {sorted(VALID_DIRECTIONS)}, got {direction!r}"
        )
    return "CALL" if direction == "long" else "PUT"


def feeling_gate(
    side: str, feeling: Optional[str]
) -> Tuple[bool, str]:
    """Decide whether an entry signal of the given `side` is allowed under `feeling`.

    Pure function, no I/O. Caller filters out exits before invoking this.

    Truth table (8 cases):
        Bullish × CALL  → allow
        Bullish × PUT   → block ("Bullish feeling blocks PUT entries")
        Bearish × CALL  → block
        Bearish × PUT   → allow
        Inside  × CALL  → block ("Inside feeling blocks all directional entries")
        Inside  × PUT   → block
        None    × CALL  → allow ("No feeling set")
        None    × PUT   → allow

    Returns (allow: bool, reason: str). On invalid `side`, raises ValueError —
    this is a programming error (the caller should have normalized), not a
    runtime user-input issue.
    """
    if side not in VALID_SIDES:
        raise ValueError(f"side must be 'CALL' or 'PUT', got {side!r}")

    if feeling is None:
        return True, "No feeling set"

    if feeling == "Bullish":
        if side == "CALL":
            return True, "Bullish feeling allows CALL entries"
        return False, "Bullish feeling blocks PUT entries"

    if feeling == "Bearish":
        if side == "PUT":
            return True, "Bearish feeling allows PUT entries"
        return False, "Bearish feeling blocks CALL entries"

    if feeling == "Inside":
        return False, "Inside feeling blocks all directional entries"

    # Unreachable if normalize_feeling was used upstream, but fail-closed if not.
    return False, f"Unknown feeling {feeling!r} — fail-closed"


# ───────────────────────── FeelingState ─────────────────────────


class FeelingState:
    """File-backed per-underlying feeling state.

    Writes are wrapped in a threading.Lock to serialize concurrent set-feeling
    calls. Reads are lock-free (eventually consistent under concurrent writes,
    which is fine — the OS handles the atomic rename).

    The `is_unreadable` property is True when the underlying file exists but
    cannot be parsed (JSONDecodeError) or read (PermissionError). In that
    state, /health surfaces feelings_store='unreadable' and entry routes
    block with status='skipped_by_feeling_unreadable'. Recovery: operator
    deletes feelings.json and restarts.

    Missing file is NOT unreadable — it's the fresh-install default ("no
    opinion → allow all"). This is the load-bearing distinction the
    /plan-eng-review surfaced (Issue 1).
    """

    def __init__(self, path: Optional[str] = None):
        self._path = path or _FEELINGS_FILE
        self._lock = threading.Lock()

    @property
    def path(self) -> str:
        return self._path

    def _load(self):
        """Return the parsed dict (or {} on missing), plus a status string.

        status ∈ {'ok', 'missing', 'corrupt', 'denied'}
        """
        r = read_json(self._path)
        return r.data if r.data is not None else {}, r.status

    @property
    def is_unreadable(self) -> bool:
        """True if the state file exists but cannot be read / parsed."""
        _, status = self._load()
        return status in ("corrupt", "denied")

    @property
    def store_status(self) -> str:
        """Returns 'ok' (readable, including missing-as-fresh) or 'unreadable'.

        Convenience for /health: missing is reported as 'ok' because a fresh
        install with no feelings set is the normal allow-all state.
        """
        _, status = self._load()
        return "unreadable" if status in ("corrupt", "denied") else "ok"

    def get(self, underlying: str) -> Optional[str]:
        """Return the feeling for `underlying`, or None if unset or unreadable.

        Callers that need to distinguish unreadable-vs-unset must consult
        `is_unreadable` separately; this method coerces the unreadable case
        to None so the gate fails closed via the entry-route logic, not via
        a hidden "looks bullish" payload.
        """
        if not isinstance(underlying, str):
            return None
        data, status = self._load()
        if status != "ok":
            return None  # missing → no opinion; corrupt/denied → caller checks is_unreadable
        return data.get(underlying.upper())

    def get_all(self) -> dict:
        """Return the full per-underlying map. Returns {} on missing or unreadable."""
        data, status = self._load()
        if status != "ok":
            return {}
        return dict(data)

    def set(self, underlying: str, value: Optional[str]) -> None:
        """Set the feeling for `underlying`. `value` must already be normalized.

        Caller should pass the result of `normalize_feeling()` so this method
        never has to reject input. Use None to clear.

        Atomic write via atomic_json; concurrent setters are serialized by
        the shared lock.
        """
        if not isinstance(underlying, str) or not underlying:
            raise ValueError("underlying must be a non-empty string")
        if value is not None and value not in VALID_FEELINGS:
            raise ValueError(
                f"value must be one of {sorted(VALID_FEELINGS)} or None, got {value!r}"
            )

        with self._lock:
            data, status = self._load()
            if status in ("corrupt", "denied"):
                # Refuse to write into an unreadable store — the operator must
                # delete + restart per the recovery contract. Writing would
                # silently mask the corruption.
                raise RuntimeError(
                    f"feelings store is {status}; refusing to write. "
                    f"Recovery: delete {self._path} and restart."
                )
            data = dict(data)  # don't mutate the read result
            key = underlying.upper()
            if value is None:
                data.pop(key, None)
            else:
                data[key] = value
            # write_json holds its own lock arg, but we're already inside
            # self._lock — pass None to avoid double-locking.
            write_json(self._path, data, lock=None)
