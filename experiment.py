"""试次序列生成：条件平衡 + 伪随机约束。

设计要点
- 单元 = (语言 × 条件 × 字色)，每单元重复 repeats_per_cell 次，完全平衡。
- 按语言分 block，避免同一段里混用语言产生的切换成本。
- 相邻试次禁止同字色（即禁止连续相同反应）、同词；
  并尽量规避「上一题词义 == 这一题字色」造成的冲突适应污染。
- 同一 seed 生成完全相同的序列，便于复现。
"""

from __future__ import annotations

import random
from collections import Counter

from config import (
    AVOID_PREVIOUS_WORD_COLOR_MATCH,
    COLOR_KEYS,
    CONDITIONS,
    PRACTICE_TRIALS,
    REPEATS_PER_CELL,
)
from languages import LANGUAGE_KEYS, neutral_for, word_for


def latin_square_order(languages: list[str], rotation: int) -> list[str]:
    """用轮换实现最简单的被试间顺序平衡。"""
    n = len(languages)
    offset = rotation % n
    return languages[offset:] + languages[:offset]


def _unit_key(trial: dict) -> tuple[str, str, str]:
    return (trial["language"], trial["condition"], trial["ink_color"])


def _make_trial(language: str, condition: str, ink_color: str, word_color: str | None) -> dict:
    if condition == "congruent":
        word_color = ink_color
    return {
        "language": language,
        "condition": condition,
        "word": neutral_for(language) if condition == "neutral" else word_for(language, word_color or ink_color),
        "word_color": None if condition == "neutral" else word_color,
        "ink_color": ink_color,
        "correct_color": ink_color,
    }


def _pool_for_language(language: str, repeats: int, rng: random.Random) -> list[dict]:
    """生成某一语言的全部试次，尚未排序。

    incongruent 的 (字色, 词义) 有序对按最小计数贪心分配，保证 12 种组合尽量均等。
    """
    pair_count: Counter[tuple[str, str]] = Counter()
    pool: list[dict] = []
    for condition in CONDITIONS:
        for ink_color in COLOR_KEYS:
            for _ in range(repeats):
                if condition == "incongruent":
                    options = [c for c in COLOR_KEYS if c != ink_color]
                    rng.shuffle(options)
                    word_color = min(options, key=lambda c: (pair_count[(ink_color, c)], options.index(c)))
                    pair_count[(ink_color, word_color)] += 1
                elif condition == "congruent":
                    word_color = ink_color
                else:
                    word_color = None
                pool.append(_make_trial(language, condition, ink_color, word_color))
    rng.shuffle(pool)
    return pool


def _pair_violations(prev: dict, cur: dict, avoid_prev_word_color: bool) -> int:
    """相邻两题的冲突分。连续相同反应会污染 RT，权重远高于其余两项。"""
    score = 0
    if cur["ink_color"] == prev["ink_color"]:
        score += 10
    if cur["word"] == prev["word"]:
        score += 1
    if (
        avoid_prev_word_color
        and prev["word_color"] is not None
        and prev["word_color"] == cur["ink_color"]
    ):
        score += 1
    return score


def _greedy_once(
    pool: list[dict],
    rng: random.Random,
    avoid_prev_word_color: bool,
    prev_trial: dict | None,
) -> tuple[list[dict], int]:
    """单趟贪心：每步只从冲突分最低的候选里挑，优先消耗剩余最多的单元。"""
    remaining = list(pool)
    ordered: list[dict] = []
    total = 0
    prev = prev_trial
    while remaining:
        if prev is None:
            candidates = list(range(len(remaining)))
            violation = 0
        else:
            scored = [(i, _pair_violations(prev, t, avoid_prev_word_color)) for i, t in enumerate(remaining)]
            violation = min(v for _, v in scored)
            candidates = [i for i, v in scored if v == violation]
        counts = Counter(_unit_key(t) for t in remaining)
        most_left = max(counts[_unit_key(remaining[i])] for i in candidates)
        top = [i for i in candidates if counts[_unit_key(remaining[i])] == most_left]
        pick = rng.choice(top)
        chosen = remaining.pop(pick)
        total += violation
        ordered.append(chosen)
        prev = chosen
    return ordered, total


