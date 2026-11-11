"""화면·정적 파일·채팅 응답과 서비스 연결, 학종이 신호 해석, 요리 단계 규칙을 확인합니다.

신호 해석과 단계 규칙의 근거는 data/knowledge/paper_rules.md(R1~R15)를 따릅니다.
"""

import json
import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ["OPENAI_API_KEY"] = ""  # .env의 실제 키로 OpenAI를 부르지 않게 (load_dotenv는 있는 값을 덮지 않는다). AI 경로는 mock으로 시험

from app import app
from services.chatbot_service import (
    AXES,
    mark_misreads,
    pick_misreads,
    record_tags,
    DEFAULT_RELIABILITY,
    ChatbotService,
    color_clarity,
    judge_dish,
    parse_signal,
    scores_of,
    should_advance,
    stage_distance,
    turn_expression,
    update_confidence,
    TURN_EXPRESSIONS,
)
from services.generator import DemoGenerator
from services.retriever import DemoRetriever, KnowledgeHit, load_record_lines


def setUpModule():
    # .env에 OpenAI 키가 있어도 테스트는 모델을 부르지 않는다 (느리고 비용이 든다). 준비된 문구로 확인
    patcher = patch.dict("os.environ", {"OPENAI_API_KEY": ""})
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


# ═══════════════════════════════════════════════════════════════
# 1. 베이스 스모크 테스트 (화면·API·서비스 연결)
# ═══════════════════════════════════════════════════════════════

