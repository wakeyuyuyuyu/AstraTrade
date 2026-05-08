from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Set


STYLE_LIBRARY: Dict[str, Dict[str, str]] = {
    "investment_period": {
        "short_term": "短线交易，关注 1 天至 2 周内的价格波动、资金异动、市场情绪和事件催化；更重视买卖时机、止损纪律和短期风险。",
        "swing": "波段交易，关注 2 周至 3 个月内的趋势延续、板块轮动和基本面边际变化；避免过度频繁交易。",
        "long_term": "中长期投资，关注 3 个月以上的公司质量、行业空间、估值水平和业绩成长；弱化短期波动影响。",
    },
    "risk_preference": {
        "conservative": "保守型风险偏好，优先控制本金损失和账户回撤；宁可错过机会，也不承担高不确定性风险。",
        "balanced": "稳健型风险偏好，在控制回撤的前提下追求合理收益；交易必须具备清晰理由、止损位和风险收益比。",
        "aggressive": "进攻型风险偏好，在趋势明确、资金活跃或事件催化强烈时可适度提高积极性；仍必须设置止损。",
        "very_aggressive": "激进型风险偏好，允许参与高波动、高弹性机会；必须严格限制最大亏损和连续亏损次数。",
    },
    "stock_selection": {
        "value": "偏好估值合理或偏低、盈利稳定、现金流较好、分红能力较强的标的；谨慎对待高估值题材股。",
        "growth": "偏好收入、利润或行业空间具备成长性的标的；关注成长逻辑是否持续兑现。",
        "trend": "偏好价格趋势明确、均线结构良好、成交量配合且相对强势的标的；趋势破坏时降低优先级。",
        "event_driven": "关注政策、公告、业绩预告、并购重组、行业催化和突发事件带来的机会；评估催化强度、持续性和兑现风险。",
        "quality_filter": "使用基本面作为过滤条件，排除财务质量差、经营风险高、业绩恶化或重大不确定性的标的。",
        "low_reversal": "关注充分调整后出现止跌、放量、资金回流或基本面改善迹象的标的；不得仅因“跌得多”而买入。",
    },
    "trading_frequency": {
        "low": "低频交易，只在高确定性机会或持仓逻辑明显变化时操作；没有充分理由时优先观察或持有。",
        "medium_low": "中低频交易，有机会才操作，不为了交易而交易；未触发止盈、止损或逻辑变化时不频繁调仓。",
        "medium": "中频交易，机会质量较高、风险收益比清晰时可适度调仓；通常控制每周交易次数。",
        "opportunity_driven": "机会驱动，不固定交易频率；机会不足时保持空仓或低仓位，机会增强时提高分析和交易频率。",
    },
    "decision_basis": {
        "fundamental_first": "优先参考业绩、盈利能力、估值、行业地位和长期竞争力；技术面和消息面只作辅助。",
        "technical_first": "优先参考趋势结构、均线系统、成交量、支撑压力位和价格强弱；基本面和消息面用于排除重大风险。",
        "fund_flow_first": "优先参考主力资金、板块资金流、成交活跃度、量价配合和市场关注度；避免高位盲目追随资金。",
        "position_first": "优先考虑当前持仓、成本价、浮盈浮亏、仓位暴露和已有策略；新增交易不得破坏账户风险结构。",
        "balanced": "综合参考基本面、技术面、资金面、消息面和持仓状态；多维度印证时提高优先级，关键维度冲突时降低积极性。",
    },
    "position_style": {
        "light_probe": "倾向小仓位试探，趋势、资金和逻辑继续验证后再考虑加仓；重点控制试错成本。",
        "batch_build": "倾向分批买入降低择时风险；每次加仓必须基于新的确认信号，不因下跌而被动补仓。",
        "concentrated": "倾向集中配置少数高质量或高确定性机会；必须限制单票最大仓位并持续跟踪核心逻辑。",
        "diversified": "倾向分散到多个标的或方向以降低单票波动影响；分散持仓不得降低选股标准。",
        "dynamic": "根据市场强弱、机会质量和账户风险状态动态调整仓位；市场弱时降仓，机会强且风险可控时加仓。",
    },
    "take_profit_stop_loss": {
        "strict_stop_loss": "严格执行预设止损位；触发止损条件时优先减仓或卖出，不得随意下移止损。",
        "wide_stop_loss": "允许为中长期逻辑或高波动标的设置较宽止损；宽止损必须对应更小仓位和明确最大亏损。",
        "trailing_profit": "盈利后根据趋势延续逐步上移保护位；不急于过早卖出强势标的，但防止浮盈大幅回撤。",
        "target_profit": "买入前设定目标价格或收益区间；达到目标后优先分批止盈，调整目标必须说明依据。",
        "logic_based": "关注交易逻辑是否成立；买入理由消失、催化落空、趋势破坏或基本面恶化时重新评估退出。",
    },
    "market_adaptability": {
        "trend_following": "市场趋势向上、板块活跃时积极寻找机会；市场走弱或情绪退潮时降低交易频率和仓位。",
        "defensive": "市场不确定性较高时优先保护本金，减少新增买入和高波动暴露；风险增多时收缩仓位。",
        "rotation": "关注板块强弱切换和资金轮动，优先选择资金流入更明显的方向；避免追逐过度拥挤板块。",
        "contrarian": "可在恐慌、超跌或情绪过度悲观时寻找反向机会；必须有估值、资金回流或基本面改善支撑。",
    },
}


