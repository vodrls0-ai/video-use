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


# ── 공용 유틸 ─────────────────────────────────────────────
FORMAL_ENDING_RE = re.compile(r"(입니다|합니다|됩니다|있습니다|가능합니다|제공합니다|드립니다)\s*[.!?]?\s*$")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.?!])\s+|\n+")
FORMAL_RATIO_MAX_DEFAULT = 0.20
SENTENCE_LEN_MAX = 40


def _emit(level_fail: bool, msg: str, errors: list, warnings: list):
    (errors if level_fail else warnings).append(msg)


def _sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE_SPLIT_RE.split(text or "") if p and p.strip()]
    return parts or ([text.strip()] if text and text.strip() else [])


def beat_texts(beats: list[dict]) -> list[tuple[str, str]]:
    """[(beat_id, narration)] — narration이 비면 제외."""
    out = []
    for b in beats or []:
        t = (b.get("narration") or "").strip()
        if t:
            out.append((str(b.get("id", "?")), t))
    return out


# ── G1 문어체 비율 ─────────────────────────────────────────
def check_formal_tone(beats: list[dict], errors: list, warnings: list, *, strict: bool,
                      ratio_max: float = FORMAL_RATIO_MAX_DEFAULT):
    sentences = []
    for _, t in beat_texts(beats):
        sentences.extend(_sentences(t))
    if not sentences:
        return
    formal = [s for s in sentences if FORMAL_ENDING_RE.search(s)]
    ratio = len(formal) / len(sentences)
    if ratio > ratio_max:
        sample = formal[0][:30]
        _emit(strict,
              f"[문어체과다] 종결 '~입니다/~합니다'류 {len(formal)}/{len(sentences)}문장({ratio:.0%}) — "
              f"상한 {ratio_max:.0%}. 예: '{sample}' → 구어체로 재작성(CONVERSION_CARD §11)",
              errors, warnings)


# ── G2 문장 길이 ───────────────────────────────────────────
def check_sentence_length(beats: list[dict], warnings: list, max_len: int = SENTENCE_LEN_MAX):
    for bid, t in beat_texts(beats):
        for s in _sentences(t):
            if len(s) > max_len:
                warnings.append(f"[문장길이] {bid} '{s[:20]}…' {len(s)}자 — {max_len}자 초과, TTS 호흡 끊기 권장")
