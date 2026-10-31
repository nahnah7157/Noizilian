"""5기 캐릭터 챗봇 베이스의 웹 진입점."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, url_for

from services import ChatbotService
from services.chatbot_service import parse_signal


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

    try:
        response = chatbot.generate_response(message, username, load_config(), signal=signal)
        if not isinstance(response, dict) or not isinstance(response.get("reply"), str):
            raise TypeError("챗봇 응답에는 문자열 reply가 필요합니다.")
        image = response.get("image")
        if image is not None and not isinstance(image, str):
            raise TypeError("image는 URL 문자열 또는 null이어야 합니다.")
        sources = response.get("sources", [])
        if not isinstance(sources, list) or not all(isinstance(source, str) for source in sources):
            raise TypeError("sources는 출처 이름 문자열의 목록이어야 합니다.")
        return jsonify({"reply": response["reply"], "image": image, "sources": sources})
    except Exception:
        app.logger.exception("챗봇 응답 생성 실패")
        return error_response("chat_failed", "답변을 생성하지 못했습니다. 다시 시도해주세요.", 500)


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=os.getenv("FLASK_DEBUG") == "1",
    )
