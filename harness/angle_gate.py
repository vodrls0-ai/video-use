# -*- coding: utf-8 -*-
"""angle_gate.py — 앵글 다양성 게이트 (qa-angle 에이전트 기준의 코드화, 2026-09-10).

`.claude/agents/qa-angle.md`는 정의만 있고 tools/harness/rules 어디서도 호출되지 않았다(2026-09-10 감사).
그 기준을 validate_reels.validate()가 실행하는 코드 게이트로 옮긴다.

  A1 체형 수렴   : 현재 대본 포함 최근 WINDOW편 중 체형 앵글이 BODY_MAX편을 넘으면 FAIL(신규분) / WARN(구분)
  A2 훅 카테고리 : 최근 편들의 훅 카테고리 종류가 MIN_CATEGORIES 미만이면 WARN
  A3 타겟 반복   : 현재 타겟 문구가 최근 TARGET_WINDOW편 중 2편 이상과 같으면 FAIL(신규분) / WARN(구분), 1편이면 WARN
                  (2026-09-10 실측: 최근 12편 중 "코디하기 귀찮은 대학생"이 상품만 바꿔 3편 — 이게 "타겟이 매번 같다"의 실체)

"최근 편" = video/**/reels/<variant>/script.json 중 **실제로 나간 것**:
  (a) 상품폴더/.draft_done(generate_capcut이 씀)의 spec_used가 그 variant를 가리키면 "드래프트 생성됨" — 1순위 신호
  (b) 또는 script_approval.status == approved
approved_at(없으면 .draft_done created_at, 없으면 mtime) 내림차순으로 자른 것. 인덱스는 video/_angle_index.json에
mtime 캐시(consistency_gate._build_cta_index와 같은 방식; script.json과 .draft_done 둘 다의 mtime을 본다).
걷기 비용을 줄이기 위해 _cta_index.json이 있으면 그 경로 목록을 후보로 재사용한다.

script.json에 `angle` 필드가 있으면 그 값을 우선한다:
  "angle": {"hook_category": "가격", "body": false}   또는   "angle": "가격"
없으면 story_context.target_customer + meta.benchmark_usage.three_axis_map.타겟설정 + 첫 비트 나레이션으로 분류한다.

CLI:  python angle_gate.py --recent 10     # 최근 10편 앵글 표 (수렴 상태 육안 확인)
"""
import argparse
import datetime as _dt
import difflib
import json
import os
import re
import sys
from pathlib import Path

from consistency_gate import CTA_INDEX_PATH, VIDEO_ROOT, uses_consistency_gate

ANGLE_INDEX_PATH = VIDEO_ROOT / "_angle_index.json"
WINDOW = 5
BODY_MAX = 2          # 현재 포함 WINDOW편 중 체형 허용 최대 — 3편부터 위반 (qa-angle §1)
MIN_CATEGORIES = 3    # 훅 카테고리 종류가 이 미만이면 편중 경고 (qa-angle §2: 2개 이하 = WARN)
TARGET_MIN_COMMON = 8 # 정규화한 타겟 문구의 최장 공통 부분이 이 길이 이상이면 "같은 타겟"
TARGET_DUP_FAIL = 2   # 최근 편 중 같은 타겟이 이 수 이상이면 위반
TARGET_WINDOW = 10    # 타겟 반복은 더 긴 창으로 본다 — 같은 날 일괄 드래프트된 3편이 5편 창 밖으로 밀려 안 잡힌 실측(2026-09-10 위너_3003)