STYLE_RULES: Dict[str, Dict[str, Any]] = {
    "investment_period": {
        "min_items": 1,
        "max_items": 1,
        "reason": "投资周期是主时间框架，只能单选，避免短线/波段/长线同时驱动决策。",
    },
    "risk_preference": {
        "min_items": 1,
        "max_items": 1,
        "reason": "风险偏好是账户级风险基调，只能单选。",
    },
    "stock_selection": {
        "min_items": 1,
        "max_items": 4,
        "reason": "选股偏好可以组合，但不宜过多，否则筛选标准会变得发散。",
        "conflicts": [
            ["value", "low_reversal"],
        ],
    },
    "trading_frequency": {
        "min_items": 1,
        "max_items": 1,
        "reason": "交易频率是运行节奏，只能单选。",
    },
    "decision_basis": {
        "min_items": 1,
        "max_items": 2,
        "reason": "决策依据最多保留一个主框架加一个补充优先级。",
        "conflicts": [
            ["fundamental_first", "technical_first", "fund_flow_first", "balanced"],
        ],
    },
    "position_style": {
        "min_items": 1,
        "max_items": 3,
        "reason": "仓位风格可以组合，例如轻仓试探 + 分批建仓，但互斥风格不能同时出现。",
        "conflicts": [
            ["concentrated", "diversified"],
        ],
    },
    "take_profit_stop_loss": {
        "min_items": 1,
        "max_items": 3,
        "reason": "止盈止损可以组合，但严格止损和宽止损不能同时作为默认风格。",
        "conflicts": [
            ["strict_stop_loss", "wide_stop_loss"],
        ],
    },
    "market_adaptability": {
        "min_items": 1,
        "max_items": 3,
        "reason": "市场适应性可以组合，例如防守 + 趋势跟随，但不宜过多。",
    },
}


DEFAULT_STYLE_CONFIG: Dict[str, List[str]] = {
    "investment_period": ["swing"],
    "risk_preference": ["balanced"],
    "stock_selection": ["trend", "event_driven", "quality_filter"],
    "trading_frequency": ["medium_low"],
    "decision_basis": ["balanced", "position_first"],
    "position_style": ["light_probe", "batch_build"],
    "take_profit_stop_loss": ["strict_stop_loss", "trailing_profit", "logic_based"],
    "market_adaptability": ["defensive", "trend_following"],
}


TITLE_MAP = {
    "investment_period": "投资周期",
    "risk_preference": "风险偏好",
    "stock_selection": "选股偏好",
    "trading_frequency": "交易频率",
    "decision_basis": "决策依据",
    "position_style": "仓位风格",
    "take_profit_stop_loss": "止盈止损风格",
    "market_adaptability": "市场环境适应性",
}


