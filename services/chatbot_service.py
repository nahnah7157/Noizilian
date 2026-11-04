"""검색·답변 생성·이미지 선택을 연결해 API 응답을 조립합니다.

이 파일은 세 부분으로 되어 있습니다.
1. 학종이 신호 해석: 색·질감 → 감각 점수 (Lucassen, Gevers, Gijsenij 2011, Table III 색 질감 공식)
   브라우저의 public/assets/js/chatbot.js에 같은 공식이 있습니다. 한쪽을 고치면 다른 쪽도 함께 고치세요.
   서버는 브라우저가 보낸 점수를 믿지 않고 색·질감 값으로 다시 계산합니다.
2. 요리 단계 규칙: 외계인의 확신 갱신, 다음 단계 판정, 요리 성공 판정
   근거 번호(R1~R15)는 data/knowledge/paper_rules.md를 따릅니다.
   - [논문] 논문 표·본문의 값 / [앱 설정] 우리가 정한 값(config에서 조정) / [가정] 논문에 정확한 수치가 없어 단순화한 부분
   2-2. 요리 게임 규칙: 메뉴 결정, 단계 판정(success/under/over/unstable), 확신, 결과 확정 (config.game)
        외계인 추측 타일(alien.scores)은 2부 update_confidence로 계속 움직이고, 진행·판정은 2-2부가 정한다
3. ChatbotService: 검색 → 생성 → 이미지 선택 → 응답 조립
"""

import math
import random

from .generator import DemoGenerator
from .image_selector import DemoImageSelector, pick_line_images
from .retriever import DemoRetriever


# ═══════════════════════════════════════════════════════════════
# 1. 학종이 신호 해석 (색·질감 → 감각 점수)
# ═══════════════════════════════════════════════════════════════

AXES = ("wc", "mf", "hs", "hl")
AXIS_WORDS = {
    "wc": ("따뜻함", "차가움"),
    "mf": ("남성적", "여성적"),
    "hs": ("단단함", "부드러움"),
    "hl": ("무거움", "가벼움"),
}

# 사용자가 고를 수 있는 질감 범위 (논문 그림 2 기준값 주변, library.js의 TEXTURES와 같음)
TEXTURE_RANGE = {"oct": (1, 12), "freq": (0.4, 0.9), "pers": (0.4, 0.8), "lac": (1.8, 3.2)}


def _cosd(deg: float) -> float:
    return math.cos(math.radians(deg))


def raw_scores(color: dict, texture: dict) -> dict:
    """논문 공식 그대로의 점수 (대략 -4~+4, 음수 = 왼쪽 단어)."""
    L, C, h = color["L"], color["C"], color["h"]
    oct_, freq, pers, lac = texture["oct"], texture["freq"], texture["pers"], texture["lac"]
    return {
        "wc": -0.80 + 0.015 * L - 0.2 * C**0.65 * _cosd(h - 40) + 0.056 * oct_,
        "mf": 0.84 * L**0.25 + 0.022 * C - 0.017 * h + 0.00000014 * h**3 - 0.57 * oct_**0.5 - 0.70 * freq**0.5,
        # 단단함–부드러움: 색 변수가 없다. 질감만으로 결정된다.
        "hs": 586.33 - 178.78 * oct_**0.01 - 84.20 * freq**0.01 - 106.83 * pers**0.02 - 213.89 * lac**0.01,
        "hl": 0.33 * L**0.6 + 0.020 * C**0.8 - 2.57 * oct_**0.1 - 1.41 * freq**0.1 + 0.015 * lac**3,
    }


def _linear_rgb(L: float, C: float, h: float) -> tuple[float, float, float]:
    a, b = C * math.cos(math.radians(h)), C * math.sin(math.radians(h))
    fy = (L + 16) / 116
    fx, fz = fy + a / 500, fy - b / 200
    finv = lambda t: t**3 if t**3 > 0.008856 else (t - 16 / 116) / 7.787
    X, Y, Z = 0.95047 * finv(fx), finv(fy), 1.08883 * finv(fz)
    return (
        3.2406 * X - 1.5372 * Y - 0.4986 * Z,
        -0.9689 * X + 1.8758 * Y + 0.0415 * Z,
        0.0557 * X - 0.2040 * Y + 1.0570 * Z,
    )


