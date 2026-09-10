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
from capcut_feature_gate import analyze_spec, write_report
from consistency_gate import run_consistency_gate
from angle_gate import run_angle_gate

HARNESS_DIR = Path(__file__).absolute().parent
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


PRODUCT_ANALYSIS_REQUIRED_FIELDS = [
    "category", "sub_categories", "comparable_products",
    "pain_context", "identity", "available_assets",
]

STORY_CONTEXT_REQUIRED = [
    "target_customer", "desired_change", "buying_barrier", "value_promise",
]


def check_product_analysis(product_dir: str, errors: list, warnings: list):
    """상품분석(product_analysis.json) 존재 및 필수 필드 검증."""
    analysis_path = None
    for sub in ["reels", ""]:
        candidate = os.path.join(product_dir, sub, "product_analysis.json") if sub else os.path.join(product_dir, "product_analysis.json")
        if os.path.exists(candidate):
            analysis_path = candidate
            break
    if not analysis_path:
        errors.append(
            "[상품분석누락] product_analysis.json 없음 — "
            "대본 작성 전 상품 카테고리/용도/에셋현황 분석 필수. "
            "rule 43_product_analysis_gate.md 참조"
        )
        return
    try:
        analysis = load_json(analysis_path)
    except Exception as e:
        errors.append(f"[상품분석오류] product_analysis.json 파싱 실패: {e}")
        return
    missing = [f for f in PRODUCT_ANALYSIS_REQUIRED_FIELDS if f not in analysis]
    if missing:
        errors.append(f"[상품분석불완전] 필수 필드 누락: {', '.join(missing)}")
    assets = analysis.get("available_assets", {})
    if not assets.get("video") and not assets.get("hooks_folder"):
        warnings.append("[에셋경고] 영상(mp4) 에셋 0건 — 이미지+모션으로만 구성해야 함. 벤치마크 워싱 시 영상 필수 구조는 피할 것")


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


def find_product_info(product_dir: str, product_name_override: str = "") -> str:
    """상품정보.txt 경로 탐색 — 상페자동화에서 검색"""
    product_name = product_name_override or os.path.basename(product_dir)
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


def check_cta_banned_patterns(spec: dict, errors: list):
    """CTA에서 금지 패턴 감지 (rule25 폐기 후 채널별 강제는 없음, 금지 패턴만 체크)."""
    clips = spec.get("clips", [])
    cta_clips = [c for c in clips if c.get("section", "").upper() == "CTA"]
    for clip in cta_clips:
        texts = [t.get("content", "") for t in clip.get("texts", [])]
        narration = " ".join(texts)
        for pattern in BANNED_CTA_PATTERNS:
            if re.search(pattern, narration):
                errors.append(f"[CTA금지패턴] 클립{clip['id']} '{narration}' — 금지 패턴 '{pattern}' 감지")


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
            hint = ""
            if re.search(r"^Z:[/\\]NOMAL", img, re.IGNORECASE):
                hint = " — Z:드라이브 경로로 보임. 사무실 PC라면 Z:가 NAS 루트가 아닐 수 있음, 'C:/nomal/...'로 치환 후 재시도"
            errors.append(f"[이미지없음] 클립{clip['id']} 전체경로 '{img}' 없음{hint}")


BANNED_ASSET_PATTERNS = re.compile(r"hstack|vstack|_vs_|side.?by.?side|split|비교합성|분할", re.IGNORECASE)


def check_split_image_banned(spec: dict, errors: list):
    for clip in spec.get("clips", []):
        img = clip.get("image", "")
        basename = os.path.basename(img)
        if BANNED_ASSET_PATTERNS.search(basename):
            errors.append(
                f"[분할이미지금지] 클립{clip['id']} '{basename}' — "
                f"hstack/vstack/비교합성 분할이미지는 릴스에 사용 금지. "
                f"단일 피사체 에셋으로 교체 필수"
            )