BODY_RE = re.compile(
    r"키\s*작|어깨|뱃살|배\s*나온|똥배|다리\s*(?:얇|짧|굵|길어)|허벅지|마른|통통|체형|하체|상체|골반|종아리|왜소|덩치|살집"
)
# 순서가 우선순위다. 첫 비트(훅) 나레이션에 처음 걸리는 카테고리를 쓴다.
CATEGORY_RULES = [
    ("가격", re.compile(r"\d[\d,]*\s*원|만\s*원|천\s*원|가격|가성비|할인|장당|세일|특가|얼마")),
    ("체형", BODY_RE),
    ("TPO", re.compile(r"출근|데이트|소개팅|개강|여행|주말|캠핑|한강|결혼식|면접|등교|외출|모임|휴가")),
    ("소재기능", re.compile(r"원단|밴딩|포켓|기장|신축|냉감|기모|스웨트|코듀로이|린넨|데님|두께|통풍|스판|방수")),
    ("비교", re.compile(r"\bvs\b|보다\s|일반\s*\S+는|다른\s*(?:브랜드|바지|옷)|차이")),
    ("금지경고", re.compile(r"하지\s*마|금지|절대|사지\s*마|입지\s*마")),
    ("감탄", re.compile(r"미쳤|대박|진짜\s*이뻐|역대급|찢었")),
    ("자문자답", re.compile(r"\?|냐고|나요|일까")),
]


def _first_narrations(script: dict, n: int = 2) -> str:
    beats = script.get("beats") or []
    return " ".join(str(b.get("narration") or "") for b in beats[:n])


def _target_text(script: dict) -> str:
    ctx = script.get("story_context") or {}
    axis = (((script.get("meta") or {}).get("benchmark_usage") or {}).get("three_axis_map") or {})
    return " ".join(str(x) for x in (ctx.get("target_customer", ""), axis.get("타겟설정", "")) if x)


def _norm_target(text: str) -> str:
    return re.sub(r"[\s,.\-·/()\[\]'\"]", "", text or "")


def same_target(a: str, b: str) -> bool:
    """정규화 후 동일하거나 최장 공통 부분이 TARGET_MIN_COMMON자 이상이면 같은 타겟."""
    a, b = _norm_target(a), _norm_target(b)
    if not a or not b:
        return False
    if a == b:
        return True
    m = difflib.SequenceMatcher(None, a, b, autojunk=False).find_longest_match(0, len(a), 0, len(b))
    return m.size >= TARGET_MIN_COMMON


def hook_category(text: str) -> str:
    for name, rx in CATEGORY_RULES:
        if rx.search(text or ""):
            return name
    return "기타"


def angle_of(script: dict) -> dict:
    """{"body": bool, "hook_category": str, "target": str} — 명시 angle 필드가 있으면 그것을 따른다."""
    explicit = script.get("angle")
    target = _target_text(script)[:60]
    if isinstance(explicit, dict) and explicit.get("hook_category"):
        cat = str(explicit["hook_category"])
        body = bool(explicit.get("body", cat == "체형"))
        return {"body": body, "hook_category": cat, "target": target}
    if isinstance(explicit, str) and explicit.strip():
        cat = explicit.strip()
        return {"body": cat == "체형", "hook_category": cat, "target": target}
    hook = _first_narrations(script, 1)
    body = bool(BODY_RE.search(_target_text(script)) or BODY_RE.search(hook))
    return {"body": body, "hook_category": hook_category(hook), "target": target}


# ── 인덱스 ────────────────────────────────────────────────
def _candidate_paths(video_root: str) -> list[str]:
    """_cta_index.json이 있으면 그 경로 목록(이미 video/ 전수 walk 결과)을 재사용, 없으면 직접 walk."""
    cta_index = Path(video_root) / CTA_INDEX_PATH.name
    if cta_index.exists():
        try:
            with open(cta_index, encoding="utf-8") as f:
                paths = [p for p in json.load(f) if os.path.isfile(p)]
            if paths:
                return paths
        except (json.JSONDecodeError, OSError):
            pass
    out = []
    for root, dirs, files in os.walk(video_root):
        dirs[:] = [d for d in dirs if d not in ("archive", "_tts_sample_khaki_series")]
        if "script.json" in files and os.path.basename(os.path.dirname(root)) == "reels":
            out.append(os.path.join(root, "script.json"))
    return out


ENTRY_VERSION = 2  # 분류/승인 판정 로직이 바뀌면 올린다 — 캐시된 항목을 전부 다시 계산하게


def _product_dir_of(script_path: str) -> str | None:
    """…/<product>/reels/<variant>/script.json → <product>"""
    variant_dir = os.path.dirname(script_path)
    reels_dir = os.path.dirname(variant_dir)
    if os.path.basename(reels_dir) != "reels":
        return None
    return os.path.dirname(reels_dir)


