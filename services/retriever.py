"""질문에 맞는 자료를 찾는 경계.

기본 구현: data/knowledge/cooking_rules.md를 "## 제목" 단위로 나누고, 질문의 단어가 제목에 몇 개 들어 있는지로 고른다.
요리 게임은 "메뉴 단계 판정"(예: "pizza cook over")으로 묻는다. 맞는 제목이 없으면 빈 목록.
"""

from dataclasses import dataclass
from pathlib import Path

KNOWLEDGE_FILES = (Path(__file__).resolve().parent.parent / "data" / "knowledge" / "cooking_rules.md",)


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
