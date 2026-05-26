"""
Tests for atomic_json — the shared atomic JSON read/write primitive.

Coverage:
  - write→read round-trip preserves data
  - read on missing file → status='missing', data={}
  - read on corrupt JSON → status='corrupt', data=None
  - read on non-dict JSON (list, scalar) → status='corrupt'
  - read on permission-denied → status='denied', data=None
  - partial write failure does NOT corrupt target (.tmp cleaned, target untouched)
  - lock parameter serializes concurrent writes
"""
import json
import os
import stat
import threading
from unittest.mock import patch

import pytest

from atomic_json import ReadResult, read_json, write_json


# ───────────────────────── read_json ─────────────────────────
class TestRead:
    def test_round_trip(self, tmp_path):
        p = str(tmp_path / "state.json")
        write_json(p, {"feeling": "Bullish", "count": 3})
        r = read_json(p)
        assert r.status == "ok"
        assert r.data == {"feeling": "Bullish", "count": 3}

    def test_missing_returns_missing_sentinel(self, tmp_path):
        p = str(tmp_path / "does_not_exist.json")
        r = read_json(p)
        assert r == ReadResult(status="missing", data={})

    def test_corrupt_json_returns_corrupt_sentinel(self, tmp_path):
        p = str(tmp_path / "torn.json")
        # Simulate a half-written file (e.g. crash mid-dump).
        with open(p, "w") as f:
            f.write('{"feeling": "Bull')
        r = read_json(p)
        assert r.status == "corrupt"
        assert r.data is None

    def test_non_dict_json_treated_as_corrupt(self, tmp_path):
        # A JSON list or scalar at the root is unexpected for our state files
        # (which all wrap a {} root). Treat as corrupt so the caller fail-closes
        # rather than trusting an unexpected shape.
        for value in ('["NIFTY", "BANKNIFTY"]', '42', '"Bullish"', "null"):
            p = str(tmp_path / "weird.json")
            with open(p, "w") as f:
                f.write(value)
            r = read_json(p)
            assert r.status == "corrupt", f"value {value!r} should be corrupt"
            assert r.data is None

    def test_permission_denied_returns_denied_sentinel(self, tmp_path):
        p = str(tmp_path / "locked.json")
        with open(p, "w") as f:
            f.write("{}")
        os.chmod(p, 0)  # u-rwx,g-rwx,o-rwx
        try:
            # If we're running as root, chmod 0 doesn't block reads. Skip.
            if os.geteuid() == 0:
                pytest.skip("running as root; cannot test PermissionError")
            r = read_json(p)
            assert r.status == "denied"
            assert r.data is None
        finally:
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)  # restore for cleanup


# ───────────────────────── write_json ─────────────────────────
class TestWrite:
    def test_write_creates_file_with_expected_content(self, tmp_path):
        p = str(tmp_path / "out.json")
        write_json(p, {"a": 1, "b": [1, 2, 3]})
        with open(p, "r") as f:
            assert json.load(f) == {"a": 1, "b": [1, 2, 3]}

    def test_write_overwrites_existing_file_atomically(self, tmp_path):
        p = str(tmp_path / "out.json")
        write_json(p, {"v": 1})
        write_json(p, {"v": 2})
        assert read_json(p).data == {"v": 2}

    def test_write_failure_at_replace_does_not_corrupt_target(self, tmp_path):
        p = str(tmp_path / "out.json")
        # Seed an initial file we want preserved across a failed write.
        write_json(p, {"v": 1})

        # Force os.replace to fail; the .tmp should be cleaned up and the
        # target untouched (still v=1).
        with patch("atomic_json.os.replace", side_effect=OSError("simulated")):
            with pytest.raises(OSError, match="simulated"):
                write_json(p, {"v": 2})

        assert read_json(p).data == {"v": 1}, "target was corrupted by failed write"
        assert not os.path.exists(p + ".tmp"), ".tmp not cleaned up after failure"

    def test_lock_parameter_serializes_writes(self, tmp_path):
        p = str(tmp_path / "concurrent.json")
        lock = threading.Lock()
        errors: list[Exception] = []

        def writer(value: int) -> None:
            try:
                write_json(p, {"v": value}, lock=lock)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # No exceptions, file is readable as valid JSON (no torn write),
        # final value is one of the 50 we wrote.
        assert errors == []
        r = read_json(p)
        assert r.status == "ok"
        assert 0 <= r.data["v"] < 50