def check_subtitle_chunk_length(spec: dict, errors: list):
    """자막 = 6글자 이내(rule 08/13 등). subtitle_chunks가 비어있거나
    6자 초과 청크가 있으면 FAIL. 숫자+단위(가격 등, 예: '29,800')만 예외로
    콤마 포함 최대 7자까지 허용 — 그 외 순수 한글/기호 청크는 6자 하드 컷.
    2026-09-05: 61개 기존 드래프트 중 58개가 이 체크 부재로 자막이 통짜/장문으로
    나간 사고 이후 신설. subtitle_chunks가 비어있는 것 자체도 실패 사유 —
    generate_capcut.py의 무청크 폴백은 6자 규칙을 지키지 않는다(rule47)."""
    PRICE_RE = re.compile(r"^[\d,]+원?$")
    for n in spec.get("narration", []):
        chunks = n.get("subtitle_chunks")
        nid = n.get("id", "?")
        if not chunks:
            errors.append(f"[자막청크없음] narration '{nid}' — subtitle_chunks가 비어있음. 6자 이내로 직접 분할 필수(rule47)")
            continue
        for c in chunks:
            length = len(c)
            if length > 6 and not (PRICE_RE.match(c) and length <= 8):
                errors.append(f"[자막6자초과] narration '{nid}' 청크 '{c}' ({length}자) — 6자 이내로 재분할 필요")


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


def check_conversion_role(script: dict, errors: list, warnings: list):
    """전환역할(TARGET/V↑/R↓/CTA) 코드 강제 — 구조게이트 §2·§5.
    script.json의 모든 beat에 conversion_role 필수.
    V↑(가치부여) 1개 이상, R↓(반박제거) 1개 이상 없으면 FAIL."""
    beats = script.get("beats", [])
    if not beats:
        return
    missing_role = []
    roles_found = set()
    for beat in beats:
        role = beat.get("conversion_role", "")
        if not role:
            missing_role.append(beat.get("id", "?"))
        else:
            for token in role.replace("+", " ").replace(",", " ").split():
                roles_found.add(token.strip())
    if missing_role:
        errors.append(
            f"[전환역할누락] conversion_role 없는 비트: {', '.join(missing_role)} — "
            f"TARGET/V↑/R↓/CTA/PIVOT 중 하나 이상 명시 필수"
        )
    if beats and "V↑" not in roles_found:
        errors.append(
            "[V↑누락] 가치부여(V↑) 비트 0개 — "
            "'입으면 어떻게 달라지는지' 착용 결과가 최소 1곳 필요"
        )
    if beats and "R↓" not in roles_found:
        errors.append(
            "[R↓누락] 반박제거(R↓) 비트 0개 — "
            "가격/품질/소재 의심 해소가 최소 1곳 필요"
        )


def check_story_context(script: dict, errors: list, warnings: list):
    """story_context(전환 3축 사전잠금) 존재 검증 — 구조게이트 §3.
    대본 작성 전 target/V↑근거/R↓근거/CTA를 잠그지 않으면
    매번 다른 대본이 나온다. 코드로 강제."""
    ctx = script.get("story_context", {})
    if not ctx:
        errors.append(
            "[story_context누락] script.json에 story_context 없음 — "
            "대본 전 target_customer/desired_change/buying_barrier/"
            "value_promise 잠금 필수 (구조게이트 §3)"
        )
        return
    missing = [f for f in STORY_CONTEXT_REQUIRED if not ctx.get(f)]
    if missing:
        errors.append(
            f"[story_context불완전] 필수 잠금 누락: {', '.join(missing)}"
        )


def check_conversion_brief(product_dir: str, errors: list, warnings: list):
    """conversion_brief.json 존재 검증.
    build_conversion_brief.py로 생성 — 대본 작성 전 구조 매칭 필수."""
    brief_path = os.path.join(product_dir, "conversion_brief.json")
    if not os.path.exists(brief_path):
        errors.append(
            "[conversion_brief누락] conversion_brief.json 없음 — "
            "대본 작성 전 python tools/build_conversion_brief.py 실행 필수"
        )
        return
    try:
        brief = load_json(brief_path)
    except Exception as e:
        errors.append(f"[conversion_brief오류] 파싱 실패: {e}")
        return
    matched = brief.get("matched_formats", [])
    if not matched:
        warnings.append("[conversion_brief경고] matched_formats가 비어있음 — 매칭 조건 확인 필요")
    weapons = brief.get("conversion_weapons", {})
    if not weapons.get("v_up"):
        warnings.append("[conversion_brief경고] V↑ 무기 없음 — product_analysis.json USP 확인")
    if not weapons.get("r_down"):
        warnings.append("[conversion_brief경고] R↓ 무기 없음 — 가격/반박 소재 확인")


