"""
攻击距离计算模块。

两个无状态纯函数，只依赖 config 中的攻击判定参数：
- distance(cx, pcx)：玩家与怪物的 X 距离（用于怪物排序）
- in_range(cx, pcx)：判断怪物是否在攻击范围内

注意：不做类、不处理朝向/排序——朝向在移动/攻击处各自判定且判据不同，
排序在检测门面处按 distance 升序进行，强塞进本模块会造成反向耦合。
"""

import config


def distance(cx, pcx):
    """玩家与怪物的 X 距离（纯中心点水平距离，不含偏移）。

    用于怪物由近到远排序。

    Args:
        cx: 怪物中心 X
        pcx: 玩家中心 X
    """
    return abs(cx - pcx)


def in_range(cx, pcx):
    """判断怪物是否在攻击范围内。

    不再使用攻击范围框，直接比较玩家与怪物中心的 X 距离是否
    小于等于攻击判定阈值（原攻击框宽度的一半）。

    Args:
        cx: 怪物中心 X
        pcx: 玩家中心 X
    """
    return abs(cx - pcx) <= config.ATTACK_DISTANCE_THRESHOLD
