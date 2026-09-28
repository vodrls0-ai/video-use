"""Qwen3-TTS voice clone — 5감정 비트매핑 체제 + speedup + SFX"""
import sys, json, subprocess, struct, math, time
from pathlib import Path


def _safe_replace(src: Path, dst: Path, retries: int = 30, delay: float = 1.0):
    """Path.replace가 NAS(UNC) 공유에서 간헐적 WinError5(액세스거부)로 실패하는 문제 대응
    (2026-08-21 nm1_체형 재생성 중 발견 — SMB 핸들이 잠깐 안 풀려서 생기는 것으로 보임,
    재시도하면 대부분 몇백ms 내로 풀림). 그래도 안 풀리면 최종 예외를 그대로 던진다."""
    last_err = None
    for i in range(retries):
        try:
            src.replace(dst)
            return
        except PermissionError as e:
            last_err = e
            time.sleep(delay)
    raise last_err

# ── Paths ──
HARNESS = Path(__file__).parent
MODEL_PATH = r"C:\Users\user\models\qwen3-tts\1.7B-Base"

# 프로젝트 루트 = 이 파일 위치 기준(video-use/harness → 비디오). UNC(\\192.168.0.21)는 폴백.
# 2026-08-19: 세션에 따라 Z:가 RaiDrive-Synology로 매핑되어 UNC가 안 잡히는 경우가 있어
# 하드코딩 UNC → 자기 위치 기준 해석 + UNC 폴백으로 교체 (제이엠엘 특옆절개와이드001 TTS에서 발견)
_PROJ_LOCAL = HARNESS.parent.parent          # ...\비디오
_PROJ_UNC = Path(r"\\192.168.0.21\NOMAL\자동화\비디오")
PROJ_ROOT = _PROJ_LOCAL if (_PROJ_LOCAL / "voice_clone").exists() else _PROJ_UNC

VOICE_CLONE = PROJ_ROOT / "voice_clone"

