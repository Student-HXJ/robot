"""
怪物跟踪模块。

负责"持续按住方向键"的移动决策：
- 玩家框触达检测框最左/最右禁止区域边界 → 立即反向（keep_centered，最高优先级）
- 怪物在攻击范围外 → 按住方向键朝怪物靠近（hold_toward）
- 无怪物时 → 沿持久方向移动（idle_wander），触达禁止区域才反向（替代随机移动）
- 移动被阻挡 → 卡住检测，立即反向脱困（check_stuck_and_reverse）

物理按键由 KeyControl 执行，按住状态（held_move_key）由 KeyControl 持有，
本类通过 ``keys.held_move_key`` 只读判断当前方向，不另存一份。
"""

import logging
import time

import config


class MonsterTracker:
    """怪物跟踪器：追怪靠近/持久方向巡逻/卡住反向脱困。

    Attributes:
        卡住检测状态（仅本类维护，物理按键状态在 KeyControl）：
        - _last_move_pos      上次移动基准点（周期开始时的玩家坐标）
        - _stuck_base_dir     基准点对应的按住方向；方向一变更即重置基准点
        - _move_stuck_check_at 下次卡住检查时间点
        - _stuck_reverse_until 反向脱困后禁止他处逻辑覆盖方向的截止时间
        - _centering_dir      玩家居中校正当前回中方向（None=未在校正），
                              仅用于回中日志降频（换向/进入时各记一次）
        - _phase_dir          五区巡逻持久方向（左/右），触达禁止区域时反向更新
    """

    def __init__(self, keys, log=None):
        """
        Args:
            keys: KeyControl 实例（物理按键执行者，唯一持有 held_move_key）
            log: 日志器，缺省使用 "GameBot"
        """
        self._keys = keys
        self.log = log or logging.getLogger("GameBot")

        # 卡住检测：上次移动时的玩家位置与下次检查时间点
        self._last_move_pos = None
        self._move_stuck_check_at = 0.0
        # 当前基准点对应的按住方向；方向一变更即重置基准点重新计时
        self._stuck_base_dir = None
        # 反向脱困后禁止他处逻辑覆盖方向的截止时间
        self._stuck_reverse_until = 0.0
        # 玩家居中校正当前回中方向（None 表示未在校正），用于回中日志降频
        self._centering_dir = None
        # 五区巡逻持久方向（左/右）：无怪物时沿此方向移动，触达禁止区域才反向
        self._phase_dir = None

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
        """无怪物时：沿持久方向（_phase_dir）移动，不再随机换向，防掉线。

        持久方向初始向右，之后在触达禁止区域（keep_centered）、卡住反向
        （check_stuck_and_reverse）或追怪退出（保持退出时朝向）时被更新，
        实现"一直往一个方向走，直到触达禁止区域才掉头"的巡逻寻路（替代原先
        的随机移动）。刚从追怪退出时若仍按住方向键，则保持该朝向作为新的持久
        方向，不立即切回旧持久方向（对齐"保持退出时的朝向"需求）。

        Args:
            now: 当前时间戳
            cur: 当前玩家位置 (x, y)（检测坐标系），为 None 时跳过卡住检测
            frame_count: 当前帧计数（降频日志）
        """
        # 卡住检测：移动被阻挡立即向相反方向移动（也会自动初始化基准点）
        self.check_stuck_and_reverse(now, cur)

        # 首次进入确定持久方向（默认向右）；之后保持，直到禁区/卡住反向更新
        if self._phase_dir is None:
            self._phase_dir = config.KEY_RIGHT

        # 反向脱困保护期内不覆盖方向，让反向移动先跑完脱困
        if now < self._stuck_reverse_until:
            return

        held = self._keys.held_move_key
        if held != self._phase_dir:
            if held is not None:
                # 刚从追怪退出：保持退出时的朝向（当前按住方向）作为新的持久
                # 方向继续巡逻，不立即切回旧持久方向
                self._phase_dir = held
                if frame_count % config.LOG_FRAME_INTERVAL == 0:
                    self.log.info(
                        f"追怪退出，保持朝向"
                        f"{'右' if held == config.KEY_RIGHT else '左'}巡逻")
            else:
                # 未按住方向键：沿持久方向继续巡逻
                self._keys.hold_dir(self._phase_dir)
                self._last_move_pos = cur
                self._stuck_base_dir = self._phase_dir
                self._move_stuck_check_at = (now +
                                             config.MOVE_STUCK_CHECK_INTERVAL)
                if frame_count % config.LOG_FRAME_INTERVAL == 0:
                    self.log.info(
                        f"空闲巡逻（按住"
                        f"{'右' if self._phase_dir == config.KEY_RIGHT else '左'}）")

    def keep_centered(self, now, px, pw, left_boundary, right_boundary):
        """五区巡逻禁止区域判定：玩家框触达检测框最左/最右禁止区域边界时，立即
        按住朝中间区域的方向键反向，返回 True 表示已接管移动方向。

        检测区域按宽度平均分成 5 块：最左 1/5 与最右 1/5 为禁止区域。玩家框
        左边界触达区块 1 右边界（box_left < left_boundary）按住右、右边界触达
        区块 5 左边界（box_right > right_boundary）按住左，直到触达另一侧禁止
        区域；中间 3/5 自由追怪/沿持久方向移动。用玩家框边界而非中心判定，使
        玩家框不进入禁止区域（仅可触碰其内侧边界）。禁止区域判定优先级最高
        （立即反向），并同步更新持久方向 _phase_dir，使玩家离开禁止区域后继续
        沿反向巡逻。

        Args:
            now: 当前时间戳
            px: 当前玩家中心 X（检测坐标系）
            pw: 当前玩家框宽度（像素）
            left_boundary: 左块与中间块的分界 X（检测坐标系）
            right_boundary: 中间块与右块的分界 X（检测坐标系）

        Returns:
            True 表示玩家框已触达左/右禁止区域边界，已按住反向方向键
            （本帧不再做追怪）；False 表示玩家框在中间块内，未接管。
        """
        box_left = px - pw / 2
        box_right = px + pw / 2
        if box_left < left_boundary:
            center_dir = config.KEY_RIGHT  # 框左边界触达区块1右边界 → 往右反向
        elif box_right > right_boundary:
            center_dir = config.KEY_LEFT   # 框右边界触达区块5左边界 → 往左反向
        else:
            # 玩家框整体在中间块内，清除回中状态（下次触达边界时重新记日志）
            self._centering_dir = None
            return False
        self._keys.hold_dir(center_dir)
        self._phase_dir = center_dir  # 持久方向同步为反向方向
        # 换向/重新触达边界时各记一次日志，避免每帧刷屏
        if self._centering_dir != center_dir:
            self.log.info(
                f"玩家框触达检测框"
                f"{'左' if center_dir == config.KEY_RIGHT else '右'}禁止区边界"
                f"（px={px:.0f}，中区 [{left_boundary:.0f}, "
                f"{right_boundary:.0f}]），按住"
                f"{'右' if center_dir == config.KEY_RIGHT else '左'}反向")
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
        self._phase_dir = opp  # 持久方向同步为反向方向
        # 记录反向脱困时刻：该时长内不让他处逻辑覆盖反向方向
        self._stuck_reverse_until = now + config.STUCK_REVERSE_HOLD_TIME
        self.log.info(f"移动被阻挡（{config.MOVE_STUCK_CHECK_INTERVAL:.0f}s 位移 "
                      f"{moved}px），立即反向按住"
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
        self._last_move_pos = None
        self._move_stuck_check_at = 0.0
        self._stuck_base_dir = None
        self._stuck_reverse_until = 0.0
        self._centering_dir = None  # 清除居中校正方向
        self._phase_dir = None  # 清除五区巡逻持久方向
