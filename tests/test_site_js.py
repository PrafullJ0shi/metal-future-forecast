"""Runs the node tests for the browser-side helpers. Skipped when node is not installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_browser_logic_in_node():
    files = sorted(str(p) for p in JS.glob("*.mjs"))
    assert files, "no node tests found"
    r = subprocess.run(["node", "--test", *files], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