class SmokeTest(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()

    def test_pages_and_referenced_assets(self):
        self.assertIn('data-player="female"', self.client.get("/chat?player=female").get_data(as_text=True))
        self.assertIn('data-player="male"', self.client.get("/chat?player=<b>").get_data(as_text=True))
        for route in ("/", "/detail", "/chat?username=헤슬", "/health"):
            with self.subTest(route=route):
                self.assertEqual(self.client.get(route).status_code, 200)

        chat_page = self.client.get("/chat").get_data(as_text=True)
        self.assertIn("/assets/js/chatbot.js", chat_page)
        self.assertIn('href="/detail"', self.client.get("/").get_data(as_text=True))  # 시작하기 → 이름 화면
        self.assertIn('href="/detail', chat_page)  # 결과 끝 화면의 처음으로 → 이름 화면(→ 티저 → 컷신)
        self.assertIn("/assets/video/teaser.mp4", self.client.get("/detail").get_data(as_text=True))
        for path in (
            "/assets/js/chatbot.js",
            "/assets/css/style.css",
            "/assets/images/alien/alien_default.png",
            "/assets/images/title/hero_landscape.png",  # 시작 화면 배경(style.css)
            "/assets/images/title/hero_portrait.png",
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
        self.assertIn('id="signal-left"', page)
        self.assertIn('id="signal-center"', page)
        self.assertIn('id="signal-right"', page)
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

    def test_expression_rules(self):
        # 아주 멀면 surprised, 확신이 내려가면 thinking, 오르면 확신 크기에 따라 convinced / doubt
        from services.generator import DemoGenerator
        def face(distance, step, confidence):
            update = {"distance": distance, "step": step, "confidence": confidence}
            signal = {"scores": {a: 0.0 for a in AXES}}
            return DemoGenerator().respond_to_tile(STAGES["ingredient"], {}, CONFIG, signal,
                                                   {a: 0.0 for a in AXES}, update, [])["expression"]
        self.assertEqual(face(1.5, -0.3, 0.0), "surprised")
        self.assertEqual(face(0.8, -0.1, 0.2), "thinking")
        self.assertEqual(face(0.2, 0.2, 0.6), "convinced")
        self.assertEqual(face(0.2, 0.2, 0.2), "doubt")
        self.assertTrue(set(CONFIG["expressions"]) - {"_note"} >= {"default", "doubt", "convinced", "surprised", "thinking", "joy"})


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
        self.assertEqual(data["image"], "/" + CONFIG["expressions"]["default"]["image"])

    def test_start_random_dish(self):
        self.assertIn(self.client.post("/api/start", json={}).get_json()["dish"]["id"], DISHES)

    def after_menu(self, tile=None):
        """1단계(메뉴 선택)를 지난 state와 응답."""
        state = self.start()["state"]
        for _ in range(GAME["max_attempts"]["ingredient"]):
            data = self.send(state, tile or game_tile("pizza")).get_json()
            state = data["state"]
            if data["stage"]["advanced"]:
                break
        return state, data

    def test_first_tile_picks_menu_and_moves_to_prep(self):
        state, data = self.after_menu()
        self.assertEqual((state["menu"], state["dish"], state["stage_index"]), ("pizza", "pizza", 1))
        self.assertEqual(data["dish"]["id"], "pizza")
        self.assertEqual((data["stage_number"], data["stage_name"], data["retry"]), (1, "select", False))
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual(state["finals"], {"ingredient": state["finals"]["ingredient"]})
        self.assertNotIn("ingredient", data["state"]["verdicts"].get("prep", {}))

    def test_one_exchange_updates_state(self):
        state, _ = self.after_menu()
        data = self.send(state, game_tile("pizza", "prep", "under")).get_json()
        self.assertEqual(data["stage_name"], "prep")
        self.assertIn(data["alien"]["expression"], CONFIG["expressions"])
        self.assertIsNone(data["result"])
        if data["retry"]:
            self.assertEqual(data["state"]["exchange_count"], 1)
            self.assertEqual(data["attempts_left"], GAME["max_attempts"]["prep"] - 1)

    def test_resend_after_undo_uses_previous_state(self):
        # 되돌리기 = 이전 state로 복원. 같은(이전) state로 다시 보내도 서버가 정상 응답한다
        s1, _ = self.after_menu()
        tile = game_tile("pizza", "prep", "under")
        first = self.send(s1, tile).get_json()
        again = self.send(s1, tile)  # 되돌린 뒤 같은 s1로 다시 보냄
        self.assertEqual(again.status_code, 200)
        data = again.get_json()
        self.assertIsInstance(data["reply"], str)
        self.assertEqual(data["state"], first["state"])  # 같은 state·같은 타일이면 같은 결과

    def test_stage_advances_within_max_attempts(self):
        # 같은 타일만 보내도 최대 시도 안에는 다음 단계로 넘어간다 (game.max_attempts)
        state, _ = self.after_menu()
        for _ in range(GAME["max_attempts"]["prep"]):
            data = self.send(state, game_tile("pizza", "prep", "under")).get_json()
            state = data["state"]
            if data["stage"]["advanced"]:
                break
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual(state["stage_index"], 2)
        self.assertEqual(state["verdicts"]["prep"]["verdict"], data["verdict"])
        face = data["alien"]["expression"]  # 넘어갈 때도 확신 표정 (화면은 convinced → joy로 바꾼다)
        self.assertIn(face, TURN_EXPRESSIONS)
        self.assertEqual(data["image"], "/" + CONFIG["expressions"][face]["image"])

    def test_full_game_ends_with_dish_image(self):
        from services.image_selector import _url
        state, data = self.start()["state"], None
        for _ in range(4 * max(GAME["max_attempts"].values())):
            data = self.send(state).get_json()
            state = data["state"]
            if state["done"]:
                break
        self.assertTrue(state["done"])
        menu = data["menu"]
        expected = DISHES[menu]["images"]["success" if data["result"]["success"] else "fail"]
        self.assertEqual(data["result"]["image"], _url(expected))
        self.assertEqual(data["image"], _url(expected))
        self.assertEqual(set(data["result"]["verdicts"]), {"prep", "cook", "plating"})
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

    def test_following_the_rules_succeeds_and_blue_pizza_fails(self):
        for plating, success in (("success", True), ("over", False)):
            with self.subTest(plating=plating):
                state, data = self.after_menu()
                for stage in ("prep", "cook", "plating"):
                    verdict = plating if stage == "plating" else "success"
                    for _ in range(GAME["max_attempts"][stage]):
                        data = self.send(state, game_tile("pizza", stage, verdict)).get_json()
                        state = data["state"]
                        if data["stage"]["advanced"]:
                            break
                    self.assertEqual(data["verdict"], verdict)
                self.assertEqual(data["result"]["success"], success)
                self.assertEqual(data["plating"]["abnormal"], not success)
                self.assertEqual(data["result"]["plating"]["abnormal"], not success)


STAGES_ORDER = [s["id"] for s in CONFIG["stages"]]


class RecordDialogueTest(unittest.TestCase):
    """레코드 대사: 타일마다 대사 한 문장, 외계인 대사에만 임베딩으로 고른 그림."""

    def setUp(self):
        self.client = app.test_client()

    def record(self, entries, success=True):
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            return self.client.post("/api/record", json={"dish": "ramen", "entries": entries, "success": success})

    def test_picks_most_similar_image(self):
        from services.image_selector import match_images

        vectors = {"알겠어": [1, 0], "모르겠어": [0, 1], "응…": [0.9, 0.1], "음…": [0.1, 0.9], "끄덕": [0.5, -0.5],
                   "알겠다…?!": [1, 0], "와!": [-1, 0]}
        images = {"convinced": ["끄덕", "응…"], "thinking": ["음…"], "surprised": ["와!"]}
        embed = lambda texts: [vectors[t] for t in texts]
        # 가장 비슷한 예시 하나로 고른다 (convinced의 '끄덕'은 멀어도 '응…'이 가까움)
        self.assertEqual(match_images(["알겠어", "모르겠어"], images, embed), ["convinced", "thinking"])
        # ?!가 있으면 임베딩이 convinced에 가까워도 surprised
        self.assertEqual(match_images(["알겠다…?!"], images, embed), ["surprised"])

    def test_spreads_emotions_without_breaking_punctuation(self):
        from services.image_selector import pick_diverse

        keys = ["default", "doubt", "convinced", "surprised", "thinking", "joy"]
        # 유사도가 doubt 쪽으로 조금만 앞서면 겹침 감점으로 thinking도 섞인다
        similarity = [{k: 0.5 + 0.01 * (k == "doubt") for k in keys} for _ in range(4)]
        picks = pick_diverse(["맞아…?"] * 4, keys, similarity)
        self.assertEqual(set(picks), {"doubt", "thinking"})
        # 키가 없을 때도 같은 표정만 이어지지 않고, ?는 의심·고민 / !는 기쁨·확신·놀람 안에서만 고른다
        self.assertEqual(pick_diverse(["맞아…?", "맞아…?", "알겠다…!", "알겠다…!"], keys),
                         ["doubt", "thinking", "joy", "convinced"])

    def test_without_key_uses_tagged_examples_and_alien_images(self):
        alien = {"who": "alien", "stage": "ingredient", "message": "이거…?", "scores": {a: 0.0 for a in AXES}}
        user = {"who": "user", "stage": "ingredient", "message": "타일", "signal": TILE}
        response = self.record([alien, user, alien])
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["source"], "no_key")
        texts = [l["text"] for l in data["lines"]]
        self.assertEqual(len(set(texts)), 3)
        known = {(l.stage, l.who): set() for l in load_record_lines()}
        for line in load_record_lines():
            known[line.stage, line.who].add(line.text)
        self.assertIn(texts[0], known["ingredient", "alien"])
        self.assertIn(texts[1], known["ingredient", "user"])
        self.assertIsNone(data["lines"][1]["image"])
        for line in (data["lines"][0], data["lines"][2]):
            self.assertTrue((Path("public") / line["image"].lstrip("/")).is_file(), line["image"])

    def test_record_lines_file_uses_known_tags(self):
        lines = load_record_lines()
        emotions = {None, "doubt", "surprised", "thinking", "convinced", "joy"}
        for line in lines:
            with self.subTest(line=line.text):
                self.assertIn(line.stage, STAGES_ORDER)
                self.assertIn(line.who, ("alien", "user"))
                self.assertIn(line.verdict, ("start", "success", "under", "over", "unstable", "method"))
                self.assertIn(line.emotion, emotions)
                self.assertNotIn("지직", line.text)
            if line.misread and line.who == "alien":
                self.assertTrue(any(o.who == "user" and o.stage == line.stage and o.pair == line.pair for o in lines), line.text)
        self.assertGreaterEqual(len(lines), 240)
        self.assertEqual(len({line.text for line in lines}), len(lines))

    def tags_of(self, verdicts):
        """외계인 타일이 verdicts 판정을 받은 대화 (지구인·외계인 번갈아)."""
        tags = []
        for verdict in verdicts:
            base = {"stage": "cook", "verdict": verdict, "fit": 0.5, "misread": False, "meaning": "신호"}
            tags += [{**base, "who": "user", "emotion": None}, {**base, "who": "alien", "emotion": "doubt"}]
        return tags

    def test_tags_rejudge_tiles_and_follow_screen_expressions(self):
        game = CONFIG["game"]
        hot = {**parse_signal(game_tile("ramen", "cook", "over")), "who": "user", "stage": "조리", "message": ""}
        alien = {"who": "alien", "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}}
        first = {"who": "alien", "stage": "재료 준비", "message": "", "scores": {a: 0.0 for a in AXES}}
        tags = record_tags([first, alien, hot, alien], "ramen", CONFIG)
        self.assertEqual([(t["verdict"], t["emotion"]) for t in tags],
                         [("start", "default"), ("start", "default"), ("over", None), ("over", game["verdict_expressions"]["over"])])
        self.assertLess(tags[2]["fit"], 1)
        self.assertEqual(tags[3]["fit"], tags[2]["fit"])
        chosen = record_tags([hot, {**alien, "expression": "convinced"}], "ramen", CONFIG)
        self.assertEqual(chosen[1]["emotion"], "convinced")  # 게임 때 AI가 고른 표정을 쓴다
        self.assertIn("노이즈 낮음", tags[2]["meaning"])

    def test_misread_is_a_stage_that_ended_off_target(self):
        tag = lambda who, stage, verdict: {"who": who, "stage": stage, "verdict": verdict, "misread": False}
        tags = [tag("alien", "ingredient", "start"), tag("user", "ingredient", "success"),
                tag("alien", "prep", "start"), tag("user", "prep", "over"), tag("alien", "prep", "over"), tag("user", "prep", "under"),
                tag("alien", "cook", "start"), tag("user", "cook", "success"),
                tag("alien", "plating", "start"), tag("user", "plating", "over")]
        # 손질은 under로 끝나 바로 뒤 외계인 타일, 마지막 단계는 뒤가 없어 바로 앞 타일. 조리는 맞아서 오해 없음
        spots = pick_misreads(tags)
        self.assertEqual(spots, {6, 8})
        mark_misreads(tags, spots)
        self.assertEqual([i for i, t in enumerate(tags) if t["misread"]], [6, 7, 8, 9])
        self.assertEqual(pick_misreads(self.tags_of(["success"] * 3)), set())

    def test_clean_stages_use_a_mid_stage_slip_as_the_misread(self):
        tag = lambda who, stage, verdict: {"who": who, "stage": stage, "verdict": verdict, "misread": False}
        tags = [tag("alien", "prep", "start"), tag("user", "prep", "over"), tag("alien", "prep", "over"), tag("user", "prep", "success"),
                tag("alien", "cook", "start"), tag("user", "cook", "success")]
        spots = pick_misreads(tags)  # 단계 끝 판정은 모두 success지만 중간에 over였던 순간이 있다
        self.assertEqual(spots, {2})
        mark_misreads(tags, spots)
        self.assertEqual([i for i, t in enumerate(tags) if t["misread"]], [2, 3])  # 다음 타일이 바로잡는다

    def test_game_expression_decides_the_tag_and_picture(self):
        alien = {"who": "alien", "stage": "prep", "message": "", "scores": {a: 0.0 for a in AXES}}
        user = {"who": "user", "stage": "prep", "message": "타일", "signal": game_tile("pizza", "prep", "over")}
        data = self.client.post("/api/record", json={"dish": "pizza", "success": True, "entries": [
            {**alien, "expression": "surprised"}, user, {**alien, "expression": "convinced"}, user, alien]}).get_json()
        pictures = [l["image"] for l in data["lines"]]
        self.assertEqual(pictures[0], "/" + CONFIG["expressions"]["surprised"]["image"])
        self.assertEqual(pictures[2], "/" + CONFIG["expressions"]["convinced"]["image"])
        self.assertTrue(pictures[4])  # 표정이 없으면 지금처럼 대사로 고른다

    def test_bad_expression_is_rejected(self):
        alien = {"who": "alien", "stage": "prep", "message": "", "scores": {a: 0.0 for a in AXES}}
        for bad in ("angry", 3, "_note"):
            with self.subTest(bad=bad):
                self.assertEqual(self.record([{**alien, "expression": bad}]).status_code, 400)

    def test_wrong_method_uses_method_lines_not_degree_lines(self):
        tag = {"stage": "prep", "who": "user", "verdict": "under", "reason": "method", "emotion": None, "misread": False, "meaning": "신호"}
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            pool = DemoRetriever().search_lines([tag])[0]
        self.assertEqual(pool[0].verdict, "method")
        degree = DemoRetriever().search_lines([{**tag, "reason": "size"}])[0]
        self.assertEqual(degree[0].verdict, "under")

    def test_search_prefers_matching_tags_then_relaxes(self):
        tag = {"stage": "cook", "who": "alien", "verdict": "over", "emotion": "surprised", "misread": True, "meaning": "신호"}
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            pool = DemoRetriever().search_lines([tag])[0]
        self.assertTrue(all(l.stage == "cook" and l.who == "alien" for l in pool))
        self.assertEqual({(l.verdict, l.misread) for l in pool[:2]}, {("over", True)})
        self.assertTrue(pool[2].misread)  # 맞는 줄을 다 쓰면 판정 조건부터 풀린다
        self.assertFalse(pool[-1].misread)

    def test_embeddings_order_lines_within_same_tags(self):
        tag = {"stage": "cook", "who": "alien", "verdict": "over", "emotion": "surprised", "misread": False, "meaning": "연기"}
        smoke = "헉…! 연기…! 연기…!"

        class Client:
            def __init__(self, **_):
                self.embeddings = self

            def create(self, model, input):
                data = [[1.0, 0.0] if text in ("연기", smoke) else [0.0, 1.0] for text in input]
                return SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in data])

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", Client):
            self.assertEqual(DemoRetriever().search_lines([tag])[0][0].text, smoke)

    def test_openai_gets_tags_and_duplicates_are_replaced(self):
        calls = []

        class Client:
            def __init__(self, **_):
                self.responses = self

            def create(self, **kwargs):
                calls.append(kwargs)
                texts = ["같은 대사", "같은 대사", "다른 대사"]
                items = [{"tile": i, "who": t["who"], "text": text} for i, (t, text) in enumerate(zip(tags, texts))]
                return SimpleNamespace(status="completed", output_text=json.dumps({"items": items}))

        tags = self.tags_of(["under"])[:2] + [{**self.tags_of(["under"])[0], "misread": True}]
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [load_record_lines()[:9]] * 3
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", Client):
            lines, source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, False, "허세")
        self.assertEqual(source, "openai")
        self.assertEqual(lines[0], "같은 대사")
        self.assertEqual(lines[1], pools[1][0].text)
        self.assertEqual(lines[2], "다른 대사")
        self.assertEqual(len(calls), 1)  # 겹친 줄을 바꿀 때 다시 호출하지 않는다
        self.assertIn("허세", calls[0]["instructions"])
        sent = json.loads(calls[0]["input"])
        tile = sent["tiles"][2]
        self.assertEqual((tile["verdict"], tile["fit"], tile["misread"], tile["meaning"]), ("부족함(덜 됨)", 0.5, True, "신호"))
        self.assertEqual([sent["examples"][i] for i in tile["examples"]], [line.text for line in pools[2][:3]])
        self.assertEqual(len(sent["examples"]), 3)  # 세 타일이 같은 예시를 써도 글은 한 번만 넘긴다

    def test_shifted_openai_lines_fall_back_to_examples(self):
        # 말하는 쪽이 밀린 응답을 그대로 쓰면 외계인 말이 지구인 칸에 들어간다
        tags = self.tags_of(["under"])
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [load_record_lines()[:3]] * 2
        items = [{"tile": 0, "who": "alien", "text": "음…"}, {"tile": 1, "who": "user", "text": "아니야"}]  # 입력은 user, alien

        class Client:
            def __init__(self, **_):
                self.responses = self

            def create(self, **_):
                return SimpleNamespace(status="completed", output_text=json.dumps({"items": items}))

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", Client):
            with self.assertLogs("services.generator", "ERROR"):
                lines, source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, True, "허세")
        self.assertEqual(source, "openai_failed:RuntimeError")
        self.assertEqual(lines, [pools[0][0].text, pools[0][1].text])

    def run_lines(self, tags, texts, fixes=None):
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [[l for l in load_record_lines() if l.stage == "cook" and l.who == t["who"]] for t in tags]
        fixes = fixes or {}
        paired = set(fixes) | {i + 1 for i in fixes}
        items = [{"tile": i, "who": t["who"], "text": "" if i in paired else x} for i, (t, x) in enumerate(zip(tags, texts))]
        written = [{"alien_tile": i, "alien_text": texts[i], "fix_text": fix} for i, fix in fixes.items()]
        calls = []
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", fake_openai({"items": items, "pairs": written}, calls=calls)):
            lines, self.source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, False, "허세")
        return lines, calls[0], pools

    def misread_tags(self):
        tag = lambda who, misread, emotion: {"stage": "cook", "who": who, "verdict": "under", "fit": 0.5, "emotion": emotion, "misread": misread, "meaning": "신호"}
        return [tag("user", False, None), tag("alien", True, "doubt"), tag("user", True, None)]

    def test_misread_and_fix_are_written_as_one_pair(self):
        lines, call, _ = self.run_lines(self.misread_tags(), ["불이 약해", "불 끄고… 불어…?", ""], {1: "입으로 불면 식어"})
        self.assertEqual(lines, ["불이 약해", "불 끄고… 불어…?", "입으로 불면 식어"])
        sent = json.loads(call["input"])
        self.assertEqual((sent["language"], sent["pair_tiles"]), ("한국어", [1]))
        self.assertTrue(sent["tiles"][1]["write_in_pairs"])
        self.assertEqual(sent["tiles"][2]["examples"], [])  # 다른 오해 예시를 넘기지 않는다
        schema = call["text"]["format"]["schema"]["properties"]
        self.assertEqual((schema["items"]["minItems"], schema["pairs"]["minItems"], schema["pairs"]["maxItems"]), (3, 1, 1))
        self.assertLessEqual(call["max_output_tokens"], 2400)
        self.assertTrue(call["instructions"].startswith("모든 대사는 반드시 한국어"))
        self.assertIn("뜨거워…! 이거… 맞아…!", call["instructions"][:120])
        self.assertIn("15자", call["instructions"])
        self.assertIn("25자", call["instructions"])

    def test_empty_fix_replaces_both_lines_with_an_example_pair(self):
        lines, _, _ = self.run_lines(self.misread_tags(), ["불이 약해", "불 끄고… 불어…?", ""], {1: ""})
        by_text = {l.text: l for l in load_record_lines()}
        self.assertEqual(by_text[lines[1]].pair, by_text[lines[2]].pair)
        self.assertTrue(by_text[lines[1]].pair)

    def test_missing_pair_falls_back_to_examples(self):
        tags = self.misread_tags()
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [[l for l in load_record_lines() if l.stage == "cook" and l.who == t["who"]] for t in tags]
        answer = {"items": [{"tile": i, "who": t["who"], "text": "불이 약해"} for i, t in enumerate(tags)], "pairs": []}
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", fake_openai(answer)), self.assertLogs("services.generator", "ERROR"):
            _, source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, False, "허세")
        self.assertEqual(source, "openai_failed:RuntimeError")

    def test_mostly_foreign_answer_is_reported_as_failed(self):
        tags = self.tags_of(["under", "under"])
        self.run_lines(tags, ["火を弱く", "こわい", "皿に", "불… 이거…?"])
        self.assertEqual(self.source, "openai_failed:too_many_replaced")
        self.run_lines(tags, ["불이 약해", "불… 맞아…?", "조금만 더", "皿に"])
        self.assertEqual(self.source, "openai")

    def test_only_the_foreign_line_is_replaced(self):
        for bad in ("공중に 던지지 마", "불을 弱하게 해", "불을 low로 해"):
            with self.subTest(bad=bad):
                tags = self.tags_of(["under"])
                lines, _, pools = self.run_lines(tags, [bad, "이 불… 이거…?"])
                self.assertIn(lines[0], {l.text for l in pools[0]})
                self.assertEqual(lines[1], "이 불… 이거…?")

    def test_question_rule_replaces_only_the_alien_line(self):
        tags = self.tags_of(["under"])
        tags[1]["emotion"] = "thinking"
        lines, _, pools = self.run_lines(tags, ["불이 약해?", "음… 맞아…?"])
        self.assertEqual(lines[0], "불이 약해?")  # 지구인은 물음표 규칙 대상이 아니다
        self.assertNotIn("?", lines[1])
        tags[1]["emotion"] = "doubt"
        self.assertEqual(self.run_lines(tags, ["불이 약해", "음… 맞아…?"])[0][1], "음… 맞아…?")

    def test_replacing_a_misread_line_replaces_its_fix_with_the_pair(self):
        lines, _, pools = self.run_lines(self.misread_tags(), ["불이 약해", "火… 불어…?", ""], {1: "입으로 불면 식어"})  # 외국어가 섞인 짝
        by_text = {l.text: l for l in load_record_lines()}
        self.assertEqual(by_text[lines[1]].pair, by_text[lines[2]].pair)

    def test_openai_failure_falls_back_to_examples(self):
        tags = self.tags_of(["under"])
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [load_record_lines()[:3]] * 2
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", side_effect=RuntimeError):
            with self.assertLogs("services.generator", "ERROR"):
                lines, source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, True, "허세")
        self.assertEqual(source, "openai_failed:RuntimeError")
        self.assertEqual(lines, [pools[0][0].text, pools[0][1].text])

    def test_fixing_line_is_the_pair_of_the_misread_line(self):
        tags = self.tags_of(["under"])[::-1]  # 외계인 → 지구인
        tags[0]["misread"] = tags[1]["misread"] = True
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            pools = DemoRetriever().search_lines(tags)
            lines, _ = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, False, "허세")
        by_text = {l.text: l for l in load_record_lines()}
        self.assertTrue(by_text[lines[0]].pair)
        self.assertEqual(by_text[lines[0]].pair, by_text[lines[1]].pair)

    def test_wrong_count_controls_misreads(self):
        tags = self.tags_of(["success"] * 3)
        for n in (0, 2):
            self.assertEqual(len(pick_misreads(tags, n)), n)

    def test_rejects_bad_entries(self):
        for entries in ([], [{"who": "ghost", "stage": "prep"}], [{"who": "alien", "stage": "prep", "scores": {"wc": 2}}],
                        [{"who": "user", "stage": "nope", "signal": TILE}]):
            with self.subTest(entries=entries):
                self.assertEqual(self.record(entries).status_code, 400)
        alien = {"who": "alien", "stage": "prep", "scores": {a: 0.0 for a in AXES}}
        self.assertEqual(self.record([alien], success="yes").status_code, 400)


