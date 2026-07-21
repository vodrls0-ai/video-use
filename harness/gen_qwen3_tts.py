"""Qwen3-TTS voice clone — 5감정 비트매핑 체제 + speedup + SFX"""
import sys, json, subprocess, struct, math
from pathlib import Path

# ── Paths ──
HARNESS = Path(__file__).parent
MODEL_PATH = r"C:\Users\user\models\qwen3-tts\1.7B-Base"

VOICE_CLONE = Path(r"Z:\NOMAL\자동화\비디오\voice_clone")

# 5감정 레퍼런스 매핑 (보정본 사용)
# ref_text = Whisper 전사 결과 그대로 (실제 발화와 일치해야 ICL 정상 작동)
EMOTION_REFS = {
    "hook": {
        "ref": str(VOICE_CLONE / "ref_hook_processed.wav"),
        "text": "하체가 외소에서 반바지를 못 입는 분들을 위한 한장 29,800원 여름에 편하면서도 다리 길어 보이는 와이드핏 범유다 입니다",
    },
    "pain": {
        "ref": str(VOICE_CLONE / "ref_pain_processed.wav"),
        "text": "35세부터 근육이 빠진다는 거 진짜 현실이네요 다리는 가늘어지고 나이 살은 찌고 머리 보도 자신감이 떨어졌어요 운동하면 되는 거 아니냐고요?",
    },
    "confident": {
        "ref": str(VOICE_CLONE / "ref_confident_processed.wav"),
        "text": "같은 몸인데 분위기는 완전히 달라져요 결국 나이가 문제가 아니라 분위기 문제였습니다 제가 아이에게 칭찬받을 수 있을 때까지 팔로우하고 지켜봐 주세요",
    },
    "price": {
        "ref": str(VOICE_CLONE / "ref_price_processed.wav"),
        "text": "무엇보다 이게 전보 29,800원이에요 1 플러스 1하면 한 장에 14,900원 밖에 안 하거든요 이 퀄리티의 이 가격 진짜 비쳤다고 생각해요",
    },
    "cta": {
        "ref": str(VOICE_CLONE / "ref_cta_processed.wav"),
        "text": "지금 아래 링크 클릭 하시고요 한 번만 입어보시면 진짜 다른 바지 못 입으실 거예요 꼭 한 번 입어보세요",
    },
}

# narration_id → 감정 매핑 (블루트/릴스 공통)
BEAT_TO_EMOTION = {
    "opening": "hook",
    "hook": "hook",
    "problem": "pain",
    "pain": "pain",
    "pivot": "confident",
    "usp1": "confident",
    "usp2": "confident",
    "usp3": "confident",
    "usp4": "confident",
    "usp5": "confident",
    "usp6": "price",
    "price": "price",
    "price_shock": "price",
    "price_teaser": "price",
    "price_punch": "price",
    "cta": "cta",
    "kick": "confident",
    "detail": "confident",
}

# 하위호환: --style 옵션 (단일감정 강제)
import argparse as _ap
_p = _ap.ArgumentParser(add_help=False)
_p.add_argument("--style", default=None, choices=list(EMOTION_REFS.keys()))
_a, _ = _p.parse_known_args()
FORCE_STYLE = _a.style  # None이면 비트별 자동매핑

PRODUCT = "노벨러_노이즈워싱데님반팔셔츠"
VIDEO_ROOT = Path(r"Z:\NOMAL\자동화\비디오\video")
VERSION_DIR = VIDEO_ROOT / PRODUCT / "reels" / "meta"
SCRIPT_PATH = VERSION_DIR / "script.json"
TTS_DIR = VERSION_DIR / "tts"

SPEED_FACTOR = 1.2  # 1.2x (사용자 요청: 1.3→1.2 감속)
PITCH_UP = 1.13    # rule37 확정값 (7/18 재하향 후 잠금)


def load_model():
    import torch
    from qwen_tts import Qwen3TTSModel
    print("  [모델] Qwen3-TTS Base 로딩 (CUDA fp16)...")
    model = Qwen3TTSModel.from_pretrained(MODEL_PATH, dtype=torch.float16, device_map="cuda")
    print("  [모델] 로딩 완료")
    return model


def resolve_emotion(beat_id: str) -> str:
    """beat_id → 감정 키 결정. --style 강제 시 전부 같은 감정."""
    if FORCE_STYLE:
        return FORCE_STYLE
    base = beat_id.rstrip("0123456789").lower()
    return BEAT_TO_EMOTION.get(base, BEAT_TO_EMOTION.get(beat_id, "confident"))


