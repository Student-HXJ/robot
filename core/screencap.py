"""
屏幕截图模块。

封装 mss 截图库：负责创建/释放截屏上下文，并提供区域截图能力。
所有需要截屏的模块（检测器、HP/MP 监控）应复用同一个 ScreenCapture 实例。

抓图前先把游戏窗口切到前台（config.GAME_WINDOW_KEYWORD）：全屏/被遮挡时
避免抓到桌面或其他窗口。窗口句柄首次抓图时查找并缓存，之后每次抓图只做
轻量的 SetForegroundWindow。
"""

import threading

import mss
import numpy as np

import config
from core.win_window import bring_to_front, find_game_window_hwnd


class ScreenCapture:
    """屏幕截图封装。

    用法：先 ``grab_region(region)`` 获取指定屏幕区域的 BGR 图，
    用完调用 ``close()`` 释放资源（幂等，可安全多次调用）。
    """

    def __init__(self):
        self._sct = mss.mss()
        self._closed = False
        # 游戏窗口句柄缓存：首次抓图时查找一次，避免每帧枚举全部窗口
        self._game_hwnd = None
        self._hwnd_searched = False
        self._hwnd_lock = threading.Lock()

    def _activate_game_window(self):
        """抓图前把游戏窗口切到前台（全屏时避免抓到桌面/被遮挡窗口）。

        首次抓图时按 config.GAME_WINDOW_KEYWORD 枚举查找并缓存句柄；
        之后每次只做轻量的 bring_to_front（最小化先还原）。任何失败
        静默忽略，不影响抓图。
        """
        try:
            if not self._hwnd_searched:
                with self._hwnd_lock:
                    if not self._hwnd_searched:
                        self._game_hwnd = find_game_window_hwnd(config.GAME_WINDOW_KEYWORD)
                        self._hwnd_searched = True
            if self._game_hwnd:
                bring_to_front(self._game_hwnd)
        except Exception:
            pass  # 激活失败不应影响抓图

    def grab_region(self, region):
        """截取指定屏幕区域。

        Args:
            region: (left, top, width, height) 屏幕绝对坐标

        Returns:
            np.ndarray: BGR 彩色图像（C 连续内存，可直接用于 OpenCV）
        """
        self._activate_game_window()
        left, top, w, h = region
        shot = self._sct.grab({"left": left, "top": top, "width": w, "height": h})
        return np.ascontiguousarray(np.array(shot)[:, :, :3])

    def primary_size(self):
        """主显示器分辨率。

        Returns:
            (width, height) 主显示器尺寸（像素）
        """
        mon = self._sct.monitors[1]
        return mon["width"], mon["height"]

    def close(self):
        """释放截屏资源（幂等）。"""
        if not self._closed:
            self._closed = True
            self._sct.close()
