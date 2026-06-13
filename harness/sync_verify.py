"""script.json SSOT 검증 도구.

검증 항목:
  1. script.json 내부 일관성 (비트 경계, 자막 타이밍, 강조 단어 존재)
  2. script.json ↔ tts_timing.json 나레이션 텍스트 비교
  3. script.json ↔ config.json text 필드 동기화 상태
  4. script.json ↔ index.html 자막 텍스트 비교

Usage:
    python sync_verify.py <v_dir>
    python sync_verify.py Z:/NOMAL/자동화/비디오/video/어반옐로우_레브브이넥반팔니트/edit/v14
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


class Issue:
    WARN = "WARN"
    FAIL = "FAIL"
    INFO = "INFO"

    def __init__(self, level: str, beat: str, msg: str):
        self.level = level
        self.beat = beat
        self.msg = msg

    def __str__(self):
        icon = {"FAIL": "X", "WARN": "!", "INFO": "."}[self.level]
        return f"  {icon} [{self.beat}] {self.msg}"


def load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def extract_html_subtitles(html_path: Path) -> dict[str, list[str]]:
    """index.html에서 비트별 자막 텍스트를 추출한다.

    전략: 각 beat-text 블록의 시작 위치를 찾고, 다음 beat-text 또는 EOF까지를 블록으로 잡는다.
    기존 .*?</div></div> 방식은 중첩 구조에서 조기 종료 위험.
    """
    if not html_path.exists():
        return {}
    text = html_path.read_text(encoding="utf-8")

    header_pattern = re.compile(r'id="(b\d+)-text"')
    starts = [(m.group(1), m.start()) for m in header_pattern.finditer(text)]

    result = {}
    for idx, (beat_id, start_pos) in enumerate(starts):
        end_pos = starts[idx + 1][1] if idx + 1 < len(starts) else len(text)
        block = text[start_pos:end_pos]

        sub_divs = re.findall(
            r'id="' + beat_id + r'-t\d*"[^>]*>(.*?)</div>',
            block, re.DOTALL
        )
        lines = []
        for div_content in sub_divs:
            line_words = re.findall(r'class="w[^"]*">(.*?)</span>', div_content)
            if line_words:
                lines.append(" ".join(line_words))
        if not lines:
            all_words = re.findall(r'class="w[^"]*">(.*?)</span>', block)
            if all_words:
                lines = [" ".join(all_words)]
        if lines:
            result[beat_id] = lines
    return result


def normalize(text: str) -> str:
    """비교용 텍스트 정규화: 줄바꿈->공백, 다중공백->단일, strip."""
    return re.sub(r"\s+", " ", text.replace("\n", " ")).strip()


def verify_internal(script: dict) -> list[Issue]:
    """script.json 내부 일관성 검증."""
    issues = []
    beats = script.get("beats", [])

    for i, beat in enumerate(beats):
        bid = beat["id"]

        if beat["start"] >= beat["end"]:
            issues.append(Issue(Issue.FAIL, bid, f"start({beat['start']}) >= end({beat['end']})"))

        if i > 0 and beat["start"] < beats[i - 1]["end"] - 0.05:
            issues.append(Issue(Issue.WARN, bid,
                f"비트 겹침: start({beat['start']}) < 이전 end({beats[i-1]['end']})"))

        for sub in beat.get("subtitle", []):
            sub_id = sub.get("id", f"{bid}-t?")
            appear = sub.get("appear_at")
            if appear is None:
                issues.append(Issue(Issue.WARN, bid,
                    f"자막 '{sub_id}' appear_at 미정의"))
                appear = beat["start"]
            if appear < beat["start"] - 0.1:
                issues.append(Issue(Issue.FAIL, bid,
                    f"자막 '{sub_id}' appear_at({appear}) < beat start({beat['start']})"))
            if appear > beat["end"] + 0.5:
                issues.append(Issue(Issue.WARN, bid,
                    f"자막 '{sub_id}' appear_at({appear}) > beat end({beat['end']})"))

            sub_text = normalize(sub.get("text", ""))
            if not sub_text:
                issues.append(Issue(Issue.FAIL, bid,
                    f"자막 '{sub_id}' text 비어있음"))
                continue

            for emp in sub.get("emphasis", []):
                if emp not in sub_text:
                    issues.append(Issue(Issue.FAIL, bid,
                        f"강조 단어 '{emp}'이 자막 텍스트에 없음"))

            declared_words = sub.get("words", [])
            if declared_words:
                joined = " ".join(declared_words)
                if normalize(joined) != sub_text:
                    issues.append(Issue(Issue.WARN, bid,
                        f"words 배열 합산 != text: '{joined}' vs '{sub_text}'"))

    return issues


def verify_vs_timing(script: dict, timing: dict) -> list[Issue]:
    """script.json narration ↔ tts_timing.json 비교.

    Whisper 전사 특성상 단어 분리/로마자/숫자 표현이 다를 수 있으므로
    공백 제거 후 문자 수준 SequenceMatcher로 비교한다.
    """
    issues = []

    tts_stale = script.get("meta", {}).get("tts", {}).get("timing_stale", False)
    if tts_stale:
        reason = script["meta"]["tts"].get("timing_stale_reason", "")
        issues.append(Issue(Issue.WARN, "META",
            f"timing_stale=true -> 워드타이밍 검증 건너뜀. 사유: {reason}"))
        issues.append(Issue(Issue.INFO, "META",
            "-> tts_v10.mp3를 faster-whisper/Scribe로 재추출 후 timing_stale=false로 변경 필요"))
        return issues

    from difflib import SequenceMatcher

    for beat in script.get("beats", []):
        bid = beat["id"]
        narration = normalize(beat.get("narration", ""))
        if not narration:
            continue

        start, end = beat["start"], beat["end"]
        beat_timing_words = [
            w["word"].rstrip(".,?!") for w in timing.get("words", [])
            if w["start"] >= start - 0.3 and w["end"] <= end + 0.5
        ]
        beat_timing_text = " ".join(beat_timing_words)

        if not beat_timing_words:
            issues.append(Issue(Issue.WARN, bid,
                f"tts_timing에서 {start}-{end}s 구간 단어 없음"))
            continue

        narr_chars = re.sub(r"[\s.,?!]", "", narration)
        timing_chars = re.sub(r"[\s.,?!]", "", beat_timing_text)

        ratio = SequenceMatcher(None, narr_chars, timing_chars).ratio()

        if ratio < 0.5:
            issues.append(Issue(Issue.FAIL, bid,
                f"나레이션↔타이밍 불일치({ratio:.0%}): "
                f"script='{narration}' vs timing='{beat_timing_text}'"))
        elif ratio < 0.75:
            issues.append(Issue(Issue.WARN, bid,
                f"나레이션↔타이밍 부분일치({ratio:.0%}): "
                f"script='{narration}' vs timing='{beat_timing_text}'"))

    return issues


def verify_vs_config(script: dict, config: dict) -> list[Issue]:
    """script.json ↔ config.json text 필드 동기화."""
    issues = []

    config_beats = {b["id"]: b for b in config.get("beats", [])}

    for beat in script.get("beats", []):
        bid = beat["id"]
        cb = config_beats.get(bid)
        if not cb:
            issues.append(Issue(Issue.WARN, bid, "config.json에 해당 비트 없음"))
            continue

        script_texts = [normalize(s["text"]) for s in beat.get("subtitle", [])]
        config_texts = [normalize(t.get("content", "")) for t in cb.get("text", [])]

        if script_texts != config_texts:
            issues.append(Issue(Issue.WARN, bid,
                f"config.json text 미동기화:\n"
                f"       script: {script_texts}\n"
                f"       config: {config_texts}"))

    return issues


def verify_vs_html(script: dict, html_subs: dict[str, list[str]]) -> list[Issue]:
    """script.json ↔ index.html 자막 텍스트 비교."""
    issues = []

    for beat in script.get("beats", []):
        bid = beat["id"]
        html_lines = html_subs.get(bid)
        if html_lines is None:
            issues.append(Issue(Issue.WARN, bid, "index.html에 자막 없음"))
            continue

        script_lines = []
        for sub in beat.get("subtitle", []):
            text = normalize(sub.get("text", ""))
            script_lines.append(text)

        html_joined = normalize(" ".join(html_lines))
        script_joined = normalize(" ".join(script_lines))

        if html_joined != script_joined:
            issues.append(Issue(Issue.FAIL, bid,
                f"HTML 자막 불일치:\n"
                f"       script: '{script_joined}'\n"
                f"       html:   '{html_joined}'"))

    return issues


def verify_html_opacity(html_path: Path) -> list[Issue]:
    """opacity:0 컨테이너에 대응하는 tl.set(opacity:1)이 있는지 검증.

    riseWords/springWords는 자식 .w만 애니메이션하므로,
    부모 div에 opacity:0이 있으면 반드시 tl.set으로 풀어줘야 함.
    """
    issues = []
    if not html_path.exists():
        return issues

    text = html_path.read_text(encoding="utf-8")

    hidden_divs = re.findall(
        r'id="(b\d+-t\d*)"[^>]*style="[^"]*opacity:\s*0',
        text
    )

    has_dynamic_opacity = bool(re.search(
        r'if\s*\(\s*si\s*>\s*0\s*\)\s*tl\.set\(\s*sel.*?opacity\s*:\s*1',
        text, re.DOTALL
    ))

    for div_id in hidden_divs:
        opacity_set = re.search(
            r'tl\.set\(\s*"#' + re.escape(div_id) + r'".*?opacity\s*:\s*1',
            text, re.DOTALL
        )
        if not opacity_set and not has_dynamic_opacity:
            issues.append(Issue(Issue.FAIL, div_id,
                f"opacity:0 컨테이너인데 tl.set(opacity:1) 없음 "
                f"-> riseWords/springWords 자막이 영원히 숨겨짐"))
        elif not opacity_set and has_dynamic_opacity:
            issues.append(Issue(Issue.INFO, div_id,
                f"동적 템플릿에서 런타임 opacity:1 처리 (si>0 패턴)"))

    return issues


def main():
    if len(sys.argv) < 2:
        print("Usage: python sync_verify.py <version_dir>")
        print("  예: python sync_verify.py edit/v14")
        sys.exit(1)

    v_dir = Path(sys.argv[1]).resolve()
    if not v_dir.is_dir():
        sys.exit(f"디렉토리 없음: {v_dir}")

    script_path = v_dir / "script.json"
    config_path = v_dir / "config.json"
    html_path = v_dir / "index.html"

    script = load_json(script_path)
    if script is None:
        sys.exit(f"script.json 없음: {script_path}")

    tts_cfg = script.get("meta", {}).get("tts", {})
    timing_file = tts_cfg.get("timing_file")
    timing = None
    if timing_file:
        timing_path = (v_dir / timing_file).resolve()
        timing = load_json(timing_path)

    config = load_json(config_path)
    html_subs = extract_html_subtitles(html_path) if html_path.exists() else {}

    all_issues: list[Issue] = []

    print(f"\n{'='*60}")
    print(f"  SSOT Sync Verify - {v_dir.name}")
    print(f"{'='*60}")

    print("\n[1] script.json 내부 일관성")
    internal = verify_internal(script)
    all_issues.extend(internal)
    if internal:
        for i in internal:
            print(str(i))
    else:
        print("  OK")

    print("\n[2] script.json ↔ tts_timing.json")
    if timing:
        vs_timing = verify_vs_timing(script, timing)
        all_issues.extend(vs_timing)
        if vs_timing:
            for i in vs_timing:
                print(str(i))
        else:
            print("  OK")
    else:
        print("  .tts_timing.json 없음 - 건너뜀")

    print("\n[3] script.json ↔ config.json")
    if config:
        vs_config = verify_vs_config(script, config)
        all_issues.extend(vs_config)
        if vs_config:
            for i in vs_config:
                print(str(i))
        else:
            print("  OK")
    else:
        print("  .config.json 없음 - 건너뜀")

    print("\n[4] script.json ↔ index.html")
    if html_subs:
        vs_html = verify_vs_html(script, html_subs)
        all_issues.extend(vs_html)
        if vs_html:
            for i in vs_html:
                print(str(i))
        else:
            print("  OK")
    else:
        print("  .index.html 자막 추출 실패 - 건너뜀")

    print("\n[5] index.html opacity 안전성")
    if html_path.exists():
        opacity_issues = verify_html_opacity(html_path)
        all_issues.extend(opacity_issues)
        if opacity_issues:
            for i in opacity_issues:
                print(str(i))
        else:
            print("  OK")
    else:
        print("  .index.html 없음 - 건너뜀")

    fails = sum(1 for i in all_issues if i.level == Issue.FAIL)
    warns = sum(1 for i in all_issues if i.level == Issue.WARN)
    print(f"\n{'='*60}")
    print(f"  결과: FAIL={fails}  WARN={warns}")
    if fails > 0:
        print("  -> FAIL 해결 필수")
    elif warns > 0:
        print("  -> WARN 확인 권장")
    else:
        print("  => ALL CLEAR")
    print(f"{'='*60}\n")

    sys.exit(1 if fails > 0 else 0)


if __name__ == "__main__":
    main()