if __name__ == "__main__":
    unittest.main()


# ═══════════════════════════════════════════════════════════════
# 5. 요리 게임 규칙 (config.game): 메뉴 결정 · 단계 판정 · 확신 · 결과 확정
# ═══════════════════════════════════════════════════════════════

import colorsys
import copy
import functools
import math

from services.chatbot_service import (
    GAME_RESPONSE_KEYS,
    decide_menu,
    game_metrics,
    consistency,
    hue_zone,
    ingredient_scores,
    judge_menu_result,
    judge_stage,
    menu_scores,
    plating_view,
    read_ingredient,
    stage_signal,
)

GAME = CONFIG["game"]
RULES = {k: v for k, v in GAME["rules"].items() if not k.startswith("_")}


def hsv_color(h, s=0.7, v=0.85):
    """chatbot.js의 hsvToRgb → rgbToLch와 같은 변환 (화면 색 선택기로 고를 수 있는 색)."""
    r, g, b = [x * 255 for x in colorsys.hsv_to_rgb(h / 360, s, v)]
    lin = lambda u: (u / 255) / 12.92 if u / 255 <= 0.04045 else ((u / 255 + 0.055) / 1.055) ** 2.4
    R, G, B = lin(r), lin(g), lin(b)
    X = (0.4124 * R + 0.3576 * G + 0.1805 * B) / 0.95047
    Y = 0.2126 * R + 0.7152 * G + 0.0722 * B
    Z = (0.0193 * R + 0.1192 * G + 0.9505 * B) / 1.08883
    f = lambda t: t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(X), f(Y), f(Z)
    a, bb = 500 * (fx - fy), 200 * (fy - fz)
    return {"L": 116 * fy - 16, "C": math.hypot(a, bb), "h": math.degrees(math.atan2(bb, a)) % 360}


