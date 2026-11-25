"""Runs the node tests for the browser-side alert logic. Skipped when node is not installed."""

import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parent / "js" / "alertlogic.test.mjs"


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_alert_logic_in_node():
    r = subprocess.run(["node", "--test", str(JS)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
