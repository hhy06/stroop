"""实验参数。改这里就能调整整个流程，前端通过 /api/config 读取同一份配置。"""

from __future__ import annotations

# 四种反应色。色值尽量选取观感亮度接近、在浅灰底上可辨识的深色。
# 若用于正式研究，建议在校准过的显示器上再统一一次亮度与色度。
COLORS: dict[str, dict[str, str]] = {
    "red": {"label": "红", "hex": "#D32F2F"},
    "green": {"label": "绿", "hex": "#2E7D32"},
    "blue": {"label": "蓝", "hex": "#1565C0"},
    "yellow": {"label": "黄", "hex": "#D9A400"},
}

COLOR_KEYS: tuple[str, ...] = tuple(COLORS)
CONDITIONS: tuple[str, ...] = ("congruent", "incongruent", "neutral")

TIMING = {
    "fixation_ms": 500,
    "fixation_jitter_ms": 200,
    "response_deadline_ms": 3000,
    "feedback_ms": 350,
    "iti_ms": 300,
    "min_valid_rt_ms": 200,
    "max_valid_rt_ms": 3000,
}

# 每个 (语言 × 条件 × 字色) 单元的重复次数。
# 2 → 4 语言 × 3 条件 × 4 色 × 2 = 96 个正式试次，约 4 分钟。
# 正式研究建议调到 5（240 试次），单条件样本量更稳。
REPEATS_PER_CELL = 2
PRACTICE_TRIALS = 8

# 连续两题出现「上一题词义 == 这一题字色」会引入负启动/冲突适应，
# 生成序列时主动规避；相邻同字色、同词同样规避。
AVOID_PREVIOUS_WORD_COLOR_MATCH = True

# 可选：设置环境变量 STROOP_EXPORT_TOKEN 后，CSV 导出需要 ?token=...
# 不设置则本地服务默认开放（数据仍只存本机）。
EXPORT_TOKEN_ENV = "STROOP_EXPORT_TOKEN"
