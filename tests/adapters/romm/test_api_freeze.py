"""Freeze test for api_v46.py — ensures the frozen adapter is never modified."""

import hashlib
from pathlib import Path

# Update this hash ONLY for critical bugfixes to api_v46.py.
_EXPECTED_HASH = "0f91a5954a227b07bcc7d127a329c33a68bb11a8a5d3811e03ddf88c36366a81"


def test_api_v46_is_frozen():
    """api_v46.py must not be modified. Update hash only for critical bugfixes."""
    path = Path(__file__).resolve().parent.parent.parent.parent / "py_modules" / "adapters" / "romm" / "api_v46.py"
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == _EXPECTED_HASH, (
        f"api_v46.py was modified! This file is frozen.\n"
        f"Expected hash: {_EXPECTED_HASH}\n"
        f"Actual hash:   {actual}\n"
        f"If this is an intentional critical bugfix, update _EXPECTED_HASH in this test."
    )
