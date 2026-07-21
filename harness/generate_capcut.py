"""
generate_capcut.py — CapCut 드래프트 자동 생성 (pycapcut)
사용: python generate_capcut.py {상품명}
     python generate_capcut.py {상품명} --preview
     python generate_capcut.py {상품명} --generate

이관: 컨텐츠자동화 → 비디오/video-use/harness/ (2026-06-13)
경로: VIDEO_ROOT = 비디오/video/ 기준으로 상품 검색
"""

import sys, json, os, tempfile, subprocess, shutil, copy, math, importlib
import pycapcut as cc
from pathlib import Path
from capcut_feature_gate import analyze_spec, write_report

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
SANGPE_ROOT = Path(r"C:\nomal\자동화\상페자동화")
CAPCUT_DIR = "C:/Users/user/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"

def write_draft_identity(product: str) -> None:
    draft_dir = Path(CAPCUT_DIR) / product
    meta_path = draft_dir / "draft_meta_info.json"
    if not meta_path.exists():
        return
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["draft_name"] = product
    meta["draft_fold_path"] = str(draft_dir)
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
            total_nar_dur = nar.get("tts_duration", clip_dur)
            nar_clips = [j for j, c in enumerate(clips_list) if c.get("narration_id") == nid]
            total_slot_dur = sum(clips_list[j].get("duration", 0) for j in nar_clips)
            chunk_dur = total_slot_dur / len(chunks) if chunks else clip_dur
            t = 0.0
            texts = []
            keywords = {kw["word"]: kw.get("color", "#FFFFFF") for kw in nar.get("subtitle_keywords", [])}
            for chunk_text in chunks:
                texts.append({
                    "content": chunk_text,
                    "start_offset": t,
                    "end_offset": t + chunk_dur,
                    "duration": chunk_dur,
                    "position_y": nar.get("subtitle_position_y", 0.0),
                })
                t += chunk_dur
            clip["texts"] = texts
            injected += 1
        if injected:
            print(f"  [자막 변환] narration → texts {injected}개 주입")

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


def make_text_seg(
    content: str,
    clip_start_us: int,
    window_start_offset: float,
    window_end_offset: float,
    position_y: float = 0.0,
) -> cc.TextSegment:
    style = cc.TextStyle(
        size=13.0,
        bold=True,
        color=(1.0, 1.0, 1.0),
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


def check_validation_gate(product: str, product_dir: str):
    for sub in ["reels", "edit"]:
        marker = os.path.join(product_dir, sub, ".validated")
        if os.path.exists(marker):
            print(f"[검증통과] .validated 마커 확인됨")
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

    draft_dir = Path(CAPCUT_DIR) / product
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
    draft_dir = Path(CAPCUT_DIR) / product
    if draft_dir.exists():
        write_report(report, draft_dir / "CAPCUT_FEATURE_GATE_REPORT.json")
    manual_count = len(report.get("manual_capcut", []))
    sample_count = len(report.get("sample_required", []))
    warning_count = len(report.get("warnings", []))
    error_count = len(report.get("errors", []))
    print(f"  CapCut feature gate: {report['status']} (manual={manual_count}, sample_required={sample_count}, warnings={warning_count}, errors={error_count})")


def generate(product: str, spec: dict):
    product_dir = spec.get("_product_dir", "")
    check_validation_gate(product, product_dir)

    clips = spec["clips"]
    w, h  = spec["resolution"]
    fps   = spec["fps"]

    print(f"=== CapCut 생성: {product} ({len(clips)}컷 / {fps}fps) ===")

    tmp_dir   = tempfile.mkdtemp(prefix=f"capcut_{product[:8]}_")
    mp4_paths = []
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
    existing = os.path.join(CAPCUT_DIR, product)
    if os.path.exists(existing):
        shutil.rmtree(existing)

    folder = cc.DraftFolder(CAPCUT_DIR)
    script = folder.create_draft(product, w, h, fps=fps)
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

        custom_effect = clip.get("effect")
        if custom_effect:
            eff_attr = getattr(cc.VideoSceneEffectType, custom_effect, None)
            if eff_attr:
                seg.add_effect(eff_attr)
        else:
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
            script.add_track(cc.TrackType.audio)
            placed = 0
            sorted_nars = sorted(narration_clips.items(), key=lambda x: x[1])
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
                script.add_segment(cc.AudioSegment(mat, cc.Timerange(start_us_val, audio_dur)))
                placed += 1
                print(f"  TTS: [{nid}] @ {start_us_val/1_000_000:.2f}s ({audio_dur/1_000_000:.2f}s)")
            if placed > 0:
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
        print("  [경고] TTS 파일 없음 - CapCut에서 수동 삽입 필요")

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

    draft_json = os.path.join(CAPCUT_DIR, product, "draft_content.json")
    if os.path.exists(draft_json):
        postprocess_draft(draft_json, spec)
    write_draft_identity(product)
    print(f"\n[3/3] 완료: {product} / {cursor_us/1_000_000:.1f}초")
    print(f"  mp4: {tmp_dir}")
    print("CapCut 재시작 후 확인하세요.")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python generate_capcut.py {product} --preview   # 크롭 검수")
        print("  python generate_capcut.py {product} --generate  # CapCut 생성")
        print("  python generate_capcut.py {product}             # 기본 = preview")
        sys.exit(1)

    product = sys.argv[1]
    mode    = sys.argv[2] if len(sys.argv) > 2 else "--preview"
    spec    = load_spec(product)

    if mode == "--generate":
        generate(product, spec)
    else:
        preview(product, spec)


if __name__ == "__main__":
    main()