def create_clone_prompt(model, emotion_key: str):
    """단일 감정 프롬프트 생성 (GPU 메모리 절약 — 필요 시에만 로드)"""
    emo_data = EMOTION_REFS[emotion_key]
    ref_path = emo_data["ref"]
    if not Path(ref_path).exists():
        print(f"  [WARN] {ref_path} 없음 → pain으로 대체")
        emo_data = EMOTION_REFS["pain"]
        ref_path = emo_data["ref"]
    prompt = model.create_voice_clone_prompt(
        ref_audio=ref_path,
        ref_text=emo_data["text"],
        x_vector_only_mode=False,
    )
    return prompt


def generate_beat(model, beat_id: str, text: str, output_wav: Path, _prompt_cache: dict = {}):
    """비트별 감정 자동 선택 + 프롬프트 캐싱 (같은 감정은 재사용)"""
    import numpy as np, soundfile as sf
    text = text.replace("1+1", "원플러스원")  # "일플러스일" 오발음 방지 (사용자 반복 지적, 6/29~)
    emotion = resolve_emotion(beat_id)
    if emotion not in _prompt_cache:
        print(f"  [ICL:{emotion}] {Path(EMOTION_REFS[emotion]['ref']).name}")
        _prompt_cache[emotion] = create_clone_prompt(model, emotion)
    clone_prompt = _prompt_cache[emotion]
    print(f"  [{beat_id}:{emotion}] \"{text[:35]}...\"")
    audios, sr = model.generate_voice_clone(
        text=text,
        language="korean",
        voice_clone_prompt=clone_prompt,
        non_streaming_mode=True,
    )
    audio_np = audios[0] if isinstance(audios[0], np.ndarray) else audios[0].cpu().float().numpy()
    sf.write(str(output_wav), audio_np, sr)
    dur = len(audio_np) / sr
    print(f"  [{beat_id}:{emotion}] 원본: {dur:.2f}s @ {sr}Hz")
    return dur, sr


