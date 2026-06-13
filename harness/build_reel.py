"""config.json + script.json + template.html -> index.html 빌드.

Usage:
    python build_reel.py <version_dir>
    python build_reel.py <version_dir> --verify   # 빌드 후 sync_verify 자동 실행

cuts/text/audio는 정적 HTML로 주입 (hyperframes 호환).
JS 템플릿은 GSAP 타임라인 애니메이션만 담당.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).parent
TEMPLATE_PATH = HARNESS_DIR / "template.html"
FONT_PATH = HARNESS_DIR / "fonts" / "PretendardVariable.woff2"

SIZE_MAP = {"lg": "cap-lg", "xl": "cap-xl", "md": "cap-md", "sm": "cap-sm", "price": "cap-price"}


def resolve_src(cut: dict, sources: dict) -> str:
    pool = sources.get(cut["type"], sources.get("video", sources.get("image", {})))
    entry = pool.get(cut.get("source", ""), {})
    if isinstance(entry, dict) and "path" in entry:
        return entry["path"]
    if isinstance(entry, str):
        return entry
    return f"media/{cut.get('source', 'unknown')}"


def copy_media_to_local(config: dict, v_dir: Path) -> dict:
    """Copy all referenced media to v_dir/media/ and rewrite paths in-memory."""
    media_dir = v_dir / "media"
    media_dir.mkdir(exist_ok=True)
    used_names: set[str] = set()

    def copy_one(rel_path: str) -> str | None:
        abs_src = (v_dir / rel_path).resolve()
        if not abs_src.exists():
            print(f"  [!] Not found: {rel_path}")
            return None
        name = abs_src.name
        if name in used_names:
            stem, suffix = abs_src.stem, abs_src.suffix
            i = 2
            while f"{stem}_{i}{suffix}" in used_names:
                i += 1
            name = f"{stem}_{i}{suffix}"
        used_names.add(name)
        dest = media_dir / name
        if not dest.exists() or dest.stat().st_mtime < abs_src.stat().st_mtime:
            shutil.copy2(abs_src, dest)
            print(f"  [cp] {name}")
        return f"media/{name}"

    for media_type in config.get("sources", {}):
        pool = config["sources"][media_type]
        for key in pool:
            entry = pool[key]
            path = entry["path"] if isinstance(entry, dict) else entry
            new_path = copy_one(path)
            if new_path:
                if isinstance(entry, dict):
                    entry["path"] = new_path
                else:
                    pool[key] = new_path

    audio = config.get("audio", {})
    for akey in ["tts", "sfx", "bgm"]:
        if audio.get(akey):
            new_path = copy_one(audio[akey])
            if new_path:
                audio[akey] = new_path

    return config


def build_word_span(word: str, emphasis: list[str]) -> str:
    cls = "w em" if word in emphasis else "w"
    return f'<span class="{cls}">{word}</span>'


def generate_cuts_html(config: dict) -> str:
    lines = ["    <!-- ═══ CUTS (auto-generated) ═══ -->"]
    sources = config.get("sources", {})
    beats = config.get("beats", [])

    for bi, beat in enumerate(beats):
        color_cls = " warm" if beat.get("color") == "warm" else ""
        dim_cls = f"dim-{beat.get('dim', 'center')}"
        cuts = beat.get("cuts", [])
        beat_end = beat["start"] + beat["duration"]
        track = 20 + bi

        for ci, cut in enumerate(cuts):
            src = resolve_src(cut, sources)

            lead = 0.20 if ci == 0 and bi > 0 else 0
            clip_start = round(max(0, beat["start"] + cut["start"] - lead), 2)

            if ci < len(cuts) - 1:
                clip_dur = round(cuts[ci + 1]["start"] - cut["start"] + lead + 0.05, 2)
            else:
                clip_dur = round(beat["duration"] - cut["start"] + lead + 0.50, 2)

            obj_pos = cut.get("object_position", "")
            face_hide = cut.get("face_hide", False)
            crop_pct = face_hide if isinstance(face_hide, (int, float)) and face_hide > 1 else (20 if face_hide else 0)

            clip_attrs = f'data-start="{clip_start}" data-duration="{clip_dur}" data-track-index="{track}"'

            if cut["type"] == "video":
                if crop_pct > 0:
                    h = 100 + crop_pct * 2
                    vid_style = f' style="height:{h}%;top:-{crop_pct}%"'
                elif obj_pos:
                    vid_style = f' style="object-position:{obj_pos}"'
                else:
                    vid_style = ""
                media_start_attr = f' data-media-start="{cut["mediaStart"]}"' if "mediaStart" in cut else ""
                lines.append(
                    f'    <video id="{cut["id"]}" class="clip cut{color_cls}" '
                    f'{clip_attrs}{media_start_attr}'
                    f' src="{src}" muted playsinline preload="auto"{vid_style}></video>'
                )
                overlay_track = 40 + bi
                _old_track = f'data-track-index="{track}"'
                _new_track = f'data-track-index="{overlay_track}"'
                overlay_attrs = clip_attrs.replace(_old_track, _new_track)
                lines.append(
                    f'    <div id="{cut["id"]}-o" class="clip cut-overlay" '
                    f'{overlay_attrs}'
                    f'><div class="dim {dim_cls}"></div><div class="vignette"></div></div>'
                )
            else:
                if crop_pct > 0 and not obj_pos:
                    obj_pos = f"center {50 + crop_pct}%"
                pos_style = f' style="object-position:{obj_pos}"' if obj_pos else ""
                media_el = f'<img id="{cut["id"]}-m" src="{src}"{pos_style}>'
                lines.append(
                    f'    <div id="{cut["id"]}" class="clip cut{color_cls}" '
                    f'{clip_attrs}>'
                    f'{media_el}'
                    f'<div class="dim {dim_cls}"></div><div class="vignette"></div>'
                    f'</div>'
                )

    # PIP overlays
    for bi, beat in enumerate(beats):
        pip = beat.get("pip")
        if not pip:
            continue
        pip_src = resolve_src({"type": "image", "source": pip.get("src", "")}, sources)
        pip_scale = pip.get("scale", 0.28)
        pip_w = int(1080 * pip_scale)
        pip_pos = pip.get("position", "bottom-right")
        pos_map = {
            "bottom-right": f"right:40px;bottom:280px",
            "bottom-left": f"left:40px;bottom:280px",
            "top-right": f"right:40px;top:200px",
            "center-right": f"right:40px;top:50%;margin-top:-{pip_w//2}px",
        }
        pos_css = pos_map.get(pip_pos, pos_map["bottom-right"])
        bg_cls = " no-bg" if pip.get("no_bg") else ""
        pip_offset = pip.get("offset", 0.3)
        pip_start = round(beat["start"] + pip_offset, 2)
        pip_hold = pip.get("hold", min(beat["duration"] - 0.3, 2.0))
        pip_dur = round(pip_hold + 0.5, 2)
        lines.append(
            f'    <div id="pip-{bi}" class="clip pip-frame{bg_cls}" '
            f'data-start="{pip_start}" data-duration="{pip_dur}" '
            f'data-track-index="{50 + bi}" '
            f'style="width:{pip_w}px;{pos_css}">'
            f'<img src="{pip_src}">'
            f'</div>'
        )

    return "\n".join(lines)


def generate_text_html(script: dict, config: dict | None = None) -> str:
    lines = ["\n    <!-- ═══ TEXT OVERLAYS (auto-generated, per-subtitle clips) ═══ -->"]

    cfg_beats = {b["id"]: b for b in (config or {}).get("beats", [])}
    sources = (config or {}).get("sources", {})

    for idx, beat in enumerate(script.get("beats", [])):
        subs = beat.get("subtitle", [])
        if not subs:
            continue

        track_idx = 5 if idx % 2 == 0 else 6
        beat_end_padded = beat["end"]

        overlay = cfg_beats.get(beat["id"], {}).get("overlay", {})
        logo_html = ""
        if overlay.get("logo"):
            logo_key = overlay["logo"]
            logo_src = sources.get("image", {}).get(logo_key, f"media/{logo_key}")
            if isinstance(logo_src, dict):
                logo_src = logo_src.get("path", f"media/{logo_key}")
            logo_w = overlay.get("logo_width", 120)
            logo_html = f'<img id="cta-logo" class="cta-logo" src="{logo_src}" style="width:{logo_w}px" alt="">'

        for si, sub in enumerate(subs):
            sub_start = sub.get("appear_at", beat["start"] + si * 0.3)
            if si + 1 < len(subs):
                next_appear = subs[si + 1].get("appear_at", beat["start"] + (si + 1) * 0.3)
                sub_dur = round(next_appear - sub_start, 2)
            else:
                sub_dur = round(beat_end_padded - sub_start, 2)
            sub_dur = max(sub_dur, 0.3)

            is_last_sub_with_logo = logo_html and si == len(subs) - 1
            logo_insert = logo_html if is_last_sub_with_logo else ""

            lines.append(
                f'    <div id="{sub["id"]}-clip" class="clip text-overlay" '
                f'data-start="{sub_start}" data-duration="{sub_dur}" data-track-index="{track_idx}">'
            )
            lines.append(f'      <div class="ta">{logo_insert}{_build_sub_div(sub, False)}</div>')
            lines.append('    </div>')

    return "\n".join(lines)


def _build_sub_div(sub: dict, delayed: bool) -> str:
    cls = SIZE_MAP.get(sub.get("size", "md"), "cap-md")
    emphasis = sub.get("emphasis", [])
    explicit_words = sub.get("words")
    text_lines = sub.get("text", "").split("\n")

    spans = []
    if explicit_words:
        for word in explicit_words:
            spans.append(build_word_span(word, emphasis))
    else:
        for li, line in enumerate(text_lines):
            for w in line.split():
                if not w:
                    continue
                spans.append(build_word_span(w, emphasis))
            if li < len(text_lines) - 1:
                spans.append("<br>")

    inner = " ".join(spans).replace(" <br> ", "<br>")
    op = ' style="opacity:0"' if delayed else ""
    return f'<div id="{sub["id"]}" class="cap {cls}"{op}>{inner}</div>'


def generate_audio_html(config: dict) -> str:
    lines = ["\n    <!-- ═══ AUDIO (auto-generated) ═══ -->"]
    audio = config.get("audio", {})
    dur = config.get("meta", {}).get("duration", 20)

    if audio.get("tts"):
        vol = audio.get("tts_volume", 1.0)
        lines.append(
            f'    <audio id="tts" class="clip" data-start="0" data-duration="{dur}" '
            f'data-track-index="1" src="{audio["tts"]}" data-volume="{vol}"></audio>'
        )
    if audio.get("sfx"):
        vol = audio.get("sfx_volume", 0.5)
        lines.append(
            f'    <audio id="sfx" class="clip" data-start="0" data-duration="{dur}" '
            f'data-track-index="3" src="{audio["sfx"]}" data-volume="{vol}"></audio>'
        )
    if audio.get("bgm"):
        vol = audio.get("bgm_volume", 0.15)
        lines.append(
            f'    <audio id="bgm" class="clip" data-start="0" data-duration="{dur}" '
            f'data-track-index="2" src="{audio["bgm"]}" data-volume="{vol}" loop></audio>'
        )

    return "\n".join(lines)


def build(v_dir: Path) -> Path:
    config_path = v_dir / "config.json"
    script_path = v_dir / "script.json"
    output_path = v_dir / "index.html"

    if not config_path.exists():
        sys.exit(f"config.json 없음: {config_path}")
    if not script_path.exists():
        sys.exit(f"script.json 없음: {script_path}")
    if not TEMPLATE_PATH.exists():
        sys.exit(f"template.html 없음: {TEMPLATE_PATH}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    config = copy_media_to_local(config, v_dir)
    script = json.loads(script_path.read_text(encoding="utf-8"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    if FONT_PATH.exists():
        import shutil
        dst_font = v_dir / "PretendardVariable.woff2"
        if not dst_font.exists():
            shutil.copy2(FONT_PATH, dst_font)

    meta = config.get("meta", {})
    version = meta.get("version", "reel")
    duration = meta.get("duration", 20)

    cuts_html = generate_cuts_html(config)
    text_html = generate_text_html(script, config)
    audio_html = generate_audio_html(config)

    static_html = cuts_html + "\n" + text_html + "\n" + audio_html

    config_json = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    script_json = json.dumps(script, ensure_ascii=False, separators=(",", ":"))
    inject_js = (
        f'<script>\n'
        f'  window.__REEL_CONFIG__ = {config_json};\n'
        f'  window.__REEL_SCRIPT__ = {script_json};\n'
        f'</script>\n'
    )

    html = template.replace('__ID__', f'reel-{version}')
    html = html.replace('__DUR__', str(duration))

    html = html.replace(
        '  <!-- DYNAMIC: cuts + text overlays + audio injected here -->\n'
        '  <div id="dynamic-cuts"></div>\n'
        '  <div id="dynamic-text"></div>\n'
        '  <div id="dynamic-audio"></div>',
        static_html
    )

    gsap_tag = '<script src="https://cdn.jsdelivr.net/npm/gsap@3.14.2/dist/gsap.min.js"></script>'
    html = html.replace(gsap_tag, inject_js + gsap_tag)

    html = re.sub(
        r'/\* ═+\n     1\. BUILD CUTS.*?/\* ═+\n     4\. MOGRAPH FUNCTIONS',
        '/* ═══════════════════════════════════════════\n     4. MOGRAPH FUNCTIONS',
        html, flags=re.DOTALL
    )

    output_path.write_text(html, encoding="utf-8")

    total_cuts = sum(len(b.get("cuts", [])) for b in config.get("beats", []))
    total_subs = sum(len(b.get("subtitle", [])) for b in script.get("beats", []))
    print(f"  Built: {output_path}")
    print(f"  Config: {len(config.get('beats', []))} beats, {total_cuts} cuts")
    print(f"  Script: {len(script.get('beats', []))} beats, {total_subs} subtitles")
    return output_path


def main():
    if len(sys.argv) < 2:
        print("Usage: python build_reel.py <version_dir> [--verify]")
        sys.exit(1)

    v_dir = Path(sys.argv[1]).resolve()
    do_verify = "--verify" in sys.argv

    if not v_dir.is_dir():
        sys.exit(f"디렉토리 없음: {v_dir}")

    print(f"\n{'='*60}")
    print(f"  Build Reel - {v_dir.name}")
    print(f"{'='*60}\n")

    output = build(v_dir)

    if do_verify:
        print(f"\n  Running sync_verify...")
        verify_script = HARNESS_DIR / "sync_verify.py"
        result = subprocess.run(
            [sys.executable, str(verify_script), str(v_dir)],
            capture_output=False, text=True
        )
        if result.returncode != 0:
            print(f"\n  [!] sync_verify FAIL")
        else:
            print(f"\n  [OK] sync_verify PASS")

    # 캡션 자동 전송 + 마이박스 복사
    send_caption_flag = "--no-caption" not in sys.argv
    if send_caption_flag:
        try:
            from send_caption import (
                generate_caption, send_telegram, copy_to_mybox,
                load_json, extract_hook,
            )
            script_data = load_json(v_dir / "script.json")
            product = script_data.get("meta", {}).get("product", v_dir.parent.name)
            beats = script_data.get("beats", [])
            caption = generate_caption(v_dir)
            result = send_telegram(caption, product)
            if result.get("ok"):
                print(f"  [TG] 캡션 전송 완료")
            else:
                print(f"  [TG] 전송 실패: {result}")
            dest = copy_to_mybox(v_dir, extract_hook(beats))
            if dest:
                print(f"  [MyBox] {dest.name}")
        except Exception as e:
            print(f"  [TG] 캡션 전송 스킵: {e}")

    print(f"\n{'='*60}")
    print(f"  완료: {output}")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