def raw_tile(color, density, size, seed=7):
    """chatbot.js densityToTexture와 같은 질감. size 0~100 = 크기 막대."""
    freq = 0.9 - size / 100 * 0.5
    return {"color": color, "seed": seed,
            "texture": {"oct": 1 + 11 * density, "freq": freq, "pers": 0.4 + 0.4 * density, "lac": 1.8 + 1.4 * density}}


def find_tile(density, size, ok):
    """판정값이 ok(metrics)를 만족하는 타일을 화면에서 고를 수 있는 색 중에서 찾는다."""
    for h in range(0, 360, 3):
        for s_, v in ((0.7, 0.85), (0.4, 0.8), (1, 1), (0.25, 0.6), (0.9, 0.5), (0.9, 0.3), (0.5, 0.2), (0.3, 1), (0.6, 0.65), (0.9, 0.15)):
            tile = raw_tile(hsv_color(h, s_, v), density, size)
            if ok(game_metrics(parse_signal(tile), GAME)):
                return tile
    raise AssertionError("조건에 맞는 타일이 없습니다")


MENU_INGREDIENT = {"pizza": "pepperoni", "hamburger": "patty", "ramen": "noodle", "omurice": "ketchup"}  # 그 메뉴에만 있는 재료


def zone_mid(name):
    lo, hi = GAME["hue_zones"][name]
    return (lo + ((hi - lo) % 360) / 2) % 360


@functools.cache
def game_tile(menu, stage="ingredient", verdict="success"):
    """메뉴 선택 타일, 또는 menu·stage에서 verdict가 나오는 타일."""
    if stage == "ingredient":
        item = next(i for i in GAME["ingredients"] if i["id"] == MENU_INGREDIENT[menu])
        return raw_tile(item["color"], GAME["grain"][item["grain"]]["density"], 50)
    rule = RULES[menu][stage]
    judged = lambda m: judge_stage(stage, m, rule, GAME)
    if stage == "plating":
        return find_tile(0.2, 50, lambda m: judged(m)["verdict"] == verdict)
    limit = rule["max_roughness" if stage == "prep" else "max_noise"]
    density = (limit + 15 if verdict == "unstable" else limit - 20) / 100
    size = 50
    if stage == "prep":
        lo, hi = rule["size"]
        size = {"success": (lo + hi) / 2, "under": lo - 10, "over": hi + 10, "unstable": (lo + hi) / 2}[verdict]
    # 방법(색)은 맞고 정도만 다른 타일을 찾는다
    return find_tile(density, size, lambda m: judged(m)["verdict"] == verdict and judged(m)["reason"] != "method")


def metrics_for(menu, stage, verdict):
    """기준표에서 바로 만든 판정값 (색 변환 없이 규칙만 확인)."""
    rule = RULES[menu][stage]
    m = {"size": 50.0, "roughness": 0.0, "heat": 50.0, "noise": 0.0, "power": 50.0, "sat": 70.0, "hue": 0.0}
    if stage == "plating":
        half = GAME["plating"]["judge_range"]
        m["hue"] = (rule["center"] + {"success": 0, "under": -half - 1, "over": half + 1, "unstable": 0}[verdict]) % 360
        m["roughness"] = rule["max_roughness"] + (1 if verdict == "unstable" else 0)
        return m
    m["hue"] = zone_mid(rule["hues"][0])
    key = "size" if stage == "prep" else "power"
    lo, hi = rule[key]
    m[key] = {"success": (lo + hi) / 2, "under": lo - 1, "over": hi + 1, "unstable": (lo + hi) / 2}[verdict]
    limit = "roughness" if stage == "prep" else "noise"
    m[limit] = rule[f"max_{limit}"] + (1 if verdict == "unstable" else 0)
    return m


class MenuTest(unittest.TestCase):
    def test_four_menu_branches(self):
        for warm, high, menu in ((True, True, "pizza"), (False, True, "hamburger"), (False, False, "ramen"), (True, False, "omurice")):
            with self.subTest(menu=menu):
                heat = GAME["menu"]["warm_min"] + (5 if warm else -5)
                noise = GAME["menu"]["noise_min"] + (5 if high else -5)
                self.assertEqual(decide_menu({"heat": heat, "noise": noise}, GAME), menu)

    def test_menu_boundaries_are_inclusive(self):
        rule = GAME["menu"]
        self.assertEqual(decide_menu({"heat": rule["warm_min"], "noise": rule["noise_min"]}, GAME), "pizza")
        self.assertEqual(decide_menu({"heat": rule["warm_min"] - 0.01, "noise": rule["noise_min"] - 0.01}, GAME), "ramen")

    def test_menu_from_real_tiles(self):
        client = app.test_client()
        for menu in RULES:
            with self.subTest(menu=menu):
                state = client.post("/api/start", json={}).get_json()["state"]
                for _ in range(GAME["max_attempts"]["ingredient"]):
                    data = client.post("/api/chat", json={"message": "타일", "signal": game_tile(menu), "state": state}).get_json()
                    state = data["state"]
                    if data["stage"]["advanced"]:
                        break
                self.assertEqual((data["menu"], data["state"]["menu"], data["dish"]["id"]), (menu, menu, menu))


