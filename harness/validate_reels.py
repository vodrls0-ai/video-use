# -*- coding: utf-8 -*-
"""validate_reels.py — 릴스 대본 검증루프 + 피드백루프 게이트
generate_capcut.py --generate 전에 반드시 통과해야 함.
통과 시 .validated 마커 파일 생성 → generate_capcut.py가 확인.

이관: 컨텐츠자동화 → 비디오/video-use/harness/ (2026-06-13)
경로: VIDEO_ROOT = 비디오/video/ 기준으로 상품 검색
"""
import json
import os
import re
import sys
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
VIDEO_ROOT = HARNESS_DIR.parent.parent / "video"
SANGPE_ROOT = Path(r"C:\nomal\자동화\상페자동화")

ALLOWED_CTA_PATTERNS = [
    r"댓글에\s*['\"]?.+['\"]?",
    r"프로필\s*링크",
    r"저장",
    r"DM",
]
BANNED_CTA_PATTERNS = [
    r"보내줘|보내주세요|보내드릴게",
    r"지금\s*구매",
    r"링크에서\s*구매",
    r"주문",
]

VAGUE_PATTERNS = [
    (r"진짜\s*잘\s*[돼되]", "구체적으로 뭐가 잘 되는지 명시 필요"),
    (r"너무\s*좋[아은]", "뭐가 좋은지 구체적으로"),
    (r"완전\s*[좋대됨]", "구체적 근거 없는 감탄 표현"),
    (r"갓성비", "릴스 톤에 맞지 않는 광고 표현"),
]

BANNED_TONE_ENDINGS = [
    (r"[가-힣]+줌[.\s]", "~줌 반말체 금지 → ~요체로 통일"),
    (r"[가-힣]+됨[.\s]", "~됨 반말체 금지 → ~요체로 통일"),
    (r"[가-힣]+함[.\s]", "~함 반말체 금지 → ~요체로 통일"),
]


def find_product_dir(product: str) -> str:
    """비디오/video/ 하위에서 상품 폴더 검색."""
    direct = VIDEO_ROOT / product
    if direct.is_dir():
        return str(direct)
    archive = VIDEO_ROOT / "archive" / product
    if archive.is_dir():
        return str(archive)
    return ""


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def find_product_info(product_dir: str) -> str:
    """상품정보.txt 경로 탐색 — 상페자동화에서 검색"""
    product_name = os.path.basename(product_dir)
    for base in [SANGPE_ROOT / "0.완료", SANGPE_ROOT / "1.작업중"]:
        if not base.exists():
            continue
        direct = base / product_name / "상품정보.txt"
        if direct.exists():
            return str(direct)
        for category in base.iterdir():
            if not category.is_dir():
                continue
            candidate = category / product_name / "상품정보.txt"
            if candidate.exists():
                return str(candidate)
    return ""


def read_product_info(path: str) -> dict:
    info = {}
    if not path or not os.path.exists(path):
        return info
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()
            elif " : " in line:
                k, v = line.split(" : ", 1)
                info[k.strip()] = v.strip()
    return info


def check_product_info_cross(tts_text: str, product_info: dict, errors: list):
    numbers_in_script = re.findall(r"(\d+)\s*(cm|kg|인치|사이즈|어깨|가슴|허리|키)", tts_text)
    for num, unit in numbers_in_script:
        found = False
        for v in product_info.values():
            if num in v:
                found = True
                break
        if not found:
            errors.append(f"[허구데이터] '{num}{unit}' — 상품정보.txt에 없는 수치. 출처 확인 필요")


def check_cta_channel_strategy(spec: dict, errors: list):
    clips = spec.get("clips", [])
    cta_clips = [c for c in clips if c.get("section", "").upper() == "CTA"]
    for clip in cta_clips:
        texts = [t.get("content", "") for t in clip.get("texts", [])]
        narration = " ".join(texts)
        for pattern in BANNED_CTA_PATTERNS:
            if re.search(pattern, narration):
                errors.append(f"[CTA위반] 클립{clip['id']} '{narration}' — 금지 패턴 '{pattern}' 감지. "
                              f"릴스 CTA는 '댓글에 키워드' / '프로필 링크' / '저장' 만 허용")


def check_vague_phrases(tts_text: str, spec: dict, errors: list):
    for pattern, msg in VAGUE_PATTERNS:
        match = re.search(pattern, tts_text)
        if match:
            errors.append(f"[빈문장] '{match.group()}' — {msg}")
    for clip in spec.get("clips", []):
        for t in clip.get("texts", []):
            content = t.get("content", "")
            for pattern, msg in VAGUE_PATTERNS:
                match = re.search(pattern, content)
                if match:
                    errors.append(f"[빈문장] 클립{clip['id']} '{content}' — {msg}")


def check_image_exists(spec: dict, errors: list):
    for clip in spec.get("clips", []):
        img = clip.get("image", "")
        if img and not os.path.exists(img):
            errors.append(f"[이미지없음] 클립{clip['id']} '{os.path.basename(img)}' 파일 없음")


def check_crop_full(spec: dict, errors: list):
    for clip in spec.get("clips", []):
        crop = clip.get("crop", "full")
        if crop != "full":
            errors.append(f"[crop금지] 클립{clip['id']} crop='{crop}' — 'full'만 허용. 부위 강조는 motion으로")


def check_tone(tts_text: str, errors: list):
    for pattern, msg in BANNED_TONE_ENDINGS:
        match = re.search(pattern, tts_text)
        if match:
            errors.append(f"[톤위반] '{match.group().strip()}' — {msg}")


