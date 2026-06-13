"""Post-TTS pipeline: readjust_timing -> whisper -> build -> render (skip TTS)"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
from auto_reel import readjust_timing, run_whisper, run_build, run_render

VERSION_DIR = Path(r"Z:\NOMAL\자동화\비디오\video\오션_입체포켓카라니트\edit\v1")

print("\n  === Post-TTS Pipeline (Qwen3 ICL 감정+1.3x) ===\n")

print("  [1/5] 타이밍 재조정...")
if not readjust_timing(VERSION_DIR):
    print("\n  타이밍 재조정 FAIL")
    sys.exit(1)

print("\n  [2/5] Whisper 타이밍 추출...")
if not run_whisper(VERSION_DIR):
    print("\n  Whisper FAIL")
    sys.exit(1)

print("\n  [3/5] HTML 빌드...")
if not run_build(VERSION_DIR):
    print("\n  BUILD FAIL")
    sys.exit(1)

print("\n  [4/5] 프리뷰 렌더 (FHD)...")
run_render(VERSION_DIR, preview=True)

print("\n  [5/5] 최종 렌더 (4K)...")
run_render(VERSION_DIR, preview=False)

print("\n  === 완료 ===")