def speedup_beat(input_wav: Path, output_mp3: Path, factor: float, pitch_up: float = PITCH_UP):
    """피치업 + atempo 속도 올림 + 라우드니스 정규화"""
    import json as _json
    # Qwen3 출력 sample_rate 감지
    sr_probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(input_wav)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
    )
    sr = int(sr_probe.stdout.strip()) if sr_probe.returncode == 0 else 24000
    pitched_rate = int(sr * pitch_up)

    # 무음구간 제거: TTS 모델이 문장 시작에 무음 패딩을 남기는 경우가 있어 앞쪽만 트림한다.
    # 끝쪽 트림(reverse+silenceremove)은 제거함 — 7/21 "끝음 씹힘" 반복사고의 원인이었음:
    # 어떤 임계값을 써도 단어 끝의 자연스러운 여운/약한 음절(예: "쾌적해요"의 "요")을 무음으로
    # 오판해 잘라낼 위험이 있다. 끝에 무음이 살짝 남는 것(무해)이 발화가 잘리는 것(치명적)보다 낫다.
    pre_af = (
        f"asetrate={pitched_rate},aresample={sr},"
        f"atempo={factor},"
        f"silenceremove=start_periods=1:start_duration=0.05:start_threshold=-45dB:detection=peak"
    )
    intermediate = output_mp3.with_name(output_mp3.stem + "_pre.wav")
    cmd_pre = ["ffmpeg", "-y", "-i", str(input_wav), "-filter:a", pre_af, str(intermediate)]
    r_pre = subprocess.run(cmd_pre, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if r_pre.returncode != 0:
        print(f"  전처리 실패: {(r_pre.stderr or '')[-500:]}")
        return 0.0

    # 라우드니스 2-패스 정규화 — 짧은 클립(우리 TTS 대부분 1~3초)은 싱글패스 loudnorm이
    # 목표치를 못 맞추고 실측 -13~-15 LUFS로 나오는 문제 확인됨(7/21). 측정→적용 2단계로 정확히 맞춘다.
    target_i, target_lra, target_tp = -9, 11, -1
    cmd_measure = [
        "ffmpeg", "-i", str(intermediate),
        "-af", f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:print_format=json",
        "-f", "null", "-"
    ]
    r_measure = subprocess.run(cmd_measure, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    measured = None
    try:
        stderr_text = r_measure.stderr or ""
        json_str = stderr_text[stderr_text.rindex("{"):stderr_text.rindex("}") + 1]
        measured = _json.loads(json_str)
    except (ValueError, _json.JSONDecodeError):
        measured = None

    if measured:
        af_chain = (
            f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"linear=true"
        )
    else:
        af_chain = f"loudnorm=I={target_i}:LRA={target_lra}:TP={target_tp}"  # 측정 실패 시 싱글패스 폴백

    cmd = [
        "ffmpeg", "-y", "-i", str(intermediate),
        "-filter:a", af_chain,
        "-b:a", "192k",
        str(output_mp3)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    intermediate.unlink(missing_ok=True)
    if r.returncode != 0:
        print(f"  speedup FAIL: {(r.stderr or '')[:200]}")
        return 0.0
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(output_mp3)],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
    )
    dur = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
    print(f"  [{input_wav.stem}] pitch+{pitch_up:.3f} → {factor}x → loudnorm: {dur:.2f}s")
    return dur


_whisper_model_cache = {}


def _get_whisper_model(size: str = "medium"):
    if size not in _whisper_model_cache:
        import whisper
        _whisper_model_cache[size] = whisper.load_model(size)
    return _whisper_model_cache[size]


def _verify_transcript(expected_text: str, transcript: str, sim_threshold: float = 0.7) -> tuple[bool, float, str]:
    """전체 유사도 + 마지막 어절 인식 여부를 함께 확인 (7/21: 유사도만 보면 끝 단어 누락을 놓침)."""
    import difflib
    expected_clean = expected_text.replace(" ", "")
    clean = transcript.replace(" ", "")
    sim = difflib.SequenceMatcher(None, expected_clean, clean).ratio()
    words = expected_text.split()
    last_word = words[-1] if words else ""
    last_word_clean = last_word.replace(" ", "")
    core = last_word_clean[:max(2, len(last_word_clean) - 1)]
    last_ok = (core in clean) if core else True
    ok = sim >= sim_threshold and last_ok
    reason = "" if ok else ("유사도부족" if sim < sim_threshold else f"끝어절('{last_word}') 인식실패")
    return ok, sim, reason


def generate_beat_verified(model, beat_id: str, text: str, output_mp3: Path,
                            max_tries: int = 5, sim_threshold: float = 0.7,
                            whisper_size: str = "medium") -> dict:
    """generate_beat + speedup_beat을 실행하고 Whisper로 원문 대조, 불일치 시 재생성(최대 max_tries회).

    나레이션 씹힘/끝음잘림(7/21 반복사고) 재발 방지용 표준 진입점.
    새 상품 TTS 생성 시 이 함수를 쓸 것 — 별도 스크립트로 로직 재구현하지 말 것.
    """
    whisper_model = _get_whisper_model(whisper_size)
    tmp_wav = output_mp3.with_name(f"{output_mp3.stem}_raw.wav")
    last_sim, last_reason = 0.0, ""
    for attempt in range(1, max_tries + 1):
        try_mp3 = output_mp3.with_name(f"{output_mp3.stem}_try{attempt}.mp3")
        generate_beat(model, beat_id, text, tmp_wav)
        dur = speedup_beat(tmp_wav, try_mp3, SPEED_FACTOR)
        tmp_wav.unlink(missing_ok=True)
        result = whisper_model.transcribe(str(try_mp3), language="ko")
        transcript = result["text"].strip()
        ok, sim, reason = _verify_transcript(text, transcript, sim_threshold)
        print(f"  [{beat_id}] 시도{attempt}: {dur:.3f}s | Whisper=\"{transcript}\" | 유사도={sim:.2f} | {'OK' if ok else 'FAIL:'+reason}")
        if ok:
            try_mp3.replace(output_mp3)
            for a in range(1, max_tries + 1):
                leftover = output_mp3.with_name(f"{output_mp3.stem}_try{a}.mp3")
                if leftover.exists():
                    leftover.unlink()
            return {"id": beat_id, "duration": round(dur, 3), "attempts": attempt, "sim": round(sim, 2), "ok": True}
        last_sim, last_reason = sim, reason
        try_mp3.unlink(missing_ok=True)
    print(f"  [{beat_id}] {max_tries}회 모두 실패 ({last_reason}) — 수동 확인 필요")
    return {"id": beat_id, "duration": None, "attempts": max_tries, "sim": round(last_sim, 2), "ok": False}


def generate_sfx_track(cues: list, total_duration: float, output_path: Path):
    """ffmpeg로 pop/click 사운드 믹스 — 비트 전환점에 짧은 pop"""
    sr = 44100
    total_samples = int(total_duration * sr)
    samples = [0.0] * total_samples

    for cue in cues:
        t = cue.get("at", 0.0)
        start = int(t * sr)
        # 짧은 pop: 30ms sine burst with exponential decay
        pop_dur = 0.03
        pop_samples = int(pop_dur * sr)
        for i in range(pop_samples):
            if start + i < total_samples:
                freq = 800  # Hz
                decay = math.exp(-i / (pop_samples * 0.3))
                val = 0.4 * math.sin(2 * math.pi * freq * i / sr) * decay
                samples[start + i] = val

    # Write as WAV
    wav_path = output_path.with_suffix(".wav")
    with open(wav_path, "wb") as f:
        num = len(samples)
        data = struct.pack(f"<{num}h", *[int(max(-32768, min(32767, s * 32767))) for s in samples])
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, sr, sr * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)

    # Convert to mp3
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(output_path)],
        capture_output=True, timeout=30
    )
    if wav_path.exists():
        wav_path.unlink()
    print(f"  [SFX] 생성: {output_path.name} ({len(cues)}개 pop, {total_duration:.1f}s)")


