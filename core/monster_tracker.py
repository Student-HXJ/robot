"""
怪物跟踪模块。

负责"持续按住方向键"的移动决策：
- 玩家进入检测框左/右区 → 立即回中（keep_centered，最高优先级）
- 怪物在攻击范围外 → 按住方向键朝怪物靠近（hold_toward）
- 无怪物时 → 按住方向键随机左右移动防掉线（idle_wander）
- 移动被阻挡 → 卡住检测，立即反向脱困（check_stuck_and_reverse）

物理按键由 KeyControl 执行，按住状态（held_move_key）由 KeyControl 持有，
本类通过 ``keys.held_move_key`` 只读判断当前方向，不另存一份。
"""

import logging
import random
import time

import config
from core.utils import jitter


class MonsterTracker:
    """怪物跟踪器：靠近/随机移动/卡住反向脱困。

    Attributes:
        卡住检测状态（仅本类维护，物理按键状态在 KeyControl）：
        - _last_move_pos      上次移动基准点（周期开始时的玩家坐标）
        - _stuck_base_dir     基准点对应的按住方向；方向一变更即重置基准点
        - _move_stuck_check_at 下次卡住检查时间点
        - _stuck_reverse_until 反向脱困后禁止他处逻辑覆盖方向的截止时间
        - _move_switch_at      空闲随机移动切换方向的时间点
        - _range_anchor_x     水平移动范围限制的基准 X（启动时玩家 X，仅限
                              指定分类如 lvmogu 时使用）
        - _centering_dir      玩家居中校正当前回中方向（None=未在校正），
                              仅用于回中日志降频（换向/进入时各记一次）
    """

    def __init__(self, keys, log=None):
        """
        Args:
            keys: KeyControl 实例（物理按键执行者，唯一持有 held_move_key）
            log: 日志器，缺省使用 "GameBot"
        """
        self._keys = keys
        self.log = log or logging.getLogger("GameBot")

        # 空闲随机移动切换方向的时间点
        self._move_switch_at = 0.0
        # 卡住检测：上次移动时的玩家位置与下次检查时间点
        self._last_move_pos = None
        self._move_stuck_check_at = 0.0
        # 当前基准点对应的按住方向；方向一变更即重置基准点重新计时
        self._stuck_base_dir = None
        # 反向脱困后禁止他处逻辑覆盖方向的截止时间
        self._stuck_reverse_until = 0.0
        # 水平移动范围限制基准 X（首次调用 keep_in_range 时取玩家 X）
        self._range_anchor_x = None
        # 玩家居中校正当前回中方向（None 表示未在校正），用于回中日志降频
        self._centering_dir = None

    # ------------------------------------------------------------------ #
    #  移动决策
    # ------------------------------------------------------------------ #

    def hold_toward(self, cx, px, now, frame_count, name=None, dist=None):
        """怪物超出攻击距离时，按住方向键朝怪物靠近。

        Args:
            cx: 怪物中心 X
            px: 玩家中心 X
            now: 当前时间戳
            frame_count: 当前帧计数（降频日志）
            name, dist: 用于日志的怪物信息
        """
        move_dir = (config.KEY_RIGHT
                    if cx > px + config.ATTACK_CENTER_OFFSET else
                    config.KEY_LEFT)
        if frame_count % config.LOG_FRAME_INTERVAL == 0:
            dist_txt = f"{dist:.0f}" if dist is not None else f"{cx - px:.0f}"
            self.log.info(f"移动{move_dir} 靠近 {name or ''} "
                          f"距离{dist_txt}px cx={cx} px={px}")
        # 刚反向脱困的短暂时间内不覆盖反向方向，避免立刻又被
        # 朝怪物方向拉回墙边（保持按住反向键）
        if now >= self._stuck_reverse_until:
            self._keys.hold_dir(move_dir)

    def idle_wander(self, now, cur, frame_count):
        """无怪物时：按住方向键持续随机左右移动（不松开），防掉线。

        Args:
            now: 当前时间戳
            cur: 当前玩家位置 (x, y)（检测坐标系），为 None 时跳过卡住检测
            frame_count: 当前帧计数（降频日志）
        """
        # 卡住检测：移动被阻挡立即向相反方向移动（也会自动初始化基准点）
        self.check_stuck_and_reverse(now, cur)

        # 初次进入或随机切换周期到，随机换方向（按住不松开）
        if (self._keys.held_move_key is None
                or now >= self._move_switch_at):
            new_dir = random.choice([config.KEY_LEFT, config.KEY_RIGHT])
            self._keys.hold_dir(new_dir)
            self._move_switch_at = now + jitter(config.IDLE_SWITCH_INTERVAL,
                                                config.IDLE_SWITCH_JITTER)
            self._last_move_pos = cur
            self._stuck_base_dir = new_dir
            self._move_stuck_check_at = (now +
                                         config.MOVE_STUCK_CHECK_INTERVAL)
            if frame_count % config.LOG_FRAME_INTERVAL == 0:
                self.log.info(
                    f"空闲随机移动（按住"
                    f"{'右' if new_dir == config.KEY_RIGHT else '左'}，"
                    f"下次切换约 {self._move_switch_at - now:.1f}s 后）")

    def keep_centered(self, now, px, left_boundary, right_boundary):
        """玩家居中校正：玩家 X 进入检测框最左/最右区域时，立即按住朝中间区域
        的方向键回中，返回 True 表示已接管移动方向。

        检测区域按宽度分为若干块（默认等价于均分 5 块）：玩家在中间区域
        （left_boundary 与 right_boundary 之间）时不做任何调整；进入最左区域
        （px < left_boundary）按住右方向键，进入最右区域
        （px > right_boundary）按住左方向键，尽量让玩家保持在中间区域活动。

        主决策循环先于朝怪移动/空闲随机移动调用本方法（优先级最高），
        但遵循 _stuck_reverse_until 反向脱困保护：刚反向脱困的一段时间内
        不覆盖方向，避免回中方向把刚脱困的玩家又拉回墙边。

        Args:
            now: 当前时间戳
            px: 当前玩家中心 X（检测坐标系）
            left_boundary: 左块与中间块的分界 X（检测坐标系）
            right_boundary: 中间块与右块的分界 X（检测坐标系）

        Returns:
            True 表示玩家已进入左/右块，已按住回中方向键（本帧不再做追怪/随机移动）；
            False 表示玩家在中间块内（或处于反向脱困保护期），未接管。
        """
        # 反向脱困保护期内不覆盖方向，让反向移动先跑完脱困
        if now < self._stuck_reverse_until:
            return False
        if px < left_boundary:
            center_dir = config.KEY_RIGHT  # 进入左块 → 往右回中
        elif px > right_boundary:
            center_dir = config.KEY_LEFT   # 进入右块 → 往左回中
        else:
            # 在中间块内，清除回中状态（下次进入左/右块时重新记日志）
            self._centering_dir = None
            return False
        self._keys.hold_dir(center_dir)
        # 换向/重新进入时各记一次日志，避免每帧刷屏
        if self._centering_dir != center_dir:
            self.log.info(
                f"玩家进入检测框"
                f"{'左' if center_dir == config.KEY_RIGHT else '右'}区"
                f"（px={px:.0f}，中区 [{left_boundary:.0f}, "
                f"{right_boundary:.0f}]），按住"
                f"{'右' if center_dir == config.KEY_RIGHT else '左'}回中")
            self._centering_dir = center_dir
        return True

    # ------------------------------------------------------------------ #
    #  卡住检测
    # ------------------------------------------------------------------ #

    def check_stuck_and_reverse(self, now, cur):
        """卡住检测：移动被阻挡（坐标长时间没变）时，立即向相反方向移动。

        每个检查周期开始时记录一次基准点；周期结束时用当前坐标与基准点
        比较位移，若小于 MOVE_STUCK_THRESHOLD 判定为撞墙/被阻挡，立刻向
        相反方向按住移动并跳一下脱困。按住方向一变就重置基准点重新计时。

        注意：基准点只在换方向/缺失时刷新，检查周期内保持不动，否则每帧
        刷新基准点会导致"坐标始终没变"永远测不出来（修过的旧 bug）。

        Args:
            now: 当前时间戳
            cur: 当前玩家位置 (x, y)（检测坐标系），为 None 时跳过

        Returns:
            True 表示本次触发了反向移动；False 表示正常/已初始化
        """
        held = self._keys.held_move_key
        if cur is None or held is None:
            return False
        # 基准点缺失，或按住方向已变（刚换方向）→ 记录基准点并开始新周期
        if (self._last_move_pos is None
                or self._stuck_base_dir != held):
            self._last_move_pos = cur
            self._stuck_base_dir = held
            self._move_stuck_check_at = now + config.MOVE_STUCK_CHECK_INTERVAL
            return False
        # 检查周期未到：保持基准点不动，什么都不做
        if now < self._move_stuck_check_at:
            return False

        # 到检查点：比较当前坐标与周期开始时的基准点（整周期位移）
        moved = (abs(cur[0] - self._last_move_pos[0]) +
                 abs(cur[1] - self._last_move_pos[1]))
        # 刷新下一个周期的基准点（以当前坐标为准）
        self._last_move_pos = cur
        self._move_stuck_check_at = now + config.MOVE_STUCK_CHECK_INTERVAL
        if moved >= config.MOVE_STUCK_THRESHOLD:
            # 正常移动中
            return False

        # 坐标长时间没变，撞墙/被阻挡 → 立即向相反方向移动
        opp = (config.KEY_RIGHT if held == config.KEY_LEFT
               else config.KEY_LEFT)
        self._keys.hold_dir(opp)
        self._stuck_base_dir = opp
        # 重置随机切换时间点，避免反向后立刻又被随机切换覆盖
        self._move_switch_at = now + jitter(config.IDLE_SWITCH_INTERVAL,
                                            config.IDLE_SWITCH_JITTER)
        # 记录反向脱困时刻：该时长内不让他处逻辑覆盖反向方向
        self._stuck_reverse_until = now + config.STUCK_REVERSE_HOLD_TIME
        self.log.info(f"移动被阻挡（{config.MOVE_STUCK_CHECK_INTERVAL:.0f}s 位移 "
                      f"{moved}px），立即反向按住"
                      f"{'右' if opp == config.KEY_RIGHT else '左'}")
        return True

    def keep_in_range(self, now, px):
        """水平移动范围限制：玩家 X 相对启动基准越出单侧上限时立即反向。

        仅对指定怪物分类（--monster lvmogu）启用时由主决策循环调用。
        基准位置（_range_anchor_x）取首次调用时的玩家 X；玩家向左/右各最多
        移动 move_limit_pixels 像素，到达边界立即向相反方向按住。

        与卡住反向脱困（check_stuck_and_reverse）同一套状态机制：
        - 反向按住并刷新卡住检测基准点，避免刚反向又被误判"卡住"；
        - 重置随机切换时间点，避免刚反向立刻又被随机移动切换覆盖；
        - 记录反向时刻 _stuck_reverse_until（MOVE_LIMIT_REVERSE_HOLD_TIME），
          期间不让他处逻辑（如朝怪物方向移动）覆盖反向方向。

        Args:
            now: 当前时间戳
            px: 当前玩家中心 X（检测坐标系）

        Returns:
            True 表示本次触发了反向；False 表示正常/已初始化/未按住方向键
        """
        if self._range_anchor_x is None:
            self._range_anchor_x = px
            return False
        held = self._keys.held_move_key
        if held is None:
            return False
        lo = self._range_anchor_x - config.MOVE_LIMIT_PIXELS
        hi = self._range_anchor_x + config.MOVE_LIMIT_PIXELS
        opp = None
        if held == config.KEY_RIGHT and px >= hi:
            opp = config.KEY_LEFT
        elif held == config.KEY_LEFT and px <= lo:
            opp = config.KEY_RIGHT
        if opp is None:
            return False
        self._keys.hold_dir(opp)
        self._stuck_base_dir = opp
        self._last_move_pos = None  # 重置卡住检测基准点，反向重新计时
        self._move_stuck_check_at = now + config.MOVE_STUCK_CHECK_INTERVAL
        # 重置随机切换时间点，避免反向后立刻又被随机移动切换覆盖
        self._move_switch_at = now + jitter(config.IDLE_SWITCH_INTERVAL,
                                            config.IDLE_SWITCH_JITTER)
        self._stuck_reverse_until = now + config.MOVE_LIMIT_REVERSE_HOLD_TIME
        self.log.info(f"超出水平移动范围（单侧 "
                      f"{config.MOVE_LIMIT_PIXELS}px，px={px:.0f}），反向按住"
                      f"{'右' if opp == config.KEY_RIGHT else '左'}")
        return True

    # ------------------------------------------------------------------ #
    #  状态清理
    # ------------------------------------------------------------------ #

    def release_held(self):
        """松开当前按住的方向键，并清空卡住检测基准（避免下次进入时误判）。

        与 KeyControl.release_dir() 搭配使用：本方法只清跟踪状态。
        """
        self._keys.release_dir()
        self._last_move_pos = None
        self._stuck_base_dir = None
        self._stuck_reverse_until = 0.0

    def reset(self):
        """清空全部移动/卡住状态（停止机器人时调用）。

        对应原 _release_all 的状态清理部分；物理按键由
        KeyControl.release_all() 负责，GameBot.stop() 需两者都调。
        """
        self._move_switch_at = 0.0
        self._last_move_pos = None
        self._move_stuck_check_at = 0.0
        self._stuck_base_dir = None
        self._stuck_reverse_until = 0.0
        self._range_anchor_x = None  # 重置移动范围基准，下次启动重新取玩家 X
        self._centering_dir = None  # 清除居中校正方向
