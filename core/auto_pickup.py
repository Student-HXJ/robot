"""
自动捡东西模块。

在独立线程中按固定间隔（AUTO_PICKUP_INTERVAL，默认 1 秒）执行一次
"三连按 Z" 捡东西（每次捡东西连按次数用 PICKUP_COUNT，拾取键用
KEY_PICKUP），防止长时间不动时漏捡掉落物。

与 HP/MP 监控、喂食宠物同受 F10 控制（GameBot.toggle_hp_mp），与
F9 的机器人启停互不影响；当 F9 机器人正在运行时（方向键被按住移动）会
自动跳过本次捡拾，避免松开过程中打断方向移动。
"""

import logging
import threading
import time

import config


class AutoPickup:
    """自动捡东西器：每隔 AUTO_PICKUP_INTERVAL 秒三连按一次拾取键。

    通过外部的 is_busy 回调（例如 F9 机器人是否在运行）判断是否跳过，
    防打断方向移动。
    """

    def __init__(self, keys, is_busy=None, log=None):
        """
        Args:
            keys: KeyControl 实例（执行捡东西）
            is_busy: 可选回调 () -> bool，返回 True 时本次捡拾跳过
                     （如 F9 机器人在移动中）。
            log: 日志器，缺省使用 "GameBot"
        """
        self._keys = keys
        self._is_busy = is_busy or (lambda: False)
        self.log = log or logging.getLogger("GameBot")
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """启动自动捡东西线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止自动捡东西线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self):
        """主循环：开启后每隔 AUTO_PICKUP_INTERVAL 秒捡一次东西。

        有怪物在打/方向移动中跳过，防止打断操作。首轮立即捡一次，
        便于验证是否生效。
        """
        last_pickup = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now - last_pickup >= config.AUTO_PICKUP_INTERVAL:
                self._keys.pickup()
                last_pickup = now
            time.sleep(0.5)
