"""端到端 API 测试：使用独立临时数据库，不触碰 data/stroop.db。"""

import os
import tempfile
import unittest
from pathlib import Path

os.environ["STROOP_DB"] = str(Path(tempfile.mkdtemp()) / "api_test.db")

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from languages import color_of_word, vocab_items  # noqa: E402


class TestAPI(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app_module.app)

    def test_01_config_and_index(self):
        cfg = self.client.get("/api/config").json()
        self.assertEqual(len(cfg["color_keys"]), 4)
        self.assertEqual(len(cfg["language_keys"]), 4)
        self.assertEqual(len(cfg["vocab_items"]), 16)
        self.assertTrue(all("answer" not in item for item in cfg["vocab_items"]))
        self.assertIn("多语言 Stroop", self.client.get("/").text)

    def test_02_full_session_flow(self):
        cfg = self.client.get("/api/config").json()
        rating = {k: 1 for k in cfg["language_keys"]}
        created = self.client.post(
            "/api/session", json={"self_rating": rating, "user_agent": "unittest", "screen_hz": 60.0}
        )
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()
        sid = data["session_id"]
        self.assertEqual(len(data["trials"]), 96)
        self.assertEqual(len(data["practice"]), 8)
        self.assertTrue(all("word_color" not in t for t in data["trials"]))

        base_rt = {"congruent": 550.0, "neutral": 600.0, "incongruent": 700.0}
        results = [
            {
                "trial_id": t["trial_id"],
                "response_color": t["correct_color"],
                "rt_ms": base_rt[t["condition"]],
            }
            for t in data["trials"]
        ]
        # 顺带覆盖剔除分支：抢答、超时、失焦、答错，各放一题
        results[0]["rt_ms"] = 90.0
        results[1].update({"rt_ms": None, "timeout": True, "response_color": None})
        results[2]["blurred"] = True
        results[3]["response_color"] = cfg["color_keys"][0] if data["trials"][3]["correct_color"] != cfg["color_keys"][0] else cfg["color_keys"][1]

        saved = self.client.post(f"/api/session/{sid}/trials", json={"trials": results})
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["saved"], 96)

        again = self.client.post(f"/api/session/{sid}/trials", json={"trials": results})
        self.assertEqual(again.json()["saved"], 0)
        self.assertEqual(again.json()["duplicate"], 96)

        answers = [
            {"language": item["language"], "word": item["word"], "answer": item["answer"]}
            for item in vocab_items()
        ]
        vocab = self.client.post(f"/api/session/{sid}/vocab", json={"answers": answers})
        self.assertEqual(vocab.json()["saved"], 16)

        summary = self.client.get(f"/api/session/{sid}/summary")
        self.assertEqual(summary.status_code, 200, summary.text)
        s = summary.json()
        self.assertEqual(s["n_submitted"], 96)
        self.assertEqual(len(s["by_language"]), 4)
        for info in s["by_language"].values():
            self.assertIsNotNone(info["interference_ms"])
            self.assertEqual(info["vocab"]["score"], 1.0)
        # 干扰量应来自后端重算的中位 RT：700 - 600 = 100，与前端上报数值一致
        self.assertEqual(s["by_language"][data["block_order"][0]]["interference_ms"], 100.0)

        csv_resp = self.client.get("/api/export.csv")
        self.assertEqual(csv_resp.status_code, 200)
        self.assertIn("trial_id", csv_resp.text)
        overview = self.client.get("/api/overview").json()
        self.assertEqual(overview["n_sessions"], 1)

    def test_03_validation_and_404(self):
        r = self.client.post("/api/session", json={"self_rating": {"zh": 9}})
        self.assertEqual(r.status_code, 422)
        r = self.client.post("/api/session", json={"self_rating": {"klingon": 1}})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get("/api/session/nope/summary").status_code, 404)
        self.assertEqual(
            self.client.post("/api/session/nope/trials", json={"trials": []}).status_code, 404
        )

    def test_04_backend_recomputes_correctness(self):
        """前端谎报正确颜色，后端必须依据存档序列独立判定为错。"""
        cfg = self.client.get("/api/config").json()
        data = self.client.post(
            "/api/session", json={"self_rating": {k: 3 for k in cfg["language_keys"]}, "seed": 42}
        ).json()
        sid = data["session_id"]
        t = data["trials"][0]
        wrong = next(c for c in cfg["color_keys"] if c != t["correct_color"])
        self.client.post(
            f"/api/session/{sid}/trials",
            json={"trials": [{"trial_id": t["trial_id"], "response_color": wrong, "rt_ms": 600.0}]},
        )
        import storage
        with storage.db() as conn:
            row = conn.execute("SELECT correct, invalid_reason FROM trials WHERE session_id = ?", (sid,)).fetchone()
        self.assertEqual(row["correct"], 0)
        self.assertIsNone(row["invalid_reason"])
        self.assertIsNotNone(color_of_word("zh", "红"))


if __name__ == "__main__":
    unittest.main()
