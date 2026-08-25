"""
屏幕截图模块。

封装 mss 截图库：负责创建/释放截屏上下文，并提供区域截图能力。
所有需要截屏的模块（检测器、HP/MP 监控）应复用同一个 ScreenCapture 实例。
"""

import mss
import numpy as np


class ScreenCapture:
    """屏幕截图封装。

    用法：先 ``grab_region(region)`` 获取指定屏幕区域的 BGR 图，
    用完调用 ``close()`` 释放资源（幂等，可安全多次调用）。
    """

    def __init__(self):
        self._sct = mss.mss()
        self._closed = False

    def grab_region(self, region):
        """截取指定屏幕区域。

        Args:
            region: (left, top, width, height) 屏幕绝对坐标

        Returns:
            np.ndarray: BGR 彩色图像（C 连续内存，可直接用于 OpenCV）
        """
        left, top, w, h = region
        shot = self._sct.grab({
            "left": left,
            "top": top,
            "width": w,
            "height": h
        })
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
