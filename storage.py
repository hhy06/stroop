"""SQLite 存储与统计汇总。

计时与正误的关键原则：RT 由浏览器端计算并上报，但**正误由后端依据存档的
试次序列独立重算**，invalid_reason 也由后端依据规则判定，不信任前端字段。
"""

from __future__ import annotations

import csv
import io
import json
import os
import sqlite3
import statistics
from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from config import COLOR_KEYS, CONDITIONS, TIMING
from languages import LANGUAGE_KEYS, color_of_word

DB_PATH = Path(os.environ.get("STROOP_DB", str(Path(__file__).parent / "data" / "stroop.db")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    created_at    TEXT NOT NULL,
    seed          INTEGER NOT NULL,
    block_order   TEXT NOT NULL,
    self_rating   TEXT NOT NULL,
    user_agent    TEXT,
    screen_hz     REAL,
    trials_json   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trials (
    session_id     TEXT NOT NULL,
    trial_id       TEXT NOT NULL,
    idx            INTEGER NOT NULL,
    block          INTEGER NOT NULL,
    language       TEXT NOT NULL,
    cond           TEXT NOT NULL,
    word           TEXT NOT NULL,
    word_color     TEXT,
    ink_color      TEXT NOT NULL,
    correct_color  TEXT NOT NULL,
    response_color TEXT,
    correct        INTEGER,
    rt_ms          REAL,
    timeout        INTEGER NOT NULL DEFAULT 0,
    anticipated    INTEGER NOT NULL DEFAULT 0,
    blurred        INTEGER NOT NULL DEFAULT 0,
    invalid_reason TEXT,
    client_meta    TEXT,
    PRIMARY KEY (session_id, trial_id)
);
CREATE TABLE IF NOT EXISTS vocab_checks (
    session_id TEXT NOT NULL,
    language   TEXT NOT NULL,
    word       TEXT NOT NULL,
    answer     TEXT NOT NULL,
    correct    INTEGER NOT NULL,
    PRIMARY KEY (session_id, language, word)
);
CREATE INDEX IF NOT EXISTS idx_trials_session ON trials(session_id);
"""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def db():
    """提交事务并确保连接关闭（sqlite3 自带的 with 只管事务，不关连接）。"""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA)


def count_sessions() -> int:
    with db() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0])


def create_session(
    session_id: str,
    seed: int,
    block_order: list[str],
    self_rating: dict[str, int],
    sequence: dict,
    user_agent: str | None = None,
    screen_hz: float | None = None,
) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, seed, block_order, self_rating, user_agent, screen_hz, trials_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id,
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                seed,
                json.dumps(block_order, ensure_ascii=False),
                json.dumps(self_rating, ensure_ascii=False),
                user_agent,
                screen_hz,
                json.dumps(sequence, ensure_ascii=False),
            ),
        )


def get_session(session_id: str) -> dict | None:
    with db() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    if row is None:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "seed": row["seed"],
        "block_order": json.loads(row["block_order"]),
        "self_rating": json.loads(row["self_rating"]),
        "user_agent": row["user_agent"],
        "screen_hz": row["screen_hz"],
        "sequence": json.loads(row["trials_json"]),
    }


def expected_trials(session_id: str) -> dict[str, dict] | None:
    session = get_session(session_id)
    if session is None:
        return None
    return {t["trial_id"]: t for t in session["sequence"]["test"]}


def _judge(expected: dict, result: dict) -> dict:
    """依据后端存档的序列独立判定正误与剔除原因。"""
    flags = {
        "timeout": bool(result.get("timeout")),
        "anticipated": bool(result.get("anticipated")),
        "blurred": bool(result.get("blurred")),
    }
    rt = result.get("rt_ms")
    try:
        rt = float(rt) if rt is not None else None
    except (TypeError, ValueError):
        rt = None

    reasons: list[str] = []
    for name, on in flags.items():
        if on:
            reasons.append(name)
    if rt is None:
        reasons.append("no_rt")
    elif rt < TIMING["min_valid_rt_ms"]:
        reasons.append("too_fast")
    elif rt > TIMING["max_valid_rt_ms"]:
        reasons.append("too_slow")

    response = result.get("response_color")
    if response not in COLOR_KEYS:
        response = None
    correct = int(response is not None and response == expected["correct_color"])
    meta = result.get("client_meta")
    return {
        "response_color": response,
        "correct": correct,
        "rt_ms": rt,
        "flags": flags,
        "invalid_reason": ",".join(reasons) or None,
        "client_meta": json.dumps(meta, ensure_ascii=False) if isinstance(meta, (dict, list)) else None,
    }


def save_trials(session_id: str, results: list[dict]) -> dict:
    expected = expected_trials(session_id)
    if expected is None:
        raise KeyError(session_id)
    saved, unknown, duplicate = 0, 0, 0
    with db() as conn:
        for result in results:
            trial_id = str(result.get("trial_id", ""))
            exp = expected.get(trial_id)
            if exp is None:
                unknown += 1
                continue
            verdict = _judge(exp, result)
            cur = conn.execute(
                "INSERT OR IGNORE INTO trials "
                "(session_id, trial_id, idx, block, language, cond, word, word_color, ink_color, "
                " correct_color, response_color, correct, rt_ms, timeout, anticipated, blurred, "
                " invalid_reason, client_meta) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    trial_id,
                    exp["index"],
                    exp["block"],
                    exp["language"],
                    exp["condition"],
                    exp["word"],
                    exp["word_color"],
                    exp["ink_color"],
                    exp["correct_color"],
                    verdict["response_color"],
                    verdict["correct"],
                    verdict["rt_ms"],
                    int(verdict["flags"]["timeout"]),
                    int(verdict["flags"]["anticipated"]),
                    int(verdict["flags"]["blurred"]),
                    verdict["invalid_reason"],
                    verdict["client_meta"],
                ),
            )
            if cur.rowcount:
                saved += 1
            else:
                duplicate += 1
    return {"saved": saved, "duplicate": duplicate, "unknown_trial_id": unknown}


def save_vocab(session_id: str, answers: list[dict]) -> dict:
    saved = 0
    with db() as conn:
        for item in answers:
            language = str(item.get("language", ""))
            word = str(item.get("word", ""))
            answer = str(item.get("answer", "unknown"))
            truth = color_of_word(language, word) if language in LANGUAGE_KEYS else None
            if truth is None:
                continue
            correct = int(answer == truth)
            cur = conn.execute(
                "INSERT OR IGNORE INTO vocab_checks (session_id, language, word, answer, correct) "
                "VALUES (?, ?, ?, ?, ?)",
                (session_id, language, word, answer, correct),
            )
            saved += cur.rowcount
    return {"saved": saved}


def _vocab_scores(session_id: str, conn: sqlite3.Connection) -> dict[str, dict]:
    rows = conn.execute(
        "SELECT language, COUNT(*) AS n, SUM(correct) AS hits FROM vocab_checks "
        "WHERE session_id = ? GROUP BY language",
        (session_id,),
    ).fetchall()
    return {
        r["language"]: {"correct": int(r["hits"] or 0), "total": int(r["n"]), "score": round((r["hits"] or 0) / r["n"], 3)}
        for r in rows
    }


def _interpret(vocab: dict | None, interference: float | None) -> str:
    if interference is None:
        return "有效试次不足，无法计算干扰量。"
    score = (vocab or {}).get("score")
    if score is None:
        return "尚未完成译词测验，干扰量暂无法结合语言熟悉度解读。"
    if score >= 0.5:
        return "认识该语言的颜色词，出现干扰属经典 Stroop 效应。"
    if interference > 20:
        return "译词测验显示基本不认识，却仍出现干扰：可能来自隐性词汇知识或自评偏差，值得追加被试复核。"
    return "译词测验显示基本不认识且干扰量接近 0：符合「词义未自动激活」的预期；若绝对反应时偏慢，多半是字形识别成本。"


def session_summary(session_id: str) -> dict | None:
    with db() as conn:
        session = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if session is None:
            return None
        rows = conn.execute("SELECT * FROM trials WHERE session_id = ?", (session_id,)).fetchall()
        vocab = _vocab_scores(session_id, conn)

    totals: Counter[tuple[str, str]] = Counter()
    wrong: Counter[tuple[str, str]] = Counter()
    excluded: Counter[tuple[str, str]] = Counter()
    rts: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        key = (r["language"], r["cond"])
        totals[key] += 1
        if r["correct"] == 0:
            wrong[key] += 1
        elif r["invalid_reason"]:
            excluded[key] += 1
        elif r["rt_ms"] is not None:
            rts[key].append(float(r["rt_ms"]))

    cells = []
    for (language, cond), n in sorted(totals.items()):
        values = rts[(language, cond)]
        cells.append(
            {
                "language": language,
                "condition": cond,
                "n_total": n,
                "n_valid": len(values),
                "n_wrong": wrong[(language, cond)],
                "n_excluded": excluded[(language, cond)],
                "median_rt_ms": round(statistics.median(values), 1) if values else None,
                "mean_rt_ms": round(statistics.fmean(values), 1) if values else None,
                "error_rate": round(wrong[(language, cond)] / n, 3) if n else None,
            }
        )

    by_lang: dict[str, dict] = {}
    for language in session_block_order(session):
        lookup = {c["condition"]: c for c in cells if c["language"] == language}
        inc = lookup.get("incongruent", {}).get("median_rt_ms")
        neu = lookup.get("neutral", {}).get("median_rt_ms")
        con = lookup.get("congruent", {}).get("median_rt_ms")
        interference = round(inc - neu, 1) if inc is not None and neu is not None else None
        facilitation = round(neu - con, 1) if neu is not None and con is not None else None
        by_lang[language] = {
            "cells": [lookup[c] for c in CONDITIONS if c in lookup],
            "interference_ms": interference,
            "facilitation_ms": facilitation,
            "self_rating": json.loads(session["self_rating"]).get(language),
            "vocab": vocab.get(language),
            "interpretation": _interpret(vocab.get(language), interference),
        }

    return {
        "session_id": session_id,
        "created_at": session["created_at"],
        "seed": session["seed"],
        "n_submitted": len(rows),
        "n_expected": len(json.loads(session["trials_json"])["test"]),
        "by_language": by_lang,
        "cells": cells,
        "caveat": "单次测试、每单元试次数有限，干扰量仅为描述性指标，不构成统计显著性结论。",
    }


def session_block_order(row: sqlite3.Row) -> list[str]:
    return json.loads(row["block_order"])


def overview() -> dict:
    with db() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM sessions ORDER BY created_at").fetchall()]
    return {
        "n_sessions": len(ids),
        "sessions": [s for sid in ids if (s := session_summary(sid)) is not None],
    }


def export_csv() -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "session_id", "created_at", "self_rating", "vocab_score", "trial_id", "idx", "block",
            "language", "condition", "word", "word_color", "ink_color", "correct_color",
            "response_color", "correct", "rt_ms", "timeout", "anticipated", "blurred", "invalid_reason",
        ]
    )
    with db() as conn:
        sessions = {
            r["id"]: r for r in conn.execute("SELECT id, created_at, self_rating FROM sessions").fetchall()
        }
        vocab = {
            sid: _vocab_scores(sid, conn) for sid in sessions
        }
        rows = conn.execute("SELECT * FROM trials ORDER BY session_id, idx").fetchall()
    for r in rows:
        sid = r["session_id"]
        ratings = json.loads(sessions[sid]["self_rating"]) if sid in sessions else {}
        scores = vocab.get(sid, {}).get(r["language"], {}).get("score", "")
        writer.writerow(
            [
                sid, sessions[sid]["created_at"] if sid in sessions else "",
                ratings.get(r["language"], ""), scores,
                r["trial_id"], r["idx"], r["block"], r["language"], r["cond"], r["word"],
                r["word_color"] or "", r["ink_color"], r["correct_color"], r["response_color"] or "",
                r["correct"], r["rt_ms"], r["timeout"], r["anticipated"], r["blurred"], r["invalid_reason"] or "",
            ]
        )
    return buf.getvalue()
