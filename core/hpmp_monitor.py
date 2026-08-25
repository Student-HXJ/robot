"""
HP/MP 监控模块（加血加蓝）。

采样血条/蓝条区域的颜色比例得到当前百分比，低于阈值时自动按补药键。
运行在独立线程中，与机器人主循环解耦——停止机器人后仍可继续监控。

血条区域（HP_BAR_REGION / MP_BAR_REGION）是机器/分辨率相关的：
基础坐标用 calibrate_hpmp.py 校准后填入 config.py；按 F10 开启加血加蓝时
auto_calibrate.calibrate_hpmp() 会按当前游戏窗口自动重算血条坐标。
"""

import logging
import threading
import time

import cv2
import numpy as np

import config
from core.utils import project_path


def calc_bar_percent(img_bgr, bar_type='hp'):
    """计算血条百分比（纯函数，供 HPMPMonitor 与自动校准共用）。

    通过 HSV 颜色识别血条像素宽度占区域总宽度的比例。

    Args:
        img_bgr: 血条区域截图（BGR）
        bar_type: 'hp' 或 'mp'

    Returns:
        0.0 ~ 100.0
    """
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
    if bar_type == 'hp':
        mask1 = cv2.inRange(hsv, config.HP_COLOR_LOWER,
                            config.HP_COLOR_UPPER)
        mask2 = cv2.inRange(hsv, config.HP_COLOR_LOWER2,
                            config.HP_COLOR_UPPER2)
        mask = cv2.bitwise_or(mask1, mask2)
    else:
        mask = cv2.inRange(hsv, config.MP_COLOR_LOWER,
                           config.MP_COLOR_UPPER)
    col_counts = np.count_nonzero(mask, axis=0)
    total = len(col_counts)
    if total == 0:
        return 0.0
    nonzero = np.nonzero(col_counts > mask.shape[0] * 0.3)[0]
    if len(nonzero) == 0:
        return 0.0
    width = nonzero[-1] - nonzero[0] + 1
    return max(0.0, min(100.0, (width / total) * 100))


