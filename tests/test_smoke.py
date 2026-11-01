"""화면·정적 파일·채팅 응답과 서비스 연결, 학종이 신호 해석, 요리 단계 규칙을 확인합니다.

신호 해석과 단계 규칙의 근거는 data/knowledge/paper_rules.md(R1~R15)를 따릅니다.
"""

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from app import app
from services.chatbot_service import (
    AXES,
    DEFAULT_RELIABILITY,
    ChatbotService,
    color_clarity,
    judge_dish,
    parse_signal,
    scores_of,
    should_advance,
    stage_distance,
    update_confidence,
)
from services.retriever import KnowledgeHit


# ═══════════════════════════════════════════════════════════════
# 1. 베이스 스모크 테스트 (화면·API·서비스 연결)
# ═══════════════════════════════════════════════════════════════

class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pages_and_referenced_assets(self):
        for route in ("/", "/detail", "/chat?username=헤슬", "/health"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

        chat_page = self.client.get("/chat").get_data(as_text=True)
        self.assertIn("/assets/js/chatbot.js", chat_page)
        self.assertIn("/assets/images/alien/alien_cute_a.png", self.client.get("/").get_data(as_text=True))
        for path in (
            "/assets/js/chatbot.js",
            "/assets/css/style.css",
            "/assets/images/hateslop-logo.png",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                response.close()

    def test_chat_returns_demo_response(self):
        response = self.client.post("/api/chat", json={"message": "안녕", "username": "헤슬"})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("안녕", data["reply"])
        self.assertIsNone(data["image"])
        self.assertEqual(data["sources"], [])

    def test_bad_inputs_are_rejected(self):
        cases = (
            ({}, 400, "invalid_message"),
            ({"message": "   "}, 400, "invalid_message"),
            ({"message": "x" * 2001}, 413, "message_too_long"),
            ({"message": "안녕", "username": 1}, 400, "invalid_username"),
        )
        for payload, status, code in cases:
            with self.subTest(code=code):
                response = self.client.post("/api/chat", json=payload)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_json()["error"]["code"], code)

        response = self.client.post("/api/chat", data="broken", content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_json")

    def test_service_failure_is_not_a_successful_null(self):
        with patch("app.chatbot.generate_response", side_effect=RuntimeError("upstream down")), patch(
            "app.app.logger.exception"
        ):
            response = self.client.post("/api/chat", json={"message": "안녕"})
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json()["error"]["code"], "chat_failed")

    def test_service_passes_character_and_retrieved_sources_to_generator(self):
        hit = KnowledgeHit(title="세계관 설정", content="성 안에는 오래된 도서관이 있다.")

        class Retriever:
            def search(self, question):
                self.question = question
                return [hit]

        class Generator:
            def generate(self, question, username, character, knowledge):
                self.args = (question, username, character, knowledge)
                return "도서관을 찾아보세요."

        retriever, generator = Retriever(), Generator()
        service = ChatbotService(retriever, generator)
        character = {"name": "안내인"}
        result = service.generate_response("도서관은 어디?", "헤슬", character)
        self.assertEqual(retriever.question, "도서관은 어디?")
        self.assertEqual(generator.args, ("도서관은 어디?", "헤슬", character, [hit]))
        self.assertEqual(result["sources"], ["세계관 설정"])
        self.assertEqual(result["reply"], "도서관을 찾아보세요.")


# ═══════════════════════════════════════════════════════════════
# 2. 학종이 신호 해석 (색·질감 → 감각 점수)
# ═══════════════════════════════════════════════════════════════

SIGNAL = {
    "color": {"L": 40, "C": 85, "h": 40},
    "texture": {"oct": 12, "freq": 0.9, "pers": 0.8, "lac": 3.2},
    "seed": 42,
}


class SenseModelTest(unittest.TestCase):
    def test_scores_match_browser_library(self):
        # 브라우저 library.js의 scoresOf()가 같은 입력에 낸 값 (소수 둘째 자리)
        cases = (
            ({"L": 40, "C": 85, "h": 40}, {"oct": 12, "freq": 0.9, "pers": 0.8, "lac": 3.2},
             {"wc": -0.77, "mf": 0.22, "hs": -1.0, "hl": 0.0}),
            ({"L": 60, "C": 35, "h": 230}, {"oct": 1, "freq": 0.4, "pers": 0.4, "lac": 1.8},
             {"wc": 0.64, "mf": -0.02, "hs": 1.0, "hl": 0.32}),
        )
        for color, texture, expected in cases:
            scores = scores_of(color, texture)
            for axis, value in expected.items():
                with self.subTest(color=color, axis=axis):
                    self.assertAlmostEqual(scores[axis], value, delta=0.01)

    def test_paper_directions(self):
        smooth = {"oct": 1, "freq": 0.4, "pers": 0.4, "lac": 1.8}
        rough = {"oct": 12, "freq": 0.9, "pers": 0.8, "lac": 3.2}
        gray = {"L": 50, "C": 0, "h": 0}
        # 단단함–부드러움은 질감만으로 정해진다: 거칠면 단단함(음수)
        self.assertLess(scores_of(gray, rough)["hs"], scores_of(gray, smooth)["hs"])
        # 어두울수록 무거움(음수)
        self.assertLess(scores_of({"L": 10, "C": 0, "h": 0}, smooth)["hl"], scores_of({"L": 90, "C": 0, "h": 0}, smooth)["hl"])

    def test_parse_signal_recomputes_scores(self):
        parsed = parse_signal({**SIGNAL, "scores": {"wc": 1, "mf": 1, "hs": 1, "hl": 1}})
        self.assertAlmostEqual(parsed["scores"]["hs"], -1.0, delta=0.01)  # 보낸 점수가 아니라 다시 계산한 값
        self.assertIn("따뜻", parsed["description"])

    def test_parse_signal_rejects_bad_values(self):
        bad = (
            "문자열",
            {"color": SIGNAL["color"]},
            {**SIGNAL, "color": {"L": 400, "C": 10, "h": 0}},
            {**SIGNAL, "texture": {**SIGNAL["texture"], "oct": 50}},
            {**SIGNAL, "seed": "x"},
        )
        for data in bad:
            with self.subTest(data=data), self.assertRaises(ValueError):
                parse_signal(data)


class SignalApiTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_chat_with_signal(self):
        response = self.client.post("/api/chat", json={"message": "안녕", "username": "헤슬", "signal": SIGNAL})
        self.assertEqual(response.status_code, 200)
        self.assertIn("신호를 받았어요", response.get_json()["reply"])

    def test_chat_rejects_bad_signal(self):
        response = self.client.post("/api/chat", json={"message": "안녕", "signal": {"color": {}}})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"]["code"], "invalid_signal")

    def test_chat_page_includes_composer(self):
        page = self.client.get("/chat").get_data(as_text=True)
        self.assertIn('id="signal-composer"', page)
        response = self.client.get("/assets/js/chatbot.js")
        self.assertEqual(response.status_code, 200)
        response.close()


# ═══════════════════════════════════════════════════════════════
# 3. 요리 단계 규칙 (확신 갱신 · 다음 단계 판정 · 요리 성공 판정)
# ═══════════════════════════════════════════════════════════════

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config" / "chatbot_config.json").read_text(encoding="utf-8"))
STAGES = {s["id"]: s for s in CONFIG["stages"]}
EXCHANGE = CONFIG["exchange"]
DISHES = {k: v for k, v in CONFIG["dishes"].items() if not k.startswith("_")}

ROUGH = {"oct": 12, "freq": 0.9, "pers": 0.8, "lac": 3.2}
SMOOTH = {"oct": 1, "freq": 0.4, "pers": 0.4, "lac": 1.8}
CLEAR = {"L": 50, "C": 50, "h": 40}      # L*+C* = 100 (R12에서 가장 일관된 색)
DARK = {"L": 10, "C": 0, "h": 0}         # L*+C* = 10
VIVID = {"L": 70, "C": 110, "h": 324}    # L*+C* = 180


def flat(value):
    return {a: value for a in AXES}


class ConfigTest(unittest.TestCase):
    def test_four_stages_in_order(self):
        self.assertEqual([s["id"] for s in CONFIG["stages"]], ["ingredient", "prep", "cook", "plating"])

    def test_stage_axes_follow_paper(self):
        # R3: 손질(식감)은 질감만으로 정해지는 단단함–부드러움 축만 본다
        self.assertEqual(STAGES["prep"]["axes"], ["hs"])
        for stage in CONFIG["stages"]:
            self.assertTrue(set(stage["axes"]) <= set(AXES), stage["id"])

    def test_dish_targets_use_stage_axes(self):
        for name, dish in DISHES.items():
            self.assertEqual(set(dish["targets"]), set(STAGES), name)
            for stage_id, target in dish["targets"].items():
                self.assertTrue(set(target) <= set(STAGES[stage_id]["axes"]), f"{name}/{stage_id}")
                self.assertTrue(all(-1 <= v <= 1 for v in target.values()), f"{name}/{stage_id}")

    def test_reliability_matches_paper_table1(self):
        # R13: Table I 색 질감 행 평균
        self.assertEqual(DEFAULT_RELIABILITY, {"wc": 0.74, "mf": 0.60, "hs": 0.64, "hl": 0.64})
        weights = {k: v for k, v in EXCHANGE["axis_reliability"].items() if not k.startswith("_")}
        self.assertEqual(weights, DEFAULT_RELIABILITY)


class DistanceTest(unittest.TestCase):
    def test_prep_ignores_color(self):
        # R3: 같은 질감이면 색이 완전히 달라도 손질 단계의 거리는 0
        red, blue = scores_of({"L": 50, "C": 70, "h": 40}, ROUGH), scores_of({"L": 80, "C": 30, "h": 220}, ROUGH)
        self.assertAlmostEqual(stage_distance(red, blue, STAGES["prep"]["axes"]), 0.0)
        self.assertGreater(stage_distance(red, blue, STAGES["ingredient"]["axes"]), 0.3)

    def test_prep_sees_texture(self):
        rough, smooth = scores_of(CLEAR, ROUGH), scores_of(CLEAR, SMOOTH)
        self.assertGreater(stage_distance(rough, smooth, STAGES["prep"]["axes"]), 1.5)


class ConfidenceTest(unittest.TestCase):
    def test_close_tiles_raise_far_tiles_lower(self):
        up = update_confidence(0.5, flat(0.4), flat(0.4), STAGES["cook"], CLEAR, EXCHANGE)
        down = update_confidence(0.5, flat(0.9), flat(-0.9), STAGES["cook"], CLEAR, EXCHANGE)
        self.assertGreater(up["confidence"], 0.5)
        self.assertLess(down["confidence"], 0.5)

    def test_confidence_stays_between_0_and_1(self):
        self.assertEqual(update_confidence(0.95, flat(0), flat(0), STAGES["cook"], CLEAR, EXCHANGE)["confidence"], 1.0)
        self.assertEqual(update_confidence(0.05, flat(1), flat(-1), STAGES["cook"], CLEAR, EXCHANGE)["confidence"], 0.0)

    def test_dark_or_vivid_color_counts_less(self):
        # R12: L*+C*가 100에서 멀수록 해석이 갈리므로 같은 일치라도 확신이 덜 오른다
        clear = update_confidence(0, flat(0.2), flat(0.2), STAGES["ingredient"], CLEAR, EXCHANGE)["step"]
        dark = update_confidence(0, flat(0.2), flat(0.2), STAGES["ingredient"], DARK, EXCHANGE)["step"]
        vivid = update_confidence(0, flat(0.2), flat(0.2), STAGES["ingredient"], VIVID, EXCHANGE)["step"]
        self.assertGreater(clear, dark)
        self.assertGreater(clear, vivid)
        self.assertAlmostEqual(color_clarity(CLEAR), 1.0)
        self.assertAlmostEqual(color_clarity({"L": 10, "C": 0, "h": 0}), 0.5)  # 양 끝에서 표준편차 2배 [가정]

    def test_prep_confidence_does_not_depend_on_color(self):
        # R3 + R12: 손질 단계는 단단함–부드러움만 보므로 색의 불확실성이 끼어들지 않는다
        a = update_confidence(0, flat(0.3), flat(0.3), STAGES["prep"], CLEAR, EXCHANGE)["step"]
        b = update_confidence(0, flat(0.3), flat(0.3), STAGES["prep"], DARK, EXCHANGE)["step"]
        self.assertEqual(a, b)

    def test_more_consistent_axis_counts_more(self):
        # R13: 따뜻함–차가움(0.74)은 남성적–여성적(0.60)보다 일관되므로 같은 일치에 확신이 더 오른다
        wc = update_confidence(0, flat(0), flat(0), {"id": "t", "axes": ["wc"]}, CLEAR, EXCHANGE)["step"]
        mf = update_confidence(0, flat(0), flat(0), {"id": "t", "axes": ["mf"]}, CLEAR, EXCHANGE)["step"]
        self.assertGreater(wc, mf)

    def test_several_agreements_reach_threshold(self):
        conf, count = 0.0, 0
        while not should_advance(conf, count, EXCHANGE)["advance"]:
            conf = update_confidence(conf, flat(0.1), flat(0.1), STAGES["ingredient"], CLEAR, EXCHANGE)["confidence"]
            count += 1
            self.assertLess(count, 10)
        self.assertGreaterEqual(count, 2)  # 한 번 맞았다고 바로 넘어가지 않는다


class AdvanceTest(unittest.TestCase):
    def test_advance_rules(self):
        self.assertEqual(should_advance(0.85, 1, {"confidence_threshold": 0.8})["reason"], "confident")
        self.assertFalse(should_advance(0.3, 99, {"confidence_threshold": 0.8, "max_exchanges": None})["advance"])
        self.assertEqual(should_advance(0.3, 4, {"confidence_threshold": 0.8, "max_exchanges": 4})["reason"], "max_reached")


class DishTest(unittest.TestCase):
    def test_exact_targets_succeed(self):
        for name, dish in DISHES.items():
            final = {s: {**flat(0), **t} for s, t in dish["targets"].items()}
            result = judge_dish(final, dish, CONFIG["result"])
            self.assertTrue(result["success"], name)
            self.assertEqual(result["image"], "/" + dish["images"]["success"])

    def test_opposite_targets_fail(self):
        dish = DISHES["ramen"]
        final = {s: {**flat(0), **{a: -v if v else 1 for a, v in t.items()}} for s, t in dish["targets"].items()}
        result = judge_dish(final, dish, CONFIG["result"])
        self.assertFalse(result["success"])
        self.assertEqual(result["image"], "/" + dish["images"]["fail"])

    def test_dish_images_exist(self):
        for dish in DISHES.values():
            for path in dish["images"].values():
                self.assertTrue((ROOT / "public" / path).exists(), path)


# ═══════════════════════════════════════════════════════════════
# 4. 요리 단계 진행 (/api/start, /api/chat + state)
# ═══════════════════════════════════════════════════════════════

TILE = {"color": {"L": 50, "C": 50, "h": 40}, "texture": {"oct": 6, "freq": 0.5, "pers": 0.6, "lac": 2.5}, "seed": 7}


class CookingFlowTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def start(self, dish="ramen"):
        response = self.client.post("/api/start", json={"dish": dish})
        self.assertEqual(response.status_code, 200)
        return response.get_json()

    def send(self, state, tile=TILE):
        return self.client.post("/api/chat", json={"message": "신호", "username": "헤슬", "signal": tile, "state": state})

    def test_start_returns_first_stage_and_alien_tile(self):
        data = self.start()
        self.assertEqual(data["state"]["stage_index"], 0)
        self.assertEqual(data["stage"]["id"], "ingredient")
        self.assertEqual(data["dish"], {"id": "ramen", "name": "라멘"})
        self.assertEqual(set(data["alien"]["scores"]), set(AXES))
        self.assertEqual(data["image"], "/" + STAGES["ingredient"]["pose_image"])

    def test_start_random_dish(self):
        self.assertIn(self.client.post("/api/start", json={}).get_json()["dish"]["id"], DISHES)

    def test_one_exchange_updates_state(self):
        data = self.send(self.start()["state"]).get_json()
        self.assertEqual(data["state"]["exchange_count"], 1)
        self.assertIn(data["alien"]["expression"], CONFIG["expressions"])
        self.assertIsNone(data["result"])

    def test_stage_advances_within_max_exchanges(self):
        # 같은 타일만 보내도 최대 4번 안에는 다음 단계로 넘어간다 (exchange.max_exchanges)
        state = self.start()["state"]
        for _ in range(EXCHANGE["max_exchanges"]):
            data = self.send(state).get_json()
            state = data["state"]
            if data["stage"]["advanced"]:
                break
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual(state["stage_index"], 1)
        self.assertIn("ingredient", state["finals"])
        self.assertEqual(data["image"], "/" + STAGES["prep"]["pose_image"])  # 손질: 칼 든 외계인

    def test_full_game_ends_with_dish_image(self):
        from services.image_selector import _url
        state, data = self.start()["state"], None
        for _ in range(len(STAGES) * EXCHANGE["max_exchanges"]):
            data = self.send(state).get_json()
            state = data["state"]
            if state["done"]:
                break
        self.assertTrue(state["done"])
        self.assertIn(data["result"]["image"], [_url(p) for p in DISHES["ramen"]["images"].values()])
        self.assertEqual(data["image"], _url(DISHES["ramen"]["images"]["fail"] if not data["result"]["success"] else DISHES["ramen"]["images"]["success"]))
        # 끝난 뒤에는 더 보낼 수 없다
        self.assertEqual(self.send(state).get_json()["error"]["code"], "invalid_state")

    def test_bad_state_is_rejected(self):
        good = self.start()["state"]
        for bad in ({**good, "dish": "kimchi"}, {**good, "stage_index": 9}, {**good, "confidence": 2},
                    {**good, "alien_scores": {"wc": 0}}, "문자열"):
            with self.subTest(bad=str(bad)[:40]):
                self.assertEqual(self.send(bad).get_json()["error"]["code"], "invalid_state")
        response = self.client.post("/api/chat", json={"message": "안녕", "state": good})
        self.assertEqual(response.get_json()["error"]["code"], "invalid_state")  # 신호 없이 상태만

    def test_following_the_recipe_succeeds(self):
        # 요리 목표와 같은 타일을 계속 보내면 성공 이미지가 나온다
        service, dish = ChatbotService(), DISHES["omurice"]
        state = service.start(CONFIG, "omurice")["state"]
        while not state["done"]:
            stage_id = STAGES_ORDER[state["stage_index"]]
            scores = {**{a: 0.0 for a in AXES}, **dish["targets"][stage_id]}
            data = service.play_turn("", "헤슬", CONFIG, {"scores": scores, "color": TILE["color"]}, state)
            state = data["state"]
        self.assertTrue(data["result"]["success"])
        self.assertEqual(data["image"], "/" + dish["images"]["success"])


STAGES_ORDER = [s["id"] for s in CONFIG["stages"]]


class RecordInterpretTest(unittest.TestCase):
    """대화가 끝난 뒤 레코드 해석 API. OpenAI 키가 없으면 공식 계산 설명으로 대신한다."""

    def setUp(self):
        self.client = app.test_client()

    def interpret(self, entries):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            return self.client.post("/api/interpret", json={"dish": "ramen", "entries": entries})

    def test_formula_fallback_one_per_tile(self):
        alien = {"who": "alien", "stage": "ingredient", "message": "이거…?", "scores": {a: 0.0 for a in AXES}}
        user = {"who": "user", "stage": "ingredient", "message": "따뜻하게", "signal": TILE}
        response = self.interpret([alien, user])
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["source"], "no_key")
        self.assertEqual(len(data["interpretations"]), 2)
        self.assertIn("재료 준비", data["interpretations"][1]["basis"])

    def test_user_scores_are_recomputed(self):
        # 브라우저가 보낸 점수는 무시하고 색·질감으로 다시 계산한다
        fake = {"who": "user", "stage": "prep", "signal": TILE, "scores": {a: 1.0 for a in AXES}}
        expected = parse_signal(TILE)["description"]
        self.assertIn(expected, self.interpret([fake]).get_json()["interpretations"][0]["basis"])

    def test_rejects_bad_entries(self):
        for entries in ([], [{"who": "ghost", "stage": "prep"}], [{"who": "alien", "stage": "prep", "scores": {"wc": 2}}],
                        [{"who": "user", "stage": "nope", "signal": TILE}]):
            with self.subTest(entries=entries):
                self.assertEqual(self.interpret(entries).status_code, 400)


if __name__ == "__main__":
    unittest.main()