def _in_gamut(L: float, C: float, h: float) -> bool:
    return all(-0.001 <= v <= 1.001 for v in _linear_rgb(L, C, h))


def _build_range() -> dict:
    """library.js와 같은 색 목록 × 질감 범위 양 끝 16개 조합으로 축별 최솟값·최댓값을 구한다."""
    colors = [
        {"L": L, "C": C, "h": h}
        for L in range(10, 95, 5)
        for h in range(0, 360, 10)
        for C in range(0, 115, 5)
        if not (C == 0 and h > 0) and _in_gamut(L, C, h)
    ]
    corners = [
        {"oct": o, "freq": f, "pers": p, "lac": l}
        for o in TEXTURE_RANGE["oct"]
        for f in TEXTURE_RANGE["freq"]
        for p in TEXTURE_RANGE["pers"]
        for l in TEXTURE_RANGE["lac"]
    ]
    lo = {a: math.inf for a in AXES}
    hi = {a: -math.inf for a in AXES}
    for c in colors:
        for t in corners:
            s = raw_scores(c, t)
            for a in AXES:
                lo[a], hi[a] = min(lo[a], s[a]), max(hi[a], s[a])
    return {a: (lo[a], hi[a]) for a in AXES}


RANGE = _build_range()


def scores_of(color: dict, texture: dict) -> dict:
    """-1(왼쪽 단어) ~ +1(오른쪽 단어)로 맞춘 점수."""
    raw = raw_scores(color, texture)
    out = {}
    for a in AXES:
        lo, hi = RANGE[a]
        out[a] = max(-1.0, min(1.0, (raw[a] - lo) / (hi - lo) * 2 - 1))
    return out


def describe(scores: dict) -> str:
    """'차갑고 단단한 신호'처럼 점수를 한국어로 (library.js의 describe와 같음)."""
    forms = {
        "wc": (("따뜻하고", "따뜻한"), ("차갑고", "차가운")),
        "hs": (("단단하고", "단단한"), ("부드럽고", "부드러운")),
        "hl": (("무겁고", "무거운"), ("가볍고", "가벼운")),
        "mf": (("남성적이고", "남성적인"), ("여성적이고", "여성적인")),
    }
    words = [forms[a][0 if scores[a] < 0 else 1] for a in ("wc", "hs", "hl", "mf") if abs(scores[a]) > 0.25]
    if not words:
        return "뚜렷한 쪽이 없는 중립 신호"
    return " ".join(w[1] if i == len(words) - 1 else w[0] for i, w in enumerate(words)) + " 신호"


