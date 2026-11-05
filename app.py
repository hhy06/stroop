"""多语言 Stroop 变体测试 Web 服务。

启动：
    python -m uvicorn app:app --host 127.0.0.1 --port 8000
然后浏览器打开 http://127.0.0.1:8000
"""

from __future__ import annotations

import os
import secrets
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import storage
from config import (
    COLORS,
    COLOR_KEYS,
    EXPORT_TOKEN_ENV,
    PRACTICE_TRIALS,
    REPEATS_PER_CELL,
    TIMING,
)
from experiment import generate_sequence, validate_sequence
from languages import LANGUAGES, LANGUAGE_KEYS, vocab_items

BASE = Path(__file__).parent
STATIC = BASE / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    storage.init_db()
    yield


app = FastAPI(
    title="多语言 Stroop 颜色词测试",
    description="显示带颜色的外语颜色词，记录说出字色的反应时；以干扰量检验语言熟悉度的影响。",
    version="1.0.0",
    lifespan=lifespan,
)
storage.init_db()


class SessionCreate(BaseModel):
    self_rating: dict[str, int] = Field(default_factory=dict)
    user_agent: str | None = None
    screen_hz: float | None = None
    seed: int | None = None
    languages: list[str] | None = None


class TrialResult(BaseModel):
    trial_id: str
    response_color: str | None = None
    rt_ms: float | None = None
    timeout: bool = False
    anticipated: bool = False
    blurred: bool = False
    client_meta: dict | None = None


class TrialsIn(BaseModel):
    trials: list[TrialResult]


class VocabAnswer(BaseModel):
    language: str
    word: str
    answer: str


class VocabIn(BaseModel):
    answers: list[VocabAnswer]


def public_trial(t: dict) -> dict:
    """下发给浏览器的字段：不含 word_color，也不含任何答案提示。"""
    keys = ("trial_id", "index", "block", "language", "condition", "word", "ink_color", "correct_color", "phase")
    return {k: t[k] for k in keys}


def config_payload() -> dict:
    return {
        "colors": COLORS,
        "color_keys": list(COLOR_KEYS),
        "languages": {k: {"name": v["name"], "neutral": v["neutral"]} for k, v in LANGUAGES.items()},
        "language_keys": list(LANGUAGE_KEYS),
        "timing": TIMING,
        "repeats_per_cell": REPEATS_PER_CELL,
        "practice_trials": PRACTICE_TRIALS,
        "vocab_items": [
            {"language": i["language"], "language_name": i["language_name"], "word": i["word"]}
            for i in vocab_items()
        ],
    }


@app.get("/api/config")
def get_config():
    return config_payload()


@app.post("/api/session")
def create_session(body: SessionCreate):
    for lang, score in body.self_rating.items():
        if lang not in LANGUAGE_KEYS:
            raise HTTPException(422, f"未知语言: {lang}")
        if not 1 <= score <= 5:
            raise HTTPException(422, f"{lang} 的自评熟练度须在 1-5 之间")
    langs = body.languages or list(LANGUAGE_KEYS)
    if not langs:
        raise HTTPException(422, "至少选择一种语言")

    seed = body.seed if body.seed is not None else secrets.randbelow(2**31 - 1)
    sequence = generate_sequence(seed, rotation=storage.count_sessions(), languages=langs)
    problems = validate_sequence(sequence)
    if problems:
        raise HTTPException(500, f"序列生成校验失败: {problems[:3]}")

    session_id = uuid.uuid4().hex
    storage.create_session(
        session_id=session_id,
        seed=seed,
        block_order=sequence["block_order"],
        self_rating=body.self_rating,
        sequence=sequence,
        user_agent=body.user_agent,
        screen_hz=body.screen_hz,
    )
    return {
        "session_id": session_id,
        "seed": seed,
        "block_order": sequence["block_order"],
        "config": config_payload(),
        "practice": [public_trial(t) for t in sequence["practice"]],
        "trials": [public_trial(t) for t in sequence["test"]],
    }


@app.post("/api/session/{session_id}/trials")
def submit_trials(session_id: str, body: TrialsIn):
    try:
        return storage.save_trials(session_id, [t.model_dump() for t in body.trials])
    except KeyError:
        raise HTTPException(404, "会话不存在")


@app.post("/api/session/{session_id}/vocab")
def submit_vocab(session_id: str, body: VocabIn):
    if storage.get_session(session_id) is None:
        raise HTTPException(404, "会话不存在")
    return storage.save_vocab(session_id, [a.model_dump() for a in body.answers])


@app.get("/api/session/{session_id}/summary")
def get_summary(session_id: str):
    result = storage.session_summary(session_id)
    if result is None:
        raise HTTPException(404, "会话不存在")
    return result


@app.get("/api/overview")
def get_overview():
    return storage.overview()


@app.get("/api/export.csv")
def get_export(token: str | None = Query(default=None)):
    required = os.environ.get(EXPORT_TOKEN_ENV)
    if required and token != required:
        raise HTTPException(403, "导出需要有效 token")
    content = "\ufeff" + storage.export_csv()
    return Response(
        content=content.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="stroop_trials.csv"'},
    )


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")