def _draft_marker(product_dir: str | None) -> tuple[str, str, float]:
    """(.draft_done의 spec_used 폴더(posix 상대경로), created_at 날짜, 마커 mtime). 없으면 ('', '', 0)."""
    if not product_dir:
        return "", "", 0.0
    marker = os.path.join(product_dir, ".draft_done")
    if not os.path.isfile(marker):
        return "", "", 0.0
    spec_dir, created = "", ""
    try:
        with open(marker, encoding="utf-8", errors="replace") as f:
            for line in f:
                if line.startswith("spec_used:"):
                    spec_dir = os.path.dirname(line.split(":", 1)[1].strip().replace("\\", "/"))
                elif line.startswith("created_at:"):
                    created = line.split(":", 1)[1].strip()[:10]
        return spec_dir, created, os.path.getmtime(marker)
    except OSError:
        return "", "", 0.0


def _entry_for(path: str, mtime: float) -> dict:
    product_dir = _product_dir_of(path)
    draft_dir, draft_date, draft_mtime = _draft_marker(product_dir)
    base = {"v": ENTRY_VERSION, "mtime": mtime, "draft_mtime": draft_mtime, "approved": False,
            "approved_at": "", "body": False, "hook_category": "기타", "target": ""}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return base
    variant_rel = os.path.relpath(os.path.dirname(path), product_dir).replace("\\", "/") if product_dir else ""
    drafted = bool(draft_dir) and draft_dir == variant_rel
    approval = data.get("script_approval") or {}
    status_ok = str(approval.get("status", "")).lower() == "approved"
    approved_at = str(approval.get("approved_at", "") or "")[:10] or (draft_date if drafted else "")
    if not approved_at:
        approved_at = _dt.date.fromtimestamp(mtime).isoformat()
    a = angle_of(data)
    base.update({"approved": drafted or status_ok, "drafted": drafted, "approved_at": approved_at,
                 "body": a["body"], "hook_category": a["hook_category"], "target": a["target"]})
    return base


def build_angle_index(video_root: str | None = None, index_path: str | None = None) -> dict:
    video_root = video_root or str(VIDEO_ROOT)
    index_path = index_path or str(ANGLE_INDEX_PATH)
    index = {}
    if os.path.exists(index_path):
        try:
            with open(index_path, encoding="utf-8") as f:
                index = json.load(f)
        except (json.JSONDecodeError, OSError):
            index = {}
    seen = set()
    for p in _candidate_paths(video_root):
        seen.add(p)
        mtime = os.path.getmtime(p)
        cached = index.get(p)
        if cached and cached.get("v") == ENTRY_VERSION and abs(cached.get("mtime", -1) - mtime) < 1e-6:
            _, _, draft_mtime = _draft_marker(_product_dir_of(p))
            if abs(cached.get("draft_mtime", 0.0) - draft_mtime) < 1e-6:
                continue
        index[p] = _entry_for(p, mtime)
    for p in list(index):
        if p not in seen:
            del index[p]
    try:
        with open(index_path, "w", encoding="utf-8") as f:
            json.dump(index, f, ensure_ascii=False, indent=1)
    except OSError:
        pass
    return index


_INDEX_CACHE: dict[tuple[str, str], dict] = {}


def _index(video_root: str | None, index_path: str | None) -> dict:
    key = (video_root or str(VIDEO_ROOT), index_path or str(ANGLE_INDEX_PATH))
    if key not in _INDEX_CACHE:
        _INDEX_CACHE[key] = build_angle_index(*key)
    return _INDEX_CACHE[key]


def recent_entries(index: dict, *, exclude_path: str | None = None, n: int = WINDOW - 1) -> list[tuple[str, dict]]:
    items = [(p, e) for p, e in index.items() if e.get("approved") and p != exclude_path]
    items.sort(key=lambda pe: (pe[1].get("approved_at", ""), pe[1].get("mtime", 0)), reverse=True)
    return items[:n]


def _label(path: str, video_root: str) -> str:
    try:
        rel = os.path.relpath(path, video_root)
    except ValueError:
        rel = path
    parts = rel.replace("\\", "/").split("/")
    return parts[-4] if len(parts) >= 4 else rel  # 상품 폴더명


