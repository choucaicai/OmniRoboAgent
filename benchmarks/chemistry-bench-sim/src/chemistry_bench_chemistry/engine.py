"""化学状态引擎：状态量层面的反应仿真（非分子动力学）。

设计参考 Chemistry3D 论文（arXiv:2406.08160）的"反应库 + 温度/颜色/pH
状态量"模型，代码为自研实现（原项目停维护且无许可证，不复制其代码）。

约束：纯 Python、零第三方依赖、兼容 3.10——必须能装进 Isaac Sim 4.5
内置 Python 环境。容器对象采用鸭子类型：任何具备
volume_ml/capacity_ml/solute/concentration/indicator 属性的对象都可参与。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol


class VesselLike(Protocol):
    volume_ml: float
    capacity_ml: float
    solute: str | None
    concentration: float
    indicator: str | None


@dataclass
class Vessel:
    """sim_worker 用的容器实现（mock_worker 有自己的 pydantic 版本）。"""

    name: str
    category: str = "beaker"
    position: list[float] = field(default_factory=lambda: [0.5, 0.0, 0.1])
    volume_ml: float = 0.0
    capacity_ml: float = 250.0
    solute: str | None = None
    concentration: float = 0.0  # mol/L
    indicator: str | None = None
    is_open: bool = True
    graspable: bool = True
    pourable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


# --------------------------------------------------------------------------- #
# 反应库（扩展点：新反应族加条目，不改 mix 逻辑）
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Reaction:
    """一条反应：反应物(摩尔比) → 产物 + 状态量效应。"""

    name: str
    kind: str  # neutralization / precipitation / redox / complexation
    acid: str | None = None
    base: str | None = None
    enthalpy_kj_mol: float = 0.0  # 放热为负（温度效应预留，M2 未启用）


REACTION_LIBRARY: list[Reaction] = [
    Reaction(name="HCl + NaOH -> NaCl + H2O", kind="neutralization",
             acid="HCl", base="NaOH", enthalpy_kj_mol=-57.3),
]

STRONG_ACIDS = {"HCl"}
STRONG_BASES = {"NaOH"}

# 指示剂变色表：indicator -> [(ph_lo, ph_hi, color)]
INDICATOR_TABLES: dict[str, list[tuple[float, float, str]]] = {
    "phenolphthalein": [(0.0, 8.2, "colorless"), (8.2, 14.1, "pink")],
}


def ph_of(v: VesselLike) -> float:
    """一元强酸/强碱近似 pH。"""
    if v.concentration <= 0 or v.solute is None:
        return 7.0
    c = max(v.concentration, 1e-14)
    if v.solute in STRONG_ACIDS:
        return max(0.0, min(14.0, -math.log10(c)))
    if v.solute in STRONG_BASES:
        return max(0.0, min(14.0, 14.0 + math.log10(c)))
    return 7.0


def color_of(v: VesselLike) -> str:
    """液体外观颜色（由指示剂 + pH 决定）。"""
    if v.indicator not in INDICATOR_TABLES:
        return "clear"
    ph = ph_of(v)
    for lo, hi, color in INDICATOR_TABLES[v.indicator]:
        if lo <= ph < hi:
            return color
    return "clear"


def mix(target: VesselLike, source: VesselLike, volume_ml: float) -> float:
    """把 source 的 volume_ml 倒入 target，按反应库做中和；返回实际转移体积。

    仅处理一元强酸/强碱（反应库 neutralization 族）。
    """
    volume_ml = min(volume_ml, source.volume_ml, target.capacity_ml - target.volume_ml)
    if volume_ml <= 0:
        return 0.0
    moved_moles = source.concentration * volume_ml / 1000.0
    acid = target.moles if hasattr(target, "moles") else _moles(target)
    acid_amt = acid if target.solute in STRONG_ACIDS else 0.0
    base_amt = acid if target.solute in STRONG_BASES else 0.0
    if source.solute in STRONG_ACIDS:
        acid_amt += moved_moles
    elif source.solute in STRONG_BASES:
        base_amt += moved_moles

    source.volume_ml -= volume_ml
    target.volume_ml += volume_ml
    net = base_amt - acid_amt  # >0 碱过量
    total_l = target.volume_ml / 1000.0
    if net > 1e-9:
        target.solute, target.concentration = "NaOH", net / total_l
    elif net < -1e-9:
        target.solute, target.concentration = "HCl", -net / total_l
    else:
        target.solute, target.concentration = None, 0.0
    return volume_ml


def _moles(v: VesselLike) -> float:
    return v.concentration * v.volume_ml / 1000.0


# 液体渲染颜色（RGB 0-1，供 sim/mock 渲染层共用）
COLOR_RGB: dict[str, tuple[float, float, float]] = {
    "colorless": (0.92, 0.94, 0.96),
    "clear": (0.88, 0.91, 0.94),
    "pink": (0.94, 0.47, 0.67),
}
