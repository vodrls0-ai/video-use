# 릴스 하네스 v2 — 듀얼 파이프라인

harness 위치: `video-use/harness/`
라우팅 규칙: `.claude/rules/10_render_path.md`

## 파이프라인 개요

| 파이프라인 | 입력 | 렌더 | 적합 |
|-----------|------|------|------|
| **A: CapCut/ff** | capcut_spec.json | `helpers/render.py` (ffmpeg) | 노셀코지형, 블루트 메타광고 |
| **B: HyperFrames** | script.json + config.json | `npx hyperframes render` | GSAP 자막+모션 릴스 |

### Pipeline A: CapCut/ff

```
reels_script.json (대본)
  → scene-director (capcut_spec.json 생성)
  → gen_qwen3_tts.py --style nocelcozy (TTS)
  → helpers/render.py (ffmpeg EDL 렌더)

자동화: python auto_reel.py full "상품명"
```

### Pipeline B: HyperFrames (아래 상세)

```
[새 상품] new_reel.py "상품명"
     │
     └──→ video/<상품명>/edit/v1/
              ├── config.json (스캐폴딩)
              └── script.json (스캐폴딩)

script.json (SSOT) + config.json
     │
     ├──→ [빌드] build_reel.py <version_dir>
     │         config.json + script.json + template.html → index.html
     │         정적 HTML (cuts + text + audio) + 인라인 JS (GSAP)
     │
     ├──→ [TTS 생성] ElevenLabs → tts_vN.mp3
     │         │
     │         └──→ [Whisper/Scribe] → tts_timing.json (워드타이밍)
     │
     ├──→ [자막 HTML 생성] generate_subtitles.py
     │         script.json + tts_timing.json → _generated/ 자막 블록
     │
     ├──→ [검증] sync_verify.py
     │         ├── 내부 일관성 (비트경계, appear_at, emphasis 존재)
     │         ├── script.json ↔ tts_timing.json (나레이션↔whisper 일치)
     │         ├── script.json ↔ config.json (text 필드 동기화)
     │         └── script.json ↔ index.html (자막 텍스트 일치)
     │
     └──→ [렌더] npx hyperframes render <version_dir> -f 30 --resolution portrait-4k
              index.html → renders/<name>.mp4
```

## 파일 역할

| 파일 | 역할 | 권한 |
|------|------|------|
| `script.json` | SSOT. 나레이션+자막 정의 | 작성자가 편집 |
| `config.json` | 비주얼 설정 (컷, 모션, 전환, 오디오) | 자동/수동 |
| `tts_timing.json` | whisper 워드타이밍 | 자동 생성 (수정 금지) |
| `template.html` | GSAP 타임라인 템플릿 (공유) | harness/ 에 단일 관리 |
| `index.html` | 렌더용 최종 HTML | build_reel.py가 생성 |

## script.json 구조

```json
{
  "meta": { "product", "version", "duration", "tts": { "file", "timing_file", "timing_stale" } },
  "beats": [
    {
      "id": "b1",
      "start": 0.00, "end": 1.47,
      "narration": "TTS가 말하는 전체 텍스트",
      "subtitle": [
        {
          "id": "b1-t",
          "text": "화면에 표시되는 텍스트",
          "words": ["단어", "배열"],
          "emphasis": ["강조단어"],
          "size": "lg|md|sm|xl|price",
          "animation": "spring-scale-in|mask-reveal-up|rise-words|...",
          "appear_at": 0.10
        }
      ]
    }
  ]
}
```

## 도구

### 스캐폴딩 (새 상품)
```bash
python video-use/harness/new_reel.py "상품명"
python video-use/harness/new_reel.py "상품명" --version v2      # 기존 상품 새 버전
python video-use/harness/new_reel.py "상품명" --beats 7          # 비트 수 (기본: 9)
python video-use/harness/new_reel.py "상품명" --duration 15      # 영상 길이 (기본: 20s)
```
생성: `video/<상품명>/edit/<version>/config.json` + `script.json` + 폴더 구조 (영상원본/, 보정/)

### 빌드 (config + script → index.html)
```bash
python video-use/harness/build_reel.py <version_dir>            # index.html 빌드
python video-use/harness/build_reel.py <version_dir> --verify   # 빌드 후 sync_verify 자동 실행
```
template.html의 GSAP 런타임 + config.json의 컷/전환 + script.json의 자막을 합쳐 정적 HTML로 출력.
빌드 시 GSAP의 동적 빌드 함수(buildCuts 등)는 strip되고 정적 HTML만 남음.

### 검증
```bash
python video-use/harness/sync_verify.py <version_dir>
```

### 자막 생성
```bash
python video-use/harness/generate_subtitles.py <version_dir>           # HTML+JS 출력
python video-use/harness/generate_subtitles.py <version_dir> --inject  # index.html에 직접 삽입
```
출력: `_generated/subtitles.html` (HTML 블록) + `_generated/animations.js` (GSAP 코드)
지원 애니메이션: spring-scale-in, rise-words, mask-reveal-up, stagger-from-center, per-word-crossfade, soft-blur-in, shared-axis-y, spring-scale-in+shimmer

### 워드타이밍 추출
```bash
python -c "from faster_whisper import WhisperModel; ..."  # tts_vN.mp3 → tts_vN_timing.json
```
faster-whisper large-v3 사용. 추출 후 script.json의 timing_file 경로와 timing_stale=false 갱신 필수.

### 렌더
```bash
npx hyperframes render <version_dir> -f 30 --resolution portrait-4k -q standard -o renders/<name>.mp4
```

## 새 상품 워크플로우

1. `new_reel.py "상품명"` - 스캐폴딩 생성
2. 영상원본/ 에 촬영 클립 또는 이미지 배치
3. config.json - sources 경로 채우기, cuts 타이밍/모션 편집
4. script.json - narration, subtitle 텍스트 작성
5. `build_reel.py <dir> --verify` - 빌드 + 검증
6. TTS 생성 (ElevenLabs) → tts_vN.mp3
7. 워드타이밍 추출 → tts_timing.json, timing_stale=false
8. `generate_subtitles.py <dir> --inject` - 자막 삽입
9. `build_reel.py <dir> --verify` - 최종 빌드
10. `npx hyperframes render <dir>` - 30fps 렌더

## 규칙

1. **narration = subtitle**: 나레이션과 자막은 같은 텍스트 (릴스 특성상 동일)
2. **timing_stale 플래그**: tts_timing.json이 현재 TTS와 불일치하면 true. 재추출 후 false로 변경
3. **config.json text는 script.json에서 파생**: script.json 수정 → config.json 동기화 → HTML 반영
4. **FAIL = 배포 금지**: sync_verify FAIL이 0이어야 렌더 가능
5. **컷 겹침 금지**: 같은 비트 내 cuts는 start+dur이 다음 cut의 start를 넘지 않아야 함
