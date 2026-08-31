"""
玩家检测模块。

在截图检测区域范围内用玩家模板做模板匹配，定位玩家位置。
与怪物检测共用 template_matcher 的匹配/抑制工具。
"""

import cv2

import config
from core.template_matcher import (TemplateLoader, match_templates,
                                   non_max_suppression)


class PlayerDetector:
    """玩家检测器。

    在整个截图条范围内检测玩家（左右两边仅各留 PLAYER_DETECT_X_SHRINK
    像素边距，避免贴边误匹配），覆盖玩家可能出现的任意水平位置。
    """

    def __init__(self, max_width, max_height):
        # 加载玩家模板（含镜像，玩家也可能朝右）
        self.templates = TemplateLoader(config.PLAYER_DIR,
                                        with_mirror=True).load(
                                            max_width, max_height)
        if not self.templates:
            print("[WARN] 未加载到任何玩家模板！请检查 player/ 目录")

    def find(self, screen_gray):
        """检测玩家位置。

        Args:
            screen_gray: 截图检测区域灰度图

        Returns:
            (cx, cy, x, y, w, h, score) 或 None
            cx/cy 为玩家中心坐标（全图坐标系），x/y 为检测框左上角。
        """
        h, w = screen_gray.shape[:2]
        x_start = config.PLAYER_DETECT_X_SHRINK
        x_end = w - config.PLAYER_DETECT_X_SHRINK
        search_region = screen_gray[:, x_start:x_end]
        hits = match_templates(search_region, self.templates,
                               config.PLAYER_MATCH_THRESHOLD)
        hits = non_max_suppression(hits, config.NMS_DISTANCE)
        if not hits:
            return None
        cx, cy, w, h, score, name, direction = hits[0]
        cx += x_start  # 坐标偏移回全图
        return (cx, cy, cx - w // 2, cy - h // 2, w, h, score)
