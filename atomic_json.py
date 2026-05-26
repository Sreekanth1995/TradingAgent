"""Atomic JSON read/write primitive.

Why this exists:
    The project has three JSON state files (`feelings.json`, `levels.json`,
    `ai_context.txt`). The historical write pattern (`json.dump` directly on the
    target path) leaves a corrupt file if the process dies mid-write — the next
    boot reads a torn JSON and either crashes or, worse, silently returns `{}`
    and disables whatever safety the file was tracking. For the feeling-gate
    this would mean a corrupt file silently disables the gate; the bot would
    happily place contra-bias trades with no warning.

    Fix: write to a `.tmp` sibling, then `os.replace()` to swap atomically
    (POSIX `rename(2)` is atomic on a single filesystem). On crash, the
    `.tmp` may be partial but the target is either the previous version or
    the new version — never a torn half-write.

Surface:
    write_json(path, data, lock=None)
        Atomic write. If `lock` is provided (e.g. a threading.Lock the caller
        shares across writers), it is held for the duration of the write +
        replace. Tmp file is cleaned up on any failure.

    read_json(path) -> ReadResult
        Returns a ReadResult(status, data) named tuple. Never raises for the
        four expected failure modes; caller branches on .status:

            'ok'      → data is the parsed dict
            'missing' → file does not exist (data = {})
            'corrupt' → JSON decode error (data = None)
            'denied'  → PermissionError on read (data = None)

        Why split missing vs corrupt: missing means "fresh install, no state
        yet" → caller's safe behavior is to use defaults. Corrupt/denied
        means "the state we relied on is unreadable" → caller fail-closes.
        Conflating them is the bug `feelings.json` was about to ship with.

ASCII flow:

    write_json(path, data, lock)
        │
        ├── (with lock if provided)
        │       │
        │       ├── open(path + '.tmp', 'w'), json.dump, fsync
        │       │       │
        │       │       └── on exception → unlink(path + '.tmp'), re-raise
        │       │
        │       └── os.replace(path + '.tmp', path)  ← atomic swap
        │
        └── return

    read_json(path)
        │
        ├── open(path, 'r')
        │       │
        │       ├── FileNotFoundError → ReadResult('missing', {})
        │       ├── PermissionError   → ReadResult('denied', None)
        │       └── ok → json.load
        │               │
        │               ├── JSONDecodeError → ReadResult('corrupt', None)
        │               └── ok → ReadResult('ok', data)
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any, NamedTuple, Optional


class ReadResult(NamedTuple):
    """Result of read_json. Status is one of: ok|missing|corrupt|denied."""

    status: str
    data: Optional[dict]


def write_json(
    path: str,
    data: Any,
    lock: Optional[threading.Lock] = None,
) -> None:
    """Atomically write `data` as JSON to `path`.

    Strategy: write to `path + '.tmp'`, fsync, then `os.replace()` to swap.
    POSIX guarantees `rename(2)` is atomic on a single filesystem, so the
    target is always either the prior version or the new version — never
    a torn write.

    If `lock` is provided, it is acquired for the duration of write + replace.
    Callers that share writers across threads should pass a shared lock.

    On any exception during write/replace, the `.tmp` file is best-effort
    unlinked and the exception re-raised. The target file is left untouched
    if the failure happened before `os.replace`.
    """
    tmp_path = path + ".tmp"

    def _do_write() -> None:
        try:
            with open(tmp_path, "w") as f:
                json.dump(data, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            # Best-effort cleanup; do not mask the original exception.
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            raise

    if lock is not None:
        with lock:
            _do_write()
    else:
        _do_write()


def write_text(
    path: str,
    text: str,
    lock: Optional[threading.Lock] = None,
) -> None:
    """Atomic write for plain-text files (e.g. ai_context.txt).

    Same .tmp + os.replace strategy as write_json; included here so the
    "atomic state file" pattern lives in one module even when the content
    is text rather than JSON.
    """
    tmp_path = path + ".tmp"

    def _do_write() -> None:
        try:
            with open(tmp_path, "w") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except FileNotFoundError:
                pass
            except OSError:
                pass
            raise

    if lock is not None:
        with lock:
            _do_write()
    else:
        _do_write()


def read_json(path: str) -> ReadResult:
    """Read JSON from `path` and return a ReadResult.

    Does not raise for the four expected failure modes (missing/corrupt/denied).
    Callers branch on `.status` to decide policy:

        'ok'      → use `.data` (a dict)
        'missing' → fresh install / no state; caller's defaults apply
        'corrupt' → file exists but is unparseable; caller should fail-closed
        'denied'  → cannot read; caller should fail-closed

    Other OS errors (e.g. ENOSPC, EIO) propagate.
    """
    try:
        with open(path, "r") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError:
                return ReadResult(status="corrupt", data=None)
        if not isinstance(data, dict):
            # A non-dict JSON value (list, scalar) is treated as corrupt for
            # our state-file callers, all of which expect dict-shaped state.
            return ReadResult(status="corrupt", data=None)
        return ReadResult(status="ok", data=data)
    except FileNotFoundError:
        return ReadResult(status="missing", data={})
    except PermissionError:
        return ReadResult(status="denied", data=None)