class IngredientTest(unittest.TestCase):
    def test_every_ingredient_is_read_back_from_its_own_tile(self):
        for item in GAME["ingredients"]:
            with self.subTest(item=item["name"]):
                tile = parse_signal(raw_tile(item["color"], GAME["grain"][item["grain"]]["density"], 50))
                self.assertEqual(read_ingredient(tile, GAME)["id"], item["id"])

    def test_menu_lists_match_the_request(self):
        lists = {"pizza": "반죽,토마토소스,모차렐라,페퍼로니,버섯,바질,반죽 물", "hamburger": "번,패티,체더치즈,양상추,토마토,소스,패티 반죽 물",
                 "ramen": "면,육수,차슈,달걀,대파,김", "omurice": "달걀,밥,양파,당근,완두콩,케첩,밥 물,쌀뜨물"}
        for menu, names in lists.items():
            with self.subTest(menu=menu):
                self.assertEqual({i["name"] for i in GAME["ingredients"] if menu in i["menus"]}, set(names.split(",")))

    def test_blue_means_water_for_every_menu_but_indigo_is_ramen_only(self):
        zone_menus = lambda zone: {menu for i in GAME["ingredients"] if i["zone"] == zone for menu in i["menus"]}
        self.assertEqual(zone_menus("blue"), set(RULES))
        self.assertEqual(zone_menus("indigo"), {"ramen"})

    def test_every_zone_and_grain_reads_some_ingredient(self):
        for h in range(0, 360, 10):
            for density in (0.1, 0.5, 0.9):
                self.assertIsNotNone(read_ingredient(parse_signal(raw_tile(hsv_color(h), density, 50)), GAME))

    def test_rough_and_smooth_split_the_same_zone(self):
        red = hsv_color(zone_mid("red"))
        names = [read_ingredient(parse_signal(raw_tile(red, density, 50)), GAME)["name"] for density in (0.1, 0.5, 0.9)]
        self.assertEqual(names, ["차슈", "페퍼로니", "패티"])

    def test_gray_tile_means_no_ingredient(self):
        self.assertIsNone(read_ingredient(parse_signal(raw_tile(hsv_color(0, 0.05, 0.6), 0.5, 50)), GAME))

    def test_candidates_follow_ingredients_and_warmth_is_only_a_helper(self):
        signal = {"heat": 80, "noise": 80}  # 기존 매핑은 피자
        self.assertEqual(max(menu_scores(["noodle", "broth"], signal, GAME).items(), key=lambda s: s[1])[0], "ramen")
        scores = menu_scores([], signal, GAME)
        self.assertEqual(scores["pizza"], GAME["ingredient_rule"]["aux"])

    def test_menu_can_change_during_the_conversation(self):
        signal = {"heat": 50, "noise": 50}
        first = menu_scores(["ketchup"], signal, GAME)
        later = menu_scores(["ketchup", "noodle", "broth", "nori"], signal, GAME)
        self.assertEqual(max(first, key=first.get), "omurice")
        self.assertEqual(max(later, key=later.get), "ramen")

    def test_stage_can_continue_and_keeps_menu_hidden_until_confirmed(self):
        config = copy.deepcopy(CONFIG)
        config["game"]["confidence"]["thresholds"] = [1.01]
        service = ChatbotService()
        state = service.start(config, "ramen")["state"]
        data = service.play_turn("", "헤슬", config, parse_signal(game_tile("pizza")), state)
        self.assertTrue(data["retry"])
        self.assertIsNone(data["menu"])  # 화면이 menu로 1단계 칸을 칠한다
        self.assertEqual(data["ingredient"], "페퍼로니")
        self.assertEqual(data["ingredients"], ["페퍼로니"])
        self.assertEqual(max(data["menu_scores"], key=data["menu_scores"].get), "pizza")
        self.assertEqual(data["state"]["ingredients"], ["pepperoni"])
        self.assertEqual(data["state"]["stage_index"], 0)

    def test_one_clear_tile_can_finish_the_stage(self):
        service = ChatbotService()
        state = service.start(CONFIG, "ramen")["state"]
        data = service.play_turn("", "헤슬", CONFIG, parse_signal(game_tile("ramen")), state)
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual(data["menu"], "ramen")

    def test_alien_answers_with_the_representative_ingredient(self):
        scores = ingredient_scores(["noodle", "pepperoni", "pepperoni"], "pizza", GAME)
        item = next(i for i in GAME["ingredients"] if i["id"] == "pepperoni")
        density = GAME["grain"][item["grain"]]["density"]
        tile = parse_signal(raw_tile(item["color"], density, 50))
        self.assertAlmostEqual(scores["wc"], tile["scores"]["wc"], places=2)
        self.assertIsNone(ingredient_scores([], "pizza", GAME))

    def test_bad_ingredients_are_rejected(self):
        client = app.test_client()
        state = client.post("/api/start", json={}).get_json()["state"]
        for bad in ("밥", ["kimchi"], ["rice"] * 99):
            with self.subTest(bad=str(bad)[:20]):
                r = client.post("/api/chat", json={"message": "타일", "signal": game_tile("pizza"), "state": {**state, "ingredients": bad}})
                self.assertEqual(r.get_json()["error"]["code"], "invalid_state")

    def test_record_meaning_names_the_ingredient(self):
        entry = {**parse_signal(game_tile("ramen")), "who": "user", "stage": "재료 준비", "message": ""}
        self.assertIn("재료: 면", record_tags([entry], "ramen", CONFIG)[0]["meaning"])


class JudgeTest(unittest.TestCase):
    def test_each_dish_stage_and_verdict(self):
        for menu in RULES:
            for stage in ("prep", "cook", "plating"):
                for verdict in ("success", "under", "over", "unstable"):
                    with self.subTest(menu=menu, stage=stage, verdict=verdict):
                        out = judge_stage(stage, metrics_for(menu, stage, verdict), RULES[menu][stage], GAME)
                        self.assertEqual(out["verdict"], verdict)
                        if stage == "plating":
                            self.assertEqual(out["abnormal"], verdict != "success")
                        if verdict == "success":
                            self.assertEqual(out["closeness"], 1.0)
                        else:
                            self.assertLess(out["closeness"], 1.0)

    def test_unstable_wins_over_range(self):
        m = metrics_for("pizza", "prep", "under")
        m["roughness"] = 99
        self.assertEqual(judge_stage("prep", m, RULES["pizza"]["prep"], GAME)["verdict"], "unstable")

    def test_pizza_hue_boundaries(self):
        rule = RULES["pizza"]["plating"]
        center = rule["center"]
        expected = {(center - 41) % 360: "under", (center - 40) % 360: "success", center: "success", center + 40: "success", center + 41: "over"}
        for hue, verdict in expected.items():
            with self.subTest(hue=hue):
                out = judge_stage("plating", {**metrics_for("pizza", "plating", "success"), "hue": hue}, rule, GAME)
                self.assertEqual(out["verdict"], verdict)
                self.assertEqual(out["abnormal"], verdict != "success")

    def test_fit_falls_smoothly_outside_the_range(self):
        rule = RULES["pizza"]["prep"]
        lo = rule["size"][0]
        base = metrics_for("pizza", "prep", "success")
        fits = [judge_stage("prep", {**base, "size": lo - gap}, rule, GAME)["closeness"] for gap in range(0, 41, 5)]
        self.assertEqual(fits[0], 1.0)
        self.assertEqual(fits, sorted(fits, reverse=True))
        self.assertGreater(fits[1], 0.9)  # 조금 벗어났다고 크게 떨어지지 않는다
        self.assertEqual(fits[-1], 0)
        self.assertLess(max(a - b for a, b in zip(fits, fits[1:])), 0.25)

    def test_wrong_method_is_reported_and_gray_has_no_method(self):
        rule = RULES["pizza"]["prep"]
        wrong = {**metrics_for("pizza", "prep", "success"), "hue": zone_mid("red")}
        out = judge_stage("prep", wrong, rule, GAME)
        self.assertNotEqual(out["verdict"], "success")
        self.assertEqual(out["reason"], "method")
        gray = judge_stage("prep", {**wrong, "sat": GAME["gray_sat"] - 1}, rule, GAME)
        self.assertEqual((gray["reason"], gray["closeness"]), ("method", 0.5))

    def test_hue_zones_cover_the_wheel_without_gaps(self):
        names = [hue_zone(h, GAME) for h in range(360)]
        self.assertEqual(set(names), {k for k in GAME["hue_zones"] if not k.startswith("_")})

    def test_every_zone_is_right_for_some_dish(self):
        for stage in ("prep", "cook"):
            with self.subTest(stage=stage):
                used = {zone for rules in RULES.values() for zone in rules[stage]["hues"]}
                self.assertEqual(used, {k for k in GAME["hue_zones"] if not k.startswith("_")})

    def test_default_density_is_not_a_structural_failure(self):
        for menu in RULES:
            for stage, key in (("prep", "roughness"), ("cook", "noise")):
                with self.subTest(menu=menu, stage=stage):
                    m = {**metrics_for(menu, stage, "success"), key: 50.0}
                    self.assertEqual(judge_stage(stage, m, RULES[menu][stage], GAME)["closeness"], 1.0)

    def test_same_metrics_always_give_the_same_judgement(self):
        m = metrics_for("ramen", "cook", "over")
        self.assertEqual(judge_stage("cook", m, RULES["ramen"]["cook"], GAME), judge_stage("cook", dict(m), RULES["ramen"]["cook"], GAME))

    def test_plating_shift_inside_soft_and_outside(self):
        center = RULES["ramen"]["plating"]["center"]
        half, soft = GAME["plating"]["tint_range"], GAME["plating"]["soft"]
        shift = lambda off: plating_view("ramen", (center + off) % 360, "success", GAME)["hue_shift"]
        self.assertEqual(shift(half), 0)  # 안이면 원래 색 그대로
        self.assertEqual(shift(half + 10), 10)  # 바로 밖은 살짝
        self.assertEqual(shift(-half - 10), -10)
        self.assertEqual(shift(half + soft + 1), half + soft + 1)  # 더 밖은 이상한 색

    def test_judging_and_tint_use_separate_ranges(self):
        rule = RULES["ramen"]["plating"]
        hue = (rule["center"] + 50) % 360  # 판정 범위 밖, 색 입히기 범위 안
        verdict = judge_stage("plating", {**metrics_for("ramen", "plating", "success"), "hue": hue}, rule, GAME)["verdict"]
        self.assertEqual(verdict, "over")
        self.assertEqual(plating_view("ramen", hue, verdict, GAME)["hue_shift"], 0)

    def test_success_rule_candidates(self):
        good = {"verdict": "success", "metrics": metrics_for("pizza", "prep", "success")}
        cook = {"verdict": "success", "metrics": metrics_for("pizza", "cook", "success")}
        bad_plate = {"verdict": "over", "metrics": {**metrics_for("pizza", "plating", "success"), "hue": 180.0}}
        verdicts = {"prep": good, "cook": cook, "plating": bad_plate}
        rule = lambda use: {**GAME, "success": {**GAME["success"], "use": use}}
        result = lambda use: judge_menu_result("pizza", verdicts, rule(use), DISHES)["success"]
        self.assertTrue(result("A"))  # 평균 적합도 0.67
        self.assertTrue(result("B"))  # 3단계 중 2개 성공
        self.assertFalse(result("C"))  # 플레이팅이 어긋남

    def test_real_tiles_get_expected_verdicts(self):
        for menu in RULES:
            for stage in ("prep", "cook"):
                for verdict in ("success", "under", "over", "unstable"):
                    with self.subTest(menu=menu, stage=stage, verdict=verdict):
                        m = game_metrics(parse_signal(game_tile(menu, stage, verdict)), GAME)
                        self.assertEqual(judge_stage(stage, m, RULES[menu][stage], GAME)["verdict"], verdict)

    def test_metrics_follow_bars(self):
        small = game_metrics(parse_signal(raw_tile(hsv_color(0), 0.0, 0)), GAME)
        big = game_metrics(parse_signal(raw_tile(hsv_color(210), 1.0, 100)), GAME)
        self.assertEqual((small["size"], small["roughness"], small["noise"]), (0, 0, 0))
        self.assertEqual((big["size"], big["roughness"], big["noise"]), (100, 100, 100))
        self.assertGreater(small["heat"], big["heat"])  # 빨강이 파랑보다 따뜻하다 (R4)
        self.assertAlmostEqual(small["hue"], 0, delta=0.5)
        self.assertAlmostEqual(big["hue"], 210, delta=0.5)


