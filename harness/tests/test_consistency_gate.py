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


# ── Task 4: G5 브랜드 시그니처 ─────────────────────────────
def _reg(tmp_path, data):
    reg = tmp_path / "brand_signatures.json"
    reg.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return str(reg)


def test_g5_signature_missing_fails(tmp_path):
    reg = _reg(tmp_path, {"바이도": {"markers": ["심지어", "게다가"], "source": "x", "built_at": "2026-09-09"}})
    beats = _beats("다리 두껍든 얇든 예뻐요", "한장 이만구천팔백원이에요")
    errors, warnings = [], []
    cg.check_brand_signature("바이도", beats, errors, warnings, strict=True, registry_path=reg)
    assert any("[말맛시그니처]" in e for e in errors)


def test_g5_signature_present_passes(tmp_path):
    reg = _reg(tmp_path, {"바이도": {"markers": ["심지어", "게다가"], "source": "x", "built_at": "2026-09-09"}})
    beats = _beats("다리 두껍든 얇든 예뻐요", "심지어 밴딩이라 편해")
    errors, warnings = [], []
    cg.check_brand_signature("바이도", beats, errors, warnings, strict=True, registry_path=reg)
    assert errors == []


def test_g5_unregistered_brand_warns_only(tmp_path):
    reg = _reg(tmp_path, {})
    errors, warnings = [], []
    cg.check_brand_signature("짬뽕", _beats("a"), errors, warnings, strict=True, registry_path=reg)
    assert errors == [] and any("[시그니처미등록]" in w for w in warnings)


# ── Task 5: G6/G7 TARGET·CTA 비트 + G10 evidence ──────────
def test_g6_no_target_beat_fails():
    beats = [{"id": "usp1", "narration": "a", "evidence": "e", "conversion_role": "V↑"},
             {"id": "cta", "narration": "b", "evidence": "e", "conversion_role": "CTA"}]
    errors, warnings = [], []
    cg.check_target_and_cta_beats(beats, errors, warnings, strict=True)
    assert any("[TARGET누락]" in e for e in errors)


def test_g7_no_cta_beat_fails():
    beats = [{"id": "opening", "narration": "a", "evidence": "e", "conversion_role": "TARGET"},
             {"id": "usp1", "narration": "b", "evidence": "e", "conversion_role": "V↑"}]
    errors, warnings = [], []
    cg.check_target_and_cta_beats(beats, errors, warnings, strict=True)
    assert any("[CTA누락]" in e for e in errors)


def test_g6_g7_pass_with_cta_id_only():
    beats = [{"id": "opening", "narration": "a", "evidence": "e", "conversion_role": "TARGET"},
             {"id": "cta", "narration": "b", "evidence": "e", "conversion_role": "R↓"}]
    errors, warnings = [], []
    cg.check_target_and_cta_beats(beats, errors, warnings, strict=True)
    assert errors == []


def test_g10_empty_evidence_fails():
    beats = [{"id": "opening", "narration": "a", "evidence": "  ", "conversion_role": "TARGET"}]
    errors, warnings = [], []
    cg.check_evidence_present(beats, errors, warnings, strict=True)
    assert any("[근거누락]" in e and "opening" in e for e in errors)


# ── Task 6: G8 CTA 희소성 근거 / G9 CTA 중복 ─────────────
def _cta_beat(text):
    return {"id": "cta", "narration": text, "evidence": "e", "conversion_role": "CTA"}


def test_g8_scarcity_without_factlock_fails():
    errors, warnings = [], []
    cg.check_cta_scarcity({}, [_cta_beat("딱 칠일간 선착순 백명한테만 당일발송으로 보내줄게")], errors, warnings, strict=True)
    assert any("[허위희소성]" in e for e in errors)


def test_g8_korean_numeral_scarcity_detected():
    errors, warnings = [], []
    cg.check_cta_scarcity({}, [_cta_beat("딱 칠일간 백분에게만 드려요")], errors, warnings, strict=True)
    assert any("[허위희소성]" in e for e in errors)


