# video-use/harness/tests/test_consistency_gate.py
import os
import time
import json
from pathlib import Path

import consistency_gate as cg


def test_gate_active_when_approved_after_start():
    script = {"script_approval": {"approved_at": "2026-09-10"}}
    assert cg.uses_consistency_gate(script, script_path=None) is True


def test_gate_inactive_when_approved_before_start():
    script = {"script_approval": {"approved_at": "2026-09-01"}}
    assert cg.uses_consistency_gate(script, script_path=None) is False


def test_gate_uses_mtime_when_no_approval(tmp_path):
    p = tmp_path / "script.json"
    p.write_text("{}", encoding="utf-8")
    old = time.mktime((2026, 9, 1, 0, 0, 0, 0, 0, -1))
    os.utime(p, (old, old))
    assert cg.uses_consistency_gate({}, script_path=str(p)) is False
    new = time.mktime((2026, 9, 10, 0, 0, 0, 0, 0, -1))
    os.utime(p, (new, new))
    assert cg.uses_consistency_gate({}, script_path=str(p)) is True