class GameFlowTest(unittest.TestCase):
    def play(self, game_changes, menu="pizza", stage_tiles=None):
        config = copy.deepcopy(CONFIG)
        config["game"].update(game_changes)
        service = ChatbotService()
        state = service.start(config, "ramen")["state"]
        confident = {**config, "game": {**config["game"], "confidence": {**config["game"]["confidence"], "thresholds": [0]}}}
        data = service.play_turn("", "헤슬", confident, parse_signal(game_tile(menu)), state)  # 재료 선정은 바로 넘긴다
        return service, config, data

    NEVER = {**GAME["confidence"], "thresholds": [1.01]}  # 절대 확신하지 않음 → 최대 시도에서 확정

    def test_retry_until_max_attempts_then_finalize(self):
        service, config, data = self.play({"confidence": self.NEVER})
        tile = parse_signal(game_tile("pizza", "prep", "under"))
        max_attempts = GAME["max_attempts"]["prep"]
        self.assertEqual(max_attempts, 10)
        for attempt in range(1, max_attempts + 1):
            data = service.play_turn("", "헤슬", config, tile, data["state"])
            last = attempt == max_attempts
            self.assertEqual(data["retry"], not last)
            self.assertEqual(data["attempts_left"], max_attempts - attempt)
            self.assertEqual(data["stage"]["advanced"], last)
        self.assertEqual(data["stage"]["reason"], "max_reached")
        self.assertEqual(data["state"]["verdicts"]["prep"]["verdict"], "under")  # 최대 시도여도 자동 성공 아님
        self.assertEqual(data["state"]["stage_index"], 2)

    def test_signal_accumulates_with_weight_on_new_tile(self):
        service, config, data = self.play({"confidence": self.NEVER})
        under, over = parse_signal(game_tile("pizza", "prep", "under")), parse_signal(game_tile("pizza", "prep", "over"))
        data = service.play_turn("", "헤슬", config, under, data["state"])
        data = service.play_turn("", "헤슬", config, over, data["state"])
        low, high = (game_metrics(t, GAME)["size"] for t in (under, over))
        new = GAME["understanding"]["new"]
        self.assertAlmostEqual(data["metrics"]["size"], (1 - new) * low + new * high, places=1)

    def test_hue_accumulates_on_the_circle(self):
        base = metrics_for("pizza", "plating", "success")
        signal = stage_signal([{**base, "hue": 350.0}, {**base, "hue": 10.0}], GAME)
        self.assertLess(abs((signal["hue"] + 180) % 360 - 180), 10)  # 180 근처로 가지 않는다

    def test_consistency_rewards_correcting_and_falls_when_understanding_shakes(self):
        rule = RULES["pizza"]["prep"]
        good, bad = metrics_for("pizza", "prep", "success"), {**metrics_for("pizza", "prep", "success"), "size": 100.0, "hue": zone_mid("red")}
        self.assertEqual(consistency("prep", [good], rule, GAME), 1)
        self.assertEqual(consistency("prep", [good, good], rule, GAME), 1)
        self.assertEqual(consistency("prep", [bad, good], rule, GAME), 1)  # 고쳐 보내면 손해 보지 않는다
        self.assertLess(consistency("prep", [good, bad], rule, GAME), 1)  # 맞다가 멀어지면 깎인다

    def test_correcting_a_wrong_tile_raises_rule_confidence(self):
        service, config, data = self.play({"confidence": self.NEVER})
        wrong = parse_signal(raw_tile(hsv_color(zone_mid("red")), 0.3, 50))
        right = parse_signal(game_tile("pizza", "prep", "success"))
        first = service.play_turn("", "헤슬", config, wrong, data["state"])
        second = service.play_turn("", "헤슬", config, right, first["state"])
        self.assertGreater(second["confidence"], first["confidence"])
        self.assertEqual(second["understanding"]["consistency"], 1)

    def test_confidence_is_fit_times_consistency_without_random(self):
        conf = {**self.NEVER, "memory": 0}
        service, config, data = self.play({"confidence": conf})
        for verdict in ("success", "over"):
            tile = parse_signal(game_tile("pizza", "prep", verdict))
            out = service.play_turn("", "헤슬", config, tile, data["state"])
            closeness = judge_stage("prep", game_metrics(tile, GAME), RULES["pizza"]["prep"], GAME)["closeness"]
            self.assertAlmostEqual(out["confidence"], closeness, places=3)
            other = service.play_turn("", "헤슬", config, {**tile, "seed": 999}, data["state"])
            self.assertEqual(out["confidence"], other["confidence"])  # 그림용 seed는 판단에 안 쓴다

    def test_alien_tile_shows_the_accumulated_understanding(self):
        service, config, data = self.play({"confidence": self.NEVER})
        tile = parse_signal(game_tile("pizza", "prep", "under"))
        data = service.play_turn("", "헤슬", config, tile, data["state"])
        for axis in AXES:
            self.assertAlmostEqual(data["alien"]["scores"][axis], tile["scores"][axis], places=2)

    def test_same_tile_can_be_judged_differently_after_other_tiles(self):
        service, config, data = self.play({"confidence": self.NEVER})
        start = data["state"]
        tile = parse_signal(game_tile("pizza", "prep", "success"))
        alone = service.play_turn("", "헤슬", config, tile, start)
        before = service.play_turn("", "헤슬", config, parse_signal(game_tile("pizza", "prep", "over")), start)
        after = service.play_turn("", "헤슬", config, tile, before["state"])
        self.assertNotEqual(alone["confidence"], after["confidence"])

    def test_stops_within_the_threshold_steps_even_when_unsure(self):
        service, config, data = self.play({})
        tile = parse_signal(game_tile("pizza", "prep", "under"))
        for attempt in range(1, len(GAME["confidence"]["thresholds"]) + 1):
            data = service.play_turn("", "헤슬", config, tile, data["state"])
            if data["stage"]["advanced"]:
                break
        self.assertTrue(data["stage"]["advanced"])


def fake_openai(answer=None, error=None, calls=None):
    """responses.create만 흉내 내는 OpenAI. answer는 그대로 output_text가 되고, error가 있으면 그 오류를 낸다."""
    class Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.responses = self

        def create(self, **kwargs):
            if calls is not None:
                calls.append({**kwargs, "client": self.kwargs})
            if error:
                raise error
            return SimpleNamespace(status="completed", output_text=answer if isinstance(answer, str) else json.dumps(answer))
    return Client


