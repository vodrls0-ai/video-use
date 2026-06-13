"""Generate varied SFX track: per-beat diverse sounds.

Usage:
    python gen_sfx.py <version_dir>
    python gen_sfx.py <version_dir> --volume 2.5

Reads config.json from version_dir, writes sfx.mp3.
Each cue can specify a type (impact/whoosh/ding/swoosh/shutter/click/pop/snap/buzz/rise).
If no type specified, auto-assigns based on beat section and index.
"""
import json, struct, math, subprocess, sys
from pathlib import Path

SR = 44100


def _noise(seed_state):
    seed_state[0] = (seed_state[0] * 16807 + 7) % 2147483647
    return (seed_state[0] / 2147483647) * 2 - 1


def make_impact(sr=SR):
    """Low thud + noise burst"""
    seed = [99]
    samples = []
    dur = int(0.06 * sr)
    for i in range(dur):
        t = i / sr
        env = math.exp(-i / (0.015 * sr))
        val = 0.9 * math.sin(2 * math.pi * 60 * t) * env
        val += 0.5 * _noise(seed) * env * 0.7
        val += 0.3 * math.sin(2 * math.pi * 120 * t) * env
        samples.append(val)
    return samples


def make_whoosh(sr=SR):
    """Filtered noise sweep"""
    seed = [77]
    samples = []
    dur = int(0.18 * sr)
    for i in range(dur):
        t = i / sr
        progress = i / dur
        env = math.sin(math.pi * progress) * 0.6
        freq = 200 + 3000 * progress
        val = _noise(seed) * env
        val *= math.sin(2 * math.pi * freq * t) * 0.3 + 0.7
        samples.append(val * 0.5)
    return samples


def make_ding(sr=SR):
    """Bright bell ding — metallic resonance"""
    samples = []
    dur = int(0.25 * sr)
    for i in range(dur):
        t = i / sr
        env = math.exp(-i / (0.06 * sr))
        val = 0.5 * math.sin(2 * math.pi * 2400 * t) * env
        val += 0.3 * math.sin(2 * math.pi * 4800 * t) * env * 0.6
        val += 0.15 * math.sin(2 * math.pi * 7200 * t) * env * 0.3
        samples.append(val)
    return samples


def make_swoosh(sr=SR):
    """Fast swoosh — rising pitch sweep"""
    seed = [55]
    samples = []
    dur = int(0.12 * sr)
    for i in range(dur):
        t = i / sr
        progress = i / dur
        env = math.sin(math.pi * progress) * 0.7
        freq = 800 + 4000 * progress * progress
        val = _noise(seed) * env * 0.4
        val += 0.5 * math.sin(2 * math.pi * freq * t) * env * 0.3
        samples.append(val)
    return samples


def make_shutter(sr=SR):
    """Camera shutter click"""
    seed = [42]
    samples = []
    for i in range(int(0.015 * sr)):
        env = math.exp(-i / (0.005 * sr))
        samples.append(0.7 * _noise(seed) * env)
    samples.extend([0.0] * int(0.008 * sr))
    for i in range(int(0.010 * sr)):
        env = math.exp(-i / (0.003 * sr))
        samples.append(0.8 * _noise(seed) * env)
    return samples


def make_click(sr=SR):
    """UI click transient"""
    samples = []
    dur = int(0.012 * sr)
    for i in range(dur):
        t = i / sr
        env = math.exp(-i / (0.003 * sr))
        val = 0.6 * math.sin(2 * math.pi * 3200 * t) * env
        val += 0.3 * math.sin(2 * math.pi * 6400 * t) * env * 0.5
        samples.append(val)
    return samples


def make_pop(sr=SR):
    """Pop — low freq pulse"""
    samples = []
    dur = int(0.045 * sr)
    for i in range(dur):
        t = i / sr
        env = math.exp(-i / (0.008 * sr))
        val = 0.8 * math.sin(2 * math.pi * 180 * t) * env
        val += 0.4 * math.sin(2 * math.pi * 360 * t) * env * 0.6
        samples.append(val)
    return samples


def make_snap(sr=SR):
    """Snap/tick percussive"""
    samples = []
    dur = int(0.008 * sr)
    for i in range(dur):
        t = i / sr
        env = 1.0 if i < dur * 0.1 else math.exp(-(i - dur * 0.1) / (0.002 * sr))
        val = 0.7 * math.sin(2 * math.pi * 4500 * t) * env
        samples.append(val)
    return samples


def make_buzz(sr=SR):
    """Error/negative buzz"""
    seed = [33]
    samples = []
    dur = int(0.15 * sr)
    for i in range(dur):
        t = i / sr
        progress = i / dur
        env = 0.6 * (1 - progress * 0.7)
        val = 0.5 * math.sin(2 * math.pi * 150 * t) * env
        val += 0.4 * math.sin(2 * math.pi * 300 * t) * env
        val += 0.2 * _noise(seed) * env * 0.5
        samples.append(val)
    return samples


def make_rise(sr=SR):
    """Rising tone — anticipation/reveal"""
    samples = []
    dur = int(0.3 * sr)
    for i in range(dur):
        t = i / sr
        progress = i / dur
        env = progress * math.exp(-max(0, progress - 0.85) * 10)
        freq = 400 + 2000 * progress * progress
        val = 0.5 * math.sin(2 * math.pi * freq * t) * env
        val += 0.25 * math.sin(2 * math.pi * freq * 1.5 * t) * env * 0.5
        samples.append(val)
    return samples


