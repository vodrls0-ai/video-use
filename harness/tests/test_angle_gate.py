# video-use/harness/tests/test_angle_gate.py
import json

import angle_gate as ag


def _script(target, hook, *, approved_at="2026-09-10", angle=None):
    s = {
        "story_context": {"target_customer": target, "buying_barrier": "x", "desired_change": "y", "value_promise": "z"},
        "beats": [{"id": "hook", "narration": hook, "conversion_role": "TARGET", "evidence": "e"}],
        "script_approval": {"status": "approved", "approved_at": approved_at, "approved_by": "user", "source": "t"},
    }
    if angle is not None:
        s["angle"] = angle
    return s


def _write(tmp_path, name, script):
    d = tmp_path / "video" / name / "reels" / "v1"
    d.mkdir(parents=True)
    p = d / "script.json"
    p.write_text(json.dumps(script, ensure_ascii=False), encoding="utf-8")
    return str(p)


def _run(tmp_path, script, current_path=None, strict=True):
    errors, warnings = [], []
    ag._INDEX_CACHE.clear()
    ag.check_angle_diversity(script, errors, warnings, strict=strict,
                             video_root=str(tmp_path / "video"),
                             index_path=str(tmp_path / "_angle_index.json"),
                             current_path=current_path)
    return errors, warnings


# ── 분류 ──────────────────────────────────────────────────
def test_body_detected_from_target():
    a = ag.angle_of(_script("허벅지 굵어서 슬림핏 못 입는 사람", "이거 보고 가"))
    assert a["body"] is True


def test_price_hook_category():
    a = ag.angle_of(_script("편한 바지 찾는 사람", "장당 만사천구백원인데 이 핏이 나와"))
    assert a["hook_category"] == "가격" and a["body"] is False


def test_explicit_angle_field_wins():
    a = ag.angle_of(_script("허벅지 굵은 사람", "허벅지 굵으면 이거", angle={"hook_category": "TPO", "body": False}))
    assert a == {"body": False, "hook_category": "TPO", "target": "허벅지 굵은 사람"}


# ── A1 체형 수렴 ───────────────────────────────────────────
def test_body_convergence_fails_when_recent_are_body(tmp_path):
    for i in range(4):
        _write(tmp_path, f"p{i}", _script("어깨 좁은 남자", "어깨 좁으면 이거", approved_at=f"2026-09-0{i + 1}"))
    cur = _script("배 나온 30대", "뱃살 가려주는 바지")
    cur_path = _write(tmp_path, "cur", cur)
    errors, warnings = _run(tmp_path, cur, current_path=cur_path)
    assert any("[앵글수렴]" in e for e in errors)
    assert "체형 앵글 5편" in errors[0]


def test_nonbody_current_passes_even_if_recent_are_body(tmp_path):
    for i in range(4):
        _write(tmp_path, f"p{i}", _script("어깨 좁은 남자", "어깨 좁으면 이거", approved_at=f"2026-09-0{i + 1}"))
    cur = _script("출근룩 고민인 사람", "출근할 때 이 바지 하나면 돼")
    cur_path = _write(tmp_path, "cur", cur)
    errors, _ = _run(tmp_path, cur, current_path=cur_path)
    assert errors == []


def test_body_allowed_when_recent_are_diverse(tmp_path):
    _write(tmp_path, "a", _script("출근룩", "출근할 때 이거", approved_at="2026-09-01"))
    _write(tmp_path, "b", _script("가성비", "이만원대에 이 핏", approved_at="2026-09-02"))
    _write(tmp_path, "c", _script("소재", "밴딩 원단이 달라", approved_at="2026-09-03"))
    _write(tmp_path, "d", _script("어깨 좁은", "어깨 좁으면", approved_at="2026-09-04"))
    cur = _script("허벅지 굵은", "허벅지 굵어도 돼")
    cur_path = _write(tmp_path, "cur", cur)
    errors, _ = _run(tmp_path, cur, current_path=cur_path)
    assert errors == []  # 체형 2편(현재 포함) = 허용


def test_not_strict_downgrades_to_warning(tmp_path):
    for i in range(4):
        _write(tmp_path, f"p{i}", _script("어깨 좁은 남자", "어깨 좁으면", approved_at=f"2026-09-0{i + 1}"))
    cur = _script("배 나온", "뱃살")
    cur_path = _write(tmp_path, "cur", cur)
    errors, warnings = _run(tmp_path, cur, current_path=cur_path, strict=False)
    assert errors == [] and any("[앵글수렴]" in w for w in warnings)


# ── A2 훅 카테고리 편중 ─────────────────────────────────────
def test_category_concentration_warns(tmp_path):
    for i in range(4):
        _write(tmp_path, f"p{i}", _script("바지 찾는 사람", "장당 만원인데 이거", approved_at=f"2026-09-0{i + 1}"))
    cur = _script("바지 찾는 사람", "이만원대 핏")
    cur_path = _write(tmp_path, "cur", cur)
    _, warnings = _run(tmp_path, cur, current_path=cur_path)
    assert any("[훅카테고리편중]" in w for w in warnings)