class DecideTurnTest(unittest.TestCase):
    """AI 경로. OpenAI는 전부 mock이다."""
    STAY = {"confidence": 0.2, "advance": False, "action": "외계인이 재료를 다시 살핍니다."}
    GO = {"confidence": 0.9, "advance": True, "action": "외계인이 자신만만하게 칼을 듭니다."}

    def setUp(self):
        self.service = ChatbotService()
        confident = copy.deepcopy(CONFIG)
        confident["game"]["llm_decide"] = False
        confident["game"]["confidence"]["thresholds"] = [0]
        self.state = self.service.play_turn("", "헤슬", confident, parse_signal(game_tile("pizza")),
                                            self.service.start(CONFIG, "pizza")["state"])["state"]

    def turn(self, tile, answer=None, error=None, config=CONFIG, state=None, calls=None):
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", fake_openai(answer, error, calls)):
            return self.service.play_turn("", "헤슬", config, parse_signal(tile), state or self.state)

    def test_ai_stops_the_stage_even_when_the_rule_would_not(self):
        data = self.turn(game_tile("pizza", "prep", "over"), self.GO)
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual((data["decision_source"], data["confidence"], data["reply"]), ("openai", 0.9, self.GO["action"]))
        # 자신만만하게 넘어가도 단계 결과는 쌓인 신호를 규칙으로 판정한다
        self.assertEqual(data["state"]["verdicts"]["prep"]["verdict"], "over")

    def test_ai_keeps_asking_even_when_the_rule_would_stop(self):
        data = self.turn(game_tile("pizza", "prep", "success"), self.STAY)
        self.assertFalse(data["stage"]["advanced"])
        self.assertTrue(data["retry"])
        self.assertEqual(data["state"]["exchange_count"], 1)
        self.assertEqual(data["state"]["confidence"], 0.2)

    def test_format_errors_fall_back_to_rule(self):
        for bad in ("JSON 아님", {"advance": True}, {**self.GO, "confidence": 2}, {**self.GO, "confidence": True}, {**self.GO, "advance": "yes"}):
            with self.subTest(bad=str(bad)[:30]), self.assertLogs("services.generator", "ERROR"):
                self.assertEqual(self.turn(game_tile("pizza", "prep", "over"), bad)["decision_source"], "rule")

    def test_timeout_falls_back_to_rule(self):
        with self.assertLogs("services.generator", "ERROR"):
            data = self.turn(game_tile("pizza", "prep", "over"), error=TimeoutError())
        self.assertEqual(data["decision_source"], "rule")
        self.assertIsInstance(data["reply"], str)

    def test_no_key_or_switch_off_uses_rule_without_calling(self):
        calls = []
        off = copy.deepcopy(CONFIG)
        off["game"]["llm_decide"] = False
        self.assertEqual(self.turn(game_tile("pizza", "prep"), self.GO, config=off, calls=calls)["decision_source"], "rule")
        self.assertEqual(self.service.play_turn("", "헤슬", CONFIG, parse_signal(game_tile("pizza", "prep")), self.state)["decision_source"], "rule")
        self.assertEqual(calls, [])

    def test_tenth_tile_asks_for_a_final_judgement_and_moves_on(self):
        calls = []
        state = self.state
        for _ in range(GAME["max_attempts"]["prep"]):
            data = self.turn(game_tile("pizza", "prep", "under"), self.STAY, state=state, calls=calls)
            state = data["state"]
        self.assertTrue(json.loads(calls[-1]["input"])["final"])
        self.assertFalse(json.loads(calls[0]["input"])["final"])
        self.assertEqual((data["stage"]["advanced"], data["stage"]["reason"]), (True, "max_reached"))
        self.assertEqual(state["verdicts"]["prep"]["verdict"], "under")  # 자동 성공 아님

    def test_expression_follows_the_ai_confidence(self):
        # 같은 타일(쌓인 신호 변화 없음): 확신이 오르면 convinced, 내리면 thinking, 그대로면 doubt
        tile, state, faces = game_tile("pizza", "prep", "over"), self.state, []
        for confidence in (0.2, 0.05, 0.05):
            data = self.turn(tile, {**self.STAY, "confidence": confidence}, state=state)
            state = data["state"]
            faces.append(data["alien"]["expression"])
        self.assertEqual(faces, ["convinced", "thinking", "doubt"])
        self.assertEqual(state["last_expression"], "doubt")

    def test_turn_expression_rule(self):
        self.assertEqual(turn_expression(None, 0.5, 0, None, GAME), "convinced")  # 첫 타일은 neutral과 비교
        self.assertEqual(turn_expression(0.5, 0.5, 0, None, GAME), "doubt")
        self.assertEqual(turn_expression(0.5, 0.2, 0, None, GAME), "thinking")
        self.assertEqual(turn_expression(0.5, 0.5, 0.5, None, GAME), "surprised")
        self.assertEqual(turn_expression(0.5, 0.5, 0.5, "surprised", GAME), "doubt")  # 직전 표정은 연달아 안 나옴

    def test_blank_action_uses_prepared_text(self):
        data = self.turn(game_tile("pizza", "prep", "over"), {**self.STAY, "action": "  "})
        self.assertEqual(data["decision_source"], "openai")
        self.assertTrue(data["reply"])

    def test_call_stays_within_limits_and_gets_the_understanding(self):
        calls = []
        data = self.turn(game_tile("pizza", "prep", "over"), self.STAY, calls=calls)
        data = self.turn(game_tile("pizza", "prep", "success"), self.STAY, state=data["state"], calls=calls)
        call = calls[-1]
        self.assertEqual(call["client"], {"timeout": 8.0, "max_retries": 0})
        self.assertLessEqual(call["max_output_tokens"], 200)
        self.assertEqual(set(call["text"]["format"]["schema"]["properties"]), {"confidence", "advance", "action"})
        view = json.loads(call["input"])
        self.assertEqual((view["attempt"], view["attempts_left"], view["previous_confidence"]), (2, 8, 0.2))
        self.assertLess(view["patience"], 1)
        self.assertEqual(set(view["understanding"]), {"signal", "hue_zone", "fit", "verdict", "reason", "consistency", "change"})
        self.assertGreater(view["understanding"]["change"], 0)
        self.assertEqual(view["tiles_seen"], 2)
        self.assertIsInstance(view["rule_confidence"], float)
        self.assertIsInstance(view["understanding"]["consistency"], float)
        self.assertEqual(json.loads(calls[0]["input"])["understanding"]["consistency"], "비교 불가")  # 한 장은 안정됐다는 뜻이 아니다
        self.assertIn("0.4 미만이면 거의 항상 더 묻는다", call["instructions"])
        self.assertIn("pizza · prep", call["instructions"])  # 검색 자료
        self.assertIn("6번째부터는 웬만하면 결정한다", call["instructions"])
        self.assertIn("첫 타일이어도 넘어간다", call["instructions"])

    def wrong_tile(self):
        tile = raw_tile(hsv_color(zone_mid("red")), 0.3, 50)  # 피자 손질 정답(초·남)에서 먼 색
        self.assertLess(judge_stage("prep", game_metrics(parse_signal(tile), GAME), RULES["pizza"]["prep"], GAME)["closeness"], 0.3)
        return tile

    def test_overconfident_advance_is_counted_and_then_capped(self):
        data = self.turn(self.wrong_tile(), self.GO)
        self.assertEqual((data["decision_source"], data["state"]["overconfident_advances"]), ("openai", 1))
        self.assertTrue(data["stage"]["advanced"])
        capped = {**self.state, "overconfident_advances": GAME["overconfident"]["max_per_game"]}
        data = self.turn(self.wrong_tile(), self.GO, state=capped)
        self.assertEqual(data["decision_source"], "openai_capped")
        self.assertFalse(data["stage"]["advanced"])
        self.assertTrue(data["retry"])
        self.assertEqual(data["state"]["overconfident_advances"], GAME["overconfident"]["max_per_game"])

    def test_good_tiles_and_staying_do_not_count_as_overconfident(self):
        self.assertEqual(self.turn(game_tile("pizza", "prep", "success"), self.GO)["state"]["overconfident_advances"], 0)
        self.assertEqual(self.turn(self.wrong_tile(), self.STAY)["state"]["overconfident_advances"], 0)

    def test_tenth_tile_moves_on_even_when_the_cap_is_used_up(self):
        state = {**self.state, "overconfident_advances": GAME["overconfident"]["max_per_game"],
                 "exchange_count": GAME["max_attempts"]["prep"] - 1}
        data = self.turn(self.wrong_tile(), self.GO, state=state)
        self.assertTrue(data["stage"]["advanced"])
        self.assertEqual(data["decision_source"], "openai")

    def test_bad_overconfident_count_is_rejected(self):
        client = app.test_client()
        state = client.post("/api/start", json={}).get_json()["state"]
        for bad in (-1, 99, True, "1"):
            with self.subTest(bad=bad):
                r = client.post("/api/chat", json={"message": "타일", "signal": game_tile("pizza"),
                                                   "state": {**state, "overconfident_advances": bad}})
                self.assertEqual(r.get_json()["error"]["code"], "invalid_state")
        for bad in ("joy", 1, ""):
            with self.subTest(last_expression=bad):
                r = client.post("/api/chat", json={"message": "타일", "signal": game_tile("pizza"),
                                                   "state": {**state, "last_expression": bad}})
                self.assertEqual(r.get_json()["error"]["code"], "invalid_state")

    def test_ingredient_stage_asks_ai_with_candidates(self):
        calls = []
        state = self.service.start(CONFIG, "pizza")["state"]
        data = self.turn(game_tile("ramen"), self.STAY, state=state, calls=calls)
        view = json.loads(calls[0]["input"])
        self.assertEqual((view["ingredient"], view["ingredients"]), ("면", ["면"]))
        self.assertEqual(max(view["menu_scores"], key=view["menu_scores"].get), "ramen")
        self.assertIsNone(data["menu"])
        data = self.turn(game_tile("ramen"), self.GO, state=data["state"])
        self.assertEqual((data["menu"], data["state"]["stage_index"]), ("ramen", 1))


