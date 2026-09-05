"""
generate_capcut.py — CapCut 드래프트 자동 생성 (pycapcut)
사용: python generate_capcut.py {상품명}
     python generate_capcut.py {상품명} --preview
     python generate_capcut.py {상품명} --generate

이관: 컨텐츠자동화 → 비디오/video-use/harness/ (2026-06-13)
경로: VIDEO_ROOT = 비디오/video/ 기준으로 상품 검색
"""

import sys, json, os, re, tempfile, subprocess, shutil, copy, math, importlib, difflib, time
import pycapcut as cc
from pathlib import Path
from capcut_feature_gate import analyze_spec, write_report

_BANNED_ASSET_RE = re.compile(r"hstack|vstack|_vs_|side.?by.?side|split|비교합성|분할", re.IGNORECASE)

def _resolve_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    try:
        imageio_ffmpeg = importlib.import_module("imageio_ffmpeg")
        get_ffmpeg_exe = getattr(imageio_ffmpeg, "get_ffmpeg_exe", None)
        if callable(get_ffmpeg_exe):
            return str(get_ffmpeg_exe())
    except ImportError:
        pass
    capcut_ff = "C:/Users/USER/AppData/Local/CapCut/Apps/5.5.0.2028/ffmpeg.exe"
    if os.path.exists(capcut_ff):
        return capcut_ff
    return "ffmpeg"

FFMPEG = _resolve_ffmpeg()
HARNESS_DIR = Path(__file__).absolute().parent
VIDEO_ROOT = HARNESS_DIR.parent.parent / "video"

# --variant: reels/ 하위 변형 폴더(blute/dohu/baido/...) 지원.
# gen_qwen3_tts.py는 이미 --variant를 받는데 이 파일은 reels/ 직속만 봐서
# 한 상품에 포맷별 대본이 여러 개일 때 spec/TTS 경로가 어긋났다 (2026-08-19 제이엠엘에서 발견).
# 빈 값이면 기존 동작과 100% 동일.
def _parse_variant(argv):
    for i, a in enumerate(argv):
        if a == "--variant" and i + 1 < len(argv):
            return argv[i + 1].strip("/\\")
        if a.startswith("--variant="):
            return a.split("=", 1)[1].strip("/\\")
    return ""

VARIANT = _parse_variant(sys.argv)


def _spec_subs():
    """capcut_spec.json 탐색 순서. VARIANT가 있으면 reels/<variant>가 최우선."""
    base = ["reels", "meta", "edit", ""]
    return ([os.path.join("reels", VARIANT)] + base) if VARIANT else base
SANGPE_ROOT = Path(r"C:\nomal\자동화\상페자동화")
CAPCUT_DIR = "C:/Users/user/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"


def draft_name_for(product: str, spec: dict) -> str:
    """CapCut 드래프트 폴더명. 한 상품에 여러 variant(v1/w1/w2...)가 있으면
    variant별로 별도 폴더를 써야 서로 덮어쓰지 않는다 (product명만 쓰면
    나중에 생성한 variant가 이전 variant의 드래프트를 rmtree로 지워버림)."""
    safe = product.replace("/", "_")
    variant = spec.get("script_approval", {}).get("selected_variant")
    return f"{safe}_{variant}" if variant else safe


def write_draft_identity(draft_name: str) -> None:
    """드래프트 메타 정보를 채운다.

    2026-09-05: --force-overwrite로 재생성한 드래프트 3건(GM5911/웨인/인디오301)이
    CapCut에서 안 열리는 사고 발생. 원인: pycapcut의 create_draft()가 남긴
    draft_meta_info.json에 tm_draft_create/tm_draft_modified/draft_root_path가
    비어있었다(신규 생성 시에는 채워지는데 rmtree 후 재생성 시 누락되는 경로 확인됨).
    이 값이 없으면 CapCut이 드래프트를 열지 못한다. 매번 강제로 채워 재발을 막는다."""
    draft_dir = Path(CAPCUT_DIR) / draft_name
    meta_path = draft_dir / "draft_meta_info.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["draft_name"] = draft_name
    meta["draft_fold_path"] = str(draft_dir)
    if not meta.get("draft_root_path"):
        meta["draft_root_path"] = CAPCUT_DIR
    now_us = int(time.time() * 1_000_000)
    if not meta.get("tm_draft_create"):
        meta["tm_draft_create"] = now_us
    meta["tm_draft_modified"] = now_us
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=4), encoding="utf-8")