def check_text_is_narration(spec: dict, script: dict, errors: list):
    if spec.get("fresh_flow_contract", {}).get("display_text_mode") == "top_keywords":
        return
    tts_text = script.get("tts_text", "") or ""
    # rule24: 자막은 숫자(29,800원), TTS는 한글(이만구천팔백원) — 두 표기가 다른 게 정상이므로
    # spec 자체의 narration[].subtitle(숫자 표기 승인본)도 매칭 대상에 포함한다.
    spec_subtitle_text = " ".join(
        n.get("subtitle", "") for n in spec.get("narration", [])
    )
    clean_tts = re.sub(r"[⚡🤔💡→·]", "", tts_text).strip()
    clean_spec_subtitle = re.sub(r"[⚡🤔💡→·]", "", spec_subtitle_text).strip()
    for clip in spec.get("clips", []):
        for t in clip.get("texts", []):
            content = t.get("content", "")
            if not content:
                continue
            clean_content = re.sub(r"[⚡🤔💡→·]", "", content).strip()
            if len(clean_content) < 3:
                continue
            if clean_content in clean_tts or clean_content in clean_spec_subtitle:
                continue
            errors.append(f"[자막축약] 클립{clip['id']} '{content}' — 나레이션 원문에 없음. "
                          f"키워드 축약 금지, 원문 시간분할만 허용")


def check_tts_sync(spec: dict, product_dir: str, errors: list, warnings: list):
    clips = spec.get("clips", [])
    narrations = {n["id"]: n for n in spec.get("narration", [])}
    tts_dir = None
    for sub in ["reels/tts", "edit/tts", "tts"]:
        candidate = os.path.join(product_dir, sub)
        if os.path.isdir(candidate):
            tts_dir = candidate
            break

    nar_clip_dur = {}
    nar_start = {}
    cursor = 0.0
    for c in clips:
        nid = c.get("narration_id")
        if nid:
            if nid not in nar_clip_dur:
                nar_clip_dur[nid] = 0.0
                nar_start[nid] = cursor
            nar_clip_dur[nid] += c.get("duration", 0)
        cursor += c.get("duration", 0)

    for nid, clip_dur in nar_clip_dur.items():
        nar = narrations.get(nid, {})
        text = nar.get("text", "")
        if not text:
            continue

        tts_dur = nar.get("tts_duration")
        if tts_dur is None and tts_dir:
            mp3 = os.path.join(tts_dir, f"{nid}.mp3")
            if os.path.exists(mp3):
                try:
                    import subprocess
                    r = subprocess.run(
                        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", mp3],
                        capture_output=True, text=True, timeout=5,
                    )
                    tts_dur = float(r.stdout.strip())
                except Exception:
                    pass

        if tts_dur is None:
            continue

        overflow = tts_dur - clip_dur
        start = nar_start.get(nid, 0)
        if start + tts_dur > cursor + 0.03:
            errors.append(f"[TTS잘림] {nid}: TTS {tts_dur:.2f}s > 영상끝까지 {cursor-start:.2f}s (끝에서 {start+tts_dur-cursor:.2f}s 잘림)")
        elif overflow > 0.1:
                warnings.append(f"[TTS겹침] {nid}: TTS {tts_dur:.2f}s > 클립 {clip_dur:.2f}s (+{overflow:.2f}s 다음구간 침범)")


def check_capcut_feature_gate(spec: dict, spec_path: str, errors: list, warnings: list):
    report = analyze_spec(spec, strict=True)
    report_path = os.path.join(os.path.dirname(spec_path), "capcut_feature_gate_report.json")
    write_report(report, report_path)
    for warning in report.get("warnings", []):
        warnings.append(warning)
    for error in report.get("errors", []):
        errors.append(error)


def _variant_from_argv() -> str:
    """--variant: reels/ 하위 변형 폴더(blute/dohu/...) 지원. 빈 값이면 기존 동작 동일.
    2026-08-19 추가 — generate_capcut.py / gen_qwen3_tts.py와 인터페이스 통일."""
    for i, a in enumerate(sys.argv):
        if a == "--variant" and i + 1 < len(sys.argv):
            return sys.argv[i + 1].strip("/\\")
        if a.startswith("--variant="):
            return a.split("=", 1)[1].strip("/\\")
    return ""


