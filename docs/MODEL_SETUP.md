# OpenAI 모델 연결 예시

> **왹쿡 팀 안내:** 이 저장소는 이미 OpenAI가 연결돼 있습니다(`openai`는 `requirements.txt`에 있음). `services/generator.py`의 `decide_turn`·`record_lines`가 OpenAI를 부르고, 실패하거나 키가 없으면 규칙으로 대신합니다. **아래 3번처럼 `generator.py` 파일 전체를 바꾸면 게임 코드가 지워지니 따라 하지 마세요.** 키 넣는 방법은 [ENVIRONMENT.txt](../ENVIRONMENT.txt), 구조는 [ARCHITECTURE.md](ARCHITECTURE.md)를 보세요. 아래는 베이스 코드의 원래 안내입니다.

이 문서는 **데모 화면과 `/api/chat`이 동작하는 것을 확인한 다음** 읽는 선택 예시입니다. 기본 코드에는 OpenAI SDK와 실제 모델 호출이 들어 있지 않습니다. 다른 공급자를 선택하면 같은 `generate()` 입력과 문자열 반환 계약에 맞춰 구현하면 됩니다.

## 1. SDK 설치

활성화한 Conda 또는 venv에서 SDK를 설치합니다.

```bash
python -m pip install openai
```

팀원이 같은 패키지를 설치할 수 있도록 `requirements.txt`에도 `openai`를 추가합니다. Docker를 쓴다면 의존성을 바꾼 뒤 `docker compose up --build`로 다시 빌드합니다. [OpenAI Python SDK](https://github.com/openai/openai-python)

## 2. 로컬 환경 변수 설정

프로젝트 루트에 `.env` 파일을 직접 만들고 아래 세 줄을 적습니다(이 저장소에는 `.env.example`이 없습니다). `OPENAI_API_KEY`에는 운영진이 준 키를 넣습니다.

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=gpt-6-luna
OPENAI_REASONING_EFFORT=none
```

API 키는 **운영진이 제공한 키를 로컬 `.env`에만** 입력합니다. 이 예시 문자열을 실제 키로 바꾸고 문서나 코드에 복사하지 마세요. `.env`는 `.gitignore`에 들어 있으며 Git에 올리지 않습니다. 공개 배포에서는 `.env` 파일 대신 배포 플랫폼의 비밀 환경 변수 설정을 사용합니다.

Docker Compose 실행 시에는 호스트의 `.env`가 컨테이너에 모두 전달되지 않습니다. 이 저장소의 `docker-compose.yml`은 아래 세 변수만 전달하도록 이미 설정되어 있습니다. `.env`에 키를 입력했다면 컨테이너를 다시 시작하세요. SDK와 `requirements.txt`를 바꿨다면 `docker compose up --build`로 이미지를 다시 빌드합니다. 다른 공급자를 쓴다면 필요한 변수를 Compose에 추가하세요.

```yaml
OPENAI_API_KEY: ${OPENAI_API_KEY:-}
OPENAI_MODEL: ${OPENAI_MODEL:-gpt-6-luna}
OPENAI_REASONING_EFFORT: ${OPENAI_REASONING_EFFORT:-none}
```

`OPENAI_API_KEY`가 비어 있어도 데모는 동작합니다. Compose 설정 출력에는 키 값이 보일 수 있으므로 결과를 그대로 공유하지 마세요. [Docker Compose 환경 변수 안내](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)

## 3. `generator.py`의 데모 답변 교체

`services/generator.py`에서 현재 `DemoGenerator.generate()`는 입력을 되돌려주는 문장만 반환합니다. 아래는 **파일 전체를 교체하는 OpenAI 연결 예시**입니다. 기본은 `none`입니다. `low`는 테스트에서 필요성이 확인된 기능에만 적용하고, `medium`은 `low`로도 요구사항을 충족하지 못할 때만 별도로 검토합니다.

```python
"""캐릭터 설정과 검색 결과를 사용해 답변을 생성합니다."""

import os

from openai import OpenAI

from .retriever import KnowledgeHit


ALLOWED_REASONING_EFFORTS = {"none", "low", "medium"}


class DemoGenerator:
    def generate(
        self,
        question: str,
        username: str,
        character: dict,
        knowledge: list[KnowledgeHit],
        reasoning_effort: str | None = None,
    ) -> str:
        effort = (
            reasoning_effort
            if reasoning_effort is not None
            else os.getenv("OPENAI_REASONING_EFFORT", "none")
        )
        if effort not in ALLOWED_REASONING_EFFORTS:
            raise ValueError(
                "OPENAI_REASONING_EFFORT must be none, low, or medium."
            )

        persona = character.get("persona", {})
        instructions = (
            f"당신은 {character.get('name', '캐릭터')}입니다.\n"
            f"성격: {persona.get('personality', '')}\n"
            f"말투: {persona.get('speaking_style', '')}\n"
            f"세계관: {persona.get('world', '')}\n"
            "캐릭터 설정을 유지하며 답하세요. 모르는 사실은 지어내지 마세요."
        )

        if knowledge:
            context = "\n".join(
                f"- {hit.title}: {hit.content}" for hit in knowledge[:3]
            )
            instructions += f"\n참고 자료:\n{context}"

        response = OpenAI(timeout=20.0, max_retries=0).responses.create(
            model=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
            reasoning={"effort": effort},
            instructions=instructions,
            input=f"{username}: {question}",
            max_output_tokens=512,
        )
        if response.status == "incomplete":
            raise RuntimeError("모델 응답이 완료되지 않았습니다.")

        reply = response.output_text.strip()
        if not reply:
            raise RuntimeError("모델이 빈 답변을 반환했습니다.")
        return reply
```

`character`는 `config/chatbot_config.json`에서 읽은 설정이고, `knowledge`는 `services/retriever.py`가 찾은 자료입니다. 현재 검색기는 빈 목록을 반환하므로 검색 구현 전에도 모델 연결을 확인할 수 있습니다. 클래스명을 바꾸고 싶다면 `services/chatbot_service.py`의 import와 생성 코드도 함께 수정하세요. [OpenAI API 빠른 시작](https://developers.openai.com/api/docs/quickstart)

## 4. 기능에 따라 추론 강도 정하기

`OPENAI_REASONING_EFFORT=none`을 모든 호출의 시작값으로 둡니다. `none`, `low`, `medium`은 더 좋은 답변부터 덜 좋은 답변까지의 등급이 아닙니다. 강도를 올리면 답변이 자동으로 좋아지는 것이 아니므로, 먼저 같은 질문으로 확인하고 개선이 필요한 기능만 바꾸세요. 맥락 반영이 부족한 기능은 해당 `ChatbotService` 또는 생성기 호출에서 `low`를 비교합니다.

```python
EFFORT_BY_FEATURE = {
    "casual_chat": "none",
    "contextual_chat": "none",
}
feature = "casual_chat"  # 서버 코드에서 현재 처리 중인 기능을 지정합니다.

# 같은 질문으로 평가해도 특정 기능에서 문제가 반복되고,
# low가 개선하는지 확인할 때만 그 기능을 바꿔 비교합니다.
# EFFORT_BY_FEATURE["contextual_chat"] = "low"

effort = EFFORT_BY_FEATURE.get(feature, "none")
reply = generator.generate(
    question,
    username,
    character,
    knowledge,
    reasoning_effort=effort,
)
```

위 예시는 기능 종류에 따라 **한 번의 모델 호출에 하나의 값**을 전달합니다. `feature`는 서버 코드에서 지정하며 브라우저 입력이나 별도 모델 분류로 정하지 않습니다. 실제 구조에서는 `ChatbotService.generate_response()`가 `self.generator.generate(...)`를 호출하는 지점에 이 선택을 넣으면 됩니다. 처음에는 모든 호출을 `none`으로 두고, 비교 결과 개선이 확인된 기능에만 `low`를 적용하세요. `medium`은 시작 코드에 넣지 않습니다. 여러 사실이나 조건을 함께 판단해야 하는 특정 기능에서 `low`도 요구사항을 충족하지 못한 사례를 테스트로 확인한 뒤에만 별도로 실험하세요. 그 결과 응답 품질 개선이 확인될 때 해당 호출에 한해 유지하고, 그렇지 않으면 `none` 또는 `low`로 되돌립니다. `none`, `low`, `medium` 외의 값은 이 베이스의 예시에서 허용하지 않습니다.