MOTION_PRESETS = {
    "snap_zoom":     {"scale": (1.00, 1.15), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": True,  "snap_sec": 0.15},
    "zoom_in":       {"scale": (1.00, 1.10), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": True,  "snap_sec": 0.30},
    "zoom_out":      {"scale": (1.10, 1.00), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    "slow_zoom_in":  {"scale": (1.00, 1.10), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    "slow_zoom_out": {"scale": (1.05, 1.00), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    "pan_right":     {"scale": (1.10, 1.10), "pos_x": (-0.06, 0.06), "pos_y": (0.00, 0.00), "snap": False},
    "scan_left":     {"scale": (1.10, 1.10), "pos_x": (0.06, -0.06), "pos_y": (0.00, 0.00), "snap": False},
    "scan_right":    {"scale": (1.10, 1.10), "pos_x": (-0.06, 0.06), "pos_y": (0.00, 0.00), "snap": False},
    "static":        {"scale": (1.00, 1.00), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    # capcut_spec M-코드 매핑
    "M3_snap_zoom":       {"scale": (1.00, 1.15), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": True,  "snap_sec": 0.15},
    "M1_slow_zoom_in":    {"scale": (1.00, 1.10), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    "M2_slow_zoom_out":   {"scale": (1.10, 1.00), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
    "M4_pan_lr":          {"scale": (1.10, 1.10), "pos_x": (-0.06, 0.06), "pos_y": (0.00, 0.00), "snap": False},
    "M5_pan_bt":          {"scale": (1.10, 1.10), "pos_x": (0.00, 0.00), "pos_y": (0.06, -0.06), "snap": False},
    "M5_pan_tb":          {"scale": (1.10, 1.10), "pos_x": (0.00, 0.00), "pos_y": (-0.06, 0.06), "snap": False},
    "M6_ken_burns_TR":    {"scale": (1.00, 1.08), "pos_x": (-0.04, 0.04), "pos_y": (0.04, -0.04), "snap": False},
    "M6_ken_burns_TL":    {"scale": (1.00, 1.08), "pos_x": (0.04, -0.04), "pos_y": (0.04, -0.04), "snap": False},
    "M6_ken_burns_BR":    {"scale": (1.00, 1.08), "pos_x": (-0.04, 0.04), "pos_y": (-0.04, 0.04), "snap": False},
    "M6_ken_burns_BL":    {"scale": (1.00, 1.08), "pos_x": (0.04, -0.04), "pos_y": (-0.04, 0.04), "snap": False},
    "M6_ken_burns_Center":{"scale": (1.00, 1.12), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False},
}
DEFAULT_MOTION = {"scale": (1.00, 1.00), "pos_x": (0.00, 0.00), "pos_y": (0.00, 0.00), "snap": False}

MAX_CLIP_SEC = 2.2
MOTION_CYCLE = ["slow_zoom_in", "slow_zoom_out", "snap_zoom", "zoom_in", "zoom_out"]
SAFE_IMAGE_BLOCKLIST = ["비교이미지", "비교", "너무", "사이즈", "size", "thumbs"]


def is_safe_pool_image(fname: str) -> bool:
    fl = fname.lower()
    if not fl.endswith((".png", ".jpg", ".jpeg")):
        return False
    for blocked in SAFE_IMAGE_BLOCKLIST:
        if blocked.lower() in fl:
            return False
    return True


def build_unused_pool(clips: list[dict]) -> list[str]:
    used = set()
    base_dir = None
    for c in clips:
        img = c.get("image", "")
        if img:
            used.add(os.path.basename(img))
            if base_dir is None:
                base_dir = os.path.dirname(img)
    if not base_dir or not os.path.isdir(base_dir):
        return []
    pool = []
    for fname in sorted(os.listdir(base_dir)):
        if fname in used:
            continue
        if not is_safe_pool_image(fname):
            continue
        pool.append(os.path.join(base_dir, fname))
    return pool


def auto_split_clips(
    clips: list[dict],
    max_clip_sec: float = MAX_CLIP_SEC,
    split_target_sec: float = 1.8,
) -> list[dict]:
    unused_pool = build_unused_pool(clips)
    if unused_pool:
        print(f"  [풀] 미사용 이미지 {len(unused_pool)}장 사용 가능: {[os.path.basename(p) for p in unused_pool]}")
    result = []
    new_id = 1
    for clip in clips:
        dur = clip["duration"]
        if dur <= max_clip_sec:
            clip["id"] = new_id
            result.append(clip)
            new_id += 1
            continue

        n_splits = max(2, math.ceil(dur / split_target_sec))
        sub_dur = round(dur / n_splits, 2)
        texts = clip.get("texts", [])
        base_motion = clip.get("motion", "slow_zoom_in")

        for i in range(n_splits):
            sub = dict(clip)
            sub["id"] = new_id
            sub["duration"] = sub_dur

            if i == 0:
                sub["motion"] = base_motion
            else:
                sub.pop("crop_y", None)
                sub.pop("crop_scale", None)
                sub["motion"] = MOTION_CYCLE[i % len(MOTION_CYCLE)]
                if unused_pool:
                    new_img = unused_pool.pop(0)
                    sub["image"] = new_img
                    print(f"    └ 분할컷 {i+1}: 새 이미지 → {os.path.basename(new_img)} / motion={sub['motion']}")
                else:
                    print(f"    └ 분할컷 {i+1}: 같은 이미지 (원본) / motion={sub['motion']}")

            if i < len(texts):
                t = dict(texts[i])
                t["start_offset"] = 0.0
                t["end_offset"] = sub_dur
                t["duration"] = sub_dur
                sub["texts"] = [t]
            elif texts:
                t = dict(texts[-1])
                t["start_offset"] = 0.0
                t["end_offset"] = sub_dur
                t["duration"] = sub_dur
                sub["texts"] = [t]
            else:
                sub["texts"] = []

            result.append(sub)
            new_id += 1

        print(f"  [자동분할] clip {clip['id']} ({dur:.1f}s) → {n_splits}컷 × {sub_dur:.1f}s")

    return result


def _find_product_dir(product: str) -> Path | None:
    """비디오/video/ 하위에서 상품 폴더 검색."""
    direct = VIDEO_ROOT / product
    if direct.is_dir():
        return direct
    archive = VIDEO_ROOT / "archive" / product
    if archive.is_dir():
        return archive
    return None


def _find_capcut_spec(product_dir: Path) -> Path | None:
    """상품 폴더 안에서 capcut_spec.json 검색. reels/ → edit/v*/ 순."""
    if VARIANT:
        v = product_dir / "reels" / VARIANT / "capcut_spec.json"
        if v.exists():
            return v
    reels = product_dir / "reels" / "capcut_spec.json"
    if reels.exists():
        return reels
    edit_dir = product_dir / "edit"
    if edit_dir.is_dir():
        versions = sorted(edit_dir.iterdir(), reverse=True)
        for v in versions:
            candidate = v / "capcut_spec.json"
            if candidate.exists():
                return candidate
    return None


def load_spec(product: str) -> dict:
    product_dir = _find_product_dir(product)
    if not product_dir:
        print(f"[ERROR] 상품 폴더 없음: {product}")
        print(f"  검색 경로: {VIDEO_ROOT}")
        sys.exit(1)

    spec_path = _find_capcut_spec(product_dir)
    if not spec_path:
        print(f"[ERROR] capcut_spec.json 없음: {product}")
        print(f"  검색 폴더: {product_dir}")
        sys.exit(1)

    with open(spec_path, "r", encoding="utf-8") as f:
        spec = json.load(f)

    spec["_spec_path"] = str(spec_path)
    spec["_product_dir"] = str(product_dir)

    # 분할이미지(hstack/vstack/vs) 차단 — 릴스에 절대 사용 금지
    blocked = []
    for clip in spec.get("clips", []):
        img = clip.get("image", "")
        basename = os.path.basename(img)
        if _BANNED_ASSET_RE.search(basename):
            blocked.append(f"  clip {clip.get('id','?')}: {basename}")
    if blocked:
        print("[BLOCKED] 분할이미지(hstack/vstack/vs) 에셋 감지 — 단일 피사체로 교체 필수:")
        for b in blocked:
            print(b)
        sys.exit(1)

    # narration 배열 → 클립 texts 자동 변환 (블루트 spec 호환)
    narration_list = spec.get("narration", [])
    if narration_list and isinstance(narration_list, list):
        nar_map = {}
        for nar in narration_list:
            nid = nar.get("id", "")
            if nid:
                nar_map[nid] = nar
        clips_list = spec.get("clips", [])
        first_clip_for_nar = {}
        for ci, clip in enumerate(clips_list):
            nid = clip.get("narration_id", "")
            if nid and nid not in first_clip_for_nar:
                first_clip_for_nar[nid] = ci
        injected = 0
        aligned = 0
        fallback_ids = []
        word_timings = _load_word_timings(spec.get("_product_dir", ""))
        for nid, ci in first_clip_for_nar.items():
            clip = clips_list[ci]
            if clip.get("texts"):
                continue
            nar = nar_map.get(nid)
            if not nar:
                continue
            chunks = nar.get("subtitle_chunks", [])
            subtitle = nar.get("subtitle", "")
            if not chunks and subtitle:
                chunks = [subtitle]
            if not chunks:
                continue
            clip_dur = clip.get("duration", 1.0)
            nar_clips = [j for j, c in enumerate(clips_list) if c.get("narration_id") == nid]
            total_slot_dur = sum(clips_list[j].get("duration", 0) for j in nar_clips)

            # 1순위: Whisper 단어 타임코드로 실제 발화 시점에 정렬.
            # 2순위(폴백): 균등분할 — 단어 타임코드가 없거나 정렬이 신뢰도 미달일 때만.
            spans = align_chunks_to_words(chunks, word_timings.get(nid, []), total_slot_dur)
            if spans:
                aligned += 1
            else:
                chunk_dur = total_slot_dur / len(chunks) if chunks else clip_dur
                spans = [(i * chunk_dur, (i + 1) * chunk_dur) for i in range(len(chunks))]
                fallback_ids.append(nid)

            texts = []
            keywords = {kw["word"]: kw.get("color", "#FFFFFF") for kw in nar.get("subtitle_keywords", [])}
            for chunk_text, (st, en) in zip(chunks, spans):
                chunk_color = "#FFFFFF"
                for kw_word, kw_color in keywords.items():
                    if kw_word in chunk_text:
                        chunk_color = kw_color
                        break
                texts.append({
                    "content": chunk_text,
                    "start_offset": st,
                    "end_offset": en,
                    "duration": round(en - st, 3),
                    "position_y": nar.get("subtitle_position_y", 0.0),
                    "color": chunk_color,
                })
            clip["texts"] = texts
            injected += 1
        if injected:
            mode = f"단어싱크 {aligned}/{injected}"
            if fallback_ids:
                mode += f", 균등분할 폴백 {fallback_ids}"
            print(f"  [자막 변환] narration → texts {injected}개 주입 ({mode})")
            if fallback_ids and not word_timings:
                print("  [자막싱크] tts/word_timings.json 없음 — TTS를 gen_qwen3_tts.py로 재생성하면 단어 단위로 붙는다")

    spec["_text_clips"] = copy.deepcopy(spec.get("clips", []))

    if spec.get("config", {}).get("auto_split", True):
        original_count = len(spec.get("clips", []))
        cfg = spec.get("config", {})
        max_clip_sec = float(cfg.get("max_clip_sec", MAX_CLIP_SEC))
        split_target_sec = float(cfg.get("split_target_sec", min(1.8, max_clip_sec)))
        spec["clips"] = auto_split_clips(
            spec.get("clips", []),
            max_clip_sec=max_clip_sec,
            split_target_sec=split_target_sec,
        )
        new_count = len(spec["clips"])
        if new_count > original_count:
            print(f"  [이미지 다양성] {original_count}컷 → {new_count}컷 (자동 분할)")
    else:
        print(f"  [auto_split OFF] {len(spec.get('clips', []))}컷 그대로 (자막↔TTS 정확 싱크)")
    return spec


_SUB_NORM_RE = re.compile(r"[\s,.\?!~…·\-'\"]+")


def _load_word_timings(product_dir: str) -> dict:
    """tts/word_timings.json 로드 (gen_qwen3_tts.py가 TTS 생성 시 자동 저장).
    없으면 {} — 호출부가 균등분할로 폴백한다."""
    for sub in _spec_subs():
        cand = os.path.join(product_dir, sub, "tts", "word_timings.json") if sub \
            else os.path.join(product_dir, "tts", "word_timings.json")
        if os.path.isfile(cand):
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"  [자막싱크] word_timings.json 읽기 실패({e}) — 균등분할로 폴백")
                return {}
    return {}


def align_chunks_to_words(chunks: list, words: list, total_dur: float):
    """자막 청크를 Whisper 단어 타임코드에 정렬해 [(start, end), ...] 반환. 실패하면 None.

    왜 필요한가: 기존에는 chunk_dur = 구간길이/청크수 로 균등분할해서, 실제 발화 속도와
    자막이 어긋났다(사용자가 매 편 수동 보정하던 지점, 2026-08-19).

    방식: 전사 단어를 문자 단위로 펼쳐 각 문자에 시간을 보간한 뒤, 자막 문자열과
    difflib로 정렬한다. Whisper 표기가 대본과 달라도(숏 기본 롱→쇼키본롱,
    이만구천팔백원→29,800원) 문자 정렬이라 앵커가 잡히고, 못 잡은 구간은 앞뒤로 보간한다.
    """
    if not words or not chunks:
        return None

    def norm(s: str) -> str:
        return _SUB_NORM_RE.sub("", str(s))

    # 전사: 문자별 (start, end)
    w_chars, w_times = [], []
    for wd in words:
        tok = norm(wd.get("w", ""))
        if not tok:
            continue
        try:
            s, e = float(wd["s"]), float(wd["e"])
        except (KeyError, TypeError, ValueError):
            continue
        if e < s:
            s, e = e, s
        n = len(tok)
        for i, ch in enumerate(tok):
            w_chars.append(ch)
            w_times.append((s + (e - s) * i / n, s + (e - s) * (i + 1) / n))
    if not w_chars:
        return None

    # 자막: 문자열 + 청크 경계
    s_chars, bounds = [], []
    for c in chunks:
        s_chars.extend(norm(c))
        bounds.append(len(s_chars))
    if not s_chars:
        return None

    sm = difflib.SequenceMatcher(None, s_chars, w_chars, autojunk=False)
    s2w = {}
    for a, b, size in sm.get_matching_blocks():
        for k in range(size):
            s2w[a + k] = b + k
    # 앵커가 절반도 안 잡히면 정렬을 신뢰하지 않는다
    if len(s2w) < len(s_chars) * 0.5:
        return None

    n = len(s_chars)

    def boundary_time(idx):
        """자막 문자열의 idx 위치가 발화되는 시각.

        매칭이 없는 문자는 건너뛰지 않고 앞뒤 앵커 사이를 문자 수에 비례해 보간한다.
        건너뛰면 청크 첫 글자가 ASR과 다를 때(숏 기본 롱→쇼키본롱, 뒷밴딩→뒤밴딩,
        5XL→OXL) 경계가 최대 0.24s 밀린다."""
        if idx <= 0:
            return 0.0
        if idx >= n:
            return total_dur
        if idx in s2w:
            return w_times[s2w[idx]][0]
        prev = next((k for k in range(idx - 1, -1, -1) if k in s2w), None)
        nxt = next((k for k in range(idx + 1, n) if k in s2w), None)
        if prev is None and nxt is None:
            return None
        i0, t0 = (prev, w_times[s2w[prev]][1]) if prev is not None else (-1, 0.0)
        i1, t1 = (nxt, w_times[s2w[nxt]][0]) if nxt is not None else (n, total_dur)
        span = i1 - i0 - 1
        if span <= 0:
            return t0
        return t0 + (t1 - t0) * ((idx - i0 - 1) / span)

    starts = [boundary_time(0)] + [boundary_time(b) for b in bounds[:-1]]
    spans = []
    for i, st in enumerate(starts):
        en = starts[i + 1] if i + 1 < len(starts) else total_dur
        spans.append([st, en])
    spans[0][0] = 0.0
    spans[-1][1] = total_dur

    if any(s is None or e is None for s, e in spans):
        return None

    # 최소 표시시간 보장.
    # 자막이 나레이션보다 잘게 쪼개져 있으면(청크 2개가 전사 단어 1개에 매핑) 경계가 한 점으로
    # 몰려 길이 0짜리가 생긴다. 예전에는 이때 전체를 폴백시켰는데, 매칭률 90%대인 정렬까지
    # 통째로 버려졌다(제이엠엘 4개 변형). 이제 그 자막만 최소 길이로 밀어서 살린다.
    MIN = 0.15
    n = len(spans)
    for i in range(n):                       # 앞 → 뒤
        if spans[i][1] - spans[i][0] < MIN:
            spans[i][1] = spans[i][0] + MIN
        if i + 1 < n and spans[i + 1][0] < spans[i][1]:
            spans[i + 1][0] = spans[i][1]
    if spans[-1][1] > total_dur:             # 끝을 넘겼으면 뒤 → 앞으로 되민다
        spans[-1][1] = total_dur
        for i in range(n - 1, 0, -1):
            if spans[i][1] - spans[i][0] < MIN:
                spans[i][0] = spans[i][1] - MIN
            if spans[i - 1][1] > spans[i][0]:
                spans[i - 1][1] = spans[i][0]

    # 단조 증가 + 구간 내. 여기서도 깨지면(자막이 나레이션과 근본적으로 다름) 폴백.
    prev = -1e-9
    for s, e in spans:
        if not (prev - 1e-6 <= s < e <= total_dur + 1e-6):
            return None
        prev = e
    spans[0][0] = max(0.0, spans[0][0])
    spans[-1][1] = total_dur
    return [(round(s, 3), round(e, 3)) for s, e in spans]


def build_video_filter(crop: str = "full",
                       crop_y: float | None = None,
                       crop_scale: float | None = None) -> str:
    if crop_y is not None:
        sc = crop_scale or 2.5
        sz = int(1920 * sc)
        crop_top = max(0, int(sz * crop_y - 960))
        crop_top = min(crop_top, sz - 1920)
        vf = (f"scale={sz}:{sz}:force_original_aspect_ratio=increase,"
              f"crop=1080:1920:(iw-1080)/2:{crop_top},"
              f"setsar=1")
        return vf
    if crop in ("contain", "fit"):
        return ("scale=1080:1920:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                "setsar=1")
    return ("scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920:(iw-1080)/2:(ih-1920)/2,"
            "setsar=1")


def image_to_mp4(img: str, out: str, duration: float, crop: str = "full",
                  crop_y: float | None = None, crop_scale: float | None = None):
    vf = build_video_filter(crop, crop_y, crop_scale)
    is_video = img.lower().endswith((".mp4", ".mov", ".avi", ".mkv", ".webm", ".gif"))
    if is_video:
        # 목표 duration으로 -t 잘라서 굽지 않는다 — 원본 전체 길이를 살려서 크롭필터만 입힌다.
        # 이래야 CapCut에서 클립 가장자리를 드래그해 늘리거나 더 줄일 때 원본의 나머지 프레임에
        # 실제로 접근 가능하다(트림/줄이기). -t로 잘라 구우면 그 이후 프레임은 영구 소실되어
        # 늘려도 마지막 프레임 freeze만 된다 (사용자 지시로 수정, 2026-07-21).
        vf_v = vf + ",tpad=stop_mode=clone:stop_duration=10"  # 원본이 duration보다 짧을 때만 끝프레임 freeze로 보충
        cmd = [
            FFMPEG, "-y", "-i", img,
            "-vf", vf_v,
            "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-an", out,
        ]
    else:
        cmd = [
            FFMPEG, "-y", "-loop", "1", "-i", img,
            "-t", str(round(duration + 0.1, 3)),
            "-vf", vf,
            "-r", "30", "-c:v", "libx264", "-pix_fmt", "yuv420p", out,
        ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode('utf-8', 'replace')
        safe_err = err.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
        safe_img = img.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace')
        print(f"[ERROR] ffmpeg fail ({crop}): {safe_img}")
        print(safe_err[-2000:])
        sys.exit(1)


def apply_motion(seg: cc.VideoSegment, section: str, dur_us: int, motion: str = ""):
    if motion in ("static", "none"):
        return  # 키프레임 없음 — 정지 (사장님 직접대본 드래프트: 효과는 CapCut에서 직접)
    cfg = MOTION_PRESETS.get(motion, DEFAULT_MOTION)
    s0, s1 = cfg["scale"]
    x0, x1 = cfg["pos_x"]
    y0, y1 = cfg["pos_y"]
    is_snap = cfg.get("snap", False)
    snap_sec = cfg.get("snap_sec", 0.15)

    if is_snap:
        snap_us = int(snap_sec * 1_000_000)
        snap_us = min(snap_us, dur_us)
        seg.add_keyframe(cc.KeyframeProperty.uniform_scale, 0,       s0)
        seg.add_keyframe(cc.KeyframeProperty.uniform_scale, snap_us, s1)
        seg.add_keyframe(cc.KeyframeProperty.uniform_scale, dur_us,  s1)
    else:
        seg.add_keyframe(cc.KeyframeProperty.uniform_scale, 0,      s0)
        seg.add_keyframe(cc.KeyframeProperty.uniform_scale, dur_us, s1)

    if x0 != x1:
        seg.add_keyframe(cc.KeyframeProperty.position_x, 0,      x0)
        seg.add_keyframe(cc.KeyframeProperty.position_x, dur_us, x1)
    if y0 != y1:
        seg.add_keyframe(cc.KeyframeProperty.position_y, 0,      y0)
        seg.add_keyframe(cc.KeyframeProperty.position_y, dur_us, y1)


def split_subtitle(text: str) -> list[str]:
    return [text]


def _hex_to_rgb_float(hex_color: str) -> tuple[float, float, float]:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) != 6:
        return (1.0, 1.0, 1.0)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return (1.0, 1.0, 1.0)


def make_text_seg(
    content: str,
    clip_start_us: int,
    window_start_offset: float,
    window_end_offset: float,
    position_y: float = 0.0,
    color_hex: str = "#FFFFFF",
) -> cc.TextSegment:
    style = cc.TextStyle(
        size=13.0,
        bold=True,
        color=_hex_to_rgb_float(color_hex),
        align=1,
        max_line_width=0.80,
    )
    bg = cc.TextBackground(
        color=(0, 0, 0),
        alpha=0.55,
        round_radius=8,
    )
    border = cc.TextBorder(
        color=(0, 0, 0),
        alpha=0.6,
        width=0.04,
    )
    clip_s = cc.ClipSettings(transform_x=0.0, transform_y=0.0)

    t_start = clip_start_us + int(window_start_offset * 1_000_000)
    t_end   = clip_start_us + int(window_end_offset   * 1_000_000)
    return cc.TextSegment(
        content, cc.Timerange(t_start, t_end - t_start),
        style=style, clip_settings=clip_s,
        background=bg, border=border,
    )


TRANSITION_MAP = {
    "hard_cut": None,
    "zoom":     cc.TransitionType.White_Flash,
    "fade":     cc.TransitionType.Flash,
    "glitch":   cc.TransitionType.故障,
    "flash_white": cc.TransitionType.闪白,
    "flash_black": cc.TransitionType.闪黑,
    "dissolve": cc.TransitionType.叠化,
    "strobe":   cc.TransitionType.频闪,
    "bounce":   cc.TransitionType.弹跳,
    "slide_right": cc.TransitionType.向右,
    "color_glitch": cc.TransitionType.彩色故障,
}

SECTION_EFFECT_MAP = {
    "HOOK":  [cc.VideoSceneEffectType.RGB_Shake],
    "PAIN":  [cc.VideoSceneEffectType.色差],
    "USP":   [cc.VideoSceneEffectType.变焦推镜, cc.VideoSceneEffectType.电影感],
    "HERO":  [cc.VideoSceneEffectType.胶片漏光, cc.VideoSceneEffectType.电影感],
    "PUNCH": [cc.VideoSceneEffectType.震动],
    "PRICE": [cc.VideoSceneEffectType._3次推近],
    "CTA":   [cc.VideoSceneEffectType.发光],
}

VIDEO_BASE = Path(__file__).absolute().parent.parent.parent
SFX_MAP = {
    "bass_drop": VIDEO_BASE / "벤치마크" / "효과음프리셋" / "Boom.mp3",
    "buzz_error": VIDEO_BASE / "hyperframes" / "skills" / "website-to-hyperframes" / "assets" / "sfx" / "error.mp3",
    "ding": VIDEO_BASE / "효과음_리소스" / "강조효과음" / "02_small_ding.mp3",
    "whoosh": VIDEO_BASE / "효과음_리소스" / "전환효과음" / "01_whoosh_basic.mp3",
    "sparkle": VIDEO_BASE / "효과음_리소스" / "강조효과음" / "06_sparkle.mp3",
    "pop": VIDEO_BASE / "효과음_리소스" / "강조효과음" / "04_bloop.mp3",
    "chime": VIDEO_BASE / "효과음_리소스" / "강조효과음" / "03_magic_chime.mp3",
    "camera_shutter": VIDEO_BASE / "벤치마크" / "효과음프리셋" / "camera_shutter.mp3",
    "woosh_short": VIDEO_BASE / "효과음_리소스" / "전환효과음" / "08_woosh_short.mp3",
    "notification": VIDEO_BASE / "hyperframes" / "skills" / "website-to-hyperframes" / "assets" / "sfx" / "notification.mp3",
}


def postprocess_draft(draft_json_path: str, spec: dict):
    with open(draft_json_path, "r", encoding="utf-8") as f:
        draft = json.load(f)

    # --- 1. 텍스트: 그림자 + 폰트크기 ---
    texts = draft.get("materials", {}).get("texts", [])
    for mat in texts:
        mat["has_shadow"] = True
        mat["shadow_alpha"] = 0.8
        mat["shadow_angle"] = -45.0
        mat["shadow_color"] = "#000000"
        mat["shadow_distance"] = 8.0
        mat["shadow_point"] = {"x": 0.636, "y": -0.636}
        mat["shadow_smoothing"] = 0.45
        flag = mat.get("check_flag", 7)
        mat["check_flag"] = (flag | 32) & ~8
        content = json.loads(mat.get("content", "{}"))
        for st in content.get("styles", []):
            st["strokes"] = []
            st["size"] = 13.0
        mat["content"] = json.dumps(content, ensure_ascii=False)
    print(f"  텍스트: 그림자+크기13 적용 ({len(texts)}개)")

    # --- 2. 오디오 볼륨: BGM=0.15, SFX=spec별, TTS=1.0 ---
    audio_map = {a.get("id", ""): a for a in draft.get("materials", {}).get("audios", [])}
    sfx_vol_map = {}
    for entry in spec.get("sfx", []):
        sfx_vol_map[entry.get("sfx", "")] = entry.get("volume", 0.3)

    vol_fixed = 0
    for tr in draft.get("tracks", []):
        if tr.get("type") != "audio":
            continue
        for seg in tr.get("segments", []):
            mat_id = seg.get("material_id", "")
            mat = audio_map.get(mat_id, {})
            path = mat.get("path", "")
            fname = os.path.basename(path).lower()

            if "bgm" in fname:
                seg["volume"] = 0.15
                vol_fixed += 1
            elif any(sfx_name in fname for sfx_name in
                     ["boom", "error", "ding", "whoosh", "sparkle",
                      "bloop", "chime", "camera_shutter", "woosh"]):
                for sfx_key, sfx_path in SFX_MAP.items():
                    if sfx_path.name.lower() == os.path.basename(path).lower():
                        seg["volume"] = sfx_vol_map.get(sfx_key, 0.3)
                        vol_fixed += 1
                        break
                else:
                    seg["volume"] = 0.3
                    vol_fixed += 1
    print(f"  볼륨: {vol_fixed}개 세그먼트 조정 (BGM=0.15, SFX=spec)")

    with open(draft_json_path, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    print(f"  포스트프로세싱 완료")


def resolve_tts_path(tts_file: str, product_dir: str) -> str:
    if not tts_file:
        return ""
    if os.path.isabs(tts_file) and os.path.exists(tts_file):
        return tts_file
    candidate = os.path.join(product_dir, tts_file)
    if os.path.exists(candidate):
        return candidate
    return tts_file


def resolve_media_path(media_file: str, product_dir: str) -> str:
    if not media_file:
        return ""
    if os.path.isabs(media_file) and os.path.exists(media_file):
        return media_file
    candidate = os.path.join(product_dir, media_file)
    if os.path.exists(candidate):
        return candidate
    return media_file


def crop_to_jpg(img: str, out: str, crop: str = "full",
                crop_y: float | None = None, crop_scale: float | None = None):
    vf = build_video_filter(crop, crop_y, crop_scale)
    cmd = [FFMPEG, "-y", "-i", img, "-vf", vf, "-frames:v", "1", out]
    subprocess.run(cmd, capture_output=True)


def preview(product: str, spec: dict):
    clips = spec["clips"]
    product_dir = spec.get("_product_dir", "")
    spec_path = Path(spec.get("_spec_path", ""))
    preview_dir = spec_path.parent / "preview"

    os.makedirs(preview_dir, exist_ok=True)
    for f in os.listdir(preview_dir):
        os.remove(os.path.join(preview_dir, f))

    print(f"=== 프리뷰: {product} ({len(clips)}컷) ===")
    print(f"출력: {preview_dir}\n")

    for clip in clips:
        cid = clip["id"]
        section = clip.get("section", "")
        texts = [t.get("content", "") for t in clip.get("texts", [])]
        text_label = texts[0] if texts else "(텍스트 없음)"

        out = os.path.join(str(preview_dir), f"{cid:02d}_{section}_{text_label}.jpg")
        crop_to_jpg(clip["image"], out,
                    clip.get("crop", "full"),
                    clip.get("crop_y"), clip.get("crop_scale"))
        cy = clip.get('crop_y')
        if cy is not None:
            info = f"crop_y={cy} scale={clip.get('crop_scale')}"
        elif clip.get("crop", "full") in ("contain", "fit"):
            info = "9:16 contain"
        else:
            info = "9:16 cover"
        print(f"  [{cid:02d}] {section} | {text_label} | {info}")

    print(f"\n프리뷰 {len(clips)}장 완료.")
    print(f"확인 후 crop_y 수정 → 다시 --preview 또는 --generate 실행")


def _read_marker_sha256(marker_path: str) -> str:
    """마커 파일에서 spec_sha256 값을 읽는다."""
    try:
        with open(marker_path, "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("spec_sha256:"):
                    return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return ""


def _current_spec_sha256(product_dir: str) -> str:
    """현재 capcut_spec.json의 sha256을 계산."""
    import hashlib
    for sub in _spec_subs():
        candidate = os.path.join(product_dir, sub, "capcut_spec.json") if sub else os.path.join(product_dir, "capcut_spec.json")
        if os.path.isfile(candidate):
            with open(candidate, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
    return ""


def _write_draft_done_marker(product_dir: str, spec: dict, draft_name: str):
    """드래프트 완료 마커 .draft_done 생성 — 완주율 관측용 (Phase 3)."""
    from datetime import datetime, timezone, timedelta
    kst = timezone(timedelta(hours=9))
    spec_used = ""
    for sub in _spec_subs():
        candidate = os.path.join(product_dir, sub, "capcut_spec.json") if sub else os.path.join(product_dir, "capcut_spec.json")
        if os.path.isfile(candidate):
            spec_used = os.path.relpath(candidate, product_dir)
            break
    marker_path = os.path.join(product_dir, ".draft_done")
    spec_hash = _current_spec_sha256(product_dir)
    with open(marker_path, "w", encoding="utf-8") as f:
        f.write(f"draft_name: {draft_name}\n")
        f.write(f"spec_used: {spec_used}\n")
        f.write(f"spec_sha256: {spec_hash}\n")
        f.write(f"clips: {len(spec.get('clips', []))}\n")
        f.write(f"created_at: {datetime.now(kst).isoformat()}\n")
    print(f"  .draft_done 마커 생성")


def check_validation_gate(product: str, product_dir: str):
    for sub in ([os.path.join("reels", VARIANT)] if VARIANT else []) + ["reels", "edit"]:
        marker = os.path.join(product_dir, sub, ".validated")
        if os.path.exists(marker):
            saved = _read_marker_sha256(marker)
            current = _current_spec_sha256(product_dir)
            if saved and current and saved != current:
                print("=" * 60)
                print("  [BLOCKED] spec이 검증 이후 변경됨")
                print(f"  마커 sha256: {saved[:16]}...")
                print(f"  현재 sha256: {current[:16]}...")
                print(f"  validate_reels.py {product} 를 다시 실행하세요.")
                print("=" * 60)
                sys.exit(1)
            print(f"[검증통과] .validated 마커 확인됨" + (" (sha256 일치)" if saved else ""))
            return True
    if os.path.isdir(os.path.join(product_dir, "edit")):
        for v in sorted(os.listdir(os.path.join(product_dir, "edit")), reverse=True):
            marker = os.path.join(product_dir, "edit", v, ".validated")
            if os.path.exists(marker):
                print(f"[검증통과] .validated 마커 확인됨 ({v})")
                return True
    print("=" * 60)
    print("  [BLOCKED] validation gate")
    print("  .validated marker not found.")
    print(f"  Run first: python validate_reels.py {product}")
    print("  Then retry --generate.")
    print("=" * 60)
    sys.exit(1)


def build_clip_start_map(clips: list[dict]) -> dict[str, int]:
    clip_start_map = {}
    t = 0
    for clip in clips:
        clip_start_map[f"clip_{clip['id']}"] = t
        t += int(clip["duration"] * 1_000_000)
    return clip_start_map


def write_chroma_key_manifest(product: str, product_dir: str, spec: dict):
    targets = []
    for overlay in spec.get("overlays", []):
        chroma = overlay.get("chroma_key")
        if not chroma:
            continue
        targets.append({
            "trigger": overlay.get("trigger", ""),
            "asset": overlay.get("asset", ""),
            "mode": chroma.get("mode", "capcut_internal"),
            "color": chroma.get("color", "#00FF00"),
            "strength": chroma.get("strength", 62),
            "shadow": chroma.get("shadow", 30),
            "edge": chroma.get("edge", 18),
            "note": chroma.get("note", "CapCut Remove BG > Chroma Key"),
        })
    if not targets:
        return

    payload = {
        "product": product,
        "policy": "Use CapCut internal Remove BG > Chroma Key for listed overlay clips.",
        "targets": targets,
    }
    spec_dir = Path(spec.get("_spec_path", "")).parent
    spec_manifest = spec_dir / "chroma_key_manifest.json"
    spec_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    draft_dir = Path(CAPCUT_DIR) / draft_name_for(product, spec)
    draft_manifest = draft_dir / "CHROMA_KEY_MANIFEST.json"
    draft_manifest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    draft_note = draft_dir / "CHROMA_KEY_APPLY.md"
    lines = [
        "# CapCut Chroma Key Apply",
        "",
        "이 draft의 아래 overlay는 CapCut 내부 기능으로 초록 배경을 제거해야 합니다.",
        "",
        "경로: Video > Remove BG > Chroma Key",
        "",
        "| trigger | asset | color | strength | shadow | edge |",
        "|---|---|---|---:|---:|---:|",
    ]
    for target in targets:
        lines.append(
            f"| {target['trigger']} | `{os.path.basename(target['asset'])}` | "
            f"{target['color']} | {target['strength']} | {target['shadow']} | {target['edge']} |"
        )
    draft_note.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Chroma Key manifest: {len(targets)}개 대상 기록")


def write_feature_gate_report(product: str, spec: dict, *, strict: bool = False):
    report = analyze_spec(spec, strict=strict)
    spec_dir = Path(spec.get("_spec_path", "")).parent
    write_report(report, spec_dir / "capcut_feature_gate_report.json")
    draft_dir = Path(CAPCUT_DIR) / draft_name_for(product, spec)
    if draft_dir.exists():
        write_report(report, draft_dir / "CAPCUT_FEATURE_GATE_REPORT.json")
    manual_count = len(report.get("manual_capcut", []))
    sample_count = len(report.get("sample_required", []))
    warning_count = len(report.get("warnings", []))
    error_count = len(report.get("errors", []))
    print(f"  CapCut feature gate: {report['status']} (manual={manual_count}, sample_required={sample_count}, warnings={warning_count}, errors={error_count})")


def generate(product: str, spec: dict, force_overwrite: bool = False, tts_only: bool = False):
    product_dir = spec.get("_product_dir", "")
    check_validation_gate(product, product_dir)

    clips = spec["clips"]
    w, h  = spec["resolution"]
    fps   = spec["fps"]

    draft_name = draft_name_for(product, spec)
    print(f"=== CapCut 생성: {draft_name} ({len(clips)}컷 / {fps}fps) ===")

    tmp_dir   = tempfile.mkdtemp(prefix=f"capcut_{product.replace('/', '_')[:8]}_")
    mp4_paths = []
    if tts_only:
        print("\n[1/3] TTS-only mode - skip image/video conversion (placeholder)")
        total_dur = sum(c["duration"] for c in clips)
        placeholder = os.path.join(tmp_dir, "placeholder_black.mp4")
        subprocess.run([
            FFMPEG, "-y", "-f", "lavfi", "-i", f"color=black:s={w}x{h}:r={fps}",
            "-t", str(round(total_dur + 0.5, 3)),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", placeholder,
        ], capture_output=True, check=True)
        mp4_paths = [placeholder] * len(clips)
        print(f"  placeholder {total_dur:.1f}s - replace clips in CapCut")
    else:
        print("\n[1/3] 이미지 -> mp4")
        for clip in clips:
            out = os.path.join(tmp_dir, f"clip_{clip['id']:02d}.mp4")
            image_to_mp4(clip["image"], out, clip["duration"],
                         clip.get("crop", "full"),
                         clip.get("crop_y"), clip.get("crop_scale"))
            mp4_paths.append(out)
            cy = clip.get('crop_y')
            if cy is not None:
                crop_label = f"crop_y={cy} scale={clip.get('crop_scale')}"
            elif clip.get("crop", "full") in ("contain", "fit"):
                crop_label = "9:16 contain"
            else:
                crop_label = "9:16 cover"
            print(f"  [{clip['section']}] {clip['duration']}s {crop_label}")

    print("\n[2/3] CapCut 프로젝트 생성")
    existing = os.path.join(CAPCUT_DIR, draft_name)
    if os.path.exists(existing):
        if not force_overwrite:
            print("=" * 60)
            print(f"  [BLOCKED] 기존 드래프트 존재: {draft_name}")
            print("  기존 편집이 날아갑니다. --force-overwrite 로 재실행하세요.")
            print("=" * 60)
            sys.exit(1)
        shutil.rmtree(existing)

    folder = cc.DraftFolder(CAPCUT_DIR)
    script = folder.create_draft(draft_name, w, h, fps=fps)
    script.add_track(cc.TrackType.video)
    script.add_track(cc.TrackType.text)

    abs_texts = []
    text_timeline_sec = 0.0
    for orig_clip in spec.get("_text_clips", clips):
        clip_dur = orig_clip.get("duration", 0.0)
        for txt in orig_clip.get("texts", []):
            content = txt.get("content", "")
            if not content:
                continue
            t_start_off = txt.get("start_offset", 0.0)
            t_end_off = txt.get("end_offset", clip_dur)
            t_dur = txt.get("duration", max(0.1, t_end_off - t_start_off))
            t_start = text_timeline_sec + t_start_off
            abs_texts.append({
                "content": content,
                "start_us": int(t_start * 1_000_000),
                "dur_sec": t_dur,
                "position_y": txt.get("position_y", 0.0),
                "color": txt.get("color", "#FFFFFF"),
            })
        text_timeline_sec += clip_dur

    cursor_us = 0
    import re as _re
    section_start_us = {}

    for i, clip in enumerate(clips):
        dur_us  = int(clip["duration"] * 1_000_000)
        section = clip.get("section", "HOOK")
        sec_key = _re.sub(r"\d+$", "", section)

        if section not in section_start_us:
            section_start_us[section] = cursor_us
        if sec_key not in section_start_us:
            section_start_us[sec_key] = cursor_us

        seg = cc.VideoSegment(mp4_paths[i], cc.Timerange(cursor_us, dur_us))
        seg.add_background_filling('blur', blur=0.06)
        apply_motion(seg, section, dur_us, clip.get("motion", ""))

        trans = TRANSITION_MAP.get(clip.get("transition_out", "hard_cut"))
        if trans:
            seg.add_transition(trans, duration=300_000)

        effects_enabled = not spec.get("config", {}).get("disable_effects", False)
        custom_effect = clip.get("effect")
        if effects_enabled and custom_effect:
            eff_attr = getattr(cc.VideoSceneEffectType, custom_effect, None)
            if eff_attr:
                seg.add_effect(eff_attr)
        elif effects_enabled:
            effect_pool = SECTION_EFFECT_MAP.get(sec_key, [])
            if effect_pool:
                eff = effect_pool[i % len(effect_pool)]
                seg.add_effect(eff)

        seg.add_filter(cc.FilterType.Enhance, intensity=40.0)

        script.add_segment(seg)
        cursor_us += dur_us

    overlays = spec.get("overlays", [])
    if overlays:
        script.add_track(cc.TrackType.video, track_name="overlay")
        clip_start_map = build_clip_start_map(clips)
        overlay_placed = 0
        print(f"\n[2.5/3] Overlay 배치 ({len(overlays)}개)")
        for idx, overlay in enumerate(overlays, start=1):
            asset = resolve_media_path(overlay.get("asset", ""), product_dir)
            if not asset or not os.path.exists(asset):
                print(f"  [경고] overlay 파일 없음: {overlay.get('asset', '')}")
                continue
            trigger = overlay.get("trigger", "")
            base_start_us = clip_start_map.get(trigger, int(float(overlay.get("start", 0.0)) * 1_000_000))
            start_us = base_start_us + int(float(overlay.get("offset", 0.0)) * 1_000_000)
            duration = float(overlay.get("duration", 0.65))
            dur_us = int(duration * 1_000_000)
            if start_us >= cursor_us:
                print(f"  [경고] overlay 시작점이 영상 밖: {trigger}")
                continue
            dur_us = min(dur_us, max(100_000, cursor_us - start_us))

            out = os.path.join(tmp_dir, f"overlay_{idx:02d}.mp4")
            image_to_mp4(
                asset,
                out,
                dur_us / 1_000_000,
                overlay.get("crop", "contain"),
                overlay.get("crop_y"),
                overlay.get("crop_scale"),
            )
            scale = float(overlay.get("scale", 0.38))
            clip_s = cc.ClipSettings(
                alpha=float(overlay.get("alpha", 1.0)),
                scale_x=scale,
                scale_y=scale,
                transform_x=float(overlay.get("x", 0.0)),
                transform_y=float(overlay.get("y", 0.0)),
                rotation=float(overlay.get("rotation", 0.0)),
            )
            seg = cc.VideoSegment(
                out,
                cc.Timerange(start_us, dur_us),
                clip_settings=clip_s,
                volume=float(overlay.get("volume", 0.0)),
            )
            motion = overlay.get("motion", "")
            if motion:
                apply_motion(seg, overlay.get("section", "OVERLAY"), dur_us, motion)
            effect = overlay.get("effect", "")
            if effect:
                eff_attr = getattr(cc.VideoSceneEffectType, effect, None)
                if eff_attr:
                    seg.add_effect(eff_attr)
            script.add_segment(seg, track_name="overlay")
            overlay_placed += 1
            print(f"  Overlay: {os.path.basename(asset)} @ {start_us/1_000_000:.2f}s ({dur_us/1_000_000:.2f}s)")
        print(f"  Overlay {overlay_placed}개 배치 완료")

    for at in abs_texts:
        safe_dur = max(0.05, at["dur_sec"] - 0.002)
        tseg = make_text_seg(
            at["content"], at["start_us"], 0.0, safe_dur, at["position_y"],
            color_hex=at.get("color", "#FFFFFF"),
        )
        if spec.get("config", {}).get("text_animation", True):
            tseg.add_animation(cc.TextIntro.渐显, duration=150_000)
        script.add_segment(tseg)

    # --- TTS 삽입: narration_id 기반 per-line TTS 우선, 그 다음 section_tts, 마지막 단일 tts_file ---
    spec_dir = Path(spec.get("_spec_path", "")).parent
    tts_dir = spec_dir / "tts"
    tts_timing_path = spec_dir / "tts_timing.json"

    tts_placed = False

    # 방법 1: narration_id 매핑 (capcut_spec.json의 clips에 narration_id가 있는 경우)
    if tts_dir.is_dir():
        narration_clips = {}
        t = 0
        for clip in clips:
            nid = clip.get("narration_id")
            if nid and nid not in narration_clips:  # 첫 등장만 — 덮어쓰기 방지 (TTS 싱크 버그 수정)
                narration_clips[nid] = t
            t += int(clip["duration"] * 1_000_000)

        if narration_clips:
            placed = 0
            sorted_nars = sorted(narration_clips.items(), key=lambda x: x[1])
            segments_to_add = []
            for idx_n, (nid, start_us_val) in enumerate(sorted_nars):
                mp3_path = tts_dir / f"{nid}.mp3"
                if not mp3_path.exists():
                    print(f"  [경고] TTS 없음: {mp3_path.name}")
                    continue
                mat = cc.AudioMaterial(str(mp3_path))
                audio_dur = mat.duration
                if idx_n + 1 < len(sorted_nars):
                    max_dur = sorted_nars[idx_n + 1][1] - start_us_val
                    audio_dur = min(audio_dur, max_dur)
                audio_dur = max(audio_dur, 100_000)
                segments_to_add.append((mat, start_us_val, audio_dur, nid))
                placed += 1
            if placed > 0:
                script.add_track(cc.TrackType.audio)
                for mat, start_us_val, audio_dur, nid in segments_to_add:
                    script.add_segment(cc.AudioSegment(mat, cc.Timerange(start_us_val, audio_dur)))
                    print(f"  TTS: [{nid}] @ {start_us_val/1_000_000:.2f}s ({audio_dur/1_000_000:.2f}s)")
                tts_placed = True
                print(f"  TTS {placed}라인 배치 완료")

    # 방법 2: spec["audio"]["section_tts"] (기존 방식)
    if not tts_placed:
        audio = spec.get("audio", {})
        section_tts = audio.get("section_tts", {})
        if section_tts:
            script.add_track(cc.TrackType.audio)
            for sec_key, tts_rel_path in section_tts.items():
                tts_abs = resolve_tts_path(tts_rel_path, product_dir)
                if not os.path.exists(tts_abs):
                    continue
                start_us_val = section_start_us.get(sec_key, 0)
                mat = cc.AudioMaterial(tts_abs)
                script.add_segment(cc.AudioSegment(mat, cc.Timerange(start_us_val, mat.duration)))
                print(f"  TTS 배치: [{sec_key}] {os.path.basename(tts_abs)}")
            tts_placed = True

    # 방법 3: 단일 tts_file 또는 tts_merged.mp3
    if not tts_placed:
        tts_file = spec.get("audio", {}).get("tts_file", "")
        tts_abs = resolve_tts_path(tts_file, product_dir)
        if not tts_abs or not os.path.exists(tts_abs):
            merged = spec_dir / "tts_merged.mp3"
            if merged.exists():
                tts_abs = str(merged)
        if tts_abs and os.path.exists(tts_abs):
            script.add_track(cc.TrackType.audio)
            mat = cc.AudioMaterial(tts_abs)
            audio_dur = min(cursor_us, mat.duration)
            script.add_segment(cc.AudioSegment(mat, cc.Timerange(0, audio_dur)))
            print(f"  TTS 통합파일 삽입: {os.path.basename(tts_abs)}")
            tts_placed = True

    if not tts_placed:
        print("=" * 60)
        print("  [BLOCKED] TTS 파일 없음 — 드래프트 생성 중단")
        print("  gen_qwen3_tts.py 를 먼저 실행하세요.")
        print("=" * 60)
        sys.exit(1)

    bgm_path = HARNESS_DIR / "assets" / "bgm_common.mp3"
    if bgm_path.exists():
        script.add_track(cc.TrackType.audio, track_name="bgm")
        bgm_mat = cc.AudioMaterial(str(bgm_path))
        bgm_pos = 0
        loops = 0
        while bgm_pos < cursor_us:
            seg_dur = min(bgm_mat.duration, cursor_us - bgm_pos)
            script.add_segment(
                cc.AudioSegment(bgm_mat, cc.Timerange(bgm_pos, seg_dur), volume=0.15),
                track_name="bgm",
            )
            bgm_pos += seg_dur
            loops += 1
        print(f"  BGM 삽입: {bgm_path.name} (vol=0.15, {loops}회 반복으로 {cursor_us/1_000_000:.1f}s 전체 커버)")

    sfx_list = spec.get("sfx", [])
    if sfx_list:
        script.add_track(cc.TrackType.audio, track_name="sfx")
        clip_start_map = build_clip_start_map(spec.get("_text_clips", clips))
        sfx_placed = 0
        for sfx_entry in sfx_list:
            trigger = sfx_entry.get("trigger", "")
            sfx_name = sfx_entry.get("sfx", "")
            vol = sfx_entry.get("volume", 0.3)
            sfx_path = SFX_MAP.get(sfx_name)
            if not sfx_path or not sfx_path.exists():
                print(f"  [경고] SFX 없음: {sfx_name}")
                continue
            offset_us = int(sfx_entry.get("offset", 0.0) * 1_000_000)
            start_us = clip_start_map.get(trigger, 0) + offset_us
            sfx_mat = cc.AudioMaterial(str(sfx_path))
            max_sfx_us = int(sfx_entry.get("duration", 0.6) * 1_000_000)
            sfx_dur = min(sfx_mat.duration, max_sfx_us)
            try:
                script.add_segment(
                    cc.AudioSegment(sfx_mat, cc.Timerange(start_us, sfx_dur), volume=vol),
                    track_name="sfx",
                )
                sfx_placed += 1
                print(f"  SFX: [{sfx_name}] @ {start_us/1_000_000:.2f}s (vol={vol})")
            except Exception as e:
                print(f"  [경고] SFX 스킵 ({sfx_name} @ {start_us/1_000_000:.2f}s): {e}")
        print(f"  SFX {sfx_placed}종 배치 완료")

    script.save()
    write_feature_gate_report(product, spec, strict=False)
    write_chroma_key_manifest(product, product_dir, spec)

    draft_json = os.path.join(CAPCUT_DIR, draft_name, "draft_content.json")
    if os.path.exists(draft_json):
        postprocess_draft(draft_json, spec)
    write_draft_identity(draft_name)

    _write_draft_done_marker(product_dir, spec, draft_name)

    print(f"\n[3/3] 완료: {draft_name} / {cursor_us/1_000_000:.1f}초")
    print(f"  mp4: {tmp_dir}")
    print("CapCut 재시작 후 확인하세요.")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python generate_capcut.py {product} --preview              # 크롭 검수")
        print("  python generate_capcut.py {product} --generate             # CapCut 생성")
        print("  python generate_capcut.py {product} --generate --force-overwrite  # 기존 드래프트 덮어쓰기")
        print("  python generate_capcut.py {product} --generate --tts-only         # TTS+자막만 (영상 직접교체)")
        print("  python generate_capcut.py {product}                        # 기본 = preview")
        sys.exit(1)

    product = sys.argv[1]
    args_rest = sys.argv[2:]
    mode = "--preview"
    force_overwrite = False
    tts_only = False
    for a in args_rest:
        if a == "--generate":
            mode = a
        elif a == "--force-overwrite":
            force_overwrite = True
        elif a == "--tts-only":
            tts_only = True
    spec = load_spec(product)

    if mode == "--generate":
        generate(product, spec, force_overwrite=force_overwrite, tts_only=tts_only)
    else:
        preview(product, spec)


if __name__ == "__main__":
    main()