def _find_spec_and_script(product_dir: str) -> tuple[str, str]:
    """capcut_spec.json과 reels_script.json 경로 탐색."""
    _v = _variant_from_argv()
    for sub in ([os.path.join("reels", _v)] if _v else []) + ["reels"]:
        spec = os.path.join(product_dir, sub, "capcut_spec.json")
        script = os.path.join(product_dir, sub, "reels_script.json")
        if not os.path.exists(script):
            script = os.path.join(product_dir, sub, "script.json")
        if os.path.exists(spec):
            return spec, script
    edit_dir = os.path.join(product_dir, "edit")
    if os.path.isdir(edit_dir):
        for v in sorted(os.listdir(edit_dir), reverse=True):
            spec = os.path.join(edit_dir, v, "capcut_spec.json")
            script = os.path.join(edit_dir, v, "reels_script.json")
            if not os.path.exists(script):
                script = os.path.join(edit_dir, v, "script.json")
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

    source_product_name = spec.get("source_product_name", "") or spec.get("source_product", "")
    info_path = find_product_info(product_dir, source_product_name)
    product_info = read_product_info(info_path)
    if not product_info:
        warnings.append(f"[경고] 상품정보.txt 못 찾음 — 허구 데이터 검증 건너뜀")

    print("── 상품분석 게이트 ──")
    check_product_analysis(product_dir, errors, warnings)

    print("── 전환역할 게이트 ──")
    check_conversion_brief(product_dir, errors, warnings)
    check_conversion_role(script, errors, warnings)
    check_story_context(script, errors, warnings)

    print("── 일관성 게이트 ──")
    run_consistency_gate(script, script_path=script_path or None, errors=errors, warnings=warnings)

    print("── 앵글 다양성 게이트 ──")
    run_angle_gate(script, script_path=script_path or None, errors=errors, warnings=warnings)

    print("── 검증루프 ──")
    if product_info:
        check_product_info_cross(tts_text, product_info, errors)
    check_cta_banned_patterns(spec, errors)
    check_vague_phrases(tts_text, spec, errors)
    check_image_exists(spec, errors)
    check_split_image_banned(spec, errors)
    check_crop_full(spec, errors)
    check_subtitle_chunk_length(spec, errors)
    check_tone(tts_text, errors)
    check_text_is_narration(spec, script, errors)
    check_tts_sync(spec, product_dir, errors, warnings)
    check_capcut_feature_gate(spec, spec_path, errors, warnings)

    return errors, warnings


def _spec_sha256(product_dir: str) -> str:
    """capcut_spec.json의 sha256을 계산. 파일 없으면 빈 문자열.

    2026-08-19: variant 미인식 버그 수정 — 검증은 reels/<variant>/capcut_spec.json을 보면서
    해시는 reels/capcut_spec.json(다른 포맷의 구버전)을 기록해, generate_capcut의
    sha 대조가 항상 [BLOCKED]로 떨어졌다 (신안 1007 NM-1에서 발견).
    generate_capcut._spec_subs()와 탐색 순서를 일치시킨다."""
    import hashlib
    _v = _variant_from_argv()
    for sub in ([os.path.join("reels", _v)] if _v else []) + ["reels", "meta", "edit", ""]:
        candidate = os.path.join(product_dir, sub, "capcut_spec.json") if sub else os.path.join(product_dir, "capcut_spec.json")
        if os.path.isfile(candidate):
            with open(candidate, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()
    return ""


def create_validated_marker(product_dir: str):
    spec_hash = _spec_sha256(product_dir)
    _v = _variant_from_argv()
    # variant 검증분은 그 variant 폴더에 마커를 남긴다. reels/ 루트에 남기면
    # 다른 포맷(blute/dohu 등)까지 검증된 것처럼 보이는 오염이 생긴다.
    for sub in ([os.path.join("reels", _v)] if _v else []) + ["reels", "edit"]:
        target = os.path.join(product_dir, sub)
        if os.path.isdir(target):
            marker = os.path.join(target, ".validated")
            with open(marker, "w", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"validated_at: {datetime.now().isoformat()}\n")
                f.write("status: PASS\n")
                if spec_hash:
                    f.write(f"spec_sha256: {spec_hash}\n")
            print(f"\n[PASS] .validated 마커 생성됨: {marker}")
            if spec_hash:
                print(f"  spec_sha256: {spec_hash[:16]}...")
            return
    if os.path.isdir(os.path.join(product_dir, "edit")):
        versions = sorted(os.listdir(os.path.join(product_dir, "edit")), reverse=True)
        if versions:
            marker = os.path.join(product_dir, "edit", versions[0], ".validated")
            with open(marker, "w", encoding="utf-8") as f:
                from datetime import datetime
                f.write(f"validated_at: {datetime.now().isoformat()}\n")
                f.write("status: PASS\n")
                if spec_hash:
                    f.write(f"spec_sha256: {spec_hash}\n")
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
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    main()
