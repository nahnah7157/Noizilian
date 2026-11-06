"""질문에 맞는 자료를 찾는 경계.

기본 구현: data/knowledge/cooking_rules.md를 "## 제목" 단위로 나누고, 질문의 단어가 제목에 몇 개 들어 있는지로 고른다.
요리 게임은 "메뉴 단계 판정"(예: "pizza cook over")으로 묻는다. 맞는 제목이 없으면 빈 목록.
레코드 대사: data/knowledge/record_lines.md의 예시를 타일 태그로 거르고, 키가 있으면 임베딩 유사도로 순서를 정한다.
"""

import logging
import os
import random
from dataclasses import dataclass
from pathlib import Path

from .image_selector import EMBEDDING_MODEL, _cosine

KNOWLEDGE_FILES = (Path(__file__).resolve().parent.parent / "data" / "knowledge" / "cooking_rules.md",)
RECORD_LINES = Path(__file__).resolve().parent.parent / "data" / "knowledge" / "record_lines.md"


@dataclass(frozen=True)
class KnowledgeHit:
    title: str
    content: str


def load_sections(paths=KNOWLEDGE_FILES) -> list[KnowledgeHit]:
    """마크다운을 "## 제목" 단위 조각으로 나눈다."""
    sections = []
    for path in paths:
        if not path.is_file():
            continue
        for chunk in path.read_text(encoding="utf-8").split("\n## ")[1:]:
            title, _, body = chunk.partition("\n")
            sections.append(KnowledgeHit(title=title.strip(), content=body.strip()))
    return sections


@dataclass(frozen=True)
class RecordLine:
    stage: str
    who: str
    verdict: str
    emotion: str | None
    misread: bool
    pair: str | None  # misread=짝이름: 같은 단계에서 오해 대사와 바로잡는 대사를 잇는다
    text: str


def load_record_lines(path=RECORD_LINES) -> list[RecordLine]:
    """"## 단계 · 말한 쪽 · 판정" 섹션의 "- 태그, 태그 | 대사" 줄을 읽는다. 세 칸이 아닌 제목은 설명이라 건너뛴다."""
    lines = []
    for section in load_sections((path,)):
        parts = [part.strip() for part in section.title.split("·")]
        if len(parts) != 3:
            continue
        for row in section.content.splitlines():
            if not row.startswith("- "):
                continue
            head, _, text = row[2:].rpartition("|")
            tags = {tag.strip() for tag in head.split(",") if tag.strip()}
            mark = next((tag for tag in tags if tag.startswith("misread")), "")
            emotion = next(iter(tags - {mark}), None)
            lines.append(RecordLine(*parts, emotion, bool(mark), mark.partition("=")[2] or None, text.strip()))
    return lines


def _line_similarity(tags: list[dict], lines: list[RecordLine]) -> list[dict] | None:
    """타일 의미와 예시 대사의 유사도 [{대사: 값}]. 키가 없거나 실패하면 None (태그 순서만 쓴다)."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    try:
        from openai import OpenAI

        texts = [line.text for line in lines]
        # shortcut: 판마다 예시 전체를 다시 임베딩한다. 호출이 많아지면 예시 벡터를 저장해 둘 것
        data = OpenAI(timeout=20.0, max_retries=2).embeddings.create(
            model=EMBEDDING_MODEL, input=[tag["meaning"] for tag in tags] + texts).data
        vectors = [item.embedding for item in data]
        return [{text: _cosine(query, vector) for text, vector in zip(texts, vectors[len(tags):])}
                for query in vectors[:len(tags)]]
    except Exception:
        logging.getLogger(__name__).exception("레코드 예시 임베딩 실패")
        return None


class DemoRetriever:
    def __init__(self, sections: list[KnowledgeHit] | None = None, limit: int = 2):
        self.sections = load_sections() if sections is None else sections
        self.limit = limit

    def search(self, question: str) -> list[KnowledgeHit]:
        """질문 단어가 제목에 가장 많이 들어간 조각들(최대 limit개). 하나도 안 맞으면 []."""
        words = {w for w in question.lower().split() if w}
        scored = [(sum(w in hit.title.lower().split() for w in words), hit) for hit in self.sections]
        top = max((score for score, _ in scored), default=0)
        return [hit for score, hit in scored if score == top and top > 0][: self.limit]

    def search_lines(self, tags: list[dict], rng=random, use_llm: bool = True) -> list[list[RecordLine]]:
        """타일마다 단계·말한 쪽이 같은 예시를 잘 맞는 순서로. 파일은 매번 읽어서 고치면 바로 반영된다.

        오해 > 판정 > 감정 순으로 맞는 줄이 앞에 오므로, 맞는 줄을 다 쓰면 조건이 저절로 풀린다.
        같은 순위 안에서는 임베딩 유사도순, 키가 없으면 무작위.
        """
        lines = load_record_lines()
        similarity = _line_similarity(tags, lines) if use_llm else None
        pools = []
        for i, tag in enumerate(tags):
            same = [line for line in lines if line.stage == tag["stage"] and line.who == tag["who"]]
            pools.append(sorted(rng.sample(same, len(same)), reverse=True, key=lambda line: (
                line.misread == tag["misread"], line.verdict == tag["verdict"], line.emotion == tag["emotion"],
                similarity[i][line.text] if similarity else 0.0)))
        return pools