# 5감정 레퍼런스 매핑 (보정본 사용)
# ref_text = Whisper 전사 결과 그대로 (실제 발화와 일치해야 ICL 정상 작동)
VOICE_PROFILES = {
    "owner": {
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
    },
    "sseum": {
        "hook": {
            "ref": str(VOICE_CLONE / "sseum_ref_hook_processed.wav"),
            "text": "왜 월베당이 이선을 넘기 쉬운지 배당은 그대로 받는 방법까지 딱 세 가지로 지포드립니다 자 그럼 첫번째부터 차근차근 지포보겠습니다 요즘 은퇴하신 분들 아니면 은퇴를 앞두신 분들 투자 모아",
        },
        "pain": {
            "ref": str(VOICE_CLONE / "sseum_ref_pain_processed.wav"),
            "text": "자정되기 1분 전에 타면 기본 요금이에요. 그런데 자정을 딱 1분 넘겨 타면요. 할증이 붙습니다. 그것도 처음 요금부터 통체로 올라가요. 건보료도 똑같습니다. 1천만 원까지는 기본 요금.",
        },
        "confident": {
            "ref": str(VOICE_CLONE / "sseum_ref_confident_processed.wav"),
            "text": "저런 돈이 들어온다. 이 한마디 때문이에요. 생각해 보세요. 직장 그만 두면 매달들어오던 월급이 뚜껑킵니다. 그 허전함 겪어보신 분은 아실 거예요. 그런데 이 월 배당이 그 자리를 맥꽃 주는 거죠.",
        },
        "price": {
            "ref": str(VOICE_CLONE / "sseum_ref_price_processed.wav"),
            "text": "나중에 요양원이나 간병에 쓰는 돈을 미리 걷는 거예요 이걸 다 합치면 실제 체감은 약 8.13%가 됩니다 이 8.13%라는 숫자 장관 기억해 주세요 이 숫자로 계산",
        },
        "cta": {
            "ref": str(VOICE_CLONE / "sseum_ref_cta_processed.wav"),
            "text": "한 만 혜택을 봅니다. 가만히 있으면 아무도 안 깎아줘요. 그리고 막회직하셨다면 이미 계속 가입이라는 게 있습니다. 최대 36개월 직장 단일 때 수준으로 낼 수 있어요.",
        },
    },
    "female": {
        "hook": {
            "ref": str(VOICE_CLONE / "ref_female_hook_processed.wav"),
            "text": "비율 똥망이고 싶은 사람들은 이 영상 보지 마세요",
        },
        "pain": {
            "ref": str(VOICE_CLONE / "ref_female_confident_processed.wav"),
            "text": "근데 이건 드랍숄더로 어깨 넓어 보이고 크롭 기장이라 다리까지 길어 보여서 카페 갈 때 여행 갈 때 데이트 갈 때도 계속 손이 가는",
        },
        "confident": {
            "ref": str(VOICE_CLONE / "ref_female_confident_processed.wav"),
            "text": "근데 이건 드랍숄더로 어깨 넓어 보이고 크롭 기장이라 다리까지 길어 보여서 카페 갈 때 여행 갈 때 데이트 갈 때도 계속 손이 가는",
        },
        "price": {
            "ref": str(VOICE_CLONE / "ref_female_hook_processed.wav"),
            "text": "비율 똥망이고 싶은 사람들은 이 영상 보지 마세요",
        },
        "cta": {
            "ref": str(VOICE_CLONE / "ref_female_confident_processed.wav"),
            "text": "근데 이건 드랍숄더로 어깨 넓어 보이고 크롭 기장이라 다리까지 길어 보여서 카페 갈 때 여행 갈 때 데이트 갈 때도 계속 손이 가는",
        },
    },
    # 2026-08-20 벤치마크/목소리분석 3클립에서 클론 (htdemucs 보컬분리→절단→loudnorm).
    # 고속 남성 정보전달형 내레이터 (Praat 재검증: F0 137~194Hz 남성대역, 최초 pyin 분석은
    # 옥타브 오배로 233~310Hz 여성대로 오판했었음 — 2026-08-20 사용자 지적으로 정정).
    # owner 목소리 대비 전달력(Whisper avg_logprob) 우위 확인 — owner 나레이션 대체 후보.
    # 원속도 이미 7.4음절/초라 SPEED/PITCH 오버라이드 1.0 필수 (하단 참조).
    # pain 비트는 원본에 없어 hook 재사용.
    "male_fast": {
        "hook": {
            "ref": str(VOICE_CLONE / "ref_ffast_hook_processed.wav"),
            "text": "학교 다닐 때 뭐 입을지 고민되면 이거 하나면 됩니다 무료 배송에 22,900원인데 솔직히 가격보고 한 번 놀라고 퀄리티 보고 또 놀랐어요",
        },
        "pain": {
            "ref": str(VOICE_CLONE / "ref_ffast_hook_processed.wav"),
            "text": "학교 다닐 때 뭐 입을지 고민되면 이거 하나면 됩니다 무료 배송에 22,900원인데 솔직히 가격보고 한 번 놀라고 퀄리티 보고 또 놀랐어요",
        },
        "confident": {
            "ref": str(VOICE_CLONE / "ref_ffast_confident_processed.wav"),
            "text": "일반 티셔츠보다 깔끔한 반지법 디자인에 카라 디테일까지 더해져 단정하게 입이 좋습니다. 신축성 좋은 탄탄한 원단이라 몸에 비침 걱정 없고 하루종일 편하게 입을 수 있어요. 니단은 시보리로 마감해서 대충 입어도 핏이 자연스럽게 잡힙니다.",
        },
        "price": {
            "ref": str(VOICE_CLONE / "ref_ffast_price_processed.wav"),
            "text": "무료배송 23,800원 지금 가장 가성비 좋은 버뮤다 잘 팔리던 버뮤다 이번엔 포켓 버전으로 나왔습니다",
        },
        "cta": {
            "ref": str(VOICE_CLONE / "ref_ffast_cta_processed.wav"),
            "text": "반바지와 세트로도 구매 가능하고 추가 구매 할인까지 적용됩니다. 학생룩 캠퍼스룩으로 정말 추천드려요.",
        },
    },
}

