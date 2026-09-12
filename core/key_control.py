"""
按键模拟模块。

封装 pydirectinput，统一处理按键按下/保持/释放、随机抖动，
以及"停止时释放全部按键"。同时是物理按住方向键状态（held_move_key）
的唯一持有者，供 MonsterTracker 读取当前按住的方向。
"""

import logging
import time

import pydirectinput

import config
from core.utils import jitter


class KeyControl:
    """按键模拟封装（pydirectinput）。

    Attributes:
        held_move_key: 当前按住不放的方向键名（'left'/'right' 等），None 表示未按住。
                       只读属性，由 hold_dir/release_dir 维护，MonsterTracker 通过它
                       判断"当前方向"与"方向是否已变"。
    """

    def __init__(self, log=None):
        # 消除 pydirectinput 内置的固定延迟，提高按键响应速度（只在构造时设置一次）
        pydirectinput.PAUSE = config.PYDIRECTINPUT_PAUSE
        self.log = log or logging.getLogger("GameBot")
        # 当前按住不放的方向键（None 表示未按住）
        self._held_move_key = None

    @property
    def held_move_key(self):
        """当前按住不放的方向键名，None 表示未按住。"""
        return self._held_move_key

    # ------------------------------------------------------------------ #
    #  基础按键
    # ------------------------------------------------------------------ #

    def key_press(self, key_name):
        """按下→随机保持→释放。

        Args:
            key_name: pydirectinput 键名，如 'ctrl'、'9'
        """
        try:
            pydirectinput.keyDown(key_name)
            time.sleep(jitter(config.PRESS_DELAY, config.PRESS_JITTER))
            pydirectinput.keyUp(key_name)
        except Exception as e:
            self.log.error(f"按键 {key_name} 异常: {e}")

    def attack(self):
        """攻击。"""
        self.key_press(config.KEY_ATTACK)

    # ------------------------------------------------------------------ #
    #  带朝向的攻击
    # ------------------------------------------------------------------ #

    def attack_toward(self,
                      cx,
                      px,
                      name=None,
                      direction=None,
                      dist=None,
                      score=None,
                      frame_count=0):
        """朝怪物方向攻击：先确保面朝怪物再攻击，绝不朝反方向攻击。

        攻击朝向判定：怪物中心 cx 明显在玩家中心 px 左侧（|cx-px| 超过
        ATTACK_CENTER_OFFSET 死区）按住左、明显在右侧按住右；玩家与怪物
        大致重叠时跟随当前按住方向（无按住则保持原朝向，避免重叠时左右
        抖动/反向）。若当前按住方向已面向怪物（正在朝怪物移动），直接攻击
        不打断移动；否则先松开当前移动键、按住怪物方向键等待转身
        （ATTACK_TURN_DELAY）完成后再攻击，确保攻击时角色已对准怪物方向。

        Args:
            cx, px: 怪物中心 X、玩家中心 X
            name, direction, dist, score: 用于日志的怪物信息
            frame_count: 当前帧计数（用于降频日志）
        """
        if cx < px - config.ATTACK_CENTER_OFFSET:
            face_key = config.KEY_LEFT
        elif cx > px + config.ATTACK_CENTER_OFFSET:
            face_key = config.KEY_RIGHT
        else:
            # 玩家与怪物大致重叠：跟随当前按住方向（无按住则保持原朝向）
            face_key = self._held_move_key

        if face_key is None or self._held_move_key == face_key:
            # 已面朝怪物（或重叠且无需转身）：直接攻击，保持当前移动状态
            self.attack()
        else:
            # 需要转身：松开当前移动键 → 按住怪物方向键 → 等待转身完成 → 攻击
            self.release_dir()
            try:
                pydirectinput.keyDown(face_key)
            except Exception as e:
                self.log.error(f"转身按键 {face_key} 异常: {e}")
                self.attack()  # 转身失败也照常攻击，避免卡死
                return
            time.sleep(config.ATTACK_TURN_DELAY)
            self.attack()
            try:
                pydirectinput.keyUp(face_key)
            except Exception:
                pass
        if frame_count % config.LOG_FRAME_INTERVAL == 0:
            face = ("左" if face_key == config.KEY_LEFT
                    else "右" if face_key == config.KEY_RIGHT else "当前")
            self.log.info(f"朝{face}攻击 {name}({direction}) "
                          f"距离{dist:.0f}px 置信度={score:.2f}")

    # ------------------------------------------------------------------ #
    #  按住方向键（持续移动）与释放
    # ------------------------------------------------------------------ #

    def hold_dir(self, dir_key):
        """按住指定方向键并保持（不松开），记录当前按住的方向。

        若已按住同一方向则什么都不做；若按住的是反方向则先松开再切换。
        """
        if self._held_move_key == dir_key:
            return
        if self._held_move_key is not None:
            try:
                pydirectinput.keyUp(self._held_move_key)
            except Exception:
                pass
        try:
            pydirectinput.keyDown(dir_key)
        except Exception as e:
            self.log.error(f"按住方向键 {dir_key} 异常: {e}")
            return
        self._held_move_key = dir_key

    def release_dir(self):
        """松开当前按住的移动键。

        只负责物理按键与 held_move_key 状态，不清理卡住/随机移动状态
        （那由 MonsterTracker.reset() 负责）。
        """
        if self._held_move_key is not None:
            try:
                pydirectinput.keyUp(self._held_move_key)
            except Exception:
                pass
            self._held_move_key = None

    def release_all(self):
        """释放全部按键（防止卡键）。停止机器人时调用。

        只负责物理按键，卡住/移动状态的清理由 MonsterTracker.reset() 负责。
        """
        self._held_move_key = None
        for key in config.ALL_KEYS:
            try:
                pydirectinput.keyUp(key)
            except Exception:
                pass
