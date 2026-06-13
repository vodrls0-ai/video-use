"""릴스 풀자동화 오케스트레이터.

Usage:
    python auto_reel.py scan "상품명"
    python auto_reel.py build "상품명" [--version v1] [--force-tts]
    python auto_reel.py render "상품명" [--version v1] [--preview]
    python auto_reel.py full "상품명" [--force-tts]
    python auto_reel.py tts "상품명" [--version v1] [--force-tts] [--skip-whisper]

파이프라인:
    Phase 1 (자동): scan → media_manifest.json → Claude가 script.json + config.json 생성
    검수: 사용자가 대본 + 컷배치 확인
    Phase 2 (자동): TTS → Whisper → build_reel → sync_verify → 프리뷰(FHD) → 최종(4K)

TTS 스킵: 기존 mp3가 있으면 API 호출 건너뜀. --force-tts로 재생성 강제.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

HARNESS_DIR = Path(__file__).resolve().parent
VIDEO_USE_DIR = HARNESS_DIR.parent
VIDEO_ROOT = VIDEO_USE_DIR.parent / "video"
HELPERS_DIR = VIDEO_USE_DIR / "helpers"

SANGPE_COMPLETE = Path(r"C:\nomal\자동화\상페자동화\0.완료")
SANGPE_WIP = Path(r"C:\nomal\자동화\상페자동화\1.작업중")
VIDEO_LIST_JSON = Path(r"C:\nomal\자동화\상품판설계\video_list.json")
COMPARE_DIR = Path(r"Z:\NOMAL\업무\1. 업무폴더\업무도움\인스타\릴스\0.비교제품")
BGM_COMMON = HARNESS_DIR / "assets" / "bgm_common.mp3"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
GIF_EXTS = {".gif"}
SKIP_PATTERNS = {"handoff", "thumbnail", "썸네일", "batch_hf_"}

# --- ElevenLabs TTS 설정 ---
TTS_MODEL = "eleven_multilingual_v2"
TTS_OUTPUT_FORMAT = "mp3_44100_128"
BEAT_VOICE_PROFILES = {
    "hook":    {"stability": 0.50, "style": 0.40, "speed": 1.20, "similarity_boost": 0.80},
    "kick":    {"stability": 0.48, "style": 0.40, "speed": 1.20, "similarity_boost": 0.78},
    "pain":    {"stability": 0.45, "style": 0.40, "speed": 1.18, "similarity_boost": 0.75},
    "pivot":   {"stability": 0.45, "style": 0.45, "speed": 1.20, "similarity_boost": 0.75},
    "detail":  {"stability": 0.55, "style": 0.25, "speed": 1.20, "similarity_boost": 0.80},
    "trust":   {"stability": 0.55, "style": 0.20, "speed": 1.18, "similarity_boost": 0.82},
    "result":  {"stability": 0.55, "style": 0.25, "speed": 1.18, "similarity_boost": 0.80},
    "price":   {"stability": 0.60, "style": 0.15, "speed": 1.18, "similarity_boost": 0.85},
    "cta":     {"stability": 0.60, "style": 0.15, "speed": 1.15, "similarity_boost": 0.85},
}
TTS_DEFAULT_PROFILE = {"stability": 0.50, "style": 0.30, "speed": 1.18, "similarity_boost": 0.80}

# --- 비트 간 무음 갭 (초) ---
BEAT_GAP_AFTER = {
    "hook": 0.15,
    "kick": 0.20,
    "pain": 0.20,
    "pivot": 0.25,
    "detail": 0.15,
    "trust": 0.20,
    "result": 0.25,
    "price": 0.20,
    "cta": 0.0,
}
DEFAULT_GAP = 0.20
TAIL_SECONDS = 1.0

# --- v2 spec 변환: config.json → capcut_spec.json ---
OVERLAY_PRESETS = {
    "default": {
        "HOOK": [{"media": "assets/overlays/new_badge.png", "position": [0.88, 0.08],
                  "scale": 0.12, "start": 0, "duration": 2.0, "animation": "slide_up"}],
        "PRICE": [{"media": "assets/overlays/price_tag.png", "position": [0.5, 0.25],
                   "scale": 0.25, "start": 0, "duration": None, "animation": "slide_left"}],
        "CTA": [{"media": "assets/overlays/cta_badge.png", "position": [0.5, 0.75],
                 "scale": 0.28, "start": 0, "duration": None, "animation": "slide_up"}],
    },
    "minimal": {
        "CTA": [{"media": "assets/overlays/logo_watermark.png", "position": [0.5, 0.90],
                 "scale": 0.18, "start": 0, "duration": None, "animation": "none"}],
    },
    "none": {},
}

MOTION_MAP = {
    "snap-zoom": "snap_zoom", "slow-zoom-in": "slow_zoom_in",
    "slow-zoom-out": "slow_zoom_out", "ken-burns": "ken_burns",
    "pan-right": "pan_right", "scan-left": "scan_left",
    "scan-right": "scan_right", "slide-pan": "slide_pan",
}

SECTION_KEYWORD_COLOR = {
    "HOOK": "#FF6B35", "KICK": "#FFD700", "PRICE": "#FF4444",
    "CTA": "#00BFFF", "DETAIL": "#FFFFFF", "TRUST": "#90EE90",
}


def generate_capcut_spec(version_dir: Path, audio_mode: str = "tts",
                         bgm_path: str = "", loop: bool = False,
                         overlay_preset: str = "default") -> Path:
    """config.json + script.json → capcut_spec.json (render_reels v2 호환)."""
    script_path = version_dir / "script.json"
    config_path = version_dir / "config.json"

    if not config_path.exists():
        raise FileNotFoundError(f"config.json 없음: {config_path}")
    if not script_path.exists():
        raise FileNotFoundError(f"script.json 없음: {script_path}")

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    all_sources = {}
    for group in config.get("sources", {}).values():
        if isinstance(group, dict):
            all_sources.update(group)

    beats_script = {b["id"]: b for b in script.get("beats", [])}
    ov_cfg = OVERLAY_PRESETS.get(overlay_preset, {})
    tts_dir = version_dir / "tts"

    clips = []
    for beat in config.get("beats", []):
        beat_id = beat["id"]
        section = beat.get("section", "")
        sb = beats_script.get(beat_id, {})
        subtitles = sb.get("subtitle", [])
        cuts = beat.get("cuts", [])
        beat_start = beat.get("start", 0.0)
        beat_dur = beat.get("duration", sum(c.get("dur", c.get("duration", 1)) for c in cuts))
        beat_overlays = ov_cfg.get(section, [])

        for ci, cut in enumerate(cuts):
            source_key = cut.get("source", "")
            media_path = all_sources.get(source_key, "")
            if not media_path:
                media_path = cut.get("media", source_key)

            motion_raw = cut.get("motion", "static")
            motion = MOTION_MAP.get(motion_raw, motion_raw.replace("-", "_"))

            cut_type = cut.get("type", "image")
            dur = cut.get("dur", cut.get("duration", 1.0))

            if ci == len(cuts) - 1:
                tr = beat.get("transition_type", "hard_cut")
                if tr == "crossfade":
                    tr = "cross_fade"
            else:
                tr = "hard_cut"

            clip = {
                "image": media_path,
                "duration": round(dur, 3),
                "section": section,
                "motion": motion,
                "transition_out": tr,
                "media_type": cut_type,
            }

            if ci == 0:
                tts_file = tts_dir / f"{beat_id}.mp3"
                if tts_file.exists():
                    clip["tts_file"] = str(tts_file)

            if ci == 0 and subtitles:
                texts = []
                kw_color = SECTION_KEYWORD_COLOR.get(section, "#FF6B35")
                for si_idx, sub in enumerate(subtitles):
                    entry = {"content": sub["text"]}
                    appear = sub.get("appear_at", beat_start) - beat_start
                    if si_idx + 1 < len(subtitles):
                        end = subtitles[si_idx + 1].get("appear_at", beat_start) - beat_start
                    else:
                        end = beat_dur
                    entry["start_offset"] = round(max(appear, 0), 3)
                    entry["end_offset"] = round(end, 3)
                    emphasis = sub.get("emphasis", [])
                    if emphasis:
                        entry["keywords"] = [{"word": w, "color": kw_color} for w in emphasis]
                    texts.append(entry)
                clip["texts"] = texts

            if ci == 0 and beat_overlays:
                clip["overlays"] = []
                for ov in beat_overlays:
                    ov_copy = dict(ov)
                    if ov_copy.get("duration") is None:
                        ov_copy["duration"] = dur
                    clip["overlays"].append(ov_copy)

            clips.append(clip)

    spec = {
        "product": config.get("meta", {}).get("product", "unknown"),
        "config": {"audio_mode": audio_mode, "loop": loop},
        "clips": clips,
    }
    if bgm_path:
        spec["config"]["bgm_path"] = bgm_path

    spec_path = version_dir / "capcut_spec.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2)

    n_ov = sum(len(c.get("overlays", [])) for c in clips)
    n_kw = sum(len(t.get("keywords", []))
               for c in clips for t in c.get("texts", []))
    print(f"  capcut_spec.json 생성: {len(clips)}클립 | audio={audio_mode} loop={loop}")
    print(f"  overlay={overlay_preset}({n_ov}개) keywords={n_kw}개")
    print(f"  저장: {spec_path}")
    return spec_path


# --- capcut_spec → EDL 변환 (render.py 호환) ---

_ZP_HEADROOM = 1.15
_ZP_W = int(1080 * _ZP_HEADROOM)
_ZP_H = int(1920 * _ZP_HEADROOM)


def _image_to_clip(image_path: Path, duration: float, out_path: Path,
                   motion: str = "static", fps: int = 24) -> bool:
    """Still image → video clip with motion effect + silent audio."""
    frames = max(round(duration * fps), 1)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_encode = [
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        "-shortest", "-movflags", "+faststart",
    ]

    if motion in (None, "static", ""):
        vf = ("scale=1080:1920:force_original_aspect_ratio=decrease,"
              "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:black")
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(image_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", f"{duration:.3f}",
            "-vf", vf, "-r", str(fps),
            *base_encode, str(out_path),
        ]
    else:
        scale_crop = (
            f"scale=iw*max({_ZP_W}/iw\\,{_ZP_H}/ih):"
            f"ih*max({_ZP_W}/iw\\,{_ZP_H}/ih),"
            f"crop={_ZP_W}:{_ZP_H}"
        )
        delta = _ZP_HEADROOM - 1.0

        if motion in ("zoom_out", "zoom_settle"):
            z_expr = f"if(eq(on,0),{_ZP_HEADROOM},max(zoom-{delta}/{frames},1.0))"
        elif motion in ("snap_zoom", "M3_snap_zoom"):
            snap = max(int(frames * 0.15), 1)
            z_expr = f"if(lt(on,{snap}),1.0+{delta}*on/{snap},{_ZP_HEADROOM})"
        else:
            z_expr = f"min(zoom+{delta}/{frames},{_ZP_HEADROOM})"

        zp = (f"zoompan=z='{z_expr}':d={frames}:"
              f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
              f"s=1080x1920:fps={fps}")

        cmd = [
            "ffmpeg", "-y",
            "-i", str(image_path),
            "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-filter_complex", f"[0:v]{scale_crop},{zp}[v]",
            "-map", "[v]", "-map", "1:a",
            "-t", f"{duration:.3f}",
            *base_encode, str(out_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode != 0:
        print(f"    ffmpeg: {result.stderr[-300:]}")
    return result.returncode == 0


def _srt_ts(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, rem = divmod(ms, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms_r = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms_r:03d}"


def _build_srt_from_spec(clips: list, srt_path: Path) -> bool:
    timeline = 0.0
    cues: list[tuple[float, float, str]] = []
    for clip in clips:
        for text in clip.get("texts", []):
            start = timeline + text.get("start_offset", 0)
            end = timeline + text.get("end_offset", clip["duration"])
            cues.append((start, end, text["content"]))
        timeline += clip["duration"]
    if not cues:
        return False
    lines: list[str] = []
    for i, (s, e, t) in enumerate(cues, 1):
        lines += [str(i), f"{_srt_ts(s)} --> {_srt_ts(e)}", t, ""]
    srt_path.write_text("\n".join(lines), encoding="utf-8")
    return True


def capcut_to_edl(spec_path: Path) -> Path:
    """Convert capcut_spec.json → edl.json for render.py.

    Image clips are pre-converted to video with motion effects.
    """
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    edit_dir = spec_path.parent
    prep_dir = edit_dir / "_capcut_prep"
    prep_dir.mkdir(exist_ok=True)

    clips = spec.get("clips", [])
    sources: dict[str, str] = {}
    ranges: list[dict] = []
    overlays_edl: list[dict] = []
    timeline = 0.0

    print(f"  capcut_spec → EDL: {len(clips)}클립")

    for idx, clip in enumerate(clips):
        media_path = Path(clip["image"])
        duration = clip["duration"]
        media_type = clip.get("media_type", "image")
        section = clip.get("section", "")
        motion = clip.get("motion", "static")
        src_name = f"clip_{idx:02d}"

        if not media_path.exists():
            print(f"  [{idx:02d}] SKIP 파일없음: {media_path.name}")
            continue

        if media_type == "image":
            clip_out = prep_dir / f"{src_name}.mp4"
            if clip_out.exists() and clip_out.stat().st_size > 1024:
                print(f"  [{idx:02d}] img 캐시: {media_path.name}")
            else:
                print(f"  [{idx:02d}] img→vid {media_path.name} ({duration:.1f}s {motion})")
                if not _image_to_clip(media_path, duration, clip_out, motion=motion):
                    print(f"  [{idx:02d}] FAIL")
                    continue
            sources[src_name] = str(clip_out)
        else:
            sources[src_name] = str(media_path)
            print(f"  [{idx:02d}] video  {media_path.name} ({duration:.1f}s)")

        ranges.append({"source": src_name, "start": 0.0, "end": duration, "beat": section})

        for ov in clip.get("overlays", []):
            if ov.get("media"):
                overlays_edl.append({
                    "file": ov["media"],
                    "start_in_output": round(timeline + ov.get("start", 0), 3),
                    "duration": round(ov.get("duration", duration), 3),
                })
        timeline += duration

    if not ranges:
        raise RuntimeError("변환 가능한 클립 없음")

    srt_path = edit_dir / "master.srt"
    has_srt = _build_srt_from_spec(clips, srt_path)

    edl: dict = {"sources": sources, "ranges": ranges, "grade": "auto"}
    if overlays_edl:
        edl["overlays"] = overlays_edl
    if has_srt:
        edl["subtitles"] = str(srt_path)

    edl_path = edit_dir / "edl.json"
    with open(edl_path, "w", encoding="utf-8") as f:
        json.dump(edl, f, ensure_ascii=False, indent=2)

    print(f"  EDL: {len(ranges)}범위 {len(overlays_edl)}오버레이 SRT={'O' if has_srt else 'X'}")
    return edl_path


def find_product_folder(product: str) -> Path | None:
    for cat in SANGPE_COMPLETE.iterdir():
        if not cat.is_dir():
            continue
        target = cat / product
        if target.exists():
            return target
    wip = SANGPE_WIP / product
    if wip.exists():
        return wip
    return None


def check_video_availability(product: str) -> bool:
    if not VIDEO_LIST_JSON.exists():
        return False
    try:
        with open(VIDEO_LIST_JSON, "r", encoding="utf-8") as f:
            items = json.load(f)
        for item in items:
            name = item if isinstance(item, str) else item.get("name", "")
            status = "active" if isinstance(item, str) else item.get("status", "active")
            if name == product and status == "active":
                return True
    except (json.JSONDecodeError, IOError):
        pass
    return False


def classify_filename(fname: str) -> str:
    low = fname.lower()
    if any(skip in low for skip in SKIP_PATTERNS):
        return "skip"
    if "누끼" in low or "누기" in low:
        return "nukki"
    if "디테일" in low or "확대" in low or "클로즈" in low:
        return "detail"
    if "플랫" in low or "flat" in low:
        return "flatlay"
    if "사이즈" in low or "size" in low:
        return "size_chart"
    if "비교" in low or "vs" in low or "비침" in low:
        return "comparison"
    if "연출" in low or "코디" in low or "룩" in low:
        return "styling"
    return "wearing"


def scan_folder(folder: Path) -> list[dict]:
    results = []
    if not folder.exists():
        return results
    for f in sorted(folder.iterdir()):
        if f.is_dir():
            continue
        ext = f.suffix.lower()
        if ext in IMAGE_EXTS:
            media_type = "image"
        elif ext in VIDEO_EXTS:
            media_type = "video"
        elif ext in GIF_EXTS:
            media_type = "gif"
        else:
            continue
        if ext == ".orig":
            continue
        category = classify_filename(f.name)
        if category == "skip":
            continue
        results.append({
            "file": f.name,
            "path": str(f),
            "media_type": media_type,
            "category": category,
            "size_bytes": f.stat().st_size,
        })
    return results


def scan_product(product: str, skip_face: bool = False) -> dict:
    product_folder = find_product_folder(product)
    if not product_folder:
        return {"error": f"상품 폴더 없음: {product}"}

    has_video = check_video_availability(product)

    media = {
        "보정": scan_folder(product_folder / "보정"),
        "영상원본": scan_folder(product_folder / "영상원본"),
        "MP4": scan_folder(product_folder / "MP4"),
        "mp4": scan_folder(product_folder / "mp4"),
        "GIF": scan_folder(product_folder / "GIF"),
    }

    product_info = load_product_info(product_folder)

    all_media = []
    for source, items in media.items():
        for item in items:
            item["source_folder"] = source
            all_media.append(item)

    images = [m for m in all_media if m["media_type"] == "image"]
    videos = [m for m in all_media if m["media_type"] == "video"]
    gifs = [m for m in all_media if m["media_type"] == "gif"]

    reel_type = "video" if (videos or has_video) else "image"

    manifest = {
        "product": product,
        "product_folder": str(product_folder),
        "reel_type": reel_type,
        "has_video_record": has_video,
        "summary": {
            "total_images": len(images),
            "total_videos": len(videos),
            "total_gifs": len(gifs),
            "categories": {},
        },
        "media": all_media,
        "product_info": product_info,
    }

    for m in all_media:
        cat = m["category"]
        manifest["summary"]["categories"][cat] = manifest["summary"]["categories"].get(cat, 0) + 1

    if not skip_face:
        try:
            from face_detect import enrich_manifest
            print("  얼굴 감지 중...")
            manifest = enrich_manifest(manifest)
            face_detected = sum(1 for m in all_media if m.get("face_info", {}).get("face_detected"))
            print(f"  얼굴 감지 완료: {face_detected}/{len(all_media)}개 미디어에서 얼굴 발견")
        except ImportError:
            print("  WARN: face_detect 모듈 없음 — 얼굴 감지 생략")
        except Exception as e:
            print(f"  WARN: 얼굴 감지 실패 — {e}")

    return manifest


def load_product_info(product_folder: Path) -> dict:
    info = {}

    txt_path = product_folder / "상품정보.txt"
    if txt_path.exists():
        try:
            info["raw_text"] = txt_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            info["raw_text"] = txt_path.read_text(encoding="cp949", errors="replace")

    copy_path = product_folder / "output" / "copy.json"
    if copy_path.exists():
        try:
            with open(copy_path, "r", encoding="utf-8") as f:
                info["copy_json"] = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass

    return info


def _load_elevenlabs_env() -> tuple[str, str]:
    env_path = VIDEO_USE_DIR / ".env"
    api_key, voice_id = "", ""
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("ELEVENLABS_API_KEY="):
                api_key = line.split("=", 1)[1].strip()
            elif line.startswith("ELEVENLABS_VOICE_ID="):
                voice_id = line.split("=", 1)[1].strip()
    api_key = os.getenv("ELEVENLABS_API_KEY", api_key)
    voice_id = os.getenv("ELEVENLABS_VOICE_ID", voice_id)
    return api_key, voice_id


def _number_to_korean(n: int) -> str:
    if n == 0:
        return "영"
    digits = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
    small_units = ["", "십", "백", "천"]
    big_units = ["", "만", "억", "조"]
    parts: list[str] = []
    group_idx = 0
    while n > 0:
        group = n % 10000
        n //= 10000
        if group > 0:
            group_str = ""
            temp = group
            for pos in range(4):
                d = temp % 10
                temp //= 10
                if d > 0:
                    if d == 1 and pos > 0:
                        group_str = small_units[pos] + group_str
                    else:
                        group_str = digits[d] + small_units[pos] + group_str
            if group == 1 and group_idx > 0:
                parts.append(big_units[group_idx])
            else:
                parts.append(group_str + big_units[group_idx])
        group_idx += 1
    parts.reverse()
    return "".join(parts)


def _preprocess_tts_text(text: str) -> str:
    def _replace_price(m):
        num_str = m.group(1).replace(",", "").replace(".", "")
        try:
            n = int(num_str)
            return _number_to_korean(n) + "원" if n else m.group(0)
        except ValueError:
            return m.group(0)
    text = re.sub(r'(\d[\d,.]*)\s*원', _replace_price, text)
    for old, new in {"ㄹㅇ": "리얼", "ㄱㄱ": "고고", "ㅋㅋ": "", "ㅎㅎ": "", "ㅠㅠ": "", "ㅜㅜ": ""}.items():
        text = text.replace(old, new)
    text = re.sub(r",{2,}", ",", text)
    text = re.sub(r"\.{4,}", "...", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _get_audio_duration(path: Path) -> float:
    try:
        result = subprocess.run(
            ["ffprobe", "-i", str(path), "-show_entries", "format=duration",
             "-v", "quiet", "-of", "csv=p=0"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except (FileNotFoundError, ValueError):
        pass
    # ffprobe 없을 때 mutagen fallback (NAS 경로 대응: bytes로 읽어 전달)
    try:
        import io as _io
        from mutagen.mp3 import MP3 as _MP3
        with open(path, "rb") as _f:
            return round(_MP3(fileobj=_io.BytesIO(_f.read())).info.length, 3)
    except Exception:
        return 0.0


def _generate_silence(duration_s: float, output_path: Path) -> bool:
    result = subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=44100:cl=mono",
         "-t", str(duration_s),
         "-c:a", "libmp3lame", "-b:a", "128k",
         str(output_path)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
    )
    return result.returncode == 0


def _call_elevenlabs(text: str, output_path: Path, api_key: str, voice_id: str,
                     profile: dict | None = None) -> bool:
    import requests
    prof = profile or TTS_DEFAULT_PROFILE
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
    headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
    payload = {
        "text": text,
        "model_id": TTS_MODEL,
        "output_format": TTS_OUTPUT_FORMAT,
        "voice_settings": {
            "stability": prof.get("stability", 0.50),
            "similarity_boost": prof.get("similarity_boost", 0.80),
            "style": prof.get("style", 0.30),
            "speed": prof.get("speed", 1.10),
            "use_speaker_boost": True,
        },
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    if resp.status_code != 200:
        print(f"  ElevenLabs API 오류 ({resp.status_code}): {resp.text[:200]}")
        return False
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(resp.content)
    size_kb = len(resp.content) / 1024
    print(f"  TTS 저장: {output_path.name} ({size_kb:.0f}KB)")
    return True


def run_tts(version_dir: Path, force: bool = False) -> bool:
    script_path = version_dir / "script.json"
    if not script_path.exists():
        print("  ERROR: script.json 없음")
        return False

    api_key, voice_id = _load_elevenlabs_env()
    if not api_key:
        print("  ERROR: ELEVENLABS_API_KEY 없음 (릴스자동화/.env 또는 환경변수)")
        return False
    if not voice_id:
        print("  ERROR: ELEVENLABS_VOICE_ID 없음")
        return False

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    beats = script.get("beats", [])
    if not beats:
        print("  ERROR: beats 없음")
        return False

    version = script["meta"]["version"]
    tts_dir = version_dir / "tts"
    tts_dir.mkdir(exist_ok=True)

    beat_files: list[Path] = []
    beat_ids: list[str] = []
    total_chars = 0

    for beat in beats:
        narration = beat.get("narration", "").strip()
        if not narration:
            continue
        processed = _preprocess_tts_text(narration)
        total_chars += len(processed)

        beat_id = beat["id"]
        beat_type = beat_id.rstrip("0123456789").lower()
        profile = BEAT_VOICE_PROFILES.get(beat_type, TTS_DEFAULT_PROFILE)

        beat_file = tts_dir / f"{beat_id}.mp3"

        if not force and beat_file.exists() and beat_file.stat().st_size > 1024:
            dur = _get_audio_duration(beat_file)
            if dur > 0.1:
                print(f"  [{beat_id}] 기존 mp3 사용 ({dur:.2f}s, 스킵)")
                beat_files.append(beat_file)
                beat_ids.append(beat_id)
                continue

        print(f"  [{beat_id}] \"{processed[:40]}...\" (speed={profile['speed']})")
        if not _call_elevenlabs(processed, beat_file, api_key, voice_id, profile):
            return False
        beat_files.append(beat_file)
        beat_ids.append(beat_id)

    if not beat_files:
        print("  ERROR: 생성할 TTS 없음")
        return False

    beat_durations: list[dict] = []
    for bf, bid in zip(beat_files, beat_ids):
        dur = _get_audio_duration(bf)
        beat_type = bid.rstrip("0123456789").lower()
        gap = BEAT_GAP_AFTER.get(beat_type, DEFAULT_GAP)
        beat_durations.append({"id": bid, "duration": round(dur, 3), "gap_after": gap})
        print(f"  [{bid}] 길이={dur:.2f}s, 갭={gap:.2f}s")

    if beat_durations:
        beat_durations[-1]["gap_after"] = 0.0

    gap_files: dict[float, Path] = {}
    for bd in beat_durations:
        g = bd["gap_after"]
        if g > 0 and g not in gap_files:
            gap_path = tts_dir / f"_gap_{g:.2f}s.mp3"
            if _generate_silence(g, gap_path):
                gap_files[g] = gap_path
                print(f"  갭 생성: {g:.2f}s")

    merged_file = version_dir / f"tts_{version}.mp3"
    if len(beat_files) == 1 and beat_durations[0]["gap_after"] == 0:
        import shutil
        shutil.copy2(beat_files[0], merged_file)
    else:
        list_path = tts_dir / "_concat.txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for i, bf in enumerate(beat_files):
                f.write(f"file '{bf.name}'\n")
                gap = beat_durations[i]["gap_after"]
                if gap > 0 and gap in gap_files:
                    f.write(f"file '{gap_files[gap].name}'\n")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                 "-i", str(list_path), "-c", "copy", str(merged_file)],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                cwd=str(tts_dir), timeout=30
            )
            if result.returncode != 0:
                print(f"  ffmpeg concat 실패: {result.stderr[:200]}")
                return False
        except FileNotFoundError:
            print("  ffmpeg 없음 — 비트별 mp3를 직접 합칩니다")
            with open(merged_file, "wb") as out:
                for i, bf in enumerate(beat_files):
                    out.write(bf.read_bytes())

    total_audio = sum(bd["duration"] for bd in beat_durations)
    total_gaps = sum(bd["gap_after"] for bd in beat_durations)
    print(f"\n  TTS={total_audio:.1f}s + 갭={total_gaps:.1f}s = {total_audio + total_gaps:.1f}s")

    script["meta"]["tts"] = {
        "file": f"tts_{version}.mp3",
        "timing_file": "",
        "timing_stale": True,
        "chars": total_chars,
        "beats_count": len(beat_files),
        "beat_durations": beat_durations,
    }
    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"\n  TTS 완료: {merged_file.name} ({len(beat_files)}비트, {total_chars}자)")
    return True


def run_whisper(version_dir: Path) -> bool:
    script_path = version_dir / "script.json"
    if not script_path.exists():
        return False
    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)

    tts_file = script["meta"]["tts"].get("file", "")
    if not tts_file:
        print("  ERROR: TTS 파일 경로 없음")
        return False

    tts_path = version_dir / tts_file
    if not tts_path.exists():
        parent_edit = version_dir.parent
        tts_path = parent_edit / tts_file
    if not tts_path.exists():
        print(f"  ERROR: TTS 파일 없음: {tts_file}")
        return False

    timing_file = f"{Path(tts_file).stem}_timing.json"
    timing_path = version_dir / timing_file

    print(f"  Whisper 입력: {tts_path}")
    print(f"  타이밍 출력: {timing_path}")

    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, "-c", f"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from faster_whisper import WhisperModel
model = WhisperModel("large-v3", device="cpu", compute_type="int8")
segments, _ = model.transcribe("{str(tts_path).replace(chr(92), '/')}", word_timestamps=True)
words = []
for seg in segments:
    for w in seg.words:
        words.append({{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}})
with open("{str(timing_path).replace(chr(92), '/')}", "w", encoding="utf-8") as f:
    json.dump({{"words": words}}, f, ensure_ascii=False, indent=2)
print(f"Whisper 완료: {{len(words)}}개 단어")
"""],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=120
        )
        if result.returncode == 0:
            if result.stdout:
                print(result.stdout.strip())
            script["meta"]["tts"]["timing_file"] = timing_file
            script["meta"]["tts"]["timing_stale"] = False
            with open(script_path, "w", encoding="utf-8") as f:
                json.dump(script, f, ensure_ascii=False, indent=2)
            return True
        else:
            err = (result.stderr or "")[:200]
            print(f"  Whisper 에러: {err}")
            return False
    except subprocess.TimeoutExpired:
        print("  Whisper 타임아웃 (120초)")
        return False
    except FileNotFoundError:
        print("  faster-whisper 미설치")
        return False


