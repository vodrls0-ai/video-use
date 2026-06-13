"""
generate_capcut.py — CapCut 드래프트 자동 생성 (pycapcut)
사용: python generate_capcut.py {상품명}
     python generate_capcut.py {상품명} --preview
     python generate_capcut.py {상품명} --generate

이관: 컨텐츠자동화 → 비디오/video-use/harness/ (2026-06-13)
경로: VIDEO_ROOT = 비디오/video/ 기준으로 상품 검색
"""

import sys, json, os, tempfile, subprocess, shutil, copy
import pycapcut as cc
from pathlib import Path

def _resolve_ffmpeg() -> str:
    env = os.getenv("FFMPEG_PATH")
    if env and os.path.exists(env):
        return env
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    capcut_ff = "C:/Users/USER/AppData/Local/CapCut/Apps/5.5.0.2028/ffmpeg.exe"
    if os.path.exists(capcut_ff):
        return capcut_ff
    return "ffmpeg"

FFMPEG = _resolve_ffmpeg()
HARNESS_DIR = Path(__file__).resolve().parent
VIDEO_ROOT = HARNESS_DIR.parent.parent / "video"
SANGPE_ROOT = Path(r"C:\nomal\자동화\상페자동화")
CAPCUT_DIR = "C:/Users/user/AppData/Local/CapCut/User Data/Projects/com.lveditor.draft"

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


def auto_split_clips(clips: list[dict]) -> list[dict]:
    unused_pool = build_unused_pool(clips)
    if unused_pool:
        print(f"  [풀] 미사용 이미지 {len(unused_pool)}장 사용 가능: {[os.path.basename(p) for p in unused_pool]}")
    result = []
    new_id = 1
    for clip in clips:
        dur = clip["duration"]
        if dur <= MAX_CLIP_SEC:
            clip["id"] = new_id
            result.append(clip)
            new_id += 1
            continue

        n_splits = max(2, round(dur / 1.8))
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
    spec["_text_clips"] = copy.deepcopy(spec.get("clips", []))

    original_count = len(spec.get("clips", []))
    spec["clips"] = auto_split_clips(spec.get("clips", []))
    new_count = len(spec["clips"])
    if new_count > original_count:
        print(f"  [이미지 다양성] {original_count}컷 → {new_count}컷 (자동 분할)")
    return spec


def image_to_mp4(img: str, out: str, duration: float, crop: str = "full",
                  crop_y: float | None = None, crop_scale: float | None = None):
    if crop_y is not None:
        sc = crop_scale or 2.5
        sz = int(1920 * sc)
        crop_top = max(0, int(sz * crop_y - 960))
        crop_top = min(crop_top, sz - 1920)
        vf = (f"scale={sz}:{sz}:force_original_aspect_ratio=increase,"
              f"crop=1080:1920:(iw-1080)/2:{crop_top},"
              f"setsar=1")
    else:
        vf = "pad=ceil(iw/2)*2:ceil(ih/2)*2,setsar=1"
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
        size=16.0,
        bold=True,
        color=(1.0, 1.0, 1.0),
        align=1,
        max_line_width=0.70,
    )
    border = cc.TextBorder(color=(0.0, 0.0, 0.0), width=60.0, alpha=1.0)
    safe_y = max(-0.50, min(0.40, position_y))
    clip_s = cc.ClipSettings(transform_x=0.0, transform_y=safe_y)

    t_start = clip_start_us + int(window_start_offset * 1_000_000)
    t_end   = clip_start_us + int(window_end_offset   * 1_000_000)
    return cc.TextSegment(
        content, cc.Timerange(t_start, t_end - t_start),
        style=style, border=border, clip_settings=clip_s,
    )


TRANSITION_MAP = {
    "hard_cut": None,
    "zoom":     cc.TransitionType.White_Flash,
    "fade":     cc.TransitionType.Flash,
}


def resolve_tts_path(tts_file: str, product_dir: str) -> str:
    if not tts_file:
        return ""
    if os.path.isabs(tts_file) and os.path.exists(tts_file):
        return tts_file
    candidate = os.path.join(product_dir, tts_file)
    if os.path.exists(candidate):
        return candidate
    return tts_file


def crop_to_jpg(img: str, out: str, crop: str = "full",
                crop_y: float | None = None, crop_scale: float | None = None):
    if crop_y is not None:
        sc = crop_scale or 2.5
        sz = int(1920 * sc)
        crop_top = max(0, int(sz * crop_y - 960))
        crop_top = min(crop_top, sz - 1920)
        vf = (f"scale={sz}:{sz}:force_original_aspect_ratio=increase,"
              f"crop=1080:1920:(iw-1080)/2:{crop_top},"
              f"setsar=1")
        cmd = [FFMPEG, "-y", "-i", img, "-vf", vf, "-frames:v", "1", out]
    else:
        cmd = [FFMPEG, "-y", "-i", img, "-frames:v", "1", out]
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
        else:
            info = "원본"
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
        crop_label = f"crop_y={cy} scale={clip.get('crop_scale')}" if cy is not None else "원본"
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
        apply_motion(seg, section, dur_us, clip.get("motion", ""))

        trans = TRANSITION_MAP.get(clip.get("transition_out", "hard_cut"))
        if trans:
            seg.add_transition(trans, duration=300_000)

        script.add_segment(seg)
        cursor_us += dur_us

    for at in abs_texts:
        script.add_segment(make_text_seg(
            at["content"], at["start_us"], 0.0, at["dur_sec"], at["position_y"],
        ))

    audio = spec.get("audio", {})
    section_tts = audio.get("section_tts", {})

    if section_tts:
        script.add_track(cc.TrackType.audio)
        placed = 0
        tts_keys_sorted = sorted(
            [(k, section_start_us.get(k, 0)) for k in section_tts.keys()],
            key=lambda x: x[1],
        )
        for sec_key, tts_rel_path in section_tts.items():
            tts_abs = resolve_tts_path(tts_rel_path, product_dir)
            if not os.path.exists(tts_abs):
                print(f"  [경고] 섹션 TTS 없음: {tts_rel_path}")
                continue
            start_us = section_start_us.get(sec_key, 0)
            sec_end_us = cursor_us
            for idx, (sk, st) in enumerate(tts_keys_sorted):
                if sk == sec_key and idx + 1 < len(tts_keys_sorted):
                    sec_end_us = tts_keys_sorted[idx + 1][1]
                    break
            seg_dur = sec_end_us - start_us
            mat = cc.audio_segment.AudioMaterial(tts_abs)
            seg_dur = min(seg_dur, mat.duration)
            script.add_segment(cc.AudioSegment(mat, cc.Timerange(start_us, seg_dur)))
            placed += 1
            print(f"  TTS 배치: [{sec_key}] {os.path.basename(tts_abs)} @ {start_us/1_000_000:.2f}s")

        if placed == 0:
            print("  [경고] 섹션별 TTS 파일을 하나도 찾지 못했습니다.")
    else:
        tts_file = audio.get("tts_file", "")
        tts_abs = resolve_tts_path(tts_file, product_dir)

        if tts_abs and os.path.exists(tts_abs):
            script.add_track(cc.TrackType.audio)
            mat = cc.audio_segment.AudioMaterial(tts_abs)
            audio_dur = min(cursor_us, mat.duration)
            script.add_segment(cc.AudioSegment(mat, cc.Timerange(0, audio_dur)))
            print(f"  TTS 삽입: {os.path.basename(tts_abs)}")
        else:
            print("  TTS 없음 - CapCut에서 수동 삽입")

    script.save()
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
