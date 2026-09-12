"""
辅助技能模块（移动加速 / 攻击加速）。

在独立线程中按各自的固定间隔自动按技能键，与机器人主循环、HP/MP 监控
完全解耦（只共用 KeyControl 发按键）：

- 移动加速技能：每隔 SKILL_MOVE_INTERVAL 秒（默认 200 秒）按 SKILL_KEY_MOVE（默认 a）
- 攻击加速技能：每隔 SKILL_ATTACK_SPEED_INTERVAL 秒（默认 30 秒）按
  SKILL_KEY_ATTACK_SPEED（默认 s）

开启后先等满一个间隔再首次按键（与 PetFeeder 一致），避免和手动施放撞车；
两个技能各自独立计时，互不影响。
"""

import logging
import threading
import time

import config


class AuxSkillCaster:
    """辅助技能定时施放器：定时按移动加速键与攻击加速键。"""

    def __init__(self, keys, log=None):
        """
        Args:
            keys: KeyControl 实例（按下技能键）
            log: 日志器，缺省使用 "GameBot"
        """
        self._keys = keys
        self.log = log or logging.getLogger("GameBot")
        self._stop_event = threading.Event()
        self._thread = None
        self._last_cast = {}  # 技能键 -> 上次施放时间戳

    # ------------------------------------------------------------------ #
    #  线程控制（F11 开关）
    # ------------------------------------------------------------------ #

    def start(self):
        """启动辅助技能线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_cast = {}
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止辅助技能线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    # ------------------------------------------------------------------ #
    #  技能定时
    # ------------------------------------------------------------------ #

    def _skills(self):
        """当前启用的技能列表：[(名称, 按键, 间隔秒), ...]（间隔 <=0 表示禁用）。"""
        return [
            ("移动加速", config.KEY_SKILL_MOVE, config.SKILL_MOVE_INTERVAL),
            ("攻击加速", config.KEY_SKILL_ATTACK_SPEED,
             config.SKILL_ATTACK_SPEED_INTERVAL),
        ]

    def _loop(self):
        """技能主循环：开启后等满各自间隔再首次施放，之后每隔该间隔施放一次。"""
        start = time.time()
        while not self._stop_event.is_set():
            now = time.time()
            for name, key, interval in self._skills():
                if interval <= 0:
                    continue  # 间隔 <=0 视为禁用该技能
                last = self._last_cast.get(key, start)
                if now - last < interval:
                    continue
                self.log.info(f"辅助技能-{name}：按 {key}（间隔 {interval:.0f} 秒）")
                self._keys.key_press(key)
                self._last_cast[key] = now
            time.sleep(0.2)