def test_g8_scarcity_with_factlock_passes():
    ctx = {"fact_locks": {"promo": "2026-09-06 사용자 확인: 선착순 100명 당일발송 운영 중"}}
    errors, warnings = [], []
    cg.check_cta_scarcity(ctx, [_cta_beat("딱 칠일간 선착순 백명한테만 당일발송으로 보내줄게")], errors, warnings, strict=True)
    assert errors == []


def test_g8_slot_cta_passes():
    errors, warnings = [], []
    cg.check_cta_scarcity({}, [_cta_beat("{CTA}")], errors, warnings, strict=True)
    assert errors == []


def test_g8_plain_cta_passes():
    errors, warnings = [], []
    cg.check_cta_scarcity({}, [_cta_beat("아래 링크에서 확인해보세요")], errors, warnings, strict=True)
    assert errors == []


def test_g9_duplicate_cta_across_products_warns(tmp_path):
    for i in range(3):
        d = tmp_path / f"prod{i}" / "reels" / "v"
        d.mkdir(parents=True)
        (d / "script.json").write_text(json.dumps({"beats": [_cta_beat("딱 칠일간 선착순 백명한테만 당일발송으로 보내줄게")]},
                                                  ensure_ascii=False), encoding="utf-8")
    warnings = []
    cg.check_cta_duplicates([_cta_beat("딱 칠일간, 선착순 백명한테만 당일발송으로 보내줄게!")],
                            warnings, video_root=str(tmp_path), index_path=str(tmp_path / "_cta_index.json"),
                            current_path=None)
    assert any("[CTA중복]" in w and "3" in w for w in warnings)


def test_g9_unique_cta_no_warning(tmp_path):
    d = tmp_path / "prod0" / "reels" / "v"
    d.mkdir(parents=True)
    (d / "script.json").write_text(json.dumps({"beats": [_cta_beat("댓글에 기장 남겨줘")]}, ensure_ascii=False), encoding="utf-8")
    warnings = []
    cg.check_cta_duplicates([_cta_beat("아래 링크에서 확인해보세요")], warnings, video_root=str(tmp_path),
                            index_path=str(tmp_path / "_cta_index.json"), current_path=None)
    assert warnings == []


# ── Task 7: run_consistency_gate 진입점 ────────────────────
def _full_script(**over):
    s = {
        "story_context": _ctx(),
        "beats": [
            {"id": "n01", "narration": "허벅지 굵은 분들 데님 고를 때 핏이 애매하잖아요", "evidence": "타겟뱅크 체형", "conversion_role": "TARGET"},
            {"id": "n02", "narration": "근데 이건 사이드턱이 잡아줘서 편한데도 안 무너져요", "evidence": "USP① 사이드턱", "conversion_role": "R↓"},
            {"id": "n03", "narration": "심지어 밴딩이라 허리도 편해", "evidence": "USP② 밴딩", "conversion_role": "V↑"},
            {"id": "cta", "narration": "{CTA}", "evidence": "공통 슬롯", "conversion_role": "CTA"},
        ],
        "script_approval": {"approved_at": "2026-09-10"},
    }
    s.update(over)
    return s


def test_run_gate_pass_on_good_script(tmp_path):
    reg = _reg(tmp_path, {"바이도": {"markers": ["심지어"], "source": "x", "built_at": "d"}})
    errors, warnings = [], []
    cg.run_consistency_gate(_full_script(), script_path=None, errors=errors, warnings=warnings,
                            registry_path=reg, video_root=str(tmp_path), index_path=str(tmp_path / "idx.json"))
    assert errors == [], errors


def test_run_gate_old_script_only_warns(tmp_path):
    s = _full_script(script_approval={"approved_at": "2026-08-01"})
    del s["story_context"]["script_tone_source"]
    errors, warnings = [], []
    cg.run_consistency_gate(s, script_path=None, errors=errors, warnings=warnings,
                            registry_path=str(tmp_path / "none.json"), video_root=str(tmp_path), index_path=str(tmp_path / "idx.json"))
    assert errors == [] and any("[말맛출처누락]" in w for w in warnings)
