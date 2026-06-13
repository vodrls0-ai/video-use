"""커버이미지 자동생성기.

Usage:
    python gen_cover.py <version_dir>
    python gen_cover.py <version_dir> --pain "텍스트" --good "텍스트"

script.json의 cover 섹션에서 텍스트를 읽거나, CLI 인자로 직접 지정.
config.json sources에서 배경이미지 자동 선택.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1080, 1920
MARGIN_X = 60
TEXT_AREA_W = CANVAS_W - MARGIN_X * 2
FONT_PATH = Path(r"C:\Users\user\AppData\Local\Microsoft\Windows\Fonts\Pretendard-Bold.otf")

PAIN_COLOR = (220, 30, 30)
PAIN_BG = (255, 255, 255, 220)
PAIN_SIZE = 100
GOOD_COLOR = (255, 255, 255)
GOOD_SHADOW = (0, 0, 0, 200)
GOOD_SIZE = 72
OVERLAY_COLOR = (0, 0, 0, 120)
BOX_PAD_X, BOX_PAD_Y = 24, 16
LINE_GAP = 12
SECTION_GAP = 48


def pick_bg_image(config: dict) -> str | None:
    sources = config.get("sources", {}).get("image", {})
    priority = ["styling", "crop", "wear", "detail"]
    for prefix in priority:
        for key, val in sources.items():
            if key.startswith(prefix):
                path = val["path"] if isinstance(val, dict) else val
                if Path(path).exists():
                    return path
    for key, val in sources.items():
        if key.startswith("comp") or key.endswith("logo"):
            continue
        path = val["path"] if isinstance(val, dict) else val
        if Path(path).exists():
            return path
    return None


def wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    if "\n" in text:
        result = []
        for part in text.split("\n"):
            result.extend(wrap_text(part, font, max_width))
        return result
    words = text.split()
    if not words:
        return []
    lines = []
    current = words[0]
    for word in words[1:]:
        test = current + " " + word
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > max_width:
            lines.append(current)
            current = word
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def draw_text_block(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    font: ImageFont.FreeTypeFont,
    x: int,
    y: int,
    color: tuple,
    bg: tuple | None = None,
    shadow: tuple | None = None,
) -> int:
    cy = y
    for line in lines:
        bbox = font.getbbox(line)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        y_offset = -bbox[1]

        if bg:
            bx0 = x - BOX_PAD_X
            by0 = cy - BOX_PAD_Y
            bx1 = x + tw + BOX_PAD_X
            by1 = cy + th + BOX_PAD_Y
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=8, fill=bg)

        if shadow:
            draw.text((x + 3, cy + y_offset + 3), line, font=font, fill=shadow)

        draw.text((x, cy + y_offset), line, font=font, fill=color)
        cy += th + LINE_GAP + (BOX_PAD_Y * 2 if bg else 0)

    return cy


def measure_block(lines: list[str], font: ImageFont.FreeTypeFont, has_bg: bool = False) -> int:
    total = 0
    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        th = bbox[3] - bbox[1]
        total += th + (BOX_PAD_Y * 2 if has_bg else 0)
        if i < len(lines) - 1:
            total += LINE_GAP
    return total


def generate_cover(
    version_dir: Path,
    pain_text: str | None = None,
    good_text: str | None = None,
    bg_override: str | None = None,
) -> Path:
    config_path = version_dir / "config.json"
    script_path = version_dir / "script.json"

    config = json.loads(config_path.read_text(encoding="utf-8")) if config_path.exists() else {}
    script = json.loads(script_path.read_text(encoding="utf-8")) if script_path.exists() else {}

    cover_meta = script.get("meta", {}).get("cover", script.get("cover", {}))
    if not pain_text:
        pain_text = cover_meta.get("pain", "")
    if not good_text:
        good_text = cover_meta.get("good", "")

    if not pain_text and script.get("beats"):
        pain_text = script["beats"][0].get("narration", "")
    if not good_text and len(script.get("beats", [])) > 1:
        good_text = script["beats"][1].get("narration", "")

    bg_key = bg_override or cover_meta.get("bg_source")
    bg_path = None
    if bg_key:
        sources = config.get("sources", {}).get("image", {})
        entry = sources.get(bg_key)
        if entry:
            bg_path = entry["path"] if isinstance(entry, dict) else entry
        elif Path(bg_key).exists():
            bg_path = bg_key
    if not bg_path or not Path(bg_path).exists():
        bg_path = pick_bg_image(config)

    if bg_path and Path(bg_path).exists():
        bg = Image.open(bg_path).convert("RGBA")
        ratio = max(CANVAS_W / bg.width, CANVAS_H / bg.height)
        bg = bg.resize((int(bg.width * ratio), int(bg.height * ratio)), Image.LANCZOS)
        left = (bg.width - CANVAS_W) // 2
        top = (bg.height - CANVAS_H) // 2
        bg = bg.crop((left, top, left + CANVAS_W, top + CANVAS_H))
    else:
        bg = Image.new("RGBA", (CANVAS_W, CANVAS_H), (30, 30, 30, 255))

    overlay = Image.new("RGBA", (CANVAS_W, CANVAS_H), OVERLAY_COLOR)
    bg = Image.alpha_composite(bg, overlay)

    canvas = bg.convert("RGBA")
    txt_layer = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(txt_layer)

    pain_font = ImageFont.truetype(str(FONT_PATH), PAIN_SIZE)
    good_font = ImageFont.truetype(str(FONT_PATH), GOOD_SIZE)

    pain_wrap_w = TEXT_AREA_W - BOX_PAD_X * 2
    pain_lines = wrap_text(pain_text, pain_font, pain_wrap_w) if pain_text else []
    good_lines = wrap_text(good_text, good_font, TEXT_AREA_W) if good_text else []

    pain_h = measure_block(pain_lines, pain_font, has_bg=True) if pain_lines else 0
    good_h = measure_block(good_lines, good_font, has_bg=False) if good_lines else 0
    total_h = pain_h + (SECTION_GAP if pain_lines and good_lines else 0) + good_h

    start_y = (CANVAS_H - total_h) // 2

    cy = start_y
    if pain_lines:
        cy = draw_text_block(draw, pain_lines, pain_font, MARGIN_X, cy, PAIN_COLOR, bg=PAIN_BG)
        cy += SECTION_GAP - LINE_GAP

    if good_lines:
        draw_text_block(draw, good_lines, good_font, MARGIN_X, cy, GOOD_COLOR, shadow=GOOD_SHADOW)

    canvas = Image.alpha_composite(canvas, txt_layer)
    output = canvas.convert("RGB")

    cover_path = version_dir / "cover.jpg"
    output.save(cover_path, "JPEG", quality=92)
    print(f"  [cover] {cover_path} ({cover_path.stat().st_size // 1024}KB)")
    return cover_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="릴스 커버이미지 자동생성")
    parser.add_argument("version_dir", help="버전 디렉토리 경로")
    parser.add_argument("--pain", default=None, help="Pain 텍스트 (줄바꿈: \\n)")
    parser.add_argument("--good", default=None, help="Good 텍스트 (줄바꿈: \\n)")
    parser.add_argument("--bg", default=None, help="배경이미지 경로 또는 config source key")
    args = parser.parse_args()

    v_dir = Path(args.version_dir).resolve()
    if not v_dir.exists():
        sys.exit(f"디렉토리 없음: {v_dir}")

    pain = args.pain.replace("\\n", "\n") if args.pain else None
    good = args.good.replace("\\n", "\n") if args.good else None

    generate_cover(v_dir, pain_text=pain, good_text=good, bg_override=args.bg)


if __name__ == "__main__":
    main()
