"""학종이 신호(색·질감 → 감각 점수)와 채팅 API 연결을 확인합니다."""

import unittest

from app import app
from services.sense_model import parse_signal, scores_of


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
        response = self.client.get("/assets/js/noizilian/composer.js")
        self.assertEqual(response.status_code, 200)
        response.close()


if __name__ == "__main__":
    unittest.main()
