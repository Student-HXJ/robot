"""
宠物喂食模块。

在独立线程中按固定间隔（FEED_PET_INTERVAL）自动按下喂食键，
防止宠物饿死。与 HP/MP 监控同受 F10 控制（GameBot.toggle_hp_mp）。
"""

import logging
import threading
import time

import config


class PetFeeder:
    """宠物喂食器：每隔 FEED_PET_INTERVAL 秒按一次喂食键。"""

    def __init__(self, keys, log=None):
        """
        Args:
            keys: KeyControl 实例（按下喂食键）
            log: 日志器，缺省使用 "GameBot"
        """
        self._keys = keys
        self.log = log or logging.getLogger("GameBot")
        self._stop_event = threading.Event()
        self._thread = None

    def start(self):
        """启动喂食线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止喂食线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self):
        """喂食主循环：开启后等满一个间隔再首次喂食，之后每隔该间隔喂一次。"""
        last_feed = time.time()
        while not self._stop_event.is_set():
            now = time.time()
            if now - last_feed >= config.FEED_PET_INTERVAL:
                self.log.info(f"定时喂食宠物：按 {config.KEY_FEED_PET} "
                              f"(间隔 {config.FEED_PET_INTERVAL / 60:.0f} 分钟)")
                self._keys.key_press(config.KEY_FEED_PET)
                last_feed = now
            time.sleep(1.0)
