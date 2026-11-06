"""답변과 맞는 이미지를 고르는 경계.

1차 구현: 라벨(단계·표정·결과)로 config에 적힌 이미지 경로를 고른다.
- 요리가 끝났으면 음식 성공/실패 이미지
- 아니면 config.expressions의 표정 이미지 (default / doubt / convinced / surprised / thinking / joy)
레코드 외계인 대사 그림: 문장부호로 후보 표정을 좁히고, config.record.line_images의 표정별 예시와 대사의 임베딩 유사도로 고른다.
"""

import logging
import math
import os

EMBEDDING_MODEL = "text-embedding-3-small"


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    return dot / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)) or 1)


# 임베딩은 ?·!를 잘 가리지 못해서 문장부호로 후보 표정을 먼저 좁힌다. 맨 앞 = 키가 없을 때 고르는 표정
MARK_CANDIDATES = {
    "?!": ["surprised"],
    "?": ["doubt", "thinking"],  # 놀람은 ! 가 있을 때만
    "!": ["joy", "convinced", "surprised"],
    "": ["default", "convinced", "thinking", "doubt", "joy", "surprised"],
}


def candidates(text: str, keys) -> list[str]:
    """대사의 문장부호에 맞는 후보 표정 (keys 안에서, MARK_CANDIDATES 순서)."""
    question, exclaim = "?" in text, "!" in text
    if "모르" in text and not exclaim:  # "더 모르겠어" = 점점 헷갈림
        return [k for k in ("thinking", "doubt") if k in keys] or list(keys)
    order = MARK_CANDIDATES["?!" if question and exclaim else "?" if question else "!" if exclaim else ""]
    return [k for k in order if k in keys] or list(keys)


# 같은 그림이 몰리지 않도록 이미 쓴 표정은 쓸 때마다, 바로 앞 대사와 같은 표정은 한 번 더 감점한다 (유사도 차이 기준)
USED_PENALTY = 0.02
REPEAT_PENALTY = 0.04


def pick_diverse(texts: list[str], keys, similarity=None) -> list[str]:
    """대사마다 후보 표정 중 (유사도 - 겹침 감점)이 가장 큰 표정. similarity가 없으면 덜 쓴 표정부터 후보 순서대로."""
    used, chosen = dict.fromkeys(keys, 0), []
    for i, text in enumerate(texts):
        options = candidates(text, keys)
        score = lambda k: ((similarity[i][k] if similarity else 0.0) - USED_PENALTY * used[k]
                           - REPEAT_PENALTY * (chosen[-1:] == [k]) - (0 if similarity else 1e-3 * options.index(k)))
        chosen.append(max(options, key=score))
        used[chosen[-1]] += 1
    return chosen


def match_images(texts: list[str], images: dict, embed) -> list[str]:
    """문장마다 후보 표정 중 예시가 가장 비슷한 표정 키를 고른다 (겹침 감점 포함).
    images: {표정: [그림 설명, 예시 대사…]}, embed(문장 목록) → 벡터 목록."""
    examples = [(key, line) for key, lines in images.items() for line in lines]
    vectors = embed(texts + [line for _, line in examples])
    similarity = []
    for vector in vectors[:len(texts)]:
        best = {}  # 표정별로 가장 비슷한 예시의 유사도
        for (key, _), example in zip(examples, vectors[len(texts):]):
            best[key] = max(best.get(key, -1.0), _cosine(vector, example))
        similarity.append(best)
    return pick_diverse(texts, images, similarity)


def pick_line_images(texts: list[str], character: dict, use_llm: bool = True) -> tuple[list[str], str]:
    """외계인 대사마다 어울리는 표정 그림 URL. 키가 없거나 호출 제한에 걸리거나 실패하면 문장부호로만 고른다.
    반환: (URL 목록, "openai" | "no_key" | "rule_limited" | "openai_failed")
    """
    images = {k: v for k, v in ((character.get("record") or {}).get("line_images") or {}).items() if not k.startswith("_")}
    expressions = character.get("expressions") or {}
    if not texts or not images:
        return [], "empty"
    source = "no_key" if not os.getenv("OPENAI_API_KEY") else "openai" if use_llm else "rule_limited"
    keys = None
    if source == "openai":
        try:
            from openai import OpenAI

            client = OpenAI(timeout=20.0, max_retries=2)
            keys = match_images(texts, images, lambda batch: [
                d.embedding for d in client.embeddings.create(model=EMBEDDING_MODEL, input=batch).data])
            source = "openai"
        except Exception:
            logging.getLogger(__name__).exception("대사 그림 임베딩 실패")
            source = "openai_failed"
    keys = keys or pick_diverse(texts, images)
    return [_url(expressions[key]["image"]) for key in keys], source


def _url(path: str | None) -> str | None:
    """config의 'assets/images/...' 경로를 브라우저 주소 '/assets/images/...'로 바꾼다."""
    return f"/{path.lstrip('/')}" if path else None


class DemoImageSelector:
    def select(
        self,
        reply: str,
        character: dict,
        stage: dict | None = None,
        expression: str | None = None,
        result: dict | None = None,
    ) -> str | None:
        """브라우저에서 열리는 이미지 URL을 반환한다. 고를 이미지가 없으면 None."""
        if result:
            return _url(result.get("image"))
        expressions = character.get("expressions") or {}
        chosen = expressions.get(expression or "")
        if isinstance(chosen, dict) and chosen.get("image"):
            return _url(chosen["image"])
        return None