def _order_pool(
    pool: list[dict],
    rng: random.Random,
    avoid_prev_word_color: bool,
    prev_trial: dict | None = None,
) -> list[dict]:
    """随机重启若干次，取冲突分最低的序列；找到零冲突即停。

    prev_trial 是上一个 block 的最后一题，使约束跨 block 边界同样成立。
    """
    best: list[dict] | None = None
    best_score = float("inf")
    for _ in range(300):
        candidate, score = _greedy_once(pool, rng, avoid_prev_word_color, prev_trial)
        if score < best_score:
            best, best_score = candidate, score
        if score == 0:
            break
    return best or list(pool)


def _practice_pool(language: str, count: int, rng: random.Random) -> list[dict]:
    pool: list[dict] = []
    for condition in CONDITIONS:
        for ink_color in COLOR_KEYS:
            word_color = ink_color if condition == "congruent" else None
            if condition == "incongruent":
                word_color = next(c for c in COLOR_KEYS if c != ink_color)
            pool.append(_make_trial(language, condition, ink_color, word_color))
    rng.shuffle(pool)
    chosen = pool[:count]
    return _order_pool(chosen, rng, AVOID_PREVIOUS_WORD_COLOR_MATCH)


def generate_sequence(
    seed: int,
    rotation: int = 0,
    languages: list[str] | None = None,
    repeats_per_cell: int = REPEATS_PER_CELL,
    practice_count: int = PRACTICE_TRIALS,
) -> dict:
    """返回 {seed, block_order, practice, test}，test 中每项带 trial_id/index/block。"""
    langs = list(languages) if languages else list(LANGUAGE_KEYS)
    unknown = [lang for lang in langs if lang not in LANGUAGE_KEYS]
    if unknown:
        raise ValueError(f"未知语言: {unknown}")
    if repeats_per_cell < 1:
        raise ValueError("repeats_per_cell 必须 >= 1")

    rng = random.Random(seed)
    block_order = latin_square_order(langs, rotation)
    practice = _practice_pool(block_order[0], practice_count, rng)
    for i, trial in enumerate(practice):
        trial.update({"trial_id": f"p{i + 1:04d}", "index": i, "block": -1, "phase": "practice"})

    test: list[dict] = []
    prev_trial: dict | None = None
    for block, language in enumerate(block_order):
        block_trials = _order_pool(
            _pool_for_language(language, repeats_per_cell, rng),
            rng,
            AVOID_PREVIOUS_WORD_COLOR_MATCH,
            prev_trial,
        )
        for trial in block_trials:
            trial["block"] = block
            trial["phase"] = "test"
            test.append(trial)
        if block_trials:
            prev_trial = block_trials[-1]
    for i, trial in enumerate(test):
        trial["trial_id"] = f"t{i + 1:04d}"
        trial["index"] = i

    return {"seed": seed, "block_order": block_order, "practice": practice, "test": test}


def validate_sequence(sequence: dict, repeats_per_cell: int = REPEATS_PER_CELL) -> list[str]:
    """返回发现的问题列表，供单元测试与自检使用。"""
    problems: list[str] = []
    test = sequence["test"]
    cells = Counter(_unit_key(t) for t in test)
    expected_cells = len(sequence["block_order"]) * len(CONDITIONS) * len(COLOR_KEYS)
    if len(cells) != expected_cells:
        problems.append(f"单元数异常: {len(cells)} != {expected_cells}")
    if any(v != repeats_per_cell for v in cells.values()):
        problems.append("单元重复次数不均衡")

    for prev, cur in zip(test, test[1:]):
        if prev["ink_color"] == cur["ink_color"]:
            problems.append(f"相邻同字色: {prev['trial_id']} -> {cur['trial_id']}")
        if prev["word"] == cur["word"]:
            problems.append(f"相邻同词: {prev['trial_id']} -> {cur['trial_id']}")
        if prev["word_color"] is not None and prev["word_color"] == cur["ink_color"]:
            problems.append(f"上一题词义等于本题字色: {prev['trial_id']} -> {cur['trial_id']}")

    for t in test:
        if t["condition"] == "congruent" and t["word_color"] != t["ink_color"]:
            problems.append(f"一致条件词义不符: {t['trial_id']}")
        if t["condition"] == "incongruent" and (
            t["word_color"] is None or t["word_color"] == t["ink_color"]
        ):
            problems.append(f"不一致条件词义不符: {t['trial_id']}")
        if t["condition"] == "neutral" and t["word_color"] is not None:
            problems.append(f"中性条件不应有词义: {t['trial_id']}")
        if t["correct_color"] != t["ink_color"]:
            problems.append(f"正确答案应为字色: {t['trial_id']}")
    return problems
