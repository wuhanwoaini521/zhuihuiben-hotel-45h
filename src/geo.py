"""地理计算：只依赖坐标，不引入任何第三方地图 SDK。

设计原则：距离与步行时长都是可复算的确定性结果，误差只来自"步速"这个
显式声明的参数，而不是模型的语感。
"""
from __future__ import annotations

import math

EARTH_RADIUS_M = 6371000.0

# 步行速度按 4.5 km/h 计（成年人平路慢速），并在手册里显式声明。
DEFAULT_WALK_SPEED_KMH = 4.5

# 路程系数：直线距离 ≠ 实际路线，城市路网取 1.3 的绕行系数。
DEFAULT_DETOUR_FACTOR = 1.3


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """两点球面直线距离（米）。"""
    p = math.radians
    dlat = p(lat2 - lat1)
    dlon = p(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(p(lat1)) * math.cos(p(lat2)) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def walking_minutes(
    meters: float,
    speed_kmh: float = DEFAULT_WALK_SPEED_KMH,
    detour_factor: float = DEFAULT_DETOUR_FACTOR,
) -> float:
    """把直线距离换算成步行分钟数（含绕行系数）。"""
    route_m = meters * detour_factor
    return route_m / (speed_kmh * 1000 / 60)


def walkable(meters: float, threshold_m: float) -> bool:
    """直线距离是否落在声明的步行半径内。"""
    return meters <= threshold_m
