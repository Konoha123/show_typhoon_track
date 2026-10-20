"""洋区（basin）码表与气旋编号前缀映射（M9，纯函数）。

口径（用户逐项确认，2026-10-20；出处与核实结论见 M9 验收记录）：
- 地点侧码表 = IBTrACS 七分法 NA/EP/WP/NI/SI/SP/SA（官方数据目录核实）+ 扩展 CP
  （IBTrACS 无 CP 洋区，但中太平洋地点客观存在；140°W–180° 为 CPHC 责任区），
  共 8 码，固定显示顺序 NA/EP/CP/WP/NI/SI/SP/SA；一个地点只标一个洋区；
- 气旋侧 = track_id 前缀直映（ATCF 编号约定，Weather Lab CSV/ATCF 下载遵循），
  不做合并消歧：CP/SH 保留独立标签，避免产出结果用于交流时与原始编号产生歧义；
  AL→NA、IO→NI 仅为代码改名的 1:1 映射；
- 地点不设 SH 码（地点总能细分到 SI/SP/SA）；备用联动规则 SH ⊇ {SI, SP, SA}
  仅登记口径，本轮不实现（复选框不跟随气旋）；
- 未识别前缀（如合成数据 SYN）返回 None，不参与洋区筛选。
"""

from __future__ import annotations

BASIN_ORDER: tuple[str, ...] = ("NA", "EP", "CP", "WP", "NI", "SI", "SP", "SA")
"""地点侧洋区码的固定顺序（places.csv basin 列合法值域，前端复选框同序）。"""

BASIN_NAMES: dict[str, str] = {
    "NA": "北大西洋",
    "EP": "东北太平洋",
    "CP": "中太平洋",
    "WP": "西北太平洋",
    "NI": "北印度洋",
    "SI": "南印度洋",
    "SP": "南太平洋",
    "SA": "南大西洋",
    "SH": "南半球",
}
"""显示名（地点 8 码 + 气旋侧粗码 SH）；places.csv basin 列的合法值域以 BASIN_ORDER 为准。"""

# 气旋侧 track_id 前缀（ATCF）→ 洋区标签；SH 为气旋专属粗码，不在地点码表中。
TRACK_ID_PREFIX_TO_BASIN: dict[str, str] = {
    "AL": "NA",
    "EP": "EP",
    "CP": "CP",
    "WP": "WP",
    "IO": "NI",
    "SH": "SH",
}


def basin_label(basin: str) -> str:
    """洋区显示标签：「代码 中文名」（如 ``WP 西北太平洋``、``SH 南半球``）。

    未知代码原样返回（不臆造名称）。
    """
    name = BASIN_NAMES.get(basin)
    return f"{basin} {name}" if name else basin


def basin_from_track_id(track_id: str | None) -> str | None:
    """track_id（ATCF 编号，如 ``EP202026``）→ 洋区标签，前缀直映、不合并消歧。

    前缀取首 2 字符（忽略首尾空白、大小写归一）；不在映射表（如 ``SYN``）或
    长度不足时返回 None。
    """
    if track_id is None:
        return None
    prefix = track_id.strip().upper()[:2]
    return TRACK_ID_PREFIX_TO_BASIN.get(prefix)
