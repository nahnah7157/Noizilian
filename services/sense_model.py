"""색·질감 신호의 감각 점수 (Lucassen, Gevers, Gijsenij 2011, Table III 색 질감 공식).

브라우저의 public/assets/js/noizilian/senseModel.js, library.js와 같은 공식·정규화를 씁니다.
한쪽을 고치면 다른 쪽도 함께 고치세요. 서버는 브라우저가 보낸 점수를 믿지 않고 색·질감 값으로 다시 계산합니다.
"""

import math

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