def readjust_timing(version_dir: Path) -> bool:
    script_path = version_dir / "script.json"
    config_path = version_dir / "config.json"

    if not script_path.exists():
        print("  ERROR: script.json 없음")
        return False

    with open(script_path, "r", encoding="utf-8") as f:
        script = json.load(f)
    has_config = config_path.exists()
    config = None
    if has_config:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)

    beat_durations = script.get("meta", {}).get("tts", {}).get("beat_durations", [])
    if not beat_durations:
        print("  WARN: beat_durations 없음 — run_tts를 먼저 실행하세요")
        return False

    beats = script["beats"]
    dur_map = {bd["id"]: bd for bd in beat_durations}

    cursor = 0.0
    for beat in beats:
        bd = dur_map.get(beat["id"])
        if not bd:
            continue
        beat["start"] = round(cursor, 3)
        beat["end"] = round(cursor + bd["duration"], 3)
        subs = beat.get("subtitle", [])
        n_subs = len(subs)
        for i, sub in enumerate(subs):
            sub["appear_at"] = round(beat["start"] + (bd["duration"] * i / n_subs) + 0.05, 3)
        cursor = round(beat["end"] + bd["gap_after"], 3)

    total_dur = round(beats[-1]["end"] + TAIL_SECONDS, 1) if beats else 0
    script["meta"]["duration"] = total_dur

    if config:
        config_beats = {cb["id"]: cb for cb in config.get("beats", [])}
        for beat in beats:
            cb = config_beats.get(beat["id"])
            if cb:
                cb["start"] = beat["start"]
                cb["duration"] = round(beat["end"] - beat["start"], 3)
                subs = beat.get("subtitle", [])
                if subs:
                    cb["text"] = [{"content": s["text"]} for s in subs]
        config["meta"]["duration"] = total_dur

    with open(script_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)
    if config:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"  타이밍 재조정 완료: {len(beats)}비트, 총 {total_dur}초")
    for b in beats:
        print(f"    {b['id']}: {b['start']}s → {b['end']}s ({round(b['end'] - b['start'], 2)}s)")

    return True


