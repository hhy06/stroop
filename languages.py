"""语言包：新增语言只需在 LANGUAGES 里加一项，序列生成与问卷会自动适配。

words 的 key 必须与 config.COLOR_KEYS 一致；neutral 是无词义的中性字符串，
用于测量「纯辨色」基线。若要更严格控制字形复杂度，可把 neutral 换成
同语言的伪词列表（伪词不含颜色语义），其余逻辑无需改动。
"""

from __future__ import annotations

LANGUAGES: dict[str, dict[str, object]] = {
    "zh": {
        "name": "中文",
        "words": {"red": "红", "green": "绿", "blue": "蓝", "yellow": "黄"},
        "neutral": "□□",
        "vocab_hint": "请选出这个词表示的颜色",
    },
    "en": {
        "name": "英语",
        "words": {"red": "RED", "green": "GREEN", "blue": "BLUE", "yellow": "YELLOW"},
        "neutral": "XXXXX",
        "vocab_hint": "请选出这个词表示的颜色",
    },
    "es": {
        "name": "西班牙语",
        "words": {"red": "ROJO", "green": "VERDE", "blue": "AZUL", "yellow": "AMARILLO"},
        "neutral": "XXXXXXX",
        "vocab_hint": "请选出这个词表示的颜色",
    },
    "de": {
        "name": "德语",
        "words": {"red": "ROT", "green": "GRÜN", "blue": "BLAU", "yellow": "GELB"},
        "neutral": "XXXX",
        "vocab_hint": "请选出这个词表示的颜色",
    },
}

LANGUAGE_KEYS: tuple[str, ...] = tuple(LANGUAGES)


def word_for(language: str, color: str) -> str:
    """返回某语言中表示 color 的词。"""
    return str(LANGUAGES[language]["words"][color])  # type: ignore[index]


def neutral_for(language: str) -> str:
    return str(LANGUAGES[language]["neutral"])


def color_of_word(language: str, word: str) -> str | None:
    """反查词义对应的颜色；中性字符串或未知词返回 None。

    后端用它独立判定试次正误，不信任前端传来的 correct 字段。
    """
    words: dict[str, str] = LANGUAGES[language]["words"]  # type: ignore[assignment]
    for color, w in words.items():
        if w == word:
            return color
    return None


def vocab_items() -> list[dict[str, str]]:
    """译词测验题面：每种语言的四个颜色词，附正确答案。"""
    items = []
    for lang, meta in LANGUAGES.items():
        words: dict[str, str] = meta["words"]  # type: ignore[assignment]
        for color, word in words.items():
            items.append(
                {
                    "language": lang,
                    "language_name": str(meta["name"]),
                    "word": word,
                    "answer": color,
                }
            )
    return items