def make_drop(sr=SR):
    """Pitch drop — weight/gravity"""
    samples = []
    dur = int(0.15 * sr)
    for i in range(dur):
        t = i / sr
        progress = i / dur
        env = math.exp(-progress * 3)
        freq = 1200 * (1 - progress * 0.8)
        val = 0.6 * math.sin(2 * math.pi * freq * t) * env
        samples.append(val)
    return samples


SFX_MAP = {
    "impact": make_impact, "whoosh": make_whoosh, "ding": make_ding,
    "swoosh": make_swoosh, "shutter": make_shutter, "click": make_click,
    "pop": make_pop, "snap": make_snap, "buzz": make_buzz,
    "rise": make_rise, "drop": make_drop,
}

SECTION_SFX = {
    "HOOK": ["impact", "drop"],
    "SITUATION": ["buzz", "whoosh"],
    "REVERSAL": ["rise", "swoosh"],
    "PRODUCT_FIX": ["ding", "shutter"],
    "PROOF": ["snap", "click"],
    "CTA": ["ding", "rise"],
    "PRICE": ["ding", "pop"],
    "DETAIL": ["shutter", "click"],
    "STYLING": ["swoosh", "snap"],
    "KICK": ["impact", "pop"],
}

CUT_SFX = ["click", "snap", "shutter", "swoosh", "pop", "click", "snap", "shutter"]


def auto_sfx_type(section, beat_idx, cut_idx):
    pool = SECTION_SFX.get(section, ["click", "snap"])
    if cut_idx > 0:
        return CUT_SFX[(beat_idx * 3 + cut_idx) % len(CUT_SFX)]
    return pool[beat_idx % len(pool)]


def main():
    if len(sys.argv) < 2:
        print("Usage: python gen_sfx.py <version_dir> [--volume N]")
        sys.exit(1)

    v_dir = Path(sys.argv[1]).resolve()
    config_path = v_dir / "config.json"
    output_path = v_dir / "sfx.mp3"

    vol_boost = 2.0
    if "--volume" in sys.argv:
        vi = sys.argv.index("--volume")
        if vi + 1 < len(sys.argv):
            vol_boost = float(sys.argv[vi + 1])

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    cues = config.get("sfx", {}).get("cues", [])
    total_dur = config["meta"]["duration"] + 1.0
    total_samples = int(total_dur * SR)
    mixed = [0.0] * total_samples

    if not cues:
        for bi, beat in enumerate(config.get("beats", [])):
            section = beat.get("section", "")
            cues.append({"at": beat["start"], "type": auto_sfx_type(section, bi, 0)})
            for ci, cut in enumerate(beat.get("cuts", [])):
                if ci > 0:
                    cues.append({"at": beat["start"] + cut["start"], "type": auto_sfx_type(section, bi, ci)})

    print(f"  SFX 생성: {len(cues)}개 큐, {total_dur:.1f}초")

    for idx, cue in enumerate(cues):
        t = cue.get("at", 0.0)
        sfx_type = cue.get("type", "click")
        sfx_fn = SFX_MAP.get(sfx_type, make_click)
        start = int(t * SR)
        samples = sfx_fn()
        vol = cue.get("volume", 1.0)

        for i, s in enumerate(samples):
            pos = start + i
            if 0 <= pos < total_samples:
                mixed[pos] = max(-1.0, min(1.0, mixed[pos] + s * vol))

        name = sfx_fn.__doc__.split("—")[0].strip() if sfx_fn.__doc__ else sfx_type
        print(f"  [{idx+1:2d}] {t:5.2f}s - {sfx_type:8s} ({name}, {len(samples)/SR*1000:.0f}ms)")

    wav_path = output_path.with_suffix(".wav")
    data = struct.pack(f"<{len(mixed)}h",
                       *[int(max(-32768, min(32767, s * 32767))) for s in mixed])
    with open(wav_path, "wb") as f:
        f.write(b"RIFF")
        f.write(struct.pack("<I", 36 + len(data)))
        f.write(b"WAVE")
        f.write(b"fmt ")
        f.write(struct.pack("<IHHIIHH", 16, 1, 1, SR, SR * 2, 2, 16))
        f.write(b"data")
        f.write(struct.pack("<I", len(data)))
        f.write(data)

    subprocess.run(
        ["ffmpeg", "-y", "-i", str(wav_path), "-af", f"volume={vol_boost}", "-b:a", "192k", str(output_path)],
        capture_output=True, timeout=30
    )
    wav_path.unlink(missing_ok=True)

    r = subprocess.run(
        ["ffmpeg", "-i", str(output_path), "-af", "volumedetect", "-f", "null", "NUL"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10
    )
    for line in (r.stderr or "").split("\n"):
        if "volume" in line.lower():
            print(f"  {line.strip()}")

    print(f"\n  SFX 완료: {output_path.name} ({len(cues)} cues, {len(set(c.get('type','click') for c in cues))} unique types)")


if __name__ == "__main__":
    main()
