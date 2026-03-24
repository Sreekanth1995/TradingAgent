# Testing

## Strategy Verification
- **Scripts**: Currently uses ad-hoc unit test scripts (e.g., `test_directional_exit.py`).
- **Mocking**: `unittest.mock` used to simulate broker responses and LTP data.
- **UAT**: Verified via `0x-UAT.md` artifacts per phase.

## Manual Verification
- Testing the dashboard endpoints via `curl`.
- Interactive testing of the `index.html` interface in a local browser.
