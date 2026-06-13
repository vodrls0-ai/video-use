"""script.json + tts_timing.json → HTML 자막 블록 + JS 애니메이션 코드 생성.

SSOT인 script.json을 읽어서:
  1. index.html에 삽입할 텍스트 오버레이 HTML 블록
  2. GSAP 타임라인 텍스트 애니메이션 JS 코드
를 자동 생성한다. tts_timing.json의 워드 타이밍으로 appear_at를 정밀 보정.

Usage:
    python generate_subtitles.py <v_dir>
    python generate_subtitles.py <v_dir> --inject   # index.html에 직접 삽입
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SIZE_MAP = {
    "lg": "cap-lg",
    "xl": "cap-xl",
    "md": "cap-md",
    "sm": "cap-sm",
    "price": "cap-price",
}

ANIMATION_JS = {
    "spring-scale-in": lambda sel, t, dur: f'springWords("{sel}", {t}, {dur});',
    "spring-words": lambda sel, t, dur: f'springWords("{sel}", {t}, {dur});',
    "rise-words": lambda sel, t, dur: f'riseWords("{sel}", {t}, {dur});',
    "per-character-rise": lambda sel, t, dur: f'riseWords("{sel}", {t}, {dur});',
    "soft-blur-in": lambda sel, t, dur: f'blurResolve("{sel}", {t}, {dur});',
    "mask-reveal-up": lambda sel, t, _dur: (
        f'tl.set("{sel}", {{clipPath:"inset(100% 0 0 0)"}}, {t - 0.33:.2f});\n'
        f'    tl.to("{sel}", {{clipPath:"inset(0% 0 0 0)", duration:0.30, ease:"power3.out"}}, {t});'
    ),
    "stagger-from-center": lambda sel, t, dur: (
        f'(function() {{\n'
        f'      var ws = document.querySelectorAll("{sel} .w");\n'
        f'      var mid = (ws.length - 1) / 2;\n'
        f'      ws.forEach(function(w, i) {{\n'
        f'        var delay = Math.abs(i - mid) * 0.10;\n'
        f'        var dir = i < mid ? -60 : (i > mid ? 60 : 0);\n'
        f'        tl.fromTo(w, {{scale:0, opacity:0, x:dir, rotation:dir*0.3}},\n'
        f'          {{scale:1, opacity:1, x:0, rotation:0, duration:0.30, ease:"elastic.out(1,0.5)"}}, {t} + delay);\n'
        f'      }});\n'
        f'    }})();'
    ),
    "per-word-crossfade": lambda sel, t, _dur: (
        f'(function() {{\n'
        f'      var ws = document.querySelectorAll("{sel} .w");\n'
        f'      ws.forEach(function(w, i) {{\n'
        f'        tl.fromTo(w, {{opacity:0, y:50, scale:0.7, filter:"blur(8px)"}},\n'
        f'          {{opacity:1, y:0, scale:1, filter:"blur(0px)", duration:0.35, ease:"power3.out"}}, {t} + i*0.10);\n'
        f'      }});\n'
        f'    }})();'
    ),
    "shared-axis-y": lambda sel, t, _dur: (
        f'(function() {{\n'
        f'      var ws = document.querySelectorAll("{sel} .w");\n'
        f'      ws.forEach(function(w, i) {{\n'
        f'        tl.fromTo(w, {{y:150, opacity:0, scale:0.3, rotation:20}},\n'
        f'          {{y:0, opacity:1, scale:1, rotation:0, duration:0.40, ease:"elastic.out(1.1,0.45)"}}, {t} + i*0.08);\n'
        f'      }});\n'
        f'    }})();'
    ),
    "spring-scale-in+shimmer": lambda sel, t, _dur: (
        f'tl.fromTo("{sel}", {{scale:0, opacity:0, rotation:-10}},\n'
        f'      {{scale:1.2, opacity:1, rotation:0, duration:0.25, ease:"elastic.out(1.5,0.3)"}}, {t});\n'
        f'    tl.to("{sel}", {{scale:1, duration:0.15, ease:"power2.out"}}, {t + 0.25:.2f});\n'
        f'    tl.to("{sel}", {{scale:1.12, duration:0.12, ease:"sine.inOut", yoyo:true, repeat:2}}, {t + 0.37:.2f});'
    ),
}


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def find_word_time(timing: dict | None, word: str, beat_start: float, beat_end: float) -> float | None:
    """tts_timing.json에서 beat 구간 내 특정 단어의 시작 시간을 찾는다."""
    if not timing:
        return None
    clean = re.sub(r"[.,?!]", "", word)
    for w in timing.get("words", []):
        tw = re.sub(r"[.,?!]", "", w["word"])
        if tw == clean and w["start"] >= beat_start - 0.5 and w["end"] <= beat_end + 0.5:
            return w["start"]
    for w in timing.get("words", []):
        tw = re.sub(r"[.,?!]", "", w["word"])
        if clean in tw and w["start"] >= beat_start - 0.5 and w["end"] <= beat_end + 0.5:
            return w["start"]
    return None


def refine_appear_at(sub: dict, timing: dict | None, beat: dict) -> float:
    """tts_timing에서 첫 단어 시작 시간을 찾아 appear_at를 보정한다."""
    words = sub.get("words", [])
    if not words or not timing:
        return sub.get("appear_at", beat["start"])

    t = find_word_time(timing, words[0], beat["start"], beat["end"])
    if t is not None:
        return round(t, 2)
    return sub.get("appear_at", beat["start"])


def build_word_span(word: str, emphasis_list: list[str]) -> str:
    cls = "w"
    for emp in emphasis_list:
        if word == emp:
            cls = "w em"
            break
    return f'<span class="{cls}">{word}</span>'


def generate_html_block(beat: dict, track_idx: int) -> str:
    """한 beat의 HTML 자막 블록을 생성한다."""
    bid = beat["id"]
    start = beat["start"]
    duration = round(beat["end"] - beat["start"] + 0.30, 2)
    subs = beat.get("subtitle", [])

    if not subs:
        return ""

    lines = []
    lines.append(
        f'    <div id="{bid}-text" class="clip text-overlay" '
        f'data-start="{start}" data-duration="{duration}" data-track-index="{track_idx}">'
    )

    if len(subs) == 1:
        sub = subs[0]
        cap_cls = SIZE_MAP.get(sub.get("size", "md"), "cap-md")
        words = sub.get("words", [])
        emphasis = sub.get("emphasis", [])
        text = sub.get("text", "")

        text_lines = text.split("\n")
        word_spans = []
        word_idx = 0
        for li, line in enumerate(text_lines):
            line_words = line.split()
            for w in line_words:
                if word_idx < len(words):
                    word_spans.append(build_word_span(words[word_idx], emphasis))
                else:
                    word_spans.append(build_word_span(w, emphasis))
                word_idx += 1
            if li < len(text_lines) - 1:
                word_spans.append("<br>")

        inner = " ".join(word_spans).replace(" <br> ", "<br>")
        lines.append(
            f'      <div class="ta"><div id="{sub["id"]}" class="cap {cap_cls}">'
            f'{inner}</div></div>'
        )
    else:
        lines.append('      <div class="ta">')
        for i, sub in enumerate(subs):
            cap_cls = SIZE_MAP.get(sub.get("size", "md"), "cap-md")
            words = sub.get("words", [])
            emphasis = sub.get("emphasis", [])
            text = sub.get("text", "")

            text_lines = text.split("\n")
            word_spans = []
            word_idx = 0
            for li, line in enumerate(text_lines):
                line_words = line.split()
                for w in line_words:
                    if word_idx < len(words):
                        word_spans.append(build_word_span(words[word_idx], emphasis))
                    else:
                        word_spans.append(build_word_span(w, emphasis))
                    word_idx += 1
                if li < len(text_lines) - 1:
                    word_spans.append("<br>")

            inner = " ".join(word_spans).replace(" <br> ", "<br>")
            opacity_style = ' style="opacity:0"' if i > 0 else ""
            lines.append(
                f'        <div id="{sub["id"]}" class="cap {cap_cls}"{opacity_style}>'
                f'{inner}</div>'
            )
        lines.append('      </div>')

    lines.append('    </div>')
    return "\n".join(lines)


def generate_js_animation(beat: dict, timing: dict | None) -> str:
    """한 beat의 JS 텍스트 애니메이션 코드를 생성한다."""
    subs = beat.get("subtitle", [])
    if not subs:
        return ""

    js_lines = []
    js_lines.append(f'    /* --- {beat["id"]}: text animation --- */')

    for i, sub in enumerate(subs):
        anim = sub.get("animation", "spring-scale-in")
        appear = refine_appear_at(sub, timing, beat)
        sel = f"#{sub['id']}"
        dur = 0.35

        if i > 0:
            js_lines.append(f'    tl.set("{sel}", {{opacity:1}}, {appear});')

        gen = ANIMATION_JS.get(anim)
        if gen:
            js_lines.append(f'    {gen(sel, appear, dur)}')
        else:
            js_lines.append(f'    springWords("{sel}", {appear}, {dur}); /* fallback for: {anim} */')

        if sub.get("emphasis"):
            glow_t = round(appear + 0.25, 2)
            js_lines.append(f'    glowPulse("{sel}", {glow_t});')

    return "\n".join(js_lines)


def inject_into_html(html_path: Path, html_blocks: str) -> bool:
    """index.html의 <!-- TEXT OVERLAYS --> 섹션을 교체한다."""
    if not html_path.exists():
        return False

    text = html_path.read_text(encoding="utf-8")

    pattern = re.compile(
        r'(<!-- ═+ TEXT OVERLAYS ═+ -->\n)'
        r'(.*?)'
        r'(\n\s*<audio)',
        re.DOTALL
    )

    match = pattern.search(text)
    if not match:
        return False

    replacement = match.group(1) + "\n" + html_blocks + "\n" + match.group(3)
    new_text = text[:match.start()] + replacement + text[match.end():]

    html_path.write_text(new_text, encoding="utf-8")
    return True


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_subtitles.py <version_dir> [--inject]")
        sys.exit(1)

    v_dir = Path(sys.argv[1]).resolve()
    do_inject = "--inject" in sys.argv

    script = load_json(v_dir / "script.json")
    if not script:
        sys.exit(f"script.json 없음: {v_dir}")

    tts_cfg = script.get("meta", {}).get("tts", {})
    timing_file = tts_cfg.get("timing_file")
    timing = None
    if timing_file:
        timing = load_json((v_dir / timing_file).resolve())

    beats = script.get("beats", [])

    print(f"\n{'='*60}")
    print(f"  Generate Subtitles — {v_dir.name}")
    print(f"  beats: {len(beats)}, timing: {'✓' if timing else '✗'}")
    print(f"{'='*60}\n")

    html_blocks = []
    js_blocks = []

    for i, beat in enumerate(beats):
        track_idx = 5 if i % 2 == 0 else 6
        html = generate_html_block(beat, track_idx)
        js = generate_js_animation(beat, timing)
        if html:
            html_blocks.append(html)
        if js:
            js_blocks.append(js)

    html_output = "\n".join(html_blocks)
    js_output = "\n\n".join(js_blocks)

    print("═══ HTML BLOCKS ═══\n")
    print(html_output)
    print("\n\n═══ JS ANIMATIONS ═══\n")
    print(js_output)

    out_dir = v_dir / "_generated"
    out_dir.mkdir(exist_ok=True)
    (out_dir / "subtitles.html").write_text(html_output, encoding="utf-8")
    (out_dir / "animations.js").write_text(js_output, encoding="utf-8")
    print(f"\n✓ 저장: {out_dir / 'subtitles.html'}")
    print(f"✓ 저장: {out_dir / 'animations.js'}")

    if do_inject:
        html_path = v_dir / "index.html"
        if inject_into_html(html_path, html_output):
            print(f"✓ index.html 자막 블록 교체 완료")
        else:
            print(f"✗ index.html에 TEXT OVERLAYS 마커 없음 — 수동 삽입 필요")

    if timing:
        print("\n═══ TIMING REFINEMENT ═══\n")
        for beat in beats:
            for sub in beat.get("subtitle", []):
                original = sub.get("appear_at", beat["start"])
                refined = refine_appear_at(sub, timing, beat)
                delta = round(refined - original, 3)
                marker = " ←" if abs(delta) > 0.1 else ""
                print(f"  {sub['id']:8s}  script={original:.2f}  timing={refined:.2f}  Δ={delta:+.3f}s{marker}")

    print(f"\n{'='*60}")
    print(f"  완료")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