# ── A3 타겟 반복 ───────────────────────────────────────────
def test_same_target_detection():
    assert ag.same_target("코디하기 귀찮은 대학생", "코디가 어렵거나 코디하기 귀찮은 대학생, 개강을 앞둔 시기")
    assert not ag.same_target("출근룩 고민인 30대", "소개팅 앞둔 20대")


def test_target_repeat_fails_strict(tmp_path):
    for i, name in enumerate(("a", "b", "c")):
        _write(tmp_path, name, _script("코디하기 귀찮은 대학생", f"훅 {i} 출근", approved_at=f"2026-09-0{i + 1}"))
    _write(tmp_path, "d", _script("가성비 찾는 사람", "이만원대", approved_at="2026-09-04"))
    cur = _script("코디가 어렵거나 코디하기 귀찮은 대학생", "밴딩 원단이 달라")
    cur_path = _write(tmp_path, "cur", cur)
    errors, _ = _run(tmp_path, cur, current_path=cur_path)
    assert any("[타겟반복]" in e and "3편" in e for e in errors)


def test_single_target_overlap_only_warns(tmp_path):
    _write(tmp_path, "a", _script("코디하기 귀찮은 대학생", "출근할 때", approved_at="2026-09-01"))
    _write(tmp_path, "b", _script("가성비 찾는 사람", "이만원대", approved_at="2026-09-02"))
    cur = _script("코디하기 귀찮은 대학생", "밴딩 원단이")
    cur_path = _write(tmp_path, "cur", cur)
    errors, warnings = _run(tmp_path, cur, current_path=cur_path)
    assert errors == [] and any("[타겟유사]" in w for w in warnings)


# ── 인덱스 ────────────────────────────────────────────────
def test_drafted_variant_counts_as_shipped_without_approval_block(tmp_path):
    s = _script("어깨 좁은", "어깨 좁으면")
    del s["script_approval"]  # 실제 script.json 대부분은 승인 블록이 없다(237편 중 1편만 있었음)
    p = _write(tmp_path, "prod", s)  # …/prod/reels/v1/script.json
    product_dir = tmp_path / "video" / "prod"
    (product_dir / ".draft_done").write_text(
        "draft_name: prod_v1\nspec_used: reels/v1/capcut_spec.json\nspec_sha256: x\nclips: 7\ncreated_at: 2026-09-08T10:00:00+09:00\n",
        encoding="utf-8")
    idx = ag.build_angle_index(str(tmp_path / "video"), str(tmp_path / "_angle_index.json"))
    assert idx[p]["approved"] is True and idx[p]["drafted"] is True and idx[p]["approved_at"] == "2026-09-08"


def test_other_variant_of_drafted_product_is_not_shipped(tmp_path):
    s = _script("어깨 좁은", "어깨 좁으면")
    del s["script_approval"]
    p = _write(tmp_path, "prod", s)  # reels/v1
    product_dir = tmp_path / "video" / "prod"
    (product_dir / ".draft_done").write_text("spec_used: reels/v2/capcut_spec.json\ncreated_at: 2026-09-08T10:00:00+09:00\n", encoding="utf-8")
    idx = ag.build_angle_index(str(tmp_path / "video"), str(tmp_path / "_angle_index.json"))
    assert idx[p]["approved"] is False


def test_index_refreshes_when_draft_marker_appears_later(tmp_path):
    s = _script("어깨 좁은", "어깨 좁으면")
    del s["script_approval"]
    p = _write(tmp_path, "prod", s)
    idx_path = str(tmp_path / "_angle_index.json")
    idx = ag.build_angle_index(str(tmp_path / "video"), idx_path)
    assert idx[p]["approved"] is False
    (tmp_path / "video" / "prod" / ".draft_done").write_text("spec_used: reels/v1/capcut_spec.json\ncreated_at: 2026-09-09T10:00:00+09:00\n", encoding="utf-8")
    idx = ag.build_angle_index(str(tmp_path / "video"), idx_path)  # script.json mtime 불변 — 마커 mtime으로 갱신돼야 함
    assert idx[p]["approved"] is True


def test_index_counts_only_approved(tmp_path):
    _write(tmp_path, "ok", _script("어깨", "어깨", approved_at="2026-09-01"))
    draft = _script("어깨", "어깨")
    draft["script_approval"] = {"status": "draft"}
    _write(tmp_path, "draft", draft)
    idx = ag.build_angle_index(str(tmp_path / "video"), str(tmp_path / "_angle_index.json"))
    approved = [p for p, e in idx.items() if e["approved"]]
    assert len(idx) == 2 and len(approved) == 1
