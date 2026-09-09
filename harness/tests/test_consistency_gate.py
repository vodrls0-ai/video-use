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


# ── Task 2: G1 문어체 비율 / G2 문장 길이 ─────────────────────
def _beats(*texts):
    return [{"id": f"n{i:02d}", "narration": t, "evidence": "x", "conversion_role": "V↑"} for i, t in enumerate(texts, 1)]


def test_g1_formal_ratio_fails_when_over_20pct():
    beats = _beats("이 바지는 사이드턱이 있습니다.", "허벅지가 편합니다.", "그래서 핏이 살아요", "이거 하나면 돼요")
    errors, warnings = [], []
    cg.check_formal_tone(beats, errors, warnings, strict=True)
    assert any("[문어체과다]" in e for e in errors)


def test_g1_passes_spoken():
    beats = _beats("허벅지 굵으면 슬림은 꽉 끼잖아요", "근데 이건 사이드턱이 잡아줘요", "한장 이만구천팔백원이에요")
    errors, warnings = [], []
    cg.check_formal_tone(beats, errors, warnings, strict=True)
    assert errors == []


def test_g1_downgrades_to_warning_when_not_strict():
    beats = _beats("이 바지는 사이드턱이 있습니다.", "허벅지가 편합니다.")
    errors, warnings = [], []
    cg.check_formal_tone(beats, errors, warnings, strict=False)
    assert errors == [] and any("[문어체과다]" in w for w in warnings)


def test_g2_long_sentence_warns():
    beats = _beats("이 바지는 허벅지가 굵어도 라인이 안 무너지고 밴딩이라 허리도 편하고 기장까지 두 가지라서 고민이 없어요")
    errors, warnings = [], []
    cg.check_sentence_length(beats, warnings)
    assert any("[문장길이]" in w for w in warnings)


# ── Task 3: G3/G4 말맛 출처 ───────────────────────────────
def _ctx(**over):
    base = {
        "target_customer": "t", "desired_change": "d", "buying_barrier": "b", "value_promise": "v",
        "script_tone_source": {
            "brand": "바이도",
            "source_ref": "벤치마크/메타/바이도/바이도_워싱마스터.md#F-02",
            "imported_function": "체형양극 훅",
            "applied_line_ids": ["n01"],
        },
    }
    base.update(over)
    return base


def test_g3_missing_tone_source_fails():
    ctx = _ctx()
    del ctx["script_tone_source"]
    errors, warnings = [], []
    cg.check_tone_source(ctx, _beats("a", "b"), errors, warnings, strict=True)
    assert any("[말맛출처누락]" in e for e in errors)


def test_g3_partial_tone_source_fails():
    ctx = _ctx(script_tone_source={"brand": "바이도"})
    errors, warnings = [], []
    cg.check_tone_source(ctx, _beats("a", "b"), errors, warnings, strict=True)
    assert any("[말맛출처불완전]" in e and "source_ref" in e for e in errors)


def test_g4_unknown_line_id_fails():
    ctx = _ctx()
    ctx["script_tone_source"]["applied_line_ids"] = ["n99"]
    errors, warnings = [], []
    cg.check_tone_source(ctx, _beats("a", "b"), errors, warnings, strict=True)
    assert any("[말맛출처연결]" in e and "n99" in e for e in errors)


def test_g3_g4_pass():
    errors, warnings = [], []
    cg.check_tone_source(_ctx(), _beats("a", "b"), errors, warnings, strict=True)
    assert errors == [] and warnings == []
