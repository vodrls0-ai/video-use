"""릴스 완성 후 인스타그램 캡션을 텔레그램으로 전송 + 마이박스에 영상 복사.

Usage:
    python send_caption.py <version_dir>
    python send_caption.py <version_dir> --dry  # 전송/복사 없이 미리보기만

script.json + config.json에서 캡션을 조립해 텔레그램으로 전송한다.
한 번 탭으로 복사 가능하도록 <pre> 블록으로 감싸서 보냄.
4K 렌더가 있으면 마이박스(N:\개인\릴스)에 자동 복사.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import shutil

import requests
from dotenv import load_dotenv

# ── 환경 ─────────────────────────────────────────────────
_ENV_PATHS = [
    Path(r"C:\nomal\자동화\아이디어\.env"),
    Path(r"C:\Users\user\Desktop\아이디어\.env"),
]
for p in _ENV_PATHS:
    if p.exists():
        load_dotenv(p, override=True)
        break

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
MYBOX_REELS = Path(r"N:\개인\릴스")

HASHTAG_MAP = {
    "니트": ["남자니트", "니트코디", "여름니트"],
    "반팔": ["반팔코디", "여름코디"],
    "티셔츠": ["반팔티", "남자티셔츠"],
    "팬츠": ["남자바지", "여름바지"],
    "슬랙스": ["남자슬랙스", "슬랙스코디", "여름슬랙스"],
    "버뮤다": ["반바지", "버뮤다팬츠", "여름반바지"],
    "데님": ["데님팬츠", "청바지"],
    "셔츠": ["남자셔츠", "여름셔츠"],
    "가디건": ["남자가디건", "여름가디건"],
    "자켓": ["남자자켓", "여름자켓"],
    "단가라": ["단가라", "스트라이프"],
}
BASE_TAGS = ["노멀쉐이크", "남자옷", "남자코디", "남성패션", "데일리룩"]


# ── 캡션 생성 ─────────────────────────────────────────────
def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def extract_price(beats: list[dict]) -> str:
    for b in beats:
        if b.get("section") == "PRICE":
            for sub in b.get("subtitle", []):
                text = sub.get("text", "")
                m = re.search(r"[\d,]+원", text)
                if m:
                    return m.group(0)
            narr = b.get("narration", "")
            m = re.search(r"(\d[\d,]*)\s*원", narr)
            if m:
                raw = m.group(1).replace(",", "")
                return f"{int(raw):,}원"
    return ""


def _subtitles_to_text(beat: dict) -> str:
    subs = beat.get("subtitle", [])
    if not subs:
        return ""
    return " ".join(s.get("text", "") for s in subs).strip()


def _beat_section(beat: dict) -> str:
    sec = beat.get("section", "")
    if sec:
        return sec
    bid = beat.get("id", "").lower()
    if bid in ("hook",):
        return "HOOK"
    if bid in ("cta",):
        return "CTA"
    if "price" in bid:
        return "PRICE"
    return ""


def extract_hook(beats: list[dict]) -> str:
    for b in beats:
        if _beat_section(b) == "HOOK":
            return (b.get("narration") or _subtitles_to_text(b)).strip()
    first = beats[0] if beats else {}
    return (first.get("narration") or _subtitles_to_text(first)).strip()


def extract_body_lines(beats: list[dict]) -> list[str]:
    lines = []
    for b in beats:
        sec = _beat_section(b)
        if sec in ("HOOK", "PRICE", "CTA"):
            continue
        narr = (b.get("narration") or _subtitles_to_text(b)).strip()
        if narr:
            lines.append(narr)
    return lines


def build_hashtags(product_name: str) -> list[str]:
    tags = list(BASE_TAGS)
    lower = product_name.replace(" ", "").lower()
    for keyword, extras in HASHTAG_MAP.items():
        if keyword in lower:
            tags.extend(extras)
    seen = set()
    unique = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return unique


def generate_caption(v_dir: Path) -> str:
    script_path = v_dir / "script.json"
    config_path = v_dir / "config.json"

    if not script_path.exists():
        raise FileNotFoundError(f"script.json not found: {v_dir}")

    script = load_json(script_path)
    beats = script.get("beats", [])
    meta = script.get("meta", {})
    product = meta.get("product", "")

    if config_path.exists():
        cfg = load_json(config_path)
        product = product or cfg.get("meta", {}).get("product", "")

    hook = extract_hook(beats)
    body = extract_body_lines(beats)
    price = extract_price(beats)
    hashtags = build_hashtags(product)

    parts = []

    if hook:
        parts.append(hook)
        parts.append("")

    if body:
        parts.extend(body)
        parts.append("")

    if price:
        parts.append(price)

    parts.append("normalshake.com")
    parts.append("댓글 남기거나 노멀쉐이크 검색해주세요")
    parts.append("")
    parts.append(" ".join(f"#{t}" for t in hashtags))

    return "\n".join(parts)


# ── 텔레그램 전송 ─────────────────────────────────────────
def send_telegram(caption: str, product: str) -> dict:
    if not BOT_TOKEN or not CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    header = f"[릴스 캡션] {product}"
    html_text = f"<b>{header}</b>\n\n<pre>{caption}</pre>"

    resp = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": html_text,
            "parse_mode": "HTML",
        },
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


# ── 마이박스 복사 ─────────────────────────────────────────
def copy_to_mybox(v_dir: Path, hook: str) -> list[Path]:
    product_name = v_dir.parent.parent.name
    safe_hook = re.sub(r'[\\/:*?"<>|]', '', hook)[:20].strip()
    MYBOX_REELS.mkdir(parents=True, exist_ok=True)
    copied = []

    renders_dir = v_dir / "renders"
    if renders_dir.exists():
        four_k = list(renders_dir.glob("*_4k.mp4"))
        if four_k:
            dest = MYBOX_REELS / f"{product_name}_{safe_hook}.mp4"
            shutil.copy2(four_k[0], dest)
            copied.append(dest)

    cover = v_dir / "cover.jpg"
    if cover.exists():
        dest = MYBOX_REELS / f"{product_name}_{safe_hook}_cover.jpg"
        shutil.copy2(cover, dest)
        copied.append(dest)

    return copied


# ── CLI ──────────────────────────────────────────────────
def main():
    if len(sys.argv) < 2:
        print("Usage: python send_caption.py <version_dir> [--dry]")
        sys.exit(1)

    v_dir = Path(sys.argv[1]).resolve()
    dry = "--dry" in sys.argv

    if not v_dir.is_dir():
        print(f"Not a directory: {v_dir}")
        sys.exit(1)

    script = load_json(v_dir / "script.json")
    product = script.get("meta", {}).get("product", v_dir.parent.name)
    beats = script.get("beats", [])

    caption = generate_caption(v_dir)
    hook = extract_hook(beats)

    print("=" * 50)
    print(f"Product: {product}")
    print("=" * 50)
    print(caption)
    print("=" * 50)

    if dry:
        print("\n[DRY RUN] Not sending to Telegram.")
        return

    try:
        result = send_telegram(caption, product)
        ok = result.get("ok", False)
        if ok:
            print(f"\nSent to Telegram (chat_id={CHAT_ID})")
        else:
            print(f"\nTelegram error: {result}")
    except Exception as e:
        print(f"\nFailed to send: {e}")

    try:
        copied = copy_to_mybox(v_dir, hook)
        if copied:
            for dest in copied:
                print(f"  [MyBox] {dest}")
        else:
            print(f"  [MyBox] 4K 렌더/커버 없음, 복사 스킵")
    except Exception as e:
        print(f"  [MyBox] 복사 실패: {e}")


if __name__ == "__main__":
    main()
