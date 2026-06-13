"""Qwen3-TTS voice clone — emotional ICL mode + speedup + SFX generation"""
import sys, json, subprocess, struct, math
from pathlib import Path

# ── Paths ──
HARNESS = Path(__file__).parent
MODEL_PATH = r"C:\Users\user\models\qwen3-tts\1.7B-Base"
REF_AUDIO = str(HARNESS / "voice_ref_emotional.wav")
REF_TEXT = "35세 부터 분위기 빠진다는 거 진짜 현실이네요 다리는 가늘어지고 허리는 아물찌고 머리부터 자신감이 떨어졌어요 운동하면 되는 거 아니냐고요"

PRODUCT = "레이건_요트링거반팔티"
VIDEO_ROOT = Path(r"Z:\NOMAL\자동화\비디오\video")
VERSION_DIR = VIDEO_ROOT / PRODUCT / "edit" / "v1"
SCRIPT_PATH = VERSION_DIR / "script.json"
TTS_DIR = VERSION_DIR / "tts"

SPEED_FACTOR = 1.3  # 1.3x faster

# beat별 감정 SSML-like prefix (Qwen3 doesn't use SSML, but adding emphasis markers in text)
BEAT_EMOTIONS = {
    "hook": "",    # hook = 강하고 빠르게
    "kick": "",    # kick = 자신감 넘치게
    "detail": "",  # detail = 설명적이지만 에너지
    "cta": "",     # cta = 친근하게
}


def load_model():
    import torch
    from qwen_tts import Qwen3TTSModel
    print("  [모델] Qwen3-TTS Base 로딩 (CUDA fp16)...")
    model = Qwen3TTSModel.from_pretrained(MODEL_PATH, dtype=torch.float16, device_map="cuda")
    print("  [모델] 로딩 완료")
    return model


def create_clone_prompt(model):
    print(f"  [ICL] 감정 레퍼런스: {Path(REF_AUDIO).name}")
    print(f"  [ICL] ref_text: {REF_TEXT[:50]}...")
    prompt = model.create_voice_clone_prompt(
        ref_audio=REF_AUDIO,
        ref_text=REF_TEXT,
        x_vector_only_mode=False  # ICL = full style transfer
    )
    print("  [ICL] 클론 프롬프트 생성 완료")
    return prompt


def generate_beat(model, clone_prompt, beat_id: str, text: str, output_wav: Path):
    import numpy as np, soundfile as sf
    print(f"  [{beat_id}] \"{text[:35]}...\"")
    audios, sr = model.generate_voice_clone(
        text=text,
        language="korean",
        voice_clone_prompt=clone_prompt,
        non_streaming_mode=True,
    )
    audio_np = audios[0] if isinstance(audios[0], np.ndarray) else audios[0].cpu().float().numpy()
    sf.write(str(output_wav), audio_np, sr)
    dur = len(audio_np) / sr
    print(f"  [{beat_id}] 원본: {dur:.2f}s @ {sr}Hz")
    return dur, sr


def speedup_beat(input_wav: Path, output_mp3: Path, factor: float):
    """ffmpeg atempo로 속도 올림"""
    cmd = [
        "ffmpeg", "-y", "-i", str(input_wav),
        "-filter:a", f"atempo={factor}",
        "-b:a", "192k",
        str(output_mp3)
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        print(f"  speedup FAIL: {r.stderr[:200]}")
        return 0.0
    # get duration
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration", "-of", "csv=p=0", str(output_mp3)],
        capture_output=True, text=True, timeout=10
    )
    dur = float(probe.stdout.strip()) if probe.returncode == 0 else 0.0
    print(f"  [{input_wav.stem}] {factor}x 속도: {dur:.2f}s")
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
    clone_prompt = create_clone_prompt(model)

    beat_files = []
    beat_durations = []
    total_chars = 0

    GAPS = {"hook": 0.10, "kick": 0.12, "detail": 0.10, "cta": 0.0}

    for beat in beats:
        narration = beat.get("narration", "").strip()
        if not narration:
            continue
        bid = beat["id"]
        total_chars += len(narration)

        wav_path = TTS_DIR / f"{bid}_raw.wav"
        mp3_path = TTS_DIR / f"{bid}.mp3"

        generate_beat(model, clone_prompt, bid, narration, wav_path)
        dur = speedup_beat(wav_path, mp3_path, SPEED_FACTOR)

        beat_type = bid.rstrip("0123456789").lower()
        gap = GAPS.get(beat_type, 0.10)

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
    del model, clone_prompt
    torch.cuda.empty_cache()
    print("  GPU 메모리 해제 완료\n")


if __name__ == "__main__":
    main()