def _inject_bgm(version_dir: Path):
    """config.json에 공통 BGM이 없으면 자동 주입 (볼륨 0.15)."""
    config_path = version_dir / "config.json"
    if not config_path.exists() or not BGM_COMMON.exists():
        return
    config = json.loads(config_path.read_text(encoding="utf-8"))
    audio = config.setdefault("audio", {})
    if not audio.get("bgm"):
        import shutil
        dst = version_dir / "bgm.mp3"
        shutil.copy2(BGM_COMMON, dst)
        audio["bgm"] = "bgm.mp3"
        audio.setdefault("bgm_volume", 0.15)
        config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [BGM] 공통 BGM 주입 (볼륨 {audio['bgm_volume']})")


def run_build(version_dir: Path) -> bool:
    _inject_bgm(version_dir)
    build_script = HARNESS_DIR / "build_reel.py"
    result = subprocess.run(
        [sys.executable, str(build_script), str(version_dir), "--verify"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  BUILD FAIL: {result.stderr[:300]}")
        return False
    return True


def _cleanup_render_workdirs(renders_dir: Path):
    import shutil
    for d in renders_dir.glob("work-*"):
        if d.is_dir():
            try:
                shutil.rmtree(d, ignore_errors=True)
            except Exception:
                pass


def run_cover(version_dir: Path, pain: str | None = None, good: str | None = None) -> bool:
    """커버이미지 자동생성. script.json cover 섹션 또는 CLI 인자 사용."""
    gen_script = HARNESS_DIR / "gen_cover.py"
    if not gen_script.exists():
        print("  WARN: gen_cover.py 없음 — 커버 생성 스킵")
        return False

    cmd = [sys.executable, str(gen_script), str(version_dir)]
    if pain:
        cmd += ["--pain", pain]
    if good:
        cmd += ["--good", good]

    result = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  COVER FAIL: {result.stderr[:300]}")
        return False
    return True


def run_deliver(version_dir: Path) -> bool:
    """확정된 릴스를 마이박스에 복사하고 캡션을 텔레그램으로 전송."""
    send_script = HARNESS_DIR / "send_caption.py"
    if not send_script.exists():
        print("  ERROR: send_caption.py 없음")
        return False

    result = subprocess.run(
        [sys.executable, str(send_script), str(version_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=30,
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  DELIVER FAIL: {result.stderr[:300]}")
        return False
    return True


def run_render(version_dir: Path, preview: bool = False) -> bool:
    output_name = version_dir.parent.parent.name
    renders_dir = version_dir / "renders"
    renders_dir.mkdir(exist_ok=True)

    _cleanup_render_workdirs(renders_dir)

    npx_cmd = r"C:\Program Files\nodejs\npx.cmd"
    if not os.path.exists(npx_cmd):
        npx_cmd = "npx"

    if preview:
        output_file = renders_dir / f"{output_name}_preview.mp4"
        cmd = [npx_cmd, "hyperframes", "render", str(version_dir),
               "-f", "30", "-q", "draft", "-o", str(output_file)]
        print(f"  프리뷰 렌더 (FHD 30fps draft)...")
    else:
        output_file = renders_dir / f"{output_name}_4k.mp4"
        cmd = [npx_cmd, "hyperframes", "render", str(version_dir),
               "-f", "30", "--resolution", "portrait-4k", "-q", "standard", "-o", str(output_file)]
        print(f"  최종 렌더 (4K 30fps standard)...")

    render_timeout = 300 if preview else 1200
    print(f"  출력: {output_file}")
    # NAS(UNC) 경로에서 cwd 상속 시 CMD.EXE가 UNC를 못 잡으므로 로컬 디렉터리로 고정
    import tempfile as _tempfile
    _local_cwd = _tempfile.gettempdir()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True,
                                encoding="utf-8", errors="replace", timeout=render_timeout,
                                cwd=_local_cwd)
    except subprocess.TimeoutExpired:
        print(f"  RENDER TIMEOUT ({render_timeout}s) — 4K는 NAS에서 오래 걸릴 수 있음")
        if output_file.exists() and output_file.stat().st_size > 1024 * 1024:
            size_mb = output_file.stat().st_size / 1024 / 1024
            print(f"  부분 출력 존재: {size_mb:.1f}MB")
        return False
    if result.returncode != 0:
        print(f"  RENDER FAIL: {result.stderr[:300]}")
        return False
    size_mb = output_file.stat().st_size / 1024 / 1024 if output_file.exists() else 0
    print(f"  렌더 완료: {size_mb:.1f}MB")
    return True


def cmd_scan(args):
    print(f"\n  === Phase 1: 미디어 스캔 - {args.product} ===\n")
    manifest = scan_product(args.product)

    if "error" in manifest:
        print(f"  ERROR: {manifest['error']}")
        sys.exit(1)

    product_dir = VIDEO_ROOT / args.product
    product_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = product_dir / "media_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    s = manifest["summary"]
    print(f"  상품: {manifest['product']}")
    print(f"  폴더: {manifest['product_folder']}")
    print(f"  릴스 타입: {manifest['reel_type']}")
    print(f"  영상기록: {'있음' if manifest['has_video_record'] else '없음'}")
    print(f"  이미지: {s['total_images']}개, 영상: {s['total_videos']}개, GIF: {s['total_gifs']}개")
    print(f"  카테고리: {s['categories']}")
    print(f"  상품정보: {'있음' if manifest['product_info'] else '없음'}")
    print(f"\n  매니페스트 저장: {manifest_path}")
    print(f"\n  Next: Claude가 script.json + config.json 생성 → 사용자 검수")


def cmd_build(args):
    version = args.version or "v1"
    force_tts = getattr(args, "force_tts", False)
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    print(f"\n  === Phase 2: 빌드+렌더 - {args.product}/{version} ===\n")

    print("  [1/8] TTS 생성...")
    if not run_tts(version_dir, force=force_tts):
        print("\n  TTS FAIL - 중단")
        sys.exit(1)

    print("\n  [2/8] 타이밍 재조정...")
    if not readjust_timing(version_dir):
        print("\n  타이밍 재조정 FAIL - 중단")
        sys.exit(1)

    print("\n  [3/8] Whisper 타이밍 추출...")
    if not run_whisper(version_dir):
        print("\n  Whisper FAIL - TTS 성공, 타이밍 수동 필요")
        sys.exit(1)

    print("\n  [4/8] HTML 빌드...")
    if not run_build(version_dir):
        print("\n  BUILD FAIL - 중단")
        sys.exit(1)

    print("\n  [5/8] 커버이미지 생성...")
    run_cover(version_dir)

    print("\n  [6/8] 프리뷰 렌더 (FHD)...")
    run_render(version_dir, preview=True)

    print("\n  [7/8] 최종 렌더 (4K)...")
    final_ok = run_render(version_dir, preview=False)

    if final_ok:
        print("\n  [8/8] 마이박스 + 텔레그램 전달...")
        run_deliver(version_dir)

    print(f"\n  === 완료 ===")


def cmd_cover(args):
    version = args.version or "v1"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    print(f"\n  === 커버이미지 생성 - {args.product}/{version} ===\n")
    pain = args.pain.replace("\\n", "\n") if args.pain else None
    good = args.good.replace("\\n", "\n") if args.good else None
    run_cover(version_dir, pain=pain, good=good)


def cmd_render(args):
    version = args.version or "v1"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    preview = args.preview
    print(f"\n  === 렌더 - {args.product}/{version} ({'FHD preview' if preview else '4K final'}) ===\n")
    run_render(version_dir, preview=preview)


def cmd_tts(args):
    version = args.version or "v1"
    force_tts = getattr(args, "force_tts", False)
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    print(f"\n  === TTS 생성 - {args.product}/{version} ===\n")
    if not run_tts(version_dir, force=force_tts):
        print("\n  TTS FAIL")
        sys.exit(1)

    print("\n  타이밍 재조정...")
    readjust_timing(version_dir)

    if not args.skip_whisper:
        print("\n  Whisper 타이밍 추출...")
        if not run_whisper(version_dir):
            print("\n  Whisper FAIL — TTS는 성공, 타이밍은 수동 추출 필요")
            sys.exit(1)

    print("\n  === TTS 완료 ===")


def cmd_face_frame(args):
    version = args.version or "v1"
    product_type = args.type or "upper"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    config_path = version_dir / "config.json"

    if not config_path.exists():
        print(f"  ERROR: config.json 없음: {config_path}")
        sys.exit(1)

    print(f"\n  === 얼굴 자동 프레이밍 - {args.product}/{version} ({product_type}) ===\n")

    try:
        from face_detect import auto_frame_config
    except ImportError:
        print("  ERROR: face_detect 모듈 없음")
        sys.exit(1)

    if args.dry_run:
        print("  [DRY-RUN] 변경 없이 추천값만 표시\n")
        result = auto_frame_config(config_path, product_type=product_type, dry_run=True)
        for d in result["details"]:
            cut_id = d["cut"]
            current = d.get("current", {})
            suggested = d.get("suggested", {})
            print(f"  {cut_id} ({d['source']})")
            print(f"    현재: scale={current.get('scale', '-')} originY={current.get('originY', '-')} face_hide={current.get('face_hide', '-')}")
            print(f"    추천: scale={suggested.get('scale')} originY={suggested.get('originY')} — {suggested.get('reason', '')}")
            print()
    else:
        result = auto_frame_config(config_path, product_type=product_type, dry_run=False)
        print(f"  업데이트: {result['updated']}컷, 스킵: {result['skipped']}컷\n")
        for d in result["details"]:
            framing = d.get("framing", {})
            reason = framing.get("reason", d.get("reason", ""))
            print(f"    {d['cut']}: {d.get('action', '')} — {reason}")
        print(f"\n  config.json 저장 완료: {config_path}")


def cmd_full(args):
    version = args.version or "v1"
    force_tts = getattr(args, "force_tts", False)
    print(f"\n  === 풀 파이프라인 - {args.product}/{version} ===\n")

    # Phase 1: 스캔
    print("  [Phase 1] 미디어 스캔...")
    manifest = scan_product(args.product)
    if "error" in manifest:
        print(f"  ERROR: {manifest['error']}")
        sys.exit(1)

    product_dir = VIDEO_ROOT / args.product
    product_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = product_dir / "media_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    s = manifest["summary"]
    print(f"  상품: {manifest['product']} ({manifest['reel_type']})")
    print(f"  이미지: {s['total_images']}개, 영상: {s['total_videos']}개")
    print(f"  매니페스트: {manifest_path}")

    # 검수 대기 체크
    version_dir = product_dir / "edit" / version
    script_path = version_dir / "script.json"
    config_path = version_dir / "config.json"

    if not script_path.exists() or not config_path.exists():
        print(f"\n  ── 검수 대기 ──")
        print(f"  script.json 또는 config.json 없음.")
        print(f"  Claude가 media_manifest.json 기반으로 생성해야 합니다.")
        print(f"  생성 후 다시 실행: python auto_reel.py full \"{args.product}\"")
        return

    # Phase 2: 빌드
    print(f"\n  [Phase 2] TTS + 빌드 + 렌더\n")

    print("  [1/9] TTS 생성...")
    if not run_tts(version_dir, force=force_tts):
        print("\n  TTS FAIL - 중단")
        sys.exit(1)

    print("\n  [2/9] 타이밍 재조정...")
    if not readjust_timing(version_dir):
        print("\n  타이밍 재조정 FAIL - 수동 확인 필요")
        sys.exit(1)

    print("\n  [3/9] Whisper 타이밍 추출...")
    if not run_whisper(version_dir):
        print("\n  Whisper FAIL - TTS 성공했으나 타이밍 추출 실패")
        print("  수동 추출 후 build 서브커맨드 실행 가능")
        sys.exit(1)

    print("\n  [4/9] HTML 빌드...")
    if not run_build(version_dir):
        print("\n  BUILD FAIL - 중단")
        sys.exit(1)

    print("\n  [5/9] Sync 검증...")
    verify_result = subprocess.run(
        [sys.executable, str(HARNESS_DIR / "sync_verify.py"), str(version_dir)],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    print(verify_result.stdout)
    if verify_result.returncode != 0:
        print("\n  VERIFY FAIL - sync_verify 오류 확인 필요")
        sys.exit(1)

    print("\n  [6/9] 커버이미지 생성...")
    run_cover(version_dir)

    print("\n  [7/9] 프리뷰 렌더 (FHD)...")
    preview_ok = run_render(version_dir, preview=True)

    print("\n  [8/9] 최종 렌더 (4K)...")
    final_ok = run_render(version_dir, preview=False)

    if final_ok:
        print("\n  [9/9] 마이박스 + 텔레그램 전달...")
        run_deliver(version_dir)

    renders_dir = version_dir / "renders"
    if preview_ok and final_ok:
        print(f"\n  === 풀 파이프라인 완료 ===")
    elif not final_ok:
        print(f"\n  === 파이프라인 완료 (4K 렌더 실패 — render 서브커맨드로 재시도) ===")
    else:
        print(f"\n  === 파이프라인 완료 (렌더 일부 실패) ===")
    print(f"  렌더 출력: {renders_dir}")


def cmd_deliver(args):
    version = args.version or "v1"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    print(f"\n  === 전달 - {args.product}/{version} ===\n")
    print("  마이박스 복사 + 텔레그램 캡션 전송...")
    if not run_deliver(version_dir):
        sys.exit(1)
    print(f"\n  === 전달 완료 ===")


def cmd_spec(args):
    version = args.version or "v1"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    print(f"\n  === capcut_spec 생성 - {args.product}/{version} ===\n")
    try:
        spec_path = generate_capcut_spec(
            version_dir,
            audio_mode=args.audio_mode,
            bgm_path=args.bgm_path or "",
            loop=args.loop,
            overlay_preset=args.overlay_preset,
        )
        print(f"\n  Next: python auto_reel.py render-ff \"{args.product}\" --version {version}")
    except FileNotFoundError as e:
        print(f"  ERROR: {e}")
        sys.exit(1)


def cmd_render_ff(args):
    version = args.version or "v1"
    version_dir = VIDEO_ROOT / args.product / "edit" / version
    if not version_dir.exists():
        print(f"  ERROR: 버전 디렉토리 없음: {version_dir}")
        sys.exit(1)

    spec_path = version_dir / "capcut_spec.json"
    if not spec_path.exists():
        print(f"  capcut_spec.json 없음 — 먼저 spec 커맨드 실행")
        print(f"  python auto_reel.py spec \"{args.product}\" --version {version}")
        sys.exit(1)

    print(f"\n  === FFmpeg 렌더 - {args.product}/{version} ===\n")

    # [1/3] capcut_spec → EDL 변환
    print("  [1/3] capcut_spec → EDL 변환...")
    try:
        edl_path = capcut_to_edl(spec_path)
    except Exception as e:
        print(f"  EDL 변환 FAIL: {e}")
        sys.exit(1)

    if args.dry_run:
        print(f"  [DRY-RUN] EDL: {edl_path}")
        return

    # [2/3] render.py 호출 (EDL 기반)
    print("\n  [2/3] FFmpeg 렌더...")
    render_script = HELPERS_DIR / "render.py"
    renders_dir = version_dir / "renders"
    renders_dir.mkdir(exist_ok=True)

    tts_merged = version_dir / f"tts_{version}.mp3"
    has_tts = tts_merged.exists() and not getattr(args, "no_audio", False)
    final_out = renders_dir / f"{args.product}_ff.mp4"

    if has_tts:
        render_target = renders_dir / "_intermediate.mp4"
    else:
        render_target = final_out

    render_cmd = [
        sys.executable, str(render_script), str(edl_path),
        "-o", str(render_target), "--no-loudnorm",
    ]
    if getattr(args, "no_subs", False):
        render_cmd.append("--no-subtitles")

    result = subprocess.run(render_cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=600)
    print(result.stdout)
    if result.returncode != 0:
        print(f"  RENDER FAIL: {result.stderr[:500]}")
        sys.exit(1)

    if not has_tts:
        size_mb = final_out.stat().st_size / (1024 * 1024)
        print(f"  렌더 완료 (TTS없음): {final_out} ({size_mb:.1f}MB)")
        return

    # [3/3] TTS + BGM 오디오 합성
    print("\n  [3/3] TTS+BGM 오디오 합성...")
    bgm = BGM_COMMON

    if bgm.exists():
        audio_cmd = [
            "ffmpeg", "-y",
            "-i", str(render_target),
            "-i", str(tts_merged),
            "-i", str(bgm),
            "-filter_complex",
            "[1:a]apad[tts];[2:a]aloop=loop=-1:size=2147483647,volume=0.15[bgm];"
            "[tts][bgm]amix=inputs=2:duration=first[aout]",
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final_out),
        ]
    else:
        audio_cmd = [
            "ffmpeg", "-y",
            "-i", str(render_target),
            "-i", str(tts_merged),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            str(final_out),
        ]

    result = subprocess.run(audio_cmd, capture_output=True, text=True,
                            encoding="utf-8", errors="replace", timeout=120)
    if result.returncode != 0:
        print(f"  오디오 합성 FAIL: {result.stderr[:300]}")
        import shutil
        shutil.move(str(render_target), str(final_out))
        print(f"  오디오 없이 저장: {final_out}")
    else:
        render_target.unlink(missing_ok=True)
        size_mb = final_out.stat().st_size / (1024 * 1024)
        print(f"  렌더 완료: {final_out} ({size_mb:.1f}MB)")


def main():
    parser = argparse.ArgumentParser(description="릴스 풀자동화 오케스트레이터")
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Phase 1: 미디어 스캔+분류")
    p_scan.add_argument("product", help="상품명")
    p_scan.set_defaults(func=cmd_scan)

    p_build = sub.add_parser("build", help="Phase 2: TTS→build→verify→render")
    p_build.add_argument("product", help="상품명")
    p_build.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_build.add_argument("--force-tts", action="store_true", help="기존 TTS 무시하고 재생성")
    p_build.set_defaults(func=cmd_build)

    p_render = sub.add_parser("render", help="렌더만 실행")
    p_render.add_argument("product", help="상품명")
    p_render.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_render.add_argument("--preview", action="store_true", help="FHD 프리뷰 (기본: 4K)")
    p_render.set_defaults(func=cmd_render)

    p_tts = sub.add_parser("tts", help="TTS만 단독 실행")
    p_tts.add_argument("product", help="상품명")
    p_tts.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_tts.add_argument("--skip-whisper", action="store_true", help="Whisper 생략")
    p_tts.add_argument("--force-tts", action="store_true", help="기존 TTS 무시하고 재생성")
    p_tts.set_defaults(func=cmd_tts)

    p_face = sub.add_parser("face-frame", help="얼굴 자동 감지 → config.json framing 자동 설정")
    p_face.add_argument("product", help="상품명")
    p_face.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_face.add_argument("--type", default="upper", choices=["upper", "lower", "detail"], help="상품 유형")
    p_face.add_argument("--dry-run", action="store_true", help="변경 없이 추천값만 표시")
    p_face.set_defaults(func=cmd_face_frame)

    p_full = sub.add_parser("full", help="풀 파이프라인: scan→검수→build→render")
    p_full.add_argument("product", help="상품명")
    p_full.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_full.add_argument("--force-tts", action="store_true", help="기존 TTS 무시하고 재생성")
    p_full.set_defaults(func=cmd_full)

    p_cover = sub.add_parser("cover", help="커버이미지 자동생성")
    p_cover.add_argument("product", help="상품명")
    p_cover.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_cover.add_argument("--pain", default=None, help="Pain 텍스트 (줄바꿈: \\n)")
    p_cover.add_argument("--good", default=None, help="Good 텍스트 (줄바꿈: \\n)")
    p_cover.set_defaults(func=cmd_cover)

    p_deliver = sub.add_parser("deliver", help="마이박스 복사 + 텔레그램 캡션 전송")
    p_deliver.add_argument("product", help="상품명")
    p_deliver.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_deliver.set_defaults(func=cmd_deliver)

    p_spec = sub.add_parser("spec", help="v2 spec 생성: config+script → capcut_spec.json")
    p_spec.add_argument("product", help="상품명")
    p_spec.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_spec.add_argument("--audio-mode", default="tts", choices=["tts", "bgm_only", "silent"],
                        help="오디오 모드 (기본: tts)")
    p_spec.add_argument("--bgm-path", default=None, help="BGM 파일 경로 (bgm_only 모드 시)")
    p_spec.add_argument("--loop", action="store_true", help="루프 크로스페이드 활성화")
    p_spec.add_argument("--overlay-preset", default="default",
                        choices=["default", "minimal", "none"], help="오버레이 프리셋")
    p_spec.set_defaults(func=cmd_spec)

    p_rff = sub.add_parser("render-ff", help="FFmpeg 렌더: capcut_spec.json → mp4")
    p_rff.add_argument("product", help="상품명")
    p_rff.add_argument("--version", default=None, help="버전 (기본: v1)")
    p_rff.add_argument("--dry-run", action="store_true", help="렌더 없이 정보만 출력")
    p_rff.add_argument("--no-audio", action="store_true", help="오디오 생략")
    p_rff.add_argument("--no-subs", action="store_true", help="자막 생략")
    p_rff.set_defaults(func=cmd_render_ff)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
