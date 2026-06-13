"""Update config.json with more dynamic cuts + recalculate timings"""
import json

CONFIG = r"Z:\NOMAL\자동화\비디오\video\오션_입체포켓카라니트\edit\v1\config.json"
SCRIPT = r"Z:\NOMAL\자동화\비디오\video\오션_입체포켓카라니트\edit\v1\script.json"

with open(SCRIPT, "r", encoding="utf-8") as f:
    script = json.load(f)
with open(CONFIG, "r", encoding="utf-8") as f:
    config = json.load(f)

bd_map = {b["id"]: b for b in script["meta"]["tts"]["beat_durations"]}

t = 0.0
for sb, cb in zip(script["beats"], config["beats"]):
    bid = sb["id"]
    bd = bd_map[bid]
    dur = bd["duration"]
    gap = bd["gap_after"]
    sb["start"] = round(t, 3)
    sb["end"] = round(t + dur, 3)
    cb["start"] = round(t, 3)
    cb["duration"] = round(dur, 3)
    t += dur + gap

dynamic_cuts = {
    "hook": [
        {"id": "hookc1", "source": "crop_black", "start": 0.0, "dur": 0.65, "motion": "snap-zoom", "originX": 50, "originY": 58},
        {"id": "hookc2", "source": "comp_boring", "start": 0.65, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "hookc3", "source": "crop_ivory", "start": 1.25, "dur": 0.7, "motion": "snap-zoom", "originX": 50, "originY": 55},
        {"id": "hookc4", "source": "styling_black", "start": 1.95, "dur": 0.94, "motion": "zoom-in", "originX": 50, "originY": 55},
    ],
    "kick": [
        {"id": "kickc1", "source": "detail_black", "start": 0.0, "dur": 0.7, "motion": "snap-zoom", "originX": 50, "originY": 45},
        {"id": "kickc2", "source": "detail_ivory", "start": 0.7, "dur": 0.7, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "kickc3", "source": "styling_ivory", "start": 1.4, "dur": 0.94, "motion": "zoom-in", "originX": 50, "originY": 55},
    ],
    "detail1": [
        {"id": "d1c1", "source": "styling_black", "start": 0.0, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 55},
        {"id": "d1c2", "source": "wear_ivory_1", "start": 0.6, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 58},
        {"id": "d1c3", "source": "wear_black_1", "start": 1.2, "dur": 0.75, "motion": "zoom-in", "originX": 50, "originY": 55},
    ],
    "detail2": [
        {"id": "d2c1", "source": "detail_collar", "start": 0.0, "dur": 0.5, "motion": "snap-zoom", "originX": 50, "originY": 40},
        {"id": "d2c2", "source": "detail_sleeve", "start": 0.5, "dur": 0.55, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "d2c3", "source": "wear_ivory_2", "start": 1.05, "dur": 0.64, "motion": "zoom-in", "originX": 50, "originY": 55},
    ],
    "detail3": [
        {"id": "d3c1", "source": "detail_fabric", "start": 0.0, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "d3c2", "source": "detail_wrinkle", "start": 0.6, "dur": 0.65, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "d3c3", "source": "wear_black_2", "start": 1.25, "dur": 0.84, "motion": "zoom-in", "originX": 50, "originY": 58},
    ],
    "detail4": [
        {"id": "d4c1", "source": "detail_no_see", "start": 0.0, "dur": 0.55, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "d4c2", "source": "wear_ivory_3", "start": 0.55, "dur": 0.55, "motion": "snap-zoom", "originX": 50, "originY": 58},
        {"id": "d4c3", "source": "wear_black_3", "start": 1.1, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 55},
        {"id": "d4c4", "source": "styling_ivory", "start": 1.7, "dur": 0.68, "motion": "zoom-in", "originX": 50, "originY": 55},
    ],
    "cta": [
        {"id": "ctac1", "source": "product_black", "start": 0.0, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "ctac2", "source": "product_ivory", "start": 0.6, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "ctac3", "source": "product_beige", "start": 1.2, "dur": 0.6, "motion": "snap-zoom", "originX": 50, "originY": 50},
        {"id": "ctac4", "source": "product_all", "start": 1.8, "dur": 0.83, "motion": "zoom-in", "originX": 50, "originY": 50},
    ],
}

total_cuts = 0
for cb in config["beats"]:
    bid = cb["id"]
    if bid in dynamic_cuts:
        new_cuts = []
        for c in dynamic_cuts[bid]:
            cut = {"id": c["id"], "type": "image", "source": c["source"],
                   "start": c["start"], "dur": c["dur"], "motion": c["motion"],
                   "originX": c["originX"], "originY": c["originY"]}
            new_cuts.append(cut)
        cb["cuts"] = new_cuts
        total_cuts += len(new_cuts)

sfx_cues = []
for cb in config["beats"]:
    beat_start = cb["start"]
    for cut in cb["cuts"][1:]:
        sfx_cues.append({"type": "beat", "at": round(beat_start + cut["start"], 2)})

config["sfx"]["cues"] = sfx_cues
config["meta"]["total_cuts"] = total_cuts
all_durs = [c["dur"] for b in config["beats"] for c in b["cuts"]]
config["meta"]["avg_cut_duration"] = round(sum(all_durs) / len(all_durs), 2)
config["meta"]["duration"] = round(t, 1)
script["meta"]["duration"] = round(t, 1)

with open(SCRIPT, "w", encoding="utf-8") as f:
    json.dump(script, f, ensure_ascii=False, indent=2)
with open(CONFIG, "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"  total cuts: {total_cuts} (avg {config['meta']['avg_cut_duration']:.2f}s)")
print(f"  SFX cues: {len(sfx_cues)}")
print(f"  duration: {t:.1f}s")
print("  DONE")