EMOTION_REFS = VOICE_PROFILES["owner"]  # 기본값 = owner (2026-08-21: male_fast 풀버전 청취 후 반려, owner 복귀 — 사용자 확정)

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
    "usp6": "confident",  # price 레퍼런스는 녹음 문장("이 퀄리티의 이 가격…")이 출력에 새어 나온다(2026-09-27 인디오)
    "show": "confident",
    "urgency": "confident",
    "price": "confident",
    "price_shock": "confident",
    "price_teaser": "confident",
    "price_punch": "confident",
    "cta": "cta",
    "kick": "confident",
    "detail": "confident",
    "hook_price": "hook",
    "usp_jacket": "confident",
    "usp_pants": "confident",
    "styling_close": "confident",
    "show": "confident",
    "urgency": "confident",
}

# --style (단일감정 강제) + --voice (보이스 프로필 선택) + --product/--variant (파이프라인 자동화용)
import argparse as _ap
_p = _ap.ArgumentParser(add_help=False)
_p.add_argument("--style", default=None, choices=["hook", "pain", "confident", "price", "cta"])
# 2026-08-21: 기본 남성 보이스 owner(사용자 본인 목소리), 여성 보이스 female — 표준 체제로 복귀.
# male_fast는 2026-08-20 하루 시도됐으나 풀버전 청취 후 반려됨(짧은 테스트 클립은 괜찮았으나
# 풀버전에서 품질 미흡 판정, pain 비트 hook재사용 어색함도 원인). sseum과 함께 legacy로 보존,
# --voice로 명시 호출 시에만 사용.
_p.add_argument("--voice", default="owner", choices=list(VOICE_PROFILES.keys()))
_p.add_argument("--product", default=None, help="상품 폴더명 — 지정 시 아래 PRODUCT 상수 대신 사용 (대시보드 파이프라인 발주용)")
_p.add_argument("--variant", default=None, help="reels 하위 변형 폴더명 — 지정 시 VARIANT 상수 대신 사용")
_a, _ = _p.parse_known_args()
FORCE_STYLE = _a.style
EMOTION_REFS = VOICE_PROFILES[_a.voice]

# ⚠️ 하드코딩 함정 (feedback_gen_qwen3_tts_hardcoded_product): 수동 실행 시 PRODUCT 상수 확인 필수.
# 자동화(workbench_pipeline.js)는 반드시 --product로 명시 호출한다 — 상수 오염/오재생성 방지.
PRODUCT = _a.product or "투데이션_772751702766_시스루체크셔츠_신규"
VARIANT = _a.variant or ""  # reels 하위 변형 폴더명. 없으면 "" 로 두면 reels 직속 사용
VIDEO_ROOT = PROJ_ROOT / "video"   # PROJ_ROOT = 자기 위치 기준 해석 + UNC 폴백 (상단 참조)
VERSION_DIR = (VIDEO_ROOT / PRODUCT / "reels" / VARIANT) if VARIANT else (VIDEO_ROOT / PRODUCT / "reels")
SCRIPT_PATH = VERSION_DIR / "script.json"
TTS_DIR = VERSION_DIR / "tts"

SPEED_FACTOR = 1.2  # 1.2x (사용자 요청: 1.3→1.2 감속)
PITCH_UP = 1.13    # rule37 확정값 (7/18 재하향 후 잠금)

# 여성 보이스: 피치업 비활성 (이미 ~235Hz, 남성 +13% 불필요)
# male_fast: 원본 F0 137~194Hz — owner(115~130Hz)보다 이미 높아 피치업 불필요
VOICE_PITCH_OVERRIDES = {"female": 1.0, "male_fast": 1.0}
if _a.voice in VOICE_PITCH_OVERRIDES:
    PITCH_UP = VOICE_PITCH_OVERRIDES[_a.voice]

