"""새 상품 릴스용 config.json + script.json 스캐폴딩 생성.

Usage:
    python new_reel.py "상품명"
    python new_reel.py "상품명" --version v2      # 기존 상품의 새 버전
    python new_reel.py "상품명" --beats 7          # 비트 수 지정 (기본: 9)
    python new_reel.py "상품명" --duration 15      # 영상 길이 초 (기본: 20)

생성 결과:
    video/<상품명>/edit/v1/config.json
    video/<상품명>/edit/v1/script.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

VIDEO_ROOT = Path(__file__).resolve().parent.parent.parent / "video"

SECTION_PRESETS = {
    3: ["HOOK", "USP", "PRICE"],
    5: ["HOOK", "REACT", "USP", "FEEL", "PRICE"],
    7: ["HOOK", "REACT", "USP", "USP", "FEEL", "LAYER", "PRICE"],
    9: ["HOOK", "REACT", "USP", "USP", "USP", "FEEL", "FEEL", "LAYER", "PRICE"],
}

LABEL_MAP = {
    "HOOK": "hook",
    "REACT": "react",
    "USP": "usp",
    "FEEL": "feel",
    "LAYER": "layer",
    "PRICE": "price",
}


def pick_sections(n: int) -> list[str]:
    if n in SECTION_PRESETS:
        return SECTION_PRESETS[n]
    if n < 3:
        return ["HOOK"] + ["USP"] * (n - 2) + ["PRICE"] if n >= 2 else ["HOOK"]
    base = SECTION_PRESETS[min(k for k in SECTION_PRESETS if k >= n)] if n <= 9 else SECTION_PRESETS[9]
    while len(base) < n:
        base.insert(-1, "USP")
    return base[:n]


def make_config(product: str, version: str, duration: int, num_beats: int) -> dict:
    sections = pick_sections(num_beats)
    beat_dur = round(duration / num_beats, 2)
    beats = []
    t = 0.0

    for i, section in enumerate(sections):
        bid = f"b{i + 1}"
        label_base = LABEL_MAP.get(section, section.lower())
        usp_count = sum(1 for s in sections[:i] if s == section)
        label = f"{label_base}-{usp_count + 1}" if sections.count(section) > 1 and section not in ("HOOK", "PRICE") else label_base

        d = round(beat_dur, 2)
        if i == num_beats - 1:
            d = round(duration - t, 2)

        beats.append({
            "id": bid,
            "label": label,
            "section": section,
            "start": round(t, 2),
            "duration": d,
            "color": "warm" if section in ("HOOK", "FEEL") else "normal",
            "dim": "center" if section in ("HOOK", "LAYER") else "full-dark" if section == "PRICE" else "bottom",
            "transition_in": None,
            "transition_type": None,
            "text_animation": "spring-scale-in",
            "cuts": [
                {
                    "id": f"{bid}c1",
                    "type": "image",
                    "source": "TODO",
                    "start": round(t, 2),
                    "dur": round(d / 2, 2),
                    "motion": "slow-zoom-in",
                    "originX": 50,
                    "originY": 50,
                },
                {
                    "id": f"{bid}c2",
                    "type": "image",
                    "source": "TODO",
                    "start": round(t + d / 2, 2),
                    "dur": round(d / 2, 2),
                    "motion": "slow-zoom-in",
                    "originX": 50,
                    "originY": 50,
                },
            ],
            "text": [
                {"content": "TODO", "size": "lg" if section in ("HOOK", "USP") else "xl" if section == "PRICE" else "md", "emphasis": [], "delay": 0.10}
            ],
        })
        t = round(t + d, 2)

    return {
        "meta": {
            "product": product,
            "duration": duration,
            "fps": 30,
            "width": 1080,
            "height": 1920,
            "version": version,
            "total_cuts": num_beats * 2,
            "avg_cut_duration": round(beat_dur / 2, 2),
        },
        "sources": {
            "video": {},
            "image": {},
        },
        "beats": beats,
        "sfx_cues": {
            "beat_transitions": [round(b["start"], 2) for b in beats[1:]],
            "cut_flashes": [],
            "price_ding": round(beats[-1]["start"] + 0.26, 2),
            "text_pop": [],
        },
        "audio": {
            "tts": "",
            "sfx": "",
            "tts_volume": 1.0,
            "sfx_volume": 0.5,
        },
    }


def make_script(product: str, version: str, duration: int, num_beats: int) -> dict:
    sections = pick_sections(num_beats)
    beat_dur = round(duration / num_beats, 2)
    beats = []
    t = 0.0

    for i, section in enumerate(sections):
        bid = f"b{i + 1}"
        label_base = LABEL_MAP.get(section, section.lower())
        usp_count = sum(1 for s in sections[:i] if s == section)
        label = f"{label_base}-{usp_count + 1}" if sections.count(section) > 1 and section not in ("HOOK", "PRICE") else label_base

        d = round(beat_dur, 2)
        if i == num_beats - 1:
            d = round(duration - t, 2)

        end = round(t + d, 2)

        beats.append({
            "id": bid,
            "label": label,
            "section": section,
            "start": round(t, 2),
            "end": end,
            "narration": "TODO",
            "subtitle": [
                {
                    "id": f"{bid}-t",
                    "text": "TODO",
                    "words": ["TODO"],
                    "emphasis": [],
                    "size": "lg" if section in ("HOOK", "USP") else "price" if section == "PRICE" else "md",
                    "animation": "spring-scale-in",
                    "appear_at": round(t + 0.10, 2),
                }
            ],
        })
        t = end

    return {
        "$comment": "SSOT -- script.json + config.json -> build_reel.py -> index.html",
        "meta": {
            "product": product,
            "version": version,
            "duration": duration,
            "fps": 30,
            "tts": {
                "file": "",
                "engine": "elevenlabs",
                "voice": "Taehyung",
                "timing_file": "",
                "timing_source": "faster-whisper",
                "timing_stale": True,
            },
        },
        "beats": beats,
    }


def main():
    parser = argparse.ArgumentParser(description="새 상품 릴스 스캐폴딩")
    parser.add_argument("product", help="상품명 (폴더명으로 사용)")
    parser.add_argument("--version", default="v1", help="버전 (기본: v1)")
    parser.add_argument("--beats", type=int, default=9, help="비트 수 (기본: 9)")
    parser.add_argument("--duration", type=int, default=20, help="영상 길이 초 (기본: 20)")
    args = parser.parse_args()

    product_dir = VIDEO_ROOT / args.product
    version_dir = product_dir / "edit" / args.version

    if version_dir.exists():
        print(f"  이미 존재: {version_dir}")
        sys.exit(1)

    version_dir.mkdir(parents=True)

    config = make_config(args.product, args.version, args.duration, args.beats)
    script = make_script(args.product, args.version, args.duration, args.beats)

    config_path = version_dir / "config.json"
    script_path = version_dir / "script.json"

    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    script_path.write_text(json.dumps(script, ensure_ascii=False, indent=2), encoding="utf-8")

    for subdir in ["영상원본", "보정"]:
        (product_dir / subdir).mkdir(parents=True, exist_ok=True)

    print(f"\n  Scaffolded: {args.product} / {args.version}")
    print(f"  {config_path}")
    print(f"  {script_path}")
    print(f"  Beats: {args.beats}, Duration: {args.duration}s")
    print(f"\n  Next steps:")
    print(f"    1. sources 채우기 (영상원본/ 또는 이미지)")
    print(f"    2. config.json cuts/text 편집")
    print(f"    3. script.json narration/subtitle 작성")
    print(f"    4. python build_reel.py {version_dir} --verify")
    print()


if __name__ == "__main__":
    main()
