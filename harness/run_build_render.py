"""Build + render only (TTS + Whisper already done). No deliver until confirmed."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pathlib import Path
from auto_reel import run_render
import subprocess, sys
from pathlib import Path as _P

def run_build_no_caption(version_dir):
    """build_reel.py --verify --no-caption"""
    build_script = _P(__file__).parent / "build_reel.py"
    result = subprocess.run(
        [sys.executable, str(build_script), str(version_dir), "--verify", "--no-caption"],
        capture_output=True, text=True, encoding="utf-8", errors="replace"
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"  BUILD FAIL: {result.stderr[:300]}")
        return False
    return True

VERSION_DIR = Path(r"Z:\NOMAL\자동화\비디오\video\오션_입체포켓카라니트\edit\v1")
SKIP_DELIVER = True

print("\n  === Build + Render (deliver=OFF) ===\n")

print("  [1/3] HTML 빌드...")
if not run_build_no_caption(VERSION_DIR):
    print("\n  BUILD FAIL")
    sys.exit(1)

print("\n  [2/3] 프리뷰 렌더 (FHD)...")
run_render(VERSION_DIR, preview=True)

print("\n  [3/3] 최종 렌더 (4K)...")
run_render(VERSION_DIR, preview=False)

if SKIP_DELIVER:
    print("\n  [SKIP] 텔레그램/마이박스 전달 — 확정 후 수동 실행")

print("\n  === 완료 ===")
