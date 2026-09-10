# video-use/harness/tests/test_consistency_gate_g11.py — G11 반박제거 구체성
import consistency_gate as cg


def test_template_barrier_fails_strict():
    ctx = {"buying_barrier": "카테고리 편견, 가격 저항, 온라인 핏 불확실", "doubt_source": "x"}
    errors, warnings = [], []
    cg.check_buying_barrier_specific(ctx, errors, warnings, strict=True)
    assert any("[반박제거템플릿]" in e for e in errors)


def test_template_barrier_warns_when_not_strict():
    ctx = {"buying_barrier": "가격 저항", "doubt_source": "x"}
    errors, warnings = [], []
    cg.check_buying_barrier_specific(ctx, errors, warnings, strict=False)
    assert errors == [] and any("[반박제거템플릿]" in w for w in warnings)


def test_specific_barrier_with_source_passes():
    ctx = {"buying_barrier": "편한 바지는 핏이 흐물거려서 다리가 짧아 보인다",
           "doubt_source": "customer_language_20260909.json 핏/실루엣 6건"}
    errors, warnings = [], []
    cg.check_buying_barrier_specific(ctx, errors, warnings, strict=True)
    assert errors == [] and warnings == []


def test_missing_source_warns_only():
    ctx = {"buying_barrier": "편한 바지는 핏이 흐물거려서 다리가 짧아 보인다"}
    errors, warnings = [], []
    cg.check_buying_barrier_specific(ctx, errors, warnings, strict=True)
    assert errors == [] and any("[의심출처없음]" in w for w in warnings)


def test_short_label_warns():
    ctx = {"buying_barrier": "가격", "doubt_source": "x"}
    errors, warnings = [], []
    cg.check_buying_barrier_specific(ctx, errors, warnings, strict=True)
    assert errors == [] and any("[반박제거빈약]" in w for w in warnings)


def test_wired_into_run_consistency_gate():
    script = {
        "script_approval": {"approved_at": "2026-09-10"},
        "story_context": {"buying_barrier": "온라인 핏 불확실"},
        "beats": [],
    }
    errors, warnings = [], []
    cg.run_consistency_gate(script, script_path=None, errors=errors, warnings=warnings)
    assert any("[반박제거템플릿]" in e for e in errors)