# male_fast: 원본이 이미 7.4음절/초 고속 — 추가 배속 시 알아듣기 어려움 (2026-08-20 실측)
VOICE_SPEED_OVERRIDES = {"male_fast": 1.0}
if _a.voice in VOICE_SPEED_OVERRIDES:
    SPEED_FACTOR = VOICE_SPEED_OVERRIDES[_a.voice]


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
    """비트별 감정 자동 선택 + 프롬프트 캐싱 (같은 감정은 재사용)

    캐시 키에 id(EMOTION_REFS)를 포함한다 — 감정명만으로 키를 잡으면 한 프로세스 안에서
    EMOTION_REFS를 다른 보이스로 바꿔가며 generate_beat을 연달아 호출할 때(예: male_fast와
    female을 한 스크립트에서 비교 생성) 이전 보이스의 클론 프롬프트를 그대로 재사용해버리는
    사고가 난다(2026-08-20 male_fast→female 비교 생성 시 female 5개가 전부 male_fast
    목소리로 나온 사고로 발견). CLI 단일 보이스 실행(프로세스당 1회)에는 영향 없음.
    """
    import numpy as np, soundfile as sf
    text = text.replace("1+1", "원플러스원")  # "일플러스일" 오발음 방지 (사용자 반복 지적, 6/29~)
    emotion = resolve_emotion(beat_id)
    cache_key = (id(EMOTION_REFS), emotion)
    if cache_key not in _prompt_cache:
        print(f"  [ICL:{emotion}] {Path(EMOTION_REFS[emotion]['ref']).name}")
        _prompt_cache[cache_key] = create_clone_prompt(model, emotion)
    clone_prompt = _prompt_cache[cache_key]
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

    # 무음구간 제거: (1) 문장 시작 패딩 트림 + (2) 문장 중간(쉼표/물음표 등 구두점에서
    # TTS가 실제로 쉬는 구간, 보통 0.15~0.45s) 트림. rule30/02_tone "무음구간 절대금지" 위반
    # 실측 확인(7/25, AM960 V7 opening/cta에서 0.17~0.44s 구간 다수 검출) 후 stop_periods 추가.
    # 끝쪽(맨 마지막) 트림은 여전히 하지 않음 — 7/21 "끝음 씹힘" 반복사고 원인이었던 부분은
    # stop_periods=-1이 마지막 무음까지 반복 제거해버리는 것과는 다르게, stop_duration/threshold를
    # 보수적으로 잡아(0.15s, -40dB) 자연스러운 단어끝 여운(대개 <0.1s)은 남기고 실제 정지구간만 제거.
    pre_af = (
        f"asetrate={pitched_rate},aresample={sr},"
        f"atempo={factor},"
        f"silenceremove=start_periods=1:start_duration=0.01:start_threshold=-30dB:detection=peak:"
        f"stop_periods=-1:stop_duration=0.1:stop_threshold=-30dB"
    )
    intermediate = output_mp3.with_name(output_mp3.stem + "_pre.wav")
    cmd_pre = ["ffmpeg", "-y", "-i", str(input_wav), "-filter:a", pre_af, str(intermediate)]
    r_pre = subprocess.run(cmd_pre, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
    if r_pre.returncode != 0:
        print(f"  전처리 실패: {(r_pre.stderr or '')[-500:]}")
        return 0.0

    # 라우드니스 2-패스 정규화 — 짧은 클립(우리 TTS 대부분 1~3초)은 싱글패스 loudnorm이
    # 목표치를 못 맞추고 실측 -13~-15 LUFS로 나오는 문제 확인됨(7/21). 측정→적용 2단계로 정확히 맞춘다.
    target_i, target_lra, target_tp = -14, 11, -1
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
    # Whisper는 "예요"를 "에요", "고요"를 "구요"로 적는다 — 같은 발음이라 양쪽을 같은 표기로 맞춘다
    spell = lambda t: t.replace("예요", "에요").replace("구요", "고요")
    expected_text, transcript = spell(expected_text), spell(transcript)
    expected_clean = expected_text.replace(" ", "")
    clean = transcript.replace(" ", "")
    sim = difflib.SequenceMatcher(None, expected_clean, clean).ratio()
    # 문장부호를 떼지 않으면 "돼."처럼 짧은 끝어절은 core가 "돼." 그대로라 정확한 발음도 항상 FAIL.
    # 부호만 있는 토큰("좋아요 !"의 "!")은 건너뛰고 실제 글자가 있는 마지막 어절을 쓴다
    words = [w for w in (t.strip(".,!?~…\"'") for t in expected_text.split()) if w]
    last_word = words[-1] if words else ""
    last_word_clean = last_word
    core = last_word_clean[:max(2, len(last_word_clean) - 1)]
    last_ok = (core in clean) if core else True
    ok = sim >= sim_threshold and last_ok
    reason = "" if ok else ("유사도부족" if sim < sim_threshold else f"끝어절('{last_word}') 인식실패")
    return ok, sim, reason


def _find_internal_silence(mp3_path, noise_db=-25, min_dur=0.08, edge_margin=0.05):
    """rule46 고정계약 '무음 0초' 검증 — 발화 중간에 낀 무음 구간을 찾는다.
    (2026-08-21: Whisper 유사도만으론 못 잡음 — nm1_체형/nm1_상황_개강 owner보이스에서
    중간 무음이 낀 채로 유사도만 보고 통과시킨 사고 발견, 사용자 직접 지적으로 발견됨.
    시작/끝의 자연스러운 여백(edge_margin)은 제외하고 순수 내부 무음만 잡는다.)"""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3_path)],
        capture_output=True, encoding="utf-8", errors="replace")
    try:
        total = float(r.stdout.strip())
    except ValueError:
        return []
    r = subprocess.run(
        ["ffmpeg", "-i", str(mp3_path), "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}", "-f", "null", "-"],
        capture_output=True, encoding="utf-8", errors="replace")
    gaps = []
    start = None
    for line in (r.stderr or "").splitlines():
        if "silence_start:" in line:
            try:
                start = float(line.split("silence_start:")[1].strip())
            except ValueError:
                start = None
        elif "silence_end:" in line and start is not None:
            try:
                end = float(line.split("silence_end:")[1].split("|")[0].strip())
            except ValueError:
                start = None
                continue
            if start > edge_margin and end < total - edge_margin:
                gaps.append((round(start, 3), round(end, 3)))
            start = None
    return gaps


