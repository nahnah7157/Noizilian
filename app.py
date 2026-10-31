"""5기 캐릭터 챗봇 베이스의 웹 진입점."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, url_for

from services import ChatbotService
from services.chatbot_service import AXES, parse_signal


BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "chatbot_config.json"
load_dotenv(BASE_DIR / ".env")

# Vercel은 public/을 CDN에서 제공하고, 로컬·Render는 Flask가 제공합니다.
IS_VERCEL = os.getenv("VERCEL") == "1"
app = Flask(
    __name__,
    static_folder=None if IS_VERCEL else "public",
    static_url_path=None if IS_VERCEL else "",
)
chatbot = ChatbotService()


def asset_url(filename: str) -> str:
    """배포 방식과 관계없이 public/ 파일을 같은 URL로 참조합니다."""
    if IS_VERCEL:
        return f"/{filename.lstrip('/')}"
    return url_for("static", filename=filename)


app.jinja_env.globals["asset_url"] = asset_url


def load_config() -> dict:
    """캐릭터 설정을 읽습니다. 편집 후 새로고침하면 화면에 반영됩니다."""
    with CONFIG_PATH.open(encoding="utf-8") as file:
        config = json.load(file)

    if not isinstance(config, dict) or not isinstance(config.get("name"), str):
        raise ValueError("config/chatbot_config.json의 name을 확인하세요.")
    return config


def bot_view(config: dict) -> dict:
    thumbnail = config.get("thumbnail") or "assets/images/hateslop-logo.png"
    return {
        "name": config["name"],
        "description": config.get("description", ""),
        "tags": config.get("tags", []),
        "greeting": config.get("greeting", "안녕하세요!"),
        "image": asset_url(thumbnail),
    }


def parse_state(data, config: dict) -> dict:
    """브라우저가 보낸 요리 진행 상태를 검증한다. 형식이 틀리면 ValueError."""
    if not isinstance(data, dict):
        raise ValueError("state는 객체여야 합니다.")
    dishes = chatbot.dishes_of(config)
    stages = config.get("stages") or []
    stage_ids = {s["id"] for s in stages}

    def number(value, lo, hi, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise ValueError(f"{name} 값이 범위({lo}~{hi})를 벗어났습니다.")
        return float(value)

    def scores(value, name):
        if not isinstance(value, dict) or set(value) != set(AXES):
            raise ValueError(f"{name}에는 {', '.join(AXES)} 점수가 모두 필요합니다.")
        return {a: number(value[a], -1, 1, f"{name}.{a}") for a in AXES}

    if data.get("dish") not in dishes:
        raise ValueError("알 수 없는 요리입니다.")
    if data.get("done") is True:
        raise ValueError("이미 끝난 요리입니다. 처음부터 다시 시작해 주세요.")
    index, count = data.get("stage_index"), data.get("exchange_count")
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(stages):
        raise ValueError("stage_index가 올바르지 않습니다.")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise ValueError("exchange_count가 올바르지 않습니다.")
    finals = data.get("finals", {})
    if not isinstance(finals, dict) or not set(finals) <= stage_ids:
        raise ValueError("finals가 올바르지 않습니다.")
    return {
        "dish": data["dish"],
        "stage_index": index,
        "exchange_count": count,
        "confidence": number(data.get("confidence"), 0, 1, "confidence"),
        "alien_scores": scores(data.get("alien_scores"), "alien_scores"),
        "finals": {k: scores(v, f"finals.{k}") for k, v in finals.items()},
        "done": False,
    }


def error_response(code: str, message: str, status: int):
    return jsonify({"error": {"code": code, "message": message}}), status


@app.get("/")
def index():
    return render_template("index.html", bot=bot_view(load_config()))


@app.get("/detail")
def detail():
    return render_template("detail.html", bot=bot_view(load_config()))


@app.get("/chat")
def chat():
    username = (request.args.get("username") or "사용자").strip()[:50] or "사용자"
    return render_template("chat.html", bot=bot_view(load_config()), username=username)


@app.post("/api/chat")
def api_chat():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return error_response("invalid_json", "JSON 객체를 보내주세요.", 400)

    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return error_response("invalid_message", "메시지를 입력해주세요.", 400)
    message = message.strip()
    if len(message) > 2000:
        return error_response("message_too_long", "메시지는 2000자 이하로 입력해주세요.", 413)

    username = payload.get("username", "사용자")
    if not isinstance(username, str):
        return error_response("invalid_username", "이름은 문자열이어야 합니다.", 400)
    username = username.strip()[:50] or "사용자"

    # 학종이 신호(선택): 색·질감 값을 검증하고 서버에서 감각 점수를 다시 계산합니다.
    signal = payload.get("signal")
    if signal is not None:
        try:
            signal = parse_signal(signal)
        except ValueError as error:
            return error_response("invalid_signal", str(error), 400)

    # 요리 진행 상태(선택): 있으면 단계 진행 흐름으로, 없으면 기존 대화 흐름으로 처리합니다.
    config = load_config()
    state = payload.get("state")
    if state is not None:
        if signal is None:
            return error_response("invalid_state", "요리 단계에서는 타일 신호(signal)가 필요합니다.", 400)
        try:
            state = parse_state(state, config)
        except ValueError as error:
            return error_response("invalid_state", str(error), 400)

    try:
        if state is not None:
            response = chatbot.play_turn(message, username, config, signal, state)
        else:
            response = chatbot.generate_response(message, username, config, signal=signal)
        if not isinstance(response, dict) or not isinstance(response.get("reply"), str):
            raise TypeError("챗봇 응답에는 문자열 reply가 필요합니다.")
        image = response.get("image")
        if image is not None and not isinstance(image, str):
            raise TypeError("image는 URL 문자열 또는 null이어야 합니다.")
        sources = response.get("sources", [])
        if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources):
            raise TypeError("sources는 출처 이름 문자열의 목록이어야 합니다.")
        body = {"reply": response["reply"], "image": image, "sources": sources}
        for key in ("alien", "state", "stage", "dish", "result"):
            if key in response:
                body[key] = response[key]
        return jsonify(body)
    except Exception:
        app.logger.exception("챗봇 응답 생성 실패")
        return error_response("chat_failed", "답변을 생성하지 못했습니다. 다시 시도해주세요.", 500)


@app.post("/api/start")
def api_start():
    """요리를 시작합니다. 외계인이 만들 요리를 정하고 첫 단계의 첫 추측 타일을 돌려줍니다."""
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return error_response("invalid_json", "JSON 객체를 보내주세요.", 400)
    config = load_config()
    dish = payload.get("dish")  # 테스트·시연용으로 요리를 지정할 수 있습니다. 없으면 무작위
    if dish is not None and dish not in chatbot.dishes_of(config):
        return error_response("invalid_dish", "알 수 없는 요리입니다.", 400)
    try:
        return jsonify(chatbot.start(config, dish))
    except Exception:
        app.logger.exception("요리 시작 실패")
        return error_response("start_failed", "시작하지 못했습니다. 다시 시도해주세요.", 500)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