# ── 게이트 ────────────────────────────────────────────────
def check_angle_diversity(script: dict, errors: list, warnings: list, *, strict: bool,
                          video_root: str | None = None, index_path: str | None = None,
                          current_path: str | None = None):
    cur = angle_of(script)
    root = video_root or str(VIDEO_ROOT)
    recent = recent_entries(_index(video_root, index_path), exclude_path=current_path, n=WINDOW - 1)

    body_n = sum(1 for _, e in recent if e.get("body")) + (1 if cur["body"] else 0)
    if cur["body"] and body_n > BODY_MAX:
        names = ", ".join(f"{_label(p, root)}({'체형' if e.get('body') else e.get('hook_category')})" for p, e in recent)
        msg = (f"[앵글수렴] 현재 포함 최근 {len(recent) + 1}편 중 체형 앵글 {body_n}편 — "
               f"현재 대본을 체형 외 앵글(가격/TPO/소재기능/비교/금지경고)로 재설계. 최근: {names}")
        (errors if strict else warnings).append(msg)

    cats = {e.get("hook_category", "기타") for _, e in recent} | {cur["hook_category"]}
    if len(recent) >= 2 and len(cats) < MIN_CATEGORIES:
        warnings.append(f"[훅카테고리편중] 최근 {len(recent) + 1}편의 훅 카테고리가 {sorted(cats)} — "
                        f"{MIN_CATEGORIES}종 미만. 다른 카테고리 훅 후보를 같이 제시할 것")

    recent_t = recent_entries(_index(video_root, index_path), exclude_path=current_path, n=TARGET_WINDOW - 1)
    dups = [(p, e) for p, e in recent_t if same_target(cur["target"], e.get("target", ""))]
    if dups:
        names = ", ".join(f"{_label(p, root)}('{e.get('target', '')[:18]}…')" for p, e in dups)
        if len(dups) >= TARGET_DUP_FAIL:
            msg = (f"[타겟반복] 현재 타겟 '{cur['target'][:30]}'이 최근 {len(recent_t)}편 중 {len(dups)}편과 같은 문구 — "
                   f"상황·의심이 다른 타겟으로 다시 잡을 것. 겹침: {names}")
            (errors if strict else warnings).append(msg)
        else:
            warnings.append(f"[타겟유사] 최근 편과 타겟 문구 겹침 — 의도한 시리즈가 아니면 다른 상황으로. 겹침: {names}")


def run_angle_gate(script: dict, *, script_path: str | None, errors: list, warnings: list,
                   video_root: str | None = None, index_path: str | None = None):
    """validate_reels.validate()가 호출. 구분(GATE_START 이전 승인)은 전부 WARN."""
    if not script:
        return
    strict = uses_consistency_gate(script, script_path)
    check_angle_diversity(script, errors, warnings, strict=strict, video_root=video_root,
                          index_path=index_path, current_path=script_path)


# ── CLI ──────────────────────────────────────────────────
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="최근 승인 대본의 앵글 분포를 표로 보여준다")
    ap.add_argument("--recent", type=int, default=10)
    ap.add_argument("--video-root", default=None)
    args = ap.parse_args(argv)
    root = args.video_root or str(VIDEO_ROOT)
    index = build_angle_index(root, None if not args.video_root else str(Path(root) / "_angle_index.json"))
    rows = recent_entries(index, n=args.recent)
    body_n = sum(1 for _, e in rows if e["body"])
    cats = {}
    for _, e in rows:
        cats[e["hook_category"]] = cats.get(e["hook_category"], 0) + 1
    total_shipped = sum(1 for e in index.values() if e.get("approved"))
    print(f"인덱스 {len(index)}편 중 실제 나간 것(드래프트/승인) {total_shipped}편 — "
          f"최근 {len(rows)}편: 체형 앵글 {body_n}편 / 훅 카테고리 분포 {cats}")
    for p, e in rows:
        how = "draft" if e.get("drafted") else "appr "
        print(f"  {e['approved_at']}  {how}  {'체형' if e['body'] else '    '}  {e['hook_category']:<5}  {_label(p, root)}  | {e['target'][:40]}")
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
