"""
玩家检测模块。

在截图检测区域范围内用玩家模板做模板匹配，定位玩家位置。
与怪物检测共用 template_matcher 的匹配/抑制工具。

玩家模板按职业分子文件夹存放在 player/ 下（如 player/binglei、
player/huodu、player/xiake），由启动参数 --player 选定后只加载对应职业
的模板，加载模式与 monster/ 的怪物分类完全一致。
"""

import cv2

import config
from core.template_matcher import (TemplateLoader, match_templates, non_max_suppression)


class PlayerDetector:
    """玩家检测器。

    在整个截图条范围内检测玩家（左右两边仅各留 PLAYER_DETECT_X_SHRINK
    像素边距，避免贴边误匹配），覆盖玩家可能出现的任意水平位置。

    玩家模板与怪物模板采用同一套加载模式：player/ 下按职业分子文件夹
    （如 player/binglei），启动时选定一个职业只加载该子目录的模板。
    """

    def __init__(self, max_width, max_height, player_dir=None):
        """
        Args:
            max_width: 允许的最大模板宽度（超过则跳过该尺度）
            max_height: 允许的最大模板高度
            player_dir: 玩家模板目录（相对项目根目录），例如 "player/binglei"。
                        为 None 时使用整个 player/ 目录（递归加载所有职业）。
        """
        self._max_width = max_width
        self._max_height = max_height
        self.player_dir = player_dir or config.PLAYER_DIR
        self.templates = []
        # 加载玩家模板（含镜像，玩家也可能朝右）
        self.set_player_dir(self.player_dir)

    def set_player_dir(self, player_dir):
        """切换玩家职业并重新加载模板（可在运行前随时调用）。

        Args:
            player_dir: 玩家模板目录（相对项目根目录），如 "player/binglei"；
                        传 config.PLAYER_DIR 时递归加载所有职业。

        Returns:
            加载到的模板数量
        """
        self.player_dir = player_dir or config.PLAYER_DIR
        # 选中具体职业时只加载该子目录；选择"全部"时递归加载所有职业
        recursive = (self.player_dir == config.PLAYER_DIR)
        print(f"[INFO] 玩家模板目录: {self.player_dir}"
              f"{'（递归所有职业）' if recursive else ''}")
        self.templates = TemplateLoader(self.player_dir, with_mirror=True, recursive=recursive).load(self._max_width, self._max_height)
        if not self.templates:
            print(f"[WARN] 未加载到任何玩家模板！请检查 {self.player_dir}/ 目录")
        return len(self.templates)

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
        hits = match_templates(search_region, self.templates, config.PLAYER_MATCH_THRESHOLD)
        hits = non_max_suppression(hits, config.NMS_DISTANCE)
        if not hits:
            return None
        cx, cy, w, h, score, name, direction = hits[0]
        cx += x_start  # 坐标偏移回全图
        return (cx, cy, cx - w // 2, cy - h // 2, w, h, score)