def parse_signal(data) -> dict:
    """브라우저가 보낸 signal을 검증하고 서버에서 점수를 다시 계산한다. 형식이 틀리면 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("signal은 객체여야 합니다.")
    color, texture = data.get("color"), data.get("texture")
    if not isinstance(color, dict) or not isinstance(texture, dict):
        raise ValueError("signal에는 color와 texture가 필요합니다.")

    def number(source: dict, key: str, lo: float, hi: float) -> float:
        value = source.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError(f"{key} 값이 범위({lo}~{hi})를 벗어났습니다.")
        return float(value)

    clean_color = {"L": number(color, "L", 0, 100), "C": number(color, "C", 0, 150), "h": number(color, "h", 0, 360)}
    clean_texture = {k: number(texture, k, lo, hi) for k, (lo, hi) in TEXTURE_RANGE.items()}
    seed = data.get("seed", 0)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("seed는 정수여야 합니다.")

    scores = scores_of(clean_color, clean_texture)
    return {
        "color": clean_color,
        "texture": clean_texture,
        "seed": seed,
        "scores": scores,
        "description": describe(scores),
    }


# ═══════════════════════════════════════════════════════════════
# 2. 요리 단계 규칙 (확신 갱신 · 다음 단계 판정 · 요리 성공 판정)
#    모든 점수는 scores_of()가 만든 -1~+1 값 (음수 = 왼쪽 단어). LLM을 부르지 않는 순수 계산.
# ═══════════════════════════════════════════════════════════════

# [논문] R13: 색 질감(CT) 샘플을 1주 뒤 반복했을 때 같은 사람의 순위 상관 평균 (Table I).
# 일관되게 판단되는 축일수록 신호를 더 믿고 확신을 더 크게 올린다.
DEFAULT_RELIABILITY = {"wc": 0.74, "mf": 0.60, "hs": 0.64, "hl": 0.64}

# [논문] R12: 응답 표준편차는 L*+C* = 100에서 가장 작고, 그보다 낮거나 높으면 두 배 넘게 커진다.
# 따뜻함–차가움과 단단함–부드러움에서 나타났다. 우리 앱의 단단함–부드러움은 질감만으로 정해지므로(R3)
# 색의 불확실성은 따뜻함–차가움 축에만 적용한다.
CLEAR_COLOR_SUM = 100
UNCERTAIN_AXES = ("wc",)
# [가정] 논문은 "두 배 넘게"라고만 쓴다. 앱 색 범위의 양 끝(L*+C* ≈ 10 또는 190, 즉 100에서 90 떨어짐)에서
# 표준편차가 두 배가 되도록 직선으로 늘린다.
SPREAD_DOUBLES_AT = 90

# [앱 설정] 기본값. config의 exchange 값이 있으면 그것을 쓴다.
DEFAULT_LEARNING_RATE = 0.5
DEFAULT_MATCH_TOLERANCE = 0.6
DEFAULT_THRESHOLD = 0.8
DEFAULT_SUCCESS_DISTANCE = 0.5


def _axes_of(stage: dict) -> list[str]:
    axes = stage.get("axes") or []
    if not axes:
        raise ValueError(f"단계 {stage.get('id')}에 axes가 없습니다.")
    return list(axes)


def stage_distance(a: dict, b: dict, axes) -> float:
    """두 타일 점수의 차이를 지정한 축만으로 잰다 (축별 차이의 제곱평균제곱근, 0~2).

    단계마다 보는 축만 비교하므로, 손질 단계(단단함–부드러움)에서는 색이 달라도 거리가 변하지 않는다 (R3).
    """
    axes = list(axes)
    return math.sqrt(sum((a[x] - b[x]) ** 2 for x in axes) / len(axes))


def color_clarity(color: dict | None) -> float:
    """색이 얼마나 일관되게 읽히는지 (0~1, 1이 가장 명확). R12.

    표준편차가 r배 커지면 신호의 명확도를 1/r로 본다.
    """
    if not color:
        return 1.0
    spread = 1 + abs(color["L"] + color["C"] - CLEAR_COLOR_SUM) / SPREAD_DOUBLES_AT
    return 1 / spread


def axis_weights(axes, color: dict | None, exchange: dict | None = None) -> dict:
    """축별 신뢰 가중치 = 반복 일관성(R13) × 색의 명확도(R12, 따뜻함–차가움 축만)."""
    reliability = {**DEFAULT_RELIABILITY, **{
        k: v for k, v in ((exchange or {}).get("axis_reliability") or {}).items() if not k.startswith("_")
    }}
    clarity = color_clarity(color)
    return {x: reliability[x] * (clarity if x in UNCERTAIN_AXES else 1.0) for x in axes}


def update_confidence(
    confidence: float,
    user_scores: dict,
    alien_scores: dict,
    stage: dict,
    user_color: dict | None = None,
    exchange: dict | None = None,
) -> dict:
    """한 번 주고받은 뒤 외계인의 확신을 갱신한다.

    외계인이 추측 타일을 냈고 사용자가 타일로 답했을 때, 그 단계의 축에서
    - 두 타일이 가까우면 "맞다"는 뜻으로 읽어 확신이 오르고
    - 멀면 "아니다"로 읽어 확신이 내려간다.
    증거 크기는 축별 가중치(R13 × R12)로 조절한다. 반환값의 evidence는 개발 확인용이다.
    """
    exchange = exchange or {}
    axes = _axes_of(stage)
    rate = exchange.get("learning_rate", DEFAULT_LEARNING_RATE)
    tolerance = exchange.get("match_tolerance", DEFAULT_MATCH_TOLERANCE)
    weights = axis_weights(axes, user_color, exchange)

    evidence = {}
    for x in axes:
        diff = abs(user_scores[x] - alien_scores[x])
        # 차이 0 → +1(완전히 맞음), tolerance → 0(판단 보류), 2×tolerance 이상 → -1(아님)
        evidence[x] = max(-1.0, min(1.0, 1 - diff / tolerance))

    step = rate * sum(weights[x] * evidence[x] for x in axes) / len(axes)
    new_confidence = max(0.0, min(1.0, confidence + step))
    return {
        "confidence": round(new_confidence, 4),
        "step": round(step, 4),
        "evidence": {x: round(v, 3) for x, v in evidence.items()},
        "weights": {x: round(v, 3) for x, v in weights.items()},
        "distance": round(stage_distance(user_scores, alien_scores, axes), 4),
    }


def should_advance(confidence: float, exchange_count: int, exchange: dict | None = None) -> dict:
    """다음 단계로 넘어갈지 판정한다.

    확신이 기준 이상이면 "confident", 최대 횟수에 닿으면 확신이 낮아도 "max_reached"로 넘어간다.
    최대 횟수가 정해지지 않았으면(None) 확신이 찰 때까지 계속한다.
    """
    exchange = exchange or {}
    threshold = exchange.get("confidence_threshold", DEFAULT_THRESHOLD)
    max_exchanges = exchange.get("max_exchanges")
    if confidence >= threshold:
        return {"advance": True, "reason": "confident"}
    if max_exchanges is not None and exchange_count >= max_exchanges:
        return {"advance": True, "reason": "max_reached"}
    return {"advance": False, "reason": None}


def judge_dish(final_scores: dict, dish: dict, result: dict | None = None) -> dict:
    """네 단계에서 확정된 점수를 요리의 목표 점수와 비교해 성공/실패를 정한다.

    final_scores: {"ingredient": {...점수}, "prep": {...}, ...}. 단계마다 확정된 사용자 타일 점수.
    목표에 적힌 축만 비교하고, 단계별 거리의 평균이 success_distance 이하면 성공이다 [앱 설정].
    """
    from .image_selector import _url

    result = result or {}
    limit = result.get("success_distance", DEFAULT_SUCCESS_DISTANCE)
    per_stage = {}
    for stage_id, target in dish["targets"].items():
        if stage_id not in final_scores:
            raise ValueError(f"{stage_id} 단계의 확정 점수가 없습니다.")
        per_stage[stage_id] = round(stage_distance(final_scores[stage_id], target, target.keys()), 4)
    distance = sum(per_stage.values()) / len(per_stage)
    success = distance <= limit
    return {
        "success": success,
        "distance": round(distance, 4),
        "per_stage": per_stage,
        "image": _url(dish["images"]["success" if success else "fail"]),
    }


# ═══════════════════════════════════════════════════════════════
# 2-2. 요리 게임 규칙 (메뉴 결정 · 단계 판정 · 확신 · 결과 확정)
#    기준값은 전부 config.game [앱 설정]. 판정값은 0~100(Hue만 0~360°). LLM을 부르지 않는 순수 계산.
# ═══════════════════════════════════════════════════════════════

VERDICTS = ("success", "under", "over", "unstable")
GAME_METRICS = ("size", "roughness", "heat", "noise", "hue")
# /api/start·/api/chat 응답에 추가되는 필드 (기존 필드는 그대로)
GAME_RESPONSE_KEYS = ("menu", "menu_image", "stage_number", "stage_name", "verdict", "confidence", "retry",
                      "attempts_left", "alien_message", "plating", "metrics")


def _clamp100(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 2)


def hsv_hue(color: dict) -> float:
    """CIELAB L·C·h를 sRGB로 되돌려 화면 색 선택기와 같은 HSV 색상(0~360°)을 구한다. 회색이면 0."""
    import colorsys

    gamma = lambda v: 12.92 * v if v <= 0.0031308 else 1.055 * max(v, 0) ** (1 / 2.4) - 0.055
    rgb = [max(0.0, min(1.0, gamma(v))) for v in _linear_rgb(color["L"], color["C"], color["h"])]
    return round(colorsys.rgb_to_hsv(*rgb)[0] * 360 % 360, 2)


def game_metrics(signal: dict, game: dict) -> dict:
    """타일 한 장의 판정값. size = 손질 크기, roughness = 거침, heat = 조리 온도감, noise = 노이즈 불안정성, hue = 플레이팅 색.

    크기 막대는 freq, 밀도 막대는 oct·pers·lac을 함께 움직이므로 거침과 노이즈는 같은 밀도 값이다.
    둘은 다른 단계(손질 / 조리)에서 판정하므로 한 단계 안에서 겹치지 않는다.
    """
    m = game["metrics"]
    tex = signal["texture"]
    density = (tex["oct"] - m["oct_min"]) / (m["oct_max"] - m["oct_min"]) * 100
    return {
        "size": _clamp100((m["freq_small"] - tex["freq"]) / (m["freq_small"] - m["freq_large"]) * 100),
        "roughness": _clamp100(density),
        "heat": _clamp100((1 - signal["scores"]["wc"]) / 2 * 100),  # wc 음수 = 따뜻함 (R4)
        "noise": _clamp100(density),
        "hue": hsv_hue(signal["color"]),
    }


def decide_menu(metrics: dict, game: dict) -> str:
    """1단계 첫 타일: 색 온도(heat)와 노이즈로 메뉴를 정한다."""
    rule = game["menu"]
    warm = "warm" if metrics["heat"] >= rule["warm_min"] else "cool"
    noise = "high" if metrics["noise"] >= rule["noise_min"] else "low"
    return rule[f"{warm}_{noise}"]


def hue_in_range(hue: float, lo: float, hi: float) -> bool:
    """원형 범위. lo > hi면 0°를 넘어가는 범위(예: 345~45°)."""
    return (hue - lo) % 360 <= (hi - lo) % 360


def _hue_check(hue: float, lo: float, hi: float) -> tuple[str | None, float]:
    """(판정, 범위 밖 거리°). 범위 안이면 (None, 0). 밖이면 가까운 쪽 경계로 under(시작 전) / over(끝 뒤)."""
    if hue_in_range(hue, lo, hi):
        return None, 0.0
    before, after = (lo - hue) % 360, (hue - hi) % 360
    return ("under", before) if before < after else ("over", after)


def judge_stage(stage_id: str, metrics: dict, rules: dict, game: dict) -> dict:
    """한 단계 판정. rules = config.game.rules[메뉴][단계] 예: {"size": [30, 65], "max_roughness": 50}.

    우선순위: 거침·노이즈가 최대치를 넘으면 unstable → 범위보다 낮으면 under / 높으면 over → 아니면 success.
    closeness(0~1)는 성공 조건에 얼마나 가까운지. 플레이팅은 범위를 벗어나면 abnormal.
    """
    conf = game["confidence"]
    unstable, ranged, closeness = None, None, []
    for key, value in rules.items():
        if key.startswith("max_"):
            excess = metrics[key[4:]] - value
            closeness.append(1 - max(0.0, excess) / conf["falloff"])
            if excess > 0 and unstable is None:
                unstable = "unstable"
        elif key == "hue":
            verdict, gap = _hue_check(metrics["hue"], *value)
            closeness.append(1 - gap / conf["hue_falloff"])
            ranged = ranged or verdict
        else:
            lo, hi = value
            gap = lo - metrics[key] if metrics[key] < lo else metrics[key] - hi if metrics[key] > hi else 0.0
            closeness.append(1 - gap / conf["falloff"])
            ranged = ranged or ("under" if metrics[key] < lo else "over" if metrics[key] > hi else None)
    verdict = unstable or ranged or "success"
    out = {"verdict": verdict, "closeness": round(max(0.0, min(closeness or [1.0])), 4)}
    if stage_id == "plating":
        out["abnormal"] = verdict != "success"
    return out


def average_metrics(samples: list[dict]) -> dict:
    """여러 타일 판정값의 평균. Hue는 원형 평균."""
    avg = {k: round(sum(s[k] for s in samples) / len(samples), 2) for k in GAME_METRICS if k != "hue"}
    x = sum(math.cos(math.radians(s["hue"])) for s in samples)
    y = sum(math.sin(math.radians(s["hue"])) for s in samples)
    avg["hue"] = round(math.degrees(math.atan2(y, x)) % 360, 2)
    return avg


def alien_confidence(previous: float | None, closeness: float, game: dict, seed: int, salt: str) -> float:
    """외계인의 확신. 근접도를 따라가되 bluff만큼 근거 없이 흔들린다(틀린 조리에 자신만만할 수 있다).
    previous = 같은 단계의 직전 확신(첫 시도면 None → 이전 확신을 섞지 않는다)."""
    conf = game["confidence"]
    wobble = random.Random(f"{seed}:{salt}").random()  # 같은 타일·같은 시도면 같은 값 (재현 가능)
    target = (1 - conf["bluff"]) * closeness + conf["bluff"] * wobble
    value = target if previous is None else conf["memory"] * previous + (1 - conf["memory"]) * target
    return round(max(0.0, min(1.0, value)), 4)


def judge_menu_result(menu: str, verdicts: dict, game: dict, dishes: dict) -> dict:
    """세 판정 단계가 모두 success(플레이팅 정상)면 성공. 기존 result 필드(success, distance, per_stage, image)도 채운다."""
    from .image_selector import _url

    judged = {k: v for k, v in verdicts.items() if k != "ingredient"}
    failed = {k: 0.0 if v["verdict"] == "success" else 1.0 for k, v in judged.items()}
    success = bool(judged) and not any(failed.values())
    plating = verdicts.get("plating", {})
    return {
        "success": success,
        "distance": round(sum(failed.values()) / max(1, len(failed)), 4),  # 실패한 단계 비율 (기존 필드 유지)
        "per_stage": failed,
        "image": _url(dishes[menu]["images"]["success" if success else "fail"]),
        "menu": menu,
        "verdicts": {k: v["verdict"] for k, v in judged.items()},
        "plating": plating_view(menu, plating.get("metrics", {}).get("hue"), plating.get("verdict"), game),
    }


def plating_view(menu: str, hue: float | None, verdict: str | None, game: dict) -> dict | None:
    """화면용 플레이팅 색. hue_shift = 요리 그림 원래 색(base_hue)에서 돌릴 각도(-180~180)."""
    if hue is None:
        return None
    base = game["rules"][menu].get("base_hue", 0)
    return {"hue": hue, "abnormal": verdict != "success", "hue_shift": round((hue - base + 180) % 360 - 180, 2)}


# ═══════════════════════════════════════════════════════════════
# 3. 응답 조립
# ═══════════════════════════════════════════════════════════════

class ChatbotService:
    def __init__(self, retriever=None, generator=None, image_selector=None):
        self.retriever = retriever or DemoRetriever()
        self.generator = generator or DemoGenerator()
        self.image_selector = image_selector or DemoImageSelector()

    def generate_response(
        self,
        user_message: str,
        username: str = "사용자",
        character: dict | None = None,
        signal: dict | None = None,
    ) -> dict:
        """`reply`, `image`, `sources`로 이루어진 응답을 반환합니다.

        signal은 parse_signal()이 만든 학종이 신호(색·질감·감각 점수·설명)입니다.
        """
        knowledge = self.retriever.search(user_message)
        character = character or {}
        if signal is None:
            reply = self.generator.generate(user_message, username, character, knowledge)
        else:
            reply = self.generator.generate(user_message, username, character, knowledge, signal=signal)
        image = self.image_selector.select(reply, character)
        return {
            "reply": reply,
            "image": image,
            "sources": list(dict.fromkeys(hit.title for hit in knowledge)),
        }

    # ── 요리 단계 진행 ──────────────────────────────────────────
    # 상태(state)는 브라우저가 들고 다니고, 서버는 매번 받은 상태로 다음 상태를 계산해 돌려준다.
    #   dish          외계인이 만들려는 요리 id (config.dishes의 키)
    #   stage_index   지금 단계 (0 재료 준비 · 1 손질 · 2 조리 · 3 플레이팅)
    #   exchange_count 이 단계에서 주고받은 횟수
    #   confidence    외계인의 확신 (0~1)
    #   alien_scores  외계인의 현재 추측 타일 점수
    #   finals        단계별로 확정된 사용자 타일 점수
    #   done          요리가 끝났는지

    @staticmethod
    def dishes_of(character: dict) -> dict:
        return {k: v for k, v in (character.get("dishes") or {}).items() if not k.startswith("_")}

    @staticmethod
    def _stage_view(stage: dict, index: int, total: int, advanced: bool = False, reason: str | None = None) -> dict:
        return {"id": stage["id"], "name": stage["name"], "index": index, "total": total,
                "hint": stage.get("user_hint", ""), "advanced": advanced, "reason": reason}

    @staticmethod
    def _alien_view(alien: dict) -> dict:
        return {k: alien.get(k) for k in ("scores", "word", "expression", "reading")}

    @staticmethod
    def _max_attempts(game: dict, stage_id: str) -> int:
        """단계당 최대 시도 횟수 (config.game.max_attempts). 1단계(메뉴 선택)는 한 번."""
        return 1 if stage_id == "ingredient" else int((game.get("max_attempts") or {}).get(stage_id, 3))

    def _game_view(self, character: dict, judged_index: int, menu: str | None, verdict: str | None,
                   confidence: float, retry: bool, attempts_left: int, message: str, plating: dict | None) -> dict:
        """요리 게임 규칙으로 추가된 응답 필드. 기존 필드(stage 객체 등)는 그대로 두고 옆에 붙인다.
        stage_number·stage_name·verdict는 "방금 보낸 타일을 판정한 단계" 기준이다 (stage 객체는 지금 진행할 단계)."""
        from .image_selector import _url

        game = character["game"]
        stage_id = character["stages"][judged_index]["id"]
        dishes = self.dishes_of(character)
        return {
            "menu": menu,
            "menu_image": _url(dishes[menu]["images"]["success"]) if menu else None,
            "stage_number": judged_index + 1,
            "stage_name": game["stage_names"][stage_id],
            "verdict": verdict,
            "confidence": confidence,
            "retry": retry,
            "attempts_left": attempts_left,
            "alien_message": message,
            "plating": plating,
        }

    def start(self, character: dict, dish_id: str | None = None, rng=random) -> dict:
        """대화를 시작한다. 메뉴는 1단계 첫 타일로 정하므로 dish는 그때까지 쓰는 임시 요리(외계인 첫 추측용)다."""
        dishes = self.dishes_of(character)
        if dish_id is None:
            dish_id = rng.choice(sorted(dishes))
        dish = dishes[dish_id]
        stages = character["stages"]
        stage = stages[0]
        alien = self.generator.first_guess(stage, dish, character)
        state = {"dish": dish_id, "menu": None, "stage_index": 0, "exchange_count": 0, "confidence": 0.0,
                 "alien_scores": alien["scores"], "finals": {}, "verdicts": {}, "stage_metrics": [], "done": False}
        return {
            "reply": alien["reply"],
            "image": self.image_selector.select(alien["reply"], character, stage=stage, expression=alien["expression"]),
            "sources": [],
            "alien": self._alien_view(alien),
            "state": state,
            "stage": self._stage_view(stage, 0, len(stages)),
            "dish": {"id": dish_id, "name": dish["name"]},
            "result": None,
            **self._game_view(character, 0, None, None, 0.0, False, 1, alien["reply"], None),
        }

    def record_dialogue(self, character: dict, dish_id: str, entries: list[dict], success: bool,
                        wrong: int | None = None) -> dict:
        """대화가 끝난 뒤 레코드의 타일마다 대사를 붙이고, 외계인 대사에는 임베딩으로 고른 그림을 붙인다.
        entries는 app.parse_record()가 검증한 값. wrong은 단계별 호출 시 넣을 엉뚱한 방법 대사 수."""
        fallback = (character.get("record") or {}).get("fallback_lines") or {}
        lines, source = self.generator.record_lines(entries, self.dishes_of(character)[dish_id], fallback, success, wrong)
        alien = [i for i, e in enumerate(entries) if e["who"] == "alien"]
        images, image_source = pick_line_images([lines[i] for i in alien], character)
        image_of = dict(zip(alien, images))
        return {"lines": [{"text": line, "image": image_of.get(i)} for i, line in enumerate(lines)],
                "source": source, "image_source": image_source}

    def play_turn(self, user_message: str, username: str, character: dict, signal: dict, state: dict) -> dict:
        """사용자 타일 한 장을 판정하고, 확신·진행 상태와 외계인의 다음 타일·표정·행동 묘사를 돌려준다.

        1. 1단계(재료 선정): 첫 타일의 색 온도·노이즈로 메뉴를 정하고 바로 손질로 (조리 판정에는 쓰지 않음)
        2. 손질·조리·플레이팅: 판정값(game_metrics) → judge_stage → 외계인 확신(alien_confidence)
           확신이 기준 이상이면 다음 단계, 미만이면 같은 단계 재요청(retry). 최대 시도에 닿으면 결과 확정
        3. 마지막 단계가 끝나면 세 단계 판정으로 요리 결과(judge_menu_result)
        외계인 추측 타일(alien.scores)은 화면 기록·레코드용으로 2부 규칙(update_confidence)에 따라 계속 움직인다.
        """
        stages = character["stages"]
        game = character["game"]
        exchange = character.get("exchange") or {}
        dishes = self.dishes_of(character)
        index = state["stage_index"]
        stage = stages[index]
        attempts = state["exchange_count"] + 1
        metrics = game_metrics(signal, game)
        # 외계인 추측 타일 이동용 (개발 확인용으로 응답 update에도 남김)
        update = update_confidence(state["confidence"], signal["scores"], state["alien_scores"],
                                   stage, signal.get("color"), exchange)
        new_state = {**state, "finals": dict(state["finals"]), "verdicts": dict(state["verdicts"]),
                     "stage_metrics": list(state["stage_metrics"])}

        if stage["id"] == "ingredient":
            menu = decide_menu(metrics, game)
            new_state.update(menu=menu, dish=menu)
            judged, confidence, advance, reason = {"verdict": "success", "closeness": 1.0}, 1.0, True, "menu"
            final_metrics = metrics
        else:
            menu = state["menu"]
            rules = game["rules"][menu][stage["id"]]
            judged = judge_stage(stage["id"], metrics, rules, game)
            confidence = alien_confidence(state["confidence"] if attempts > 1 else None, judged["closeness"], game, signal["seed"],
                                          f"{stage['id']}:{attempts}")
            if confidence >= game["confidence"]["threshold"]:
                advance, reason = True, "confident"
            elif attempts >= self._max_attempts(game, stage["id"]):
                advance, reason = True, "max_reached"
            else:
                advance, reason = False, None
            final_metrics = metrics
            if reason == "max_reached" and game.get("finalize") == "average":
                final_metrics = average_metrics(new_state["stage_metrics"] + [metrics])
                judged = {**judge_stage(stage["id"], final_metrics, rules, game), "closeness": judged["closeness"]}

        verdict = judged["verdict"]
        dish = dishes[new_state["dish"]]
        stage_name = game["stage_names"][stage["id"]]
        knowledge = self.retriever.search(f"{menu} {stage_name} {verdict}")
        message = self.generator.act(stage, dish, character, verdict, confidence, not advance, knowledge, menu)
        result = None

        if advance:
            record = {"verdict": verdict, "metrics": final_metrics}
            if "abnormal" in judged:
                record["abnormal"] = judged["abnormal"]
            new_state["verdicts"][stage["id"]] = record
            new_state["finals"][stage["id"]] = signal["scores"]
            new_state["stage_metrics"] = []
            if index + 1 >= len(stages):
                result = judge_menu_result(menu, new_state["verdicts"], game, dishes)
                alien = self.generator.finish(result, dish, character)
                new_state.update(exchange_count=attempts, confidence=confidence, done=True)
                current, current_index = stage, index
            else:
                current_index = index + 1
                current = stages[current_index]
                alien = self.generator.first_guess(current, dish, character, previous=stage,
                                                   reason="max_reached" if reason == "max_reached" else "confident")
                new_state.update(stage_index=current_index, exchange_count=0, confidence=0.0,
                                 alien_scores=alien["scores"])
        else:
            current, current_index = stage, index
            alien = self.generator.respond_to_tile(stage, dish, character, signal, state["alien_scores"],
                                                   update, knowledge, username, user_message)
            alien = {**alien, "expression": game["verdict_expressions"][verdict]}  # 판정에 따른 외계인 반응
            new_state["stage_metrics"].append(metrics)
            new_state.update(exchange_count=attempts, confidence=confidence, alien_scores=alien["scores"])

        plating = plating_view(menu, final_metrics["hue"], verdict, game) if stage["id"] == "plating" else None
        return {
            "reply": message,
            "image": self.image_selector.select(message, character, stage=current,
                                                expression=alien["expression"], result=result),
            "sources": list(dict.fromkeys(hit.title for hit in knowledge)),
            "alien": self._alien_view(alien),
            "state": new_state,
            "stage": self._stage_view(current, current_index, len(stages), advance, reason),
            "dish": {"id": new_state["dish"], "name": dish["name"]},
            "result": result,
            "update": update,
            "metrics": final_metrics,  # 판정값 0~100·Hue (개발 확인용)
            **self._game_view(character, index, menu, verdict, confidence, not advance,
                              max(0, self._max_attempts(game, stage["id"]) - attempts), message, plating),
        }
