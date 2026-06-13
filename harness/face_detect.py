"""OpenCV YuNet 얼굴 자동 감지 → config.json framing 자동 계산.

이미지/영상에서 얼굴 위치를 감지하고, 상의/하의 상품 유형에 맞는
scale, originX, originY 값을 자동 추천한다.

Usage:
    python face_detect.py <media_path>           # 단일 파일 분석
    python face_detect.py config <config.json>    # config 자동 framing (dry-run)
    python face_detect.py apply <config.json>     # config 자동 framing (적용)

    from face_detect import analyze_media, suggest_framing
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi", ".mkv"}
SKIP_SOURCE_KEYWORDS = {"디테일", "확대", "클로즈", "제품컷", "누끼", "플랫", "사이즈", "비교", "logo", "nms_"}

YUNET_MODEL = os.path.expanduser("~/.opencv_models/yunet_2023mar.onnx")
YUNET_CONF = 0.7
YUNET_NMS = 0.3

_detector = None


def _get_detector(w: int, h: int):
    global _detector
    if _detector is None:
        if not os.path.exists(YUNET_MODEL):
            raise FileNotFoundError(f"YuNet 모델 없음: {YUNET_MODEL}")
        _detector = cv2.FaceDetectorYN.create(YUNET_MODEL, "", (w, h), YUNET_CONF, YUNET_NMS, 5000)
    else:
        _detector.setInputSize((w, h))
    return _detector


def _imread_unicode(path: str | Path) -> np.ndarray | None:
    try:
        buf = np.fromfile(str(path), dtype=np.uint8)
        return cv2.imdecode(buf, cv2.IMREAD_COLOR)
    except Exception:
        return None


def detect_faces_in_frame(frame) -> list[dict]:
    """BGR 프레임에서 얼굴 감지. 0~100% 좌표로 반환."""
    h, w = frame.shape[:2]
    if h == 0 or w == 0:
        return []

    detector = _get_detector(w, h)
    _, raw_faces = detector.detect(frame)

    faces = []
    if raw_faces is None:
        return faces

    for f in raw_faces:
        x, y, fw, fh = float(f[0]), float(f[1]), float(f[2]), float(f[3])
        conf = float(f[-1])
        y_pct = (y + fh / 2) / h * 100
        h_pct = fh / h * 100
        x_pct = (x + fw / 2) / w * 100

        # 패션영상 필터: y>65% = 거의 확실히 오탐, h<2% = 너무 작음
        if y_pct > 65 or h_pct < 2.0 or x_pct < 10 or x_pct > 90:
            continue

        faces.append({
            "x_center": round(x_pct, 1),
            "y_center": round(y_pct, 1),
            "width": round(fw / w * 100, 1),
            "height": round(h_pct, 1),
            "confidence": round(conf, 3),
        })
    return faces


def analyze_image(path: str | Path) -> dict:
    frame = _imread_unicode(path)
    if frame is None:
        return {"faces": [], "error": f"이미지 로드 실패: {path}"}
    h, w = frame.shape[:2]
    faces = detect_faces_in_frame(frame)
    return {"faces": faces, "frame_size": [w, h]}


def analyze_video(path: str | Path, sample_times: list[float] | None = None) -> dict:
    str_path = str(path)
    cap = cv2.VideoCapture(str_path)

    if not cap.isOpened():
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            ctypes.windll.kernel32.GetShortPathNameW(str_path, buf, 260)
            if buf.value:
                cap = cv2.VideoCapture(buf.value)
        except Exception:
            pass

    if not cap.isOpened():
        return {"faces_by_time": {}, "primary_face": None, "error": f"영상 열기 실패: {path}"}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps if fps > 0 else 0
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    if sample_times is None:
        # 더 촘촘한 샘플링 — 1초 간격
        sample_times = []
        t = 0.5
        while t < duration - 0.1:
            sample_times.append(round(t, 2))
            t += 1.0
        if not sample_times:
            sample_times = [0.5]

    faces_by_time = {}
    for t in sample_times:
        t = min(t, max(0, duration - 0.1))
        frame_no = int(t * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_no)
        ret, frame = cap.read()
        if ret:
            faces = detect_faces_in_frame(frame)
            faces_by_time[round(t, 2)] = faces

    cap.release()

    all_faces = [f for flist in faces_by_time.values() for f in flist]
    primary = _pick_primary_face(all_faces) if all_faces else None

    return {
        "faces_by_time": faces_by_time,
        "primary_face": primary,
        "duration": round(duration, 2),
        "frame_size": [w, h],
    }


def analyze_video_at(path: str | Path, media_start: float, cut_dur: float) -> dict:
    times = [
        media_start + 0.1,
        media_start + cut_dur / 2,
        media_start + max(0.1, cut_dur - 0.1),
    ]
    return analyze_video(path, sample_times=times)


def _pick_primary_face(faces: list[dict]) -> dict | None:
    if not faces:
        return None
    return max(faces, key=lambda f: f["confidence"])


def suggest_framing(face_info: dict, product_type: str = "upper") -> dict:
    """얼굴 위치 기반 config.json framing 추천."""
    faces = face_info.get("faces", [])
    primary = face_info.get("primary_face")
    if not primary and faces:
        primary = _pick_primary_face(faces)

    if not primary:
        return {
            "scale": 1.2,
            "originX": 50,
            "originY": 40,
            "face_detected": False,
            "reason": "얼굴 미감지 — 제품/디테일컷 추정",
        }

    y_center = primary["y_center"]
    face_height = primary["height"]
    x_center = primary["x_center"]

    if product_type == "upper":
        if y_center < 15:
            # 얼굴이 화면 최상단 — 카메라가 몸통을 보고 있음
            scale = 1.6
            origin_y = 60
        elif y_center < 25:
            # 전신/반신 표준
            scale = 1.8
            origin_y = 62
        elif y_center < 40:
            # 얼굴이 중간위
            scale = 1.8
            origin_y = 62
        else:
            # 얼굴이 아래쪽 — 워킹샷
            scale = 1.5
            origin_y = 58

        if face_height > 12:
            scale = min(scale + 0.2, 2.0)
            origin_y = min(origin_y + 3, 65)

    elif product_type == "lower":
        scale = 1.3
        origin_y = 70
        if y_center < 25:
            origin_y = 75

    else:
        scale = 1.2
        origin_y = 40

    origin_x = 50
    if abs(x_center - 50) > 25:
        origin_x = int(round(50 + (x_center - 50) * 0.5))

    return {
        "scale": round(scale, 1),
        "originX": origin_x,
        "originY": origin_y,
        "face_detected": True,
        "face_y_center": round(y_center, 1),
        "face_height_pct": round(face_height, 1),
        "reason": f"얼굴 y={y_center:.0f}% h={face_height:.0f}% → scale={scale} originY={origin_y}",
    }


def analyze_media(path: str | Path) -> dict:
    p = Path(path)
    ext = p.suffix.lower()
    if ext in IMAGE_EXTS:
        return analyze_image(p)
    elif ext in VIDEO_EXTS:
        return analyze_video(p)
    else:
        return {"faces": [], "error": f"지원하지 않는 형식: {ext}"}


def auto_frame_config(config_path: str | Path, product_type: str = "upper", dry_run: bool = False) -> dict:
    """config.json의 각 컷을 분석해서 framing 값을 자동 업데이트."""
    config_path = Path(config_path)
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    v_dir = config_path.parent
    sources = config.get("sources", {})

    source_face_cache: dict[str, dict] = {}
    sources_with_person: set[str] = set()

    def _resolve_path(rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        return (v_dir / rel).resolve()

    for media_type in ["video", "image"]:
        pool = sources.get(media_type, {})
        for source_id, entry in pool.items():
            src_path = entry.get("path", entry) if isinstance(entry, dict) else entry
            abs_path = _resolve_path(src_path)
            if not abs_path.exists():
                source_face_cache[source_id] = {"faces": [], "error": "파일 없음"}
                continue
            result = analyze_media(abs_path)
            source_face_cache[source_id] = result
            has_face = bool(result.get("primary_face") or result.get("faces"))
            if has_face:
                sources_with_person.add(source_id)

    updated = 0
    skipped = 0
    details = []

    for beat in config.get("beats", []):
        for cut in beat.get("cuts", []):
            source_id = cut.get("source", "")
            cut_id = cut.get("id", "?")

            if any(kw in source_id for kw in SKIP_SOURCE_KEYWORDS):
                skipped += 1
                details.append({"cut": cut_id, "action": "skip", "reason": f"소스명 스킵: {source_id}"})
                continue

            has_manual = "originY" in cut and "scale" in cut
            if has_manual and not dry_run:
                skipped += 1
                details.append({"cut": cut_id, "action": "skip", "reason": "수동값 존재"})
                continue

            source_level = source_face_cache.get(source_id, {})
            face_data = source_level

            if cut.get("type") == "video" and "mediaStart" in cut:
                src_entry = sources.get("video", {}).get(source_id, {})
                src_path = src_entry.get("path", src_entry) if isinstance(src_entry, dict) else src_entry
                abs_path = _resolve_path(src_path)
                if abs_path.exists():
                    cut_level = analyze_video_at(
                        abs_path, cut["mediaStart"], cut.get("dur", 1.0)
                    )
                    if cut_level.get("primary_face"):
                        face_data = cut_level

            framing = suggest_framing(face_data, product_type)

            if not framing["face_detected"] and source_id in sources_with_person:
                if product_type == "upper":
                    framing = {
                        "scale": 1.5, "originX": 50, "originY": 58,
                        "face_detected": False,
                        "reason": "같은 소스에서 사람 감지 → 기본 상의 프레이밍",
                    }
                elif product_type == "lower":
                    framing = {
                        "scale": 1.3, "originX": 50, "originY": 70,
                        "face_detected": False,
                        "reason": "같은 소스에서 사람 감지 → 기본 하의 프레이밍",
                    }

            if dry_run:
                details.append({
                    "cut": cut_id,
                    "source": source_id,
                    "current": {k: cut.get(k) for k in ["scale", "originX", "originY", "face_hide"]},
                    "suggested": framing,
                })
            else:
                if "face_hide" in cut and product_type == "upper":
                    del cut["face_hide"]

                cut["scale"] = framing["scale"]
                cut["originX"] = framing["originX"]
                cut["originY"] = framing["originY"]
                updated += 1
                details.append({
                    "cut": cut_id,
                    "action": "updated",
                    "framing": framing,
                })

    if not dry_run:
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)

    return {"updated": updated, "skipped": skipped, "details": details}


def enrich_manifest(manifest: dict) -> dict:
    """media_manifest.json에 face_info 추가."""
    for item in manifest.get("media", []):
        path = item.get("path", "")
        if not path or not Path(path).exists():
            continue
        cat = item.get("category", "")
        if cat in ("nukki", "detail", "flatlay", "size_chart", "comparison"):
            item["face_info"] = {"face_detected": False, "skip_reason": f"카테고리={cat}"}
            continue
        try:
            result = analyze_media(path)
            faces = result.get("faces", [])
            primary = result.get("primary_face") or (_pick_primary_face(faces) if faces else None)
            item["face_info"] = {
                "face_detected": len(faces) > 0,
                "face_count": len(faces),
                "primary_y": round(primary["y_center"], 1) if primary else None,
                "primary_height": round(primary["height"], 1) if primary else None,
            }
        except Exception as e:
            item["face_info"] = {"face_detected": False, "error": str(e)}
    return manifest


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python face_detect.py <media_path>           # 단일 파일 분석")
        print("  python face_detect.py config <config.json>    # config 자동 framing (dry-run)")
        print("  python face_detect.py apply <config.json>     # config 자동 framing (적용)")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "config" and len(sys.argv) >= 3:
        result = auto_frame_config(sys.argv[2], dry_run=True)
        print(json.dumps(result, ensure_ascii=False, indent=2))

    elif cmd == "apply" and len(sys.argv) >= 3:
        product_type = sys.argv[3] if len(sys.argv) >= 4 else "upper"
        result = auto_frame_config(sys.argv[2], product_type=product_type, dry_run=False)
        print(f"  업데이트: {result['updated']}컷, 스킵: {result['skipped']}컷")
        for d in result["details"]:
            print(f"    {d['cut']}: {d.get('action', '')} — {d.get('framing', {}).get('reason', d.get('reason', ''))}")

    else:
        result = analyze_media(cmd)
        if "faces_by_time" in result:
            primary = result.get("primary_face")
            print(f"  영상: {result['duration']}초, {result['frame_size']}")
            for t, faces in result["faces_by_time"].items():
                print(f"  {t}s: {len(faces)}명 감지")
                for f in faces:
                    print(f"    y={f['y_center']}% h={f['height']}% conf={f['confidence']}")
            if primary:
                framing = suggest_framing(result, "upper")
                print(f"\n  추천 (상의): {framing}")
        else:
            faces = result.get("faces", [])
            print(f"  감지: {len(faces)}명")
            for f in faces:
                print(f"    y={f['y_center']}% h={f['height']}% conf={f['confidence']}")
            if faces:
                framing = suggest_framing(result, "upper")
                print(f"\n  추천 (상의): {framing}")
