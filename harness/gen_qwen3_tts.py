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

PRODUCT = "아케이드랩스_DL826"
VIDEO_ROOT = Path(r"Z:\NOMAL\자동화\비디오\video")
VERSION_DIR = VIDEO_ROOT / PRODUCT / "reels" / "story"
SCRIPT_PATH = VERSION_DIR / "script.json"
TTS_DIR = VERSION_DIR / "tts"

SPEED_FACTOR = 1.2  # 1.2x (사용자 요청: 1.3→1.2 감속)
PITCH_UP = 1.10    # 10% 피치업 (7/17 사용자 지시로 7.5%→10% 상향)


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
    # Qwen3 출력 sample_rate 감지
    sr_probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "stream=sample_rate", "-of", "csv=p=0", str(input_wav)],
        capture_output=True, text=True, timeout=10
    )
    sr = int(sr_probe.stdout.strip()) if sr_probe.returncode == 0 else 24000
    pitched_rate = int(sr * pitch_up)

    af_chain = (
        f"asetrate={pitched_rate},aresample={sr},"
        f"atempo={factor},"
        f"loudnorm=I=-14:LRA=11:TP=-1"
    )
    cmd = [
        "ffmpeg", "-y", "-i", str(input_wav),
        "-filter:a", af_chain,
        "-b:a", "192k",
        str(output_mp3)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  speedup FAIL: {r.stderr[:200]}")
        return 0.0
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(output_mp3)],
        capture_output=True, text=True, timeout=10
    )
    dur = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
    print(f"  [{input_wav.stem}] pitch+{pitch_up:.3f} → {factor}x → loudnorm: {dur:.2f}s")
    return dur


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