def _trim_internal_silence(mp3_path, gaps, out_path, pad=0.02):
    """감지된 내부 무음 구간을 잘라내고 이어붙인다.

    (2026-08-21: owner보이스가 무음구간을 자주 만들어내서 재시도 5회로도 못 피하는 경우가
    많았다 — 재생성 로또 대신, 검출된 정확한 구간만 잘라내는 편집으로 rule46 '무음0초'를
    확정적으로 보장한다. 발화 내용 자체는 이미 Whisper로 맞다고 확인된 테이크에만 적용.)
    pad는 절단 경계가 음소 경계와 너무 딱 붙어 끊어지는 소리(클릭음)가 나는 걸 막기 위한 여유.
    """
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(mp3_path)],
        capture_output=True, encoding="utf-8", errors="replace")
    total = float(r.stdout.strip())
    keep = []
    cursor = 0.0
    for s, e in sorted(gaps):
        seg_end = max(cursor, s + pad)
        if seg_end > cursor:
            keep.append((cursor, seg_end))
        cursor = max(cursor, e - pad)
    if cursor < total:
        keep.append((cursor, total))
    if not keep:
        return False
    filters, labels = [], []
    for i, (s, e) in enumerate(keep):
        filters.append(f"[0:a]atrim=start={s:.3f}:end={e:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[a{i}]")
    filters.append(f"{''.join(labels)}concat=n={len(keep)}:v=0:a=1[out]")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp3_path), "-filter_complex", ";".join(filters),
         "-map", "[out]", str(out_path)],
        capture_output=True, encoding="utf-8", errors="replace")
    return out_path.exists() and out_path.stat().st_size > 0


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
        # word_timestamps=True — 자막을 실제 발화 시점에 붙이기 위한 단어 타임코드.
        # 검증 전사를 어차피 돌리므로 추가 비용이 거의 없다. 산출물은 tts/word_timings.json이며
        # generate_capcut.py가 이걸 읽어 자막을 정렬한다(없으면 균등분할로 폴백).
        result = whisper_model.transcribe(str(try_mp3), language="ko", word_timestamps=True)
        transcript = result["text"].strip()
        words = []
        for seg in result.get("segments", []):
            for wd in (seg.get("words") or []):
                token = str(wd.get("word", "")).strip()
                if not token:
                    continue
                words.append({"w": token, "s": round(float(wd["start"]), 3), "e": round(float(wd["end"]), 3)})
        ok, sim, reason = _verify_transcript(text, transcript, sim_threshold)
        gaps = _find_internal_silence(try_mp3)
        gap_note = f" | 무음{len(gaps)}건:{gaps}" if gaps else ""
        print(f"  [{beat_id}] 시도{attempt}: {dur:.3f}s | Whisper=\"{transcript}\" | 유사도={sim:.2f} | {'OK' if ok else 'FAIL:'+reason}{gap_note}")

        if gaps and ok:
            # 내용은 맞는데 무음만 낀 테이크 — 재시도 로또 대신 무음 구간만 잘라내고 재검증한다.
            trimmed = try_mp3.with_name(f"{try_mp3.stem}_trimmed.mp3")
            if _trim_internal_silence(try_mp3, gaps, trimmed):
                trimmed_gaps = _find_internal_silence(trimmed)
                if not trimmed_gaps:
                    result2 = whisper_model.transcribe(str(trimmed), language="ko", word_timestamps=True)
                    transcript2 = result2["text"].strip()
                    ok2, sim2, reason2 = _verify_transcript(text, transcript2, sim_threshold)
                    if ok2:
                        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                                             "-of", "csv=p=0", str(trimmed)],
                                            capture_output=True, encoding="utf-8", errors="replace")
                        try:
                            dur2 = float(r.stdout.strip())
                        except ValueError:
                            dur2 = dur
                        words2 = []
                        for seg in result2.get("segments", []):
                            for wd in (seg.get("words") or []):
                                token = str(wd.get("word", "")).strip()
                                if not token:
                                    continue
                                words2.append({"w": token, "s": round(float(wd["start"]), 3),
                                                "e": round(float(wd["end"]), 3)})
                        print(f"  [{beat_id}] 무음 {len(gaps)}건 트림 → {dur2:.3f}s, 재검증 유사도={sim2:.2f} OK")
                        _safe_replace(trimmed, try_mp3)
                        dur, sim, transcript, words = dur2, sim2, transcript2, words2
                        ok = True
                    else:
                        print(f"  [{beat_id}] 무음 트림 후 재검증 실패: {reason2}")
                        trimmed.unlink(missing_ok=True)
                        ok = False
                        reason = f"무음트림후재검증실패:{reason2}"
                else:
                    print(f"  [{beat_id}] 무음 트림 후에도 잔여 무음 {len(trimmed_gaps)}건 - 트림본 폐기, 재시도")
                    trimmed.unlink(missing_ok=True)
                    ok = False
                    reason = f"무음트림후잔여무음{len(trimmed_gaps)}건"
            else:
                ok = False
                reason = f"무음구간 {len(gaps)}개({gaps[0][0]}s~{gaps[0][1]}s 등) - 트림 실패"

        if ok:
            _safe_replace(try_mp3, output_mp3)
            for a in range(1, max_tries + 1):
                leftover = output_mp3.with_name(f"{output_mp3.stem}_try{a}.mp3")
                if leftover.exists():
                    leftover.unlink()
            return {"id": beat_id, "duration": round(dur, 3), "attempts": attempt, "sim": round(sim, 2),
                    "ok": True, "words": words}
        last_sim, last_reason, last_dur, last_words = sim, reason, dur, words
        if attempt < max_tries:
            try_mp3.unlink(missing_ok=True)
    try_mp3 = output_mp3.with_name(f"{output_mp3.stem}_try{max_tries}.mp3")
    if try_mp3.exists():
        _safe_replace(try_mp3, output_mp3)
    print(f"  [{beat_id}] {max_tries}회 모두 실패 ({last_reason}) - 마지막 시도 보존, 수동 확인 필요")
    # 검증 실패해도 보존된 mp3의 단어 타임코드는 그대로 유효하다(자막 싱크에 필요).
    return {"id": beat_id, "duration": round(last_dur, 3), "attempts": max_tries, "sim": round(last_sim, 2),
            "ok": False, "words": last_words}


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
    word_timings = {}   # beat_id -> [{w,s,e}] — 자막 자동 싱크용 (generate_capcut.py가 읽는다)
    total_chars = 0

    # 비트 간 무음 갭 = 0 (하드코딩, 무음구간 절대 금지)
    GAP = 0.0

    for beat in beats:
        narration = beat.get("narration", "").strip()
        if not narration:
            continue
        bid = beat["id"]
        total_chars += len(narration)

        mp3_path = TTS_DIR / f"{bid}.mp3"

        result = generate_beat_verified(model, bid, narration, mp3_path)
        if not result["ok"]:
            print(f"  [!] {bid} Whisper 검증 실패 - 수동 확인 필요")
        dur = result["duration"] or 0.0

        gap = GAP

        beat_files.append(mp3_path)
        word_timings[bid] = result.get("words", [])
        beat_durations.append({
            "id": bid, "duration": round(dur, 3), "gap_after": gap,
            "ok": result["ok"], "sim": result.get("sim", 0.0), "attempts": result.get("attempts", 0),
        })

    if beat_durations:
        beat_durations[-1]["gap_after"] = 0.0

    # 단어 타임코드 저장 — 자막을 실제 발화 시점에 붙이기 위한 정본.
    # generate_capcut.py가 이 파일을 읽어 자막을 정렬한다(없으면 균등분할 폴백).
    with open(TTS_DIR / "word_timings.json", "w", encoding="utf-8") as f:
        json.dump(word_timings, f, ensure_ascii=False, indent=1)
    _wt_beats = sum(1 for v in word_timings.values() if v)
    print(f"  word_timings.json 저장: {_wt_beats}/{len(word_timings)} 비트 단어 타임코드 확보")

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

    failed_beats = [bd for bd in beat_durations if not bd.get("ok", True)]
    tts_report = {
        "total_beats": len(beat_durations),
        "failed_beats": len(failed_beats),
        "failed_ids": [bd["id"] for bd in failed_beats],
        "beat_results": beat_durations,
    }
    report_path = TTS_DIR / "tts_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(tts_report, f, ensure_ascii=False, indent=2)
    print(f"  tts_report.json 저장: {report_path.name}")

    if failed_beats:
        print(f"\n  [FAIL] Whisper 검증 실패 {len(failed_beats)}건: {[bd['id'] for bd in failed_beats]}")
        print(f"  mp3는 보존됨(수동 확인 가능). 파이프라인은 여기서 중단.")
        print(f"  수정 후 재실행하거나, mp3를 수동 교체 후 tts_report.json의 ok를 true로 바꾸세요.")
        # GPU 정리 후 exit
        import torch
        del model
        torch.cuda.empty_cache()
        sys.exit(1)

    print(f"  TTS 완료: {merged.name} ({len(beat_files)}비트, {total_chars}자)\n")

    # 대본 브라우저 프리뷰
    try:
        from preview_script import generate as _preview
        _preview(str(SCRIPT_PATH))
    except Exception:
        pass

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