def save_bar_debug(img_bgr, bar_type, pct, log=None):
    """保存血条/蓝条分析截图，便于排查识别问题（模块级，供诊断脚本复用）。

    输出两张图到项目根目录：
      - debug_<bar>.png       : 原始区域截图
      - debug_<bar>_mask.png  : 叠加识别到的条像素（高亮）+ 左右边界线 + 百分比

    Args:
        img_bgr: 血条区域截图（BGR）
        bar_type: 'hp' 或 'mp'
        pct: 已计算出的百分比（画在图上）
        log: 日志器（缺省使用 "GameBot"）；存图失败不应影响主循环，仅告警
    """
    logger = log or logging.getLogger("GameBot")
    try:
        cv2.imwrite(project_path(f"debug_{bar_type}.png"), img_bgr)

        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        if bar_type == 'hp':
            mask1 = cv2.inRange(hsv, config.HP_COLOR_LOWER,
                                config.HP_COLOR_UPPER)
            mask2 = cv2.inRange(hsv, config.HP_COLOR_LOWER2,
                                config.HP_COLOR_UPPER2)
            mask = cv2.bitwise_or(mask1, mask2)
            color = (0, 0, 255)  # 红：HP
        else:
            mask = cv2.inRange(hsv, config.MP_COLOR_LOWER,
                               config.MP_COLOR_UPPER)
            color = (255, 0, 0)  # 蓝：MP

        overlay = img_bgr.copy()
        overlay[mask > 0] = color
        col_counts = np.count_nonzero(mask, axis=0)
        total = len(col_counts)
        if total > 0:
            nonzero = np.nonzero(col_counts > mask.shape[0] * 0.3)[0]
            if len(nonzero) > 0:
                left_x, right_x = int(nonzero[0]), int(nonzero[-1])
                cv2.line(overlay, (left_x, 0),
                         (left_x, overlay.shape[0]), (0, 255, 0), 1)
                cv2.line(overlay, (right_x, 0),
                         (right_x, overlay.shape[0]), (0, 255, 0), 1)
        cv2.putText(overlay, f"{bar_type.upper()}: {pct:.1f}%", (4, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        cv2.imwrite(project_path(f"debug_{bar_type}_mask.png"), overlay)
    except Exception as e:  # 调试存图失败不应影响主循环
        logger.warning(f"保存 {bar_type} 调试截图失败: {e}")


class HPMPMonitor:
    """HP/MP 监控：血条识别 + 补药。

    Attributes:
        hp_pct / mp_pct: 最近一次采样的血量/蓝量百分比（0~100）
    """

    def __init__(self, cap, keys, log=None):
        """
        Args:
            cap: ScreenCapture 实例（血条区域截图）
            keys: KeyControl 实例（按下补药键）
            log: 日志器，缺省使用 "GameBot"
        """
        self._cap = cap
        self._keys = keys
        self.log = log or logging.getLogger("GameBot")

        self.hp_pct = 100.0
        self.mp_pct = 100.0
        self._last_hp_potion = 0.0  # 上次补血时间戳
        self._last_mp_potion = 0.0  # 上次补蓝时间戳

        self._stop_event = threading.Event()
        self._thread = None

    # ------------------------------------------------------------------ #
    #  线程控制（F10 开关）
    # ------------------------------------------------------------------ #

    def start(self):
        """启动监控线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止监控线程。"""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _loop(self):
        """监控主循环：按 HP_MP_CHECK_INTERVAL 间隔采样检查。"""
        last_check = 0.0
        while not self._stop_event.is_set():
            now = time.time()
            if now - last_check >= config.HP_MP_CHECK_INTERVAL:
                try:
                    self._check_hp_mp()
                except Exception as e:
                    self.log.error(f"HP/MP 检查异常: {e}")
                last_check = now
            time.sleep(0.1)

    # ------------------------------------------------------------------ #
    #  血条识别
    # ------------------------------------------------------------------ #

    def _calc_bar_percent(self, img_bgr, bar_type='hp'):
        """计算血条百分比（委托 calc_bar_percent 纯函数）。"""
        return calc_bar_percent(img_bgr, bar_type)

    # ------------------------------------------------------------------ #
    #  补药决策
    # ------------------------------------------------------------------ #

    def _check_hp_mp(self):
        """采样一次 HP/MP，低于阈值且冷却结束时补药。"""
        hp_img = self._cap.grab_region(config.HP_BAR_REGION)
        mp_img = self._cap.grab_region(config.MP_BAR_REGION)
        self.hp_pct = self._calc_bar_percent(hp_img, 'hp')
        self.mp_pct = self._calc_bar_percent(mp_img, 'mp')
        # 保存 HP/MP 分析截图（开关控制，用于排查识别问题）
        if config.SAVE_HP_MP_DEBUG:
            save_bar_debug(hp_img, 'hp', self.hp_pct, log=self.log)
            save_bar_debug(mp_img, 'mp', self.mp_pct, log=self.log)
        now = time.time()

        if 0 < self.hp_pct <= config.HP_THRESHOLD:
            if now - self._last_hp_potion > config.POTION_COOLDOWN:
                self.log.info(
                    f"HP {self.hp_pct:.1f}% <= {config.HP_THRESHOLD}%，"
                    f"按 {config.KEY_HP_POTION} 补血")
                self._keys.key_press(config.KEY_HP_POTION)
                self._last_hp_potion = now
        if 0 < self.mp_pct <= config.MP_THRESHOLD:
            if now - self._last_mp_potion > config.POTION_COOLDOWN:
                self.log.info(
                    f"MP {self.mp_pct:.1f}% <= {config.MP_THRESHOLD}%，"
                    f"按 {config.KEY_MP_POTION} 补蓝")
                self._keys.key_press(config.KEY_MP_POTION)
                self._last_mp_potion = now
