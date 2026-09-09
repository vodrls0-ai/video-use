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


# ── G3/G4 말맛 출처 ────────────────────────────────────────
TONE_SOURCE_FIELDS = ("brand", "source_ref", "imported_function", "applied_line_ids")


def check_tone_source(story_context: dict, beats: list[dict], errors: list, warnings: list, *, strict: bool):
    src = (story_context or {}).get("script_tone_source")
    if not isinstance(src, dict) or not src:
        _emit(strict,
              "[말맛출처누락] story_context.script_tone_source 없음 — "
              "어느 브랜드 워싱마스터의 어떤 화법 기능을 어느 줄에 썼는지 기록 필수(CONVERSION_CARD §1 copy_bank_routing)",
              errors, warnings)
        return
    missing = [f for f in TONE_SOURCE_FIELDS if not src.get(f)]
    if missing:
        _emit(strict, f"[말맛출처불완전] script_tone_source 비어있는 필드: {', '.join(missing)}", errors, warnings)
        return
    ids = {str(b.get("id")) for b in beats or []}
    bad = [lid for lid in src.get("applied_line_ids", []) if str(lid) not in ids]
    if bad:
        _emit(strict,
              f"[말맛출처연결] applied_line_ids {bad} 가 beats[].id에 없음 — 실제 적용 줄과 연결해야 함",
              errors, warnings)


# ── G5 브랜드 시그니처 ─────────────────────────────────────
def load_signatures(registry_path: str | None = None) -> dict:
    p = Path(registry_path) if registry_path else SIGNATURES_PATH
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def check_brand_signature(brand: str, beats: list[dict], errors: list, warnings: list, *, strict: bool,
                          registry_path: str | None = None):
    if not brand:
        return
    registry = load_signatures(registry_path)
    entry = registry.get(brand)
    if not entry or not entry.get("markers"):
        warnings.append(f"[시그니처미등록] '{brand}' 가 templates/brand_signatures.json에 없음 — "
                        f"python tools/build_brand_signatures.py 실행 후 재검증")
        return
    full = " ".join(t for _, t in beat_texts(beats))
    found = [m for m in entry["markers"] if m in full]
    if not found:
        _emit(strict,
              f"[말맛시그니처] '{brand}' 시그니처 마커 0개 사용 (요구 중 하나: {entry['markers'][:5]}) — "
              f"출처만 적고 말맛은 안 가져온 상태",
              errors, warnings)


# ── G6/G7 TARGET·CTA 비트 ─────────────────────────────────
def _roles(beat: dict) -> set[str]:
    role = str(beat.get("conversion_role", ""))
    return {tok.strip() for tok in role.replace("+", " ").replace(",", " ").split() if tok.strip()}


def check_target_and_cta_beats(beats: list[dict], errors: list, warnings: list, *, strict: bool):
    if not beats:
        return
    has_target = any("TARGET" in _roles(b) for b in beats)
    has_cta = any("CTA" in _roles(b) or str(b.get("id", "")).lower() == "cta" for b in beats)
    if not has_target:
        _emit(strict, "[TARGET누락] conversion_role=TARGET 비트 0개 — 첫 줄에 누구 이야기인지 호명/상황이 있어야 함", errors, warnings)
    if not has_cta:
        _emit(strict, "[CTA누락] CTA 비트 0개 — id 'cta' 또는 conversion_role에 CTA 필요({CTA} 슬롯 가능)", errors, warnings)


# ── G10 줄별 근거 ─────────────────────────────────────────
def check_evidence_present(beats: list[dict], errors: list, warnings: list, *, strict: bool):
    empty = [str(b.get("id", "?")) for b in beats or [] if not str(b.get("evidence", "")).strip()]
    if empty:
        _emit(strict, f"[근거누락] evidence 비어있는 비트: {', '.join(empty)} — rule 45(모든 줄에 근거)", errors, warnings)


# ── G8 CTA 희소성 근거 ─────────────────────────────────────
KOR_NUM = "[일이삼사오육칠팔구십백천]+"
SCARCITY_RE = re.compile(
    rf"선착순|당일발송|한정|마감|품절|딱\s*(\d+|{KOR_NUM})\s*일|(\d+|{KOR_NUM})\s*(명|분)(에게|한테)?"
)
CTA_SLOT = "{CTA}"


def cta_beats(beats: list[dict]) -> list[dict]:
    return [b for b in beats or [] if "CTA" in _roles(b) or str(b.get("id", "")).lower() == "cta"]


def check_cta_scarcity(story_context: dict, beats: list[dict], errors: list, warnings: list, *, strict: bool):
    promo = str(((story_context or {}).get("fact_locks") or {}).get("promo", "")).strip()
    for b in cta_beats(beats):
        text = (b.get("narration") or "").strip()
        if not text or text == CTA_SLOT:
            continue
        m = SCARCITY_RE.search(text)
        if m and not promo:
            _emit(strict,
                  f"[허위희소성] CTA '{text[:30]}…' 에 희소성 어휘 '{m.group(0)}' — "
                  f"story_context.fact_locks.promo(실제 운영 근거) 없으면 사용 금지(CONVERSION_CARD §3 Line7)",
                  errors, warnings)


# ── G9 CTA 중복 ───────────────────────────────────────────
def normalize_cta(text: str) -> str:
    return re.sub(r"[\s\.,!?~…'\"\-]", "", text or "")


def _build_cta_index(video_root: str, index_path: str) -> dict:
    """{script_path: {"mtime": float, "cta": str}} — mtime 캐시. video/ 전수 스캔은 NAS에서 느리므로 재사용한다."""
    index = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            index = {}
    seen = set()
    for root, dirs, files in os.walk(video_root):
        dirs[:] = [d for d in dirs if d not in ("archive", "_tts_sample_khaki_series")]
        if "script.json" not in files or os.path.basename(os.path.dirname(root)) != "reels":
            continue
        p = os.path.join(root, "script.json")
        seen.add(p)
        mtime = os.path.getmtime(p)
        if p in index and abs(index[p].get("mtime", -1) - mtime) < 1e-6:
            continue
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            ctas = [normalize_cta(b.get("narration", "")) for b in cta_beats(data.get("beats", []))]
            index[p] = {"mtime": mtime, "cta": ctas[0] if ctas else ""}
        except (json.JSONDecodeError, OSError):
            index[p] = {"mtime": mtime, "cta": ""}
    for p in list(index):
        if p not in seen:
            del index[p]
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return index


def check_cta_duplicates(beats: list[dict], warnings: list, *, video_root: str | None = None,
                         index_path: str | None = None, current_path: str | None = None, min_count: int = 3):
    mine = [normalize_cta(b.get("narration", "")) for b in cta_beats(beats)]
    mine = [m for m in mine if m and m != normalize_cta(CTA_SLOT)]
    if not mine:
        return
    index = _build_cta_index(video_root or str(VIDEO_ROOT), index_path or str(CTA_INDEX_PATH))
    for cta in mine:
        others = [p for p, v in index.items() if v.get("cta") == cta and p != current_path]
        if len(others) >= min_count:
            warnings.append(f"[CTA중복] 같은 CTA 문장이 다른 상품 {len(others)}곳에서 사용 — "
                            f"고정구 복제 의심. 예: {os.path.relpath(others[0], video_root or str(VIDEO_ROOT))}")
