# -*- coding: utf-8 -*-
"""consistency_gate.py — 대본 일관성 게이트 (G1~G10).

validate_reels.py의 validate()가 run_consistency_gate()를 호출한다.
스펙: docs/superpowers/specs/2026-09-09-script-consistency-gate-design.md

날짜 게이트: script_approval.approved_at >= GATE_START 이거나,
script_approval이 없고 파일 mtime이 GATE_START 이후면 신규 검사가 FAIL로 동작한다.
그 외(기존 확정 대본)는 전부 WARN으로 격하한다.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

GATE_START = "2026-09-09"
HARNESS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = HARNESS_DIR.parent.parent  # 비디오/
VIDEO_ROOT = PROJECT_ROOT / "video"
SIGNATURES_PATH = PROJECT_ROOT / "templates" / "brand_signatures.json"
CTA_INDEX_PATH = VIDEO_ROOT / "_cta_index.json"


def _start_epoch() -> float:
    y, m, d = (int(x) for x in GATE_START.split("-"))
    return time.mktime((y, m, d, 0, 0, 0, 0, 0, -1))


def uses_consistency_gate(script: dict, script_path: str | None) -> bool:
    approval = (script or {}).get("script_approval") or {}
    approved_at = str(approval.get("approved_at", "")).strip()
    if approved_at:
        return approved_at[:10] >= GATE_START
    if script_path and os.path.exists(script_path):
        return os.path.getmtime(script_path) >= _start_epoch()
    return True  # 경로도 승인도 없으면 신규로 본다