def main():
    print(f"\n  === Qwen3 TTS (감정ICL + {SPEED_FACTOR}x 속도) ===\n")

    with open(SCRIPT_PATH, "r", encoding="utf-8") as f:
        script = json.load(f)

    beats = script.get("beats", [])
    if not beats:
        print("  ERROR: beats 없음")
        sys.exit(1)

    TTS_DIR.mkdir(exist_ok=True)

    model = load_model()

    beat_files = []
    beat_durations = []
    total_chars = 0

    # 비트 간 무음 갭 = 0 (하드코딩, 무음구간 절대 금지)
    GAP = 0.0

    for beat in beats:
        narration = beat.get("narration", "").strip()
        if not narration:
            continue
        bid = beat["id"]
        total_chars += len(narration)

        wav_path = TTS_DIR / f"{bid}_raw.wav"
        mp3_path = TTS_DIR / f"{bid}.mp3"

        generate_beat(model, bid, narration, wav_path)
        dur = speedup_beat(wav_path, mp3_path, SPEED_FACTOR)

        gap = GAP

        beat_files.append(mp3_path)
        beat_durations.append({"id": bid, "duration": round(dur, 3), "gap_after": gap})

    if beat_durations:
        beat_durations[-1]["gap_after"] = 0.0

    # Generate gap files
    gap_files = {}
    for bd in beat_durations:
        g = bd["gap_after"]
        if g > 0 and g not in gap_files:
            gap_path = TTS_DIR / f"_gap_{g:.2f}s.mp3"
            subprocess.run(
                ["ffmpeg", "-y", "-f", "lavfi", "-i", f"anullsrc=r=44100:cl=mono",
                 "-t", str(g), "-b:a", "128k", str(gap_path)],
                capture_output=True, timeout=10
            )
            gap_files[g] = gap_path

    # Concat all beats
    merged = VERSION_DIR / "tts_v1.mp3"
    list_path = TTS_DIR / "_concat.txt"
    with open(list_path, "w", encoding="utf-8") as f:
        for i, bf in enumerate(beat_files):
            f.write(f"file '{bf.name}'\n")
            gap = beat_durations[i]["gap_after"]
            if gap > 0 and gap in gap_files:
                f.write(f"file '{gap_files[gap].name}'\n")

    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
         "-i", str(list_path), "-c", "copy", str(merged)],
        capture_output=True, cwd=str(TTS_DIR), timeout=30
    )

    total_audio = sum(bd["duration"] for bd in beat_durations)
    total_gaps = sum(bd["gap_after"] for bd in beat_durations)
    print(f"\n  TTS={total_audio:.1f}s + 갭={total_gaps:.1f}s = {total_audio + total_gaps:.1f}s")

    # Update script.json
    if "meta" not in script:
        script["meta"] = {}
    script["meta"]["tts"] = {
        "file": "tts_v1.mp3",
        "timing_file": "",
        "timing_stale": True,
        "chars": total_chars,
        "beats_count": len(beat_files),
        "beat_durations": beat_durations,
        "engine": "qwen3-clone-icl-emotional"
    }
    with open(SCRIPT_PATH, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    print(f"  TTS 완료: {merged.name} ({len(beat_files)}비트, {total_chars}자)\n")

    # Generate SFX
    config_path = VERSION_DIR / "config.json"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
        cues = config.get("sfx", {}).get("cues", [])
        if cues:
            sfx_path = VERSION_DIR / "sfx.mp3"
            generate_sfx_track(cues, total_audio + total_gaps + 2.0, sfx_path)
            config["audio"]["sfx"] = "sfx.mp3"
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, ensure_ascii=False, indent=2)
            print("  config.json sfx 경로 업데이트 완료")

    # Cleanup raw WAVs
    for wav in TTS_DIR.glob("*_raw.wav"):
        wav.unlink()
    print("  raw WAV 정리 완료")

    # Free GPU memory
    import torch
    del model
    torch.cuda.empty_cache()
    print("  GPU 메모리 해제 완료\n")


if __name__ == "__main__":
    main()