def check_gemini_reviewed(product_dir: str, errors: list) -> bool:
    for sub in ["reels", "edit"]:
        marker = os.path.join(product_dir, sub, ".gemini_reviewed")
        if os.path.exists(marker):
            return True
    if os.path.isdir(os.path.join(product_dir, "edit")):
        for v in sorted(os.listdir(os.path.join(product_dir, "edit")), reverse=True):
            marker = os.path.join(product_dir, "edit", v, ".gemini_reviewed")
            if os.path.exists(marker):
                return True
    errors.append("[Gemini미검토] .gemini_reviewed 마커 없음. "
                  "gemini_review.py --type reels 실행 후 마커 생성 필요")
    return False


def check_text_is_narration(spec: dict, script: dict, errors: list):
    tts_text = script.get("tts_text", "") or ""
    for clip in spec.get("clips", []):
        for t in clip.get("texts", []):
            content = t.get("content", "")
            if not content:
                continue
            clean_content = re.sub(r"[⚡🤔💡→·]", "", content).strip()
            clean_tts = re.sub(r"[⚡🤔💡→·]", "", tts_text).strip()
            if len(clean_content) >= 3 and clean_content not in clean_tts:
                errors.append(f"[자막축약] 클립{clip['id']} '{content}' — 나레이션 원문에 없음. "
                              f"키워드 축약 금지, 원문 시간분할만 허용")


def _find_spec_and_script(product_dir: str) -> tuple[str, str]:
    """capcut_spec.json과 reels_script.json 경로 탐색."""
    for sub in ["reels"]:
        spec = os.path.join(product_dir, sub, "capcut_spec.json")
        script = os.path.join(product_dir, sub, "reels_script.json")
        if os.path.exists(spec):
            return spec, script
    edit_dir = os.path.join(product_dir, "edit")
    if os.path.isdir(edit_dir):
        for v in sorted(os.listdir(edit_dir), reverse=True):
            spec = os.path.join(edit_dir, v, "capcut_spec.json")
            script = os.path.join(edit_dir, v, "reels_script.json")
            if os.path.exists(spec):
                return spec, script
    return "", ""


def validate(product: str) -> tuple[list, list]:
    errors = []
    warnings = []

    product_dir = find_product_dir(product)
    if not product_dir:
        errors.append(f"[치명] 상품 폴더 없음: {product}")
        return errors, warnings

    spec_path, script_path = _find_spec_and_script(product_dir)

    if not spec_path:
        errors.append(f"[치명] capcut_spec.json 없음. 대본 먼저 작성")
        return errors, warnings

    spec = load_json(spec_path)
    script = load_json(script_path) if script_path and os.path.exists(script_path) else {}

    tts_text = script.get("tts_text", "") or spec.get("tts_text", "") or ""

    info_path = find_product_info(product_dir)
    product_info = read_product_info(info_path)
    if not product_info:
        warnings.append(f"[경고] 상품정보.txt 못 찾음 — 허구 데이터 검증 건너뜀")

    print("── 검증루프 ──")
    if product_info:
        check_product_info_cross(tts_text, product_info, errors)
    check_cta_channel_strategy(spec, errors)
    check_vague_phrases(tts_text, spec, errors)
    check_image_exists(spec, errors)
    check_crop_full(spec, errors)
    check_tone(tts_text, errors)
    check_text_is_narration(spec, script, errors)

    print("── 피드백루프 ──")
    check_gemini_reviewed(product_dir, errors)

    return errors, warnings


def create_validated_marker(product_dir: str):
    for sub in ["reels", "edit"]:
        target = os.path.join(product_dir, sub)
        if os.path.isdir(target):
            marker = os.path.join(target, ".validated")
            with open(marker, "w", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"validated_at: {datetime.now().isoformat()}\n")
                f.write("status: PASS\n")
            print(f"\n[PASS] .validated 마커 생성됨: {marker}")
            return
    if os.path.isdir(os.path.join(product_dir, "edit")):
        versions = sorted(os.listdir(os.path.join(product_dir, "edit")), reverse=True)
        if versions:
            marker = os.path.join(product_dir, "edit", versions[0], ".validated")
            with open(marker, "w", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"validated_at: {datetime.now().isoformat()}\n")
                f.write("status: PASS\n")
            print(f"\n[PASS] .validated 마커 생성됨: {marker}")
            return
    print("\n[PASS] 검증 통과 (마커 위치 결정 불가 — 수동 확인)")


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_reels.py {상품명}")
        print("  검증 통과 → .validated 마커 생성")
        print("  검증 실패 → 에러 출력, 마커 미생성")
        sys.exit(1)

    product = sys.argv[1]
    print(f"=== 릴스 검증: {product} ===\n")

    errors, warnings = validate(product)

    for w in warnings:
        print(f"  ⚠ {w}")

    if errors:
        print(f"\n{'='*50}")
        print(f"  FAIL — {len(errors)}개 오류 발견")
        print(f"{'='*50}")
        for e in errors:
            print(f"  ✗ {e}")
        print(f"\n검증 실패. 오류 수정 후 다시 실행하세요.")
        print("generate_capcut.py --generate 차단됨.")
        sys.exit(1)
    else:
        product_dir = find_product_dir(product)
        create_validated_marker(product_dir)
        print(f"\n{'='*50}")
        print(f"  PASS — 모든 검증 통과")
        print(f"{'='*50}")
        print("generate_capcut.py --generate 실행 가능.")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