@dataclass
class InvestmentStyle:
    config: Dict[str, List[str]] = field(default_factory=lambda: {k: list(v) for k, v in DEFAULT_STYLE_CONFIG.items()})

    def validate(self) -> None:
        self._validate_required_dimensions()

        for dimension, options in self.config.items():
            self._validate_dimension_exists(dimension)
            normalized_options = self._normalize_options(dimension, options)
            self._validate_option_count(dimension, normalized_options)
            self._validate_conflicts(dimension, normalized_options)
            self.config[dimension] = normalized_options

    def _validate_required_dimensions(self) -> None:
        missing = [dimension for dimension in STYLE_RULES if dimension not in self.config]
        if missing:
            raise ValueError(f"缺少投资风格维度: {', '.join(missing)}")

    @staticmethod
    def _normalize_options(dimension: str, options: List[str]) -> List[str]:
        if not isinstance(options, list) or not options:
            raise ValueError(f"维度 {dimension} 必须配置非空 list")

        normalized: List[str] = []
        seen: Set[str] = set()

        for option in options:
            option = str(option).strip()
            if not option:
                continue

            if option in seen:
                continue

            if option not in STYLE_LIBRARY[dimension]:
                allowed = ", ".join(STYLE_LIBRARY[dimension].keys())
                raise ValueError(f"未知投资风格配置: {dimension}.{option}，可选值: {allowed}")

            normalized.append(option)
            seen.add(option)

        if not normalized:
            raise ValueError(f"维度 {dimension} 至少需要配置 1 个有效选项")

        return normalized

    @staticmethod
    def _validate_dimension_exists(dimension: str) -> None:
        if dimension not in STYLE_LIBRARY:
            raise ValueError(f"未知投资风格维度: {dimension}")

        if dimension not in STYLE_RULES:
            raise ValueError(f"维度 {dimension} 缺少 STYLE_RULES 配置")

    @staticmethod
    def _validate_option_count(dimension: str, options: List[str]) -> None:
        rule = STYLE_RULES[dimension]
        min_items = int(rule.get("min_items", 1))
        max_items = int(rule.get("max_items", 99))

        if len(options) < min_items:
            raise ValueError(f"维度 {dimension} 至少需要选择 {min_items} 个选项")

        if len(options) > max_items:
            title = TITLE_MAP.get(dimension, dimension)
            reason = rule.get("reason", "")
            raise ValueError(
                f"维度 {dimension}（{title}）最多只能选择 {max_items} 个选项，"
                f"当前选择 {len(options)} 个: {options}。{reason}"
            )

    @staticmethod
    def _validate_conflicts(dimension: str, options: List[str]) -> None:
        rule = STYLE_RULES[dimension]
        conflicts = rule.get("conflicts", [])

        selected = set(options)

        for conflict_group in conflicts:
            overlap = selected.intersection(conflict_group)
            if len(overlap) > 1:
                title = TITLE_MAP.get(dimension, dimension)
                raise ValueError(
                    f"维度 {dimension}（{title}）存在互斥选项，不能同时选择: {sorted(overlap)}"
                )

    def build_prompt(self) -> str:
        self.validate()

        parts: List[str] = [
            "# 投资风格约束",
            "",
            "本节用于定义 Agent 的交易偏好。投资风格不得覆盖工具真实性、文件协议、风控规则和调用模式规则。",
            "优先级：工具真实性 / 文件协议 / 风控规则 > 调用模式规则 > 投资风格约束 > 市场背景 > 动态上下文。",
            "",
        ]

        for dimension, options in self.config.items():
            title = TITLE_MAP.get(dimension, dimension)
            parts.append(f"## {title}")
            parts.append("")

            for option in options:
                parts.append(f"- {STYLE_LIBRARY[dimension][option]}")

            parts.append("")

        parts.append("## 投资风格强制要求")
        parts.append("")
        parts.extend(
            [
                "- 买入建议必须包含买入理由、止损位和风险收益比。",
                "- 新增交易不得破坏账户整体仓位结构和风险暴露。",
                "- 市场环境不明朗时，应降低交易频率和仓位。",
                "- 如果投资风格与风控规则冲突，必须服从风控规则。",
            ]
        )

        return "\n".join(parts).strip() + "\n"


def load_config_from_json(path: str | Path) -> Dict[str, List[str]]:
    config_path = Path(path)

    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    data = json.loads(config_path.read_text(encoding="utf-8"))

    if not isinstance(data, dict):
        raise ValueError("投资风格配置必须是 JSON object")

    result: Dict[str, List[str]] = {}

    for key, value in data.items():
        if isinstance(value, str):
            result[key] = [value]
        elif isinstance(value, list):
            result[key] = [str(v) for v in value]
        else:
            raise ValueError(f"配置 {key} 必须是 string 或 list[string]")

    return result


def write_style_md(
    workspace_dir: str | Path,
    config: Dict[str, List[str]],
    output_name: str = "STYLE.md",
) -> Path:
    workspace = Path(workspace_dir)
    output_path = workspace / output_name

    style = InvestmentStyle(config=config)
    prompt = style.build_prompt()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(prompt, encoding="utf-8")

    return output_path


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate workspace/STYLE.md for AstraTrade.")

    parser.add_argument(
        "--config",
        default=None,
        help="投资风格 JSON 配置路径。默认使用 config/investment_style.json。",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        help="workspace 路径。默认使用项目根目录下的 workspace。",
    )
    parser.add_argument(
        "--output-name",
        default="STYLE.md",
        help="输出文件名，默认 STYLE.md。",
    )
    parser.add_argument(
        "--print",
        action="store_true",
        help="同时打印生成的 STYLE.md 内容。",
    )

    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    workspace_dir = Path(args.workspace) if args.workspace else project_root / "workspace"
    config_path = Path(args.config) if args.config else project_root / "config" / "investment_style.json"

    config = load_config_from_json(config_path)

    output_path = write_style_md(
        workspace_dir=workspace_dir,
        config=config,
        output_name=args.output_name,
    )

    if args.print:
        print(output_path.read_text(encoding="utf-8"))
    else:
        print(f"STYLE.md written to: {output_path}")


if __name__ == "__main__":
    main()