class RecordCallsTest(unittest.TestCase):
    """키가 있으면 대사(responses)와 임베딩이 실제로 불리는지. OpenAI는 mock."""

    def test_lines_and_embeddings_are_called_with_a_key(self):
        alien = {"who": "alien", "stage": "prep", "message": "", "scores": {a: 0.0 for a in AXES}}
        user = {"who": "user", "stage": "prep", "message": "타일", "signal": game_tile("pizza", "prep")}
        calls = {"lines": 0, "embed": 0}

        class Client:
            def __init__(self, **_):
                self.responses = self.embeddings = self

            def create(self, **kwargs):
                if "input" in kwargs and isinstance(kwargs["input"], list):
                    calls["embed"] += 1
                    return SimpleNamespace(data=[SimpleNamespace(embedding=[1.0, 0.5]) for _ in kwargs["input"]])
                calls["lines"] += 1
                who = [t["who"] for t in json.loads(kwargs["input"])["tiles"]]
                items = [{"tile": i, "who": w, "text": f"대사 {i}…"} for i, w in enumerate(who)]
                return SimpleNamespace(status="completed", output_text=json.dumps({"items": items}))

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", Client):
            data = app.test_client().post("/api/record", json={"dish": "pizza", "success": True, "entries": [alien, user, alien]}).get_json()
        self.assertEqual((data["source"], data["image_source"]), ("openai", "openai"))
        self.assertEqual(calls["lines"], 1)
        self.assertEqual(calls["embed"], 2)  # 예시 검색 + 대사 그림

    def test_long_record_sends_only_recent_tiles_to_gpt(self):
        tags = [{"stage": "cook", "who": w, "verdict": "under", "fit": 0.5, "emotion": None, "misread": False, "meaning": "신호"}
                for _ in range(40) for w in ("user", "alien")]
        entries = [{"who": t["who"], "stage": "조리", "message": "", "scores": {a: 0.0 for a in AXES}} for t in tags]
        pools = [load_record_lines()] * len(tags)
        seen = {}

        class Client:
            def __init__(self, **_):
                self.responses = self

            def create(self, **kwargs):
                tiles = json.loads(kwargs["input"])["tiles"]
                seen["tiles"] = len(tiles)
                items = [{"tile": t["tile"], "who": t["who"], "text": f"새 대사 {t['tile']}"} for t in tiles]
                return SimpleNamespace(status="completed", output_text=json.dumps({"items": items}))

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test"}), patch("openai.OpenAI", Client):
            lines, source = DemoGenerator().record_lines(entries, tags, pools, {"name": "라멘"}, True, "허세")
        self.assertEqual((source, seen["tiles"], len(lines)), ("openai", 48, 80))
        self.assertTrue(lines[-1].startswith("새 대사"))
        self.assertFalse(lines[0].startswith("새 대사"))


class CallLimitTest(unittest.TestCase):
    """호출 횟수 제한. 넘으면 오류 없이 규칙 대체. OpenAI는 mock."""
    ANSWER = {"confidence": 0.2, "advance": False, "action": "외계인이 재료를 살핍니다."}

    def setUp(self):
        import app as app_module
        self.app_module = app_module
        app_module.ip_calls.clear()
        app_module.daily_calls.update(day="", count=0)
        self.addCleanup(app_module.ip_calls.clear)
        self.client = app.test_client()
        self.state = self.client.post("/api/start", json={"dish": "pizza"}).get_json()["state"]

    def chat(self, ip="1.1.1.1", calls=None):
        return self.client.post("/api/chat", headers={"X-Forwarded-For": ip},
                                json={"message": "타일", "signal": game_tile("ramen"), "state": self.state})

    def run_chats(self, env, ips):
        calls = []
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test", **env}), patch("openai.OpenAI", fake_openai(self.ANSWER, calls=calls)):
            out = [self.chat(ip) for ip in ips]
        return [r.get_json()["decision_source"] for r in out], [r.status_code for r in out], calls

    def test_per_ip_limit_falls_back_without_error(self):
        sources, codes, calls = self.run_chats({"LLM_PER_IP_PER_10MIN": "2"}, ["1.1.1.1"] * 3)
        self.assertEqual(sources, ["openai", "openai", "rule_limited"])
        self.assertEqual(codes, [200, 200, 200])
        self.assertEqual(len(calls), 2)

    def test_each_ip_has_its_own_limit(self):
        sources, _, _ = self.run_chats({"LLM_PER_IP_PER_10MIN": "1"}, ["1.1.1.1", "2.2.2.2", "1.1.1.1"])
        self.assertEqual(sources, ["openai", "openai", "rule_limited"])

    def test_daily_limit_covers_everyone(self):
        sources, _, calls = self.run_chats({"LLM_DAILY_LIMIT": "2"}, ["1.1.1.1", "2.2.2.2", "3.3.3.3"])
        self.assertEqual(sources, ["openai", "openai", "rule_limited"])
        self.assertEqual(len(calls), 2)

    def test_old_calls_leave_the_window(self):
        with patch("time.time", return_value=1000.0):
            self.run_chats({"LLM_PER_IP_PER_10MIN": "1"}, ["1.1.1.1"])
        with patch("time.time", return_value=1000.0 + self.app_module.LIMIT_WINDOW + 1):
            sources, _, _ = self.run_chats({"LLM_PER_IP_PER_10MIN": "1"}, ["1.1.1.1"])
        self.assertEqual(sources, ["openai"])

    def test_no_key_is_not_counted(self):
        self.assertEqual(self.chat().get_json()["decision_source"], "rule")
        self.assertEqual(self.app_module.daily_calls["count"], 0)

    def test_record_limit_skips_lines_and_embeddings(self):
        alien = {"who": "alien", "stage": "prep", "message": "", "scores": {a: 0.0 for a in AXES}}
        user = {"who": "user", "stage": "prep", "message": "타일", "signal": game_tile("pizza", "prep")}
        calls = []
        with patch.dict("os.environ", {"OPENAI_API_KEY": "test", "RECORD_PER_IP_PER_10MIN": "0"}), \
                patch("openai.OpenAI", fake_openai(self.ANSWER, calls=calls)):
            response = self.client.post("/api/record", json={"dish": "pizza", "success": True, "entries": [alien, user, alien]})
        data = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual((data["source"], data["image_source"]), ("rule_limited", "rule_limited"))
        self.assertEqual(calls, [])
        self.assertTrue(all(line["text"] for line in data["lines"]))

    def test_game_log_only_when_switched_on(self):
        with self.assertNoLogs("services.chatbot_service", "WARNING"):
            self.chat()
        with patch.dict("os.environ", {"GAME_LOG": "1"}), self.assertLogs("services.chatbot_service", "WARNING") as logs:
            self.chat()
        entry = json.loads(logs.output[0].split("game ", 1)[1])
        self.assertEqual(set(entry), {"stage", "attempt", "fit", "consistency", "confidence", "decision_source", "advance"})


class GameResponseTest(unittest.TestCase):
    OLD_KEYS = {"reply", "image", "sources", "alien", "state", "stage", "dish", "result"}

    def test_existing_and_new_fields(self):
        client = app.test_client()
        start = client.post("/api/start", json={}).get_json()
        chat = client.post("/api/chat", json={"message": "타일", "signal": game_tile("ramen"), "state": start["state"]}).get_json()
        for name, data in (("start", start), ("chat", chat)):
            with self.subTest(name=name):
                self.assertTrue(self.OLD_KEYS <= set(data))
                self.assertTrue(set(GAME_RESPONSE_KEYS) - {"metrics", "understanding", "ingredient", "ingredients", "menu_scores", "decision_source"} <= set(data))
                self.assertEqual(set(data["stage"]), {"id", "name", "index", "total", "hint", "advanced", "reason"})
                self.assertEqual(set(data["alien"]), {"scores", "word", "expression", "reading"})
                self.assertIsInstance(data["reply"], str)
        self.assertEqual((start["menu"], start["stage_number"], start["stage_name"]), (None, 1, "select"))
        self.assertEqual((chat["menu"], chat["stage"]["id"], chat["alien_message"] == chat["reply"]), ("ramen", "prep", True))

    def test_retriever_finds_cooking_knowledge(self):
        from services.retriever import DemoRetriever
        hits = DemoRetriever().search("ramen cook over")
        self.assertEqual([h.title for h in hits], ["ramen · cook"])
        self.assertIn("퍼지", hits[0].content)
        self.assertEqual(DemoRetriever().search("안녕"), [])

    def test_bad_game_state_is_rejected(self):
        client = app.test_client()
        state = client.post("/api/chat", json={"message": "타일", "signal": game_tile("pizza"),
                                               "state": client.post("/api/start", json={}).get_json()["state"]}).get_json()["state"]
        for bad in ({**state, "menu": "kimchi"}, {**state, "verdicts": {"prep": {"verdict": "great"}}},
                    {**state, "stage_metrics": [{"size": 500}]}):
            with self.subTest(bad=str(bad)[:60]):
                r = client.post("/api/chat", json={"message": "타일", "signal": game_tile("pizza", "prep"), "state": bad})
                self.assertEqual(r.get_json()["error"]["code"], "invalid_state")
