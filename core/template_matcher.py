"""
模板匹配模块（玩家/怪物检测共用）。

- TemplateLoader：加载目录下所有图片模板（多尺度 + 镜像 + 预计算灰度）
- match_templates：通用模板匹配（含超大模板回退到整张图的兜底分支）
- non_max_suppression：非极大抑制，合并距离过近的命中
- 分类选择（monster/ 怪物分类、player/ 玩家职业，加载模式一致）：
  list_categories / select_category 为通用实现，
  list_monster_categories / select_monster_category 与
  list_player_categories / select_player_category 是各自的便捷包装。

模板目录基于 config.resource_dir() 解析（项目根目录下的 monster/、player/），
文件可安全放在子包 core/ 中。
"""

import os
from glob import glob

import cv2
import numpy as np

import config


class TemplateLoader:
    """加载指定目录下所有图片模板（多尺度 + 镜像 + 预计算灰度）。

    Attributes:
        dir_name: 模板所在目录名（相对项目根目录，支持 "monster/zhu" 子目录）
        with_mirror: 是否生成水平镜像模板（用于检测朝反方向的物体）
        recursive: 是否递归加载子目录中的模板
    """

    def __init__(self, dir_name, with_mirror=True, recursive=False):
        self.dir_name = dir_name
        self.with_mirror = with_mirror
        self.recursive = recursive

    def load(self, max_width, max_height):
        """加载模板，返回列表 [(tmpl_gray, scale, name, direction), ...]。

        Args:
            max_width: 允许的最大模板宽度（超过则跳过该尺度）
            max_height: 允许的最大模板高度
        """
        tpl_dir = config.resource_dir(self.dir_name)
        if not os.path.isdir(tpl_dir):
            print(f"[WARN] 模板目录不存在: {tpl_dir}")
            return []
        templates = []
        for ext in ("*.png", "*.jpg", "*.jpeg", "*.bmp"):
            pattern = (os.path.join(tpl_dir, "**", ext) if self.recursive else os.path.join(tpl_dir, ext))
            for path in glob(pattern, recursive=self.recursive):
                img = cv2.imread(path, cv2.IMREAD_COLOR)
                if img is None:
                    print(f"[WARN] 无法读取模板: {path}")
                    continue
                img = np.ascontiguousarray(img)
                img_gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                for scale in config.TEMPLATE_SCALES:
                    h, w = img_gray.shape[:2]
                    new_w = max(8, int(w * scale))
                    new_h = max(8, int(h * scale))
                    if new_w > max_width or new_h > max_height:
                        continue
                    resized = cv2.resize(img_gray, (new_w, new_h))
                    templates.append((np.ascontiguousarray(resized), scale, os.path.basename(path), "原"))
                    if self.with_mirror:
                        img_flip = np.ascontiguousarray(cv2.flip(img, 1))
                        img_flip_gray = cv2.cvtColor(img_flip, cv2.COLOR_BGR2GRAY)
                        resized_flip = cv2.resize(img_flip_gray, (new_w, new_h))
                        templates.append((np.ascontiguousarray(resized_flip), scale, os.path.basename(path), "镜像"))
                print(f"[INFO] 加载模板: {os.path.basename(path)} "
                      f"({img.shape[1]}x{img.shape[0]}), "
                      f"镜像={'是' if self.with_mirror else '否'}")
        return templates


def match_templates(screen_gray, templates, threshold, fallback=None, y_offset=0):
    """通用模板匹配。

    Args:
        screen_gray: 灰度截图（通常为紫色框 ROI）
        templates: 模板列表 [(tmpl_gray, scale, name, direction), ...]
        threshold: 匹配阈值
        fallback: 当模板尺寸超过 screen_gray 时，回退到此图（整张 strip）
                  匹配，避免大模板漏检。其命中坐标已是全图坐标（y_offset=0）
        y_offset: screen_gray 命中坐标需要额外加的 Y 偏移（ROI 相对全图）

    Returns:
        命中列表 [(cx, cy, w, h, score, name, direction), ...]
        所有坐标都已统一到 fallback/screen_gray 对应的同一坐标系
    """
    hits = []
    for tmpl_gray, scale, name, direction in templates:
        th, tw = tmpl_gray.shape[:2]
        if th <= screen_gray.shape[0] and tw <= screen_gray.shape[1]:
            result = cv2.matchTemplate(screen_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(result >= threshold)
            for x, y in zip(xs, ys):
                score = result[y, x]
                hits.append((
                    x + tw // 2,
                    y + th // 2 + y_offset,  # cx, cy
                    tw,
                    th,
                    score,
                    name,
                    direction))
        elif (fallback is not None and th <= fallback.shape[0] and tw <= fallback.shape[1]):
            # 模板超高 ROI（一般不会发生，这里仅作安全兜底）
            result = cv2.matchTemplate(fallback, tmpl_gray, cv2.TM_CCOEFF_NORMED)
            ys, xs = np.where(result >= threshold)
            for x, y in zip(xs, ys):
                score = result[y, x]
                hits.append((
                    x + tw // 2,
                    y + th // 2,  # cx, cy
                    tw,
                    th,
                    score,
                    name,
                    direction))
    return hits


def non_max_suppression(hits, distance):
    """非极大抑制：合并距离过近的命中，保留分数最高的。

    Args:
        hits: 命中列表（元素含 (cx, cy, ...)，前两位为中心坐标）
        distance: 最小距离（像素），小于此距离的命中合并

    Returns:
        过滤后的命中列表（按分数降序）
    """
    if not hits:
        return []
    hits.sort(key=lambda h: h[4], reverse=True)  # 按分数降序
    kept = []
    for h in hits:
        cx, cy = h[0], h[1]
        if not any(((cx - k[0])**2 + (cy - k[1])**2)**0.5 < distance for k in kept):
            kept.append(h)
    return kept


# ---------------------------------------------------------------------- #
#  模板分类（monster/、player/ 下的子文件夹）选择
#
#  monster/ 下按怪物种类分子文件夹、player/ 下按职业分子文件夹，二者加载模式
#  完全一致：命令行指定分类名（或 all）→ 跳过交互；否则启动时列出子文件夹菜单
#  供选择；没有子文件夹则回退到整个目录。
# ---------------------------------------------------------------------- #

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")


def _count_images(dir_path):
    """统计目录（含子目录）下的图片数量。"""
    total = 0
    for _, _, files in os.walk(dir_path):
        total += sum(1 for f in files if f.lower().endswith(IMAGE_EXTS))
    return total


def list_categories(root_dir):
    """列出模板根目录下的分类子文件夹。

    Args:
        root_dir: 模板根目录名（相对项目根目录），如 config.MONSTER_DIR /
                  config.PLAYER_DIR

    Returns:
        [(category_name, image_count), ...]，按名称排序；无子文件夹时返回 []
    """
    root = config.resource_dir(root_dir)
    if not os.path.isdir(root):
        return []
    categories = []
    for name in sorted(os.listdir(root)):
        sub = os.path.join(root, name)
        if os.path.isdir(sub):
            categories.append((name, _count_images(sub)))
    return categories


def select_category(root_dir, preset=None, menu_title="分类", noun="分类"):
    """交互式选择模板分类，返回模板目录名（相对项目根目录）。

    Args:
        root_dir: 模板根目录名（相对项目根目录），如 config.MONSTER_DIR /
                  config.PLAYER_DIR
        preset: 预先指定的分类名（命令行参数），命中则跳过交互
        menu_title: 交互菜单标题里描述用途的文字（如 "要检测的怪物分类"）
        noun: 日志/提示中使用的名词（如 "怪物分类" / "玩家职业"）

    Returns:
        目录名，例如 "monster/zhu"、"player/binglei"；若无子文件夹或选择
        "全部"则返回 root_dir；用户输入 q 取消时返回 None
    """
    categories = list_categories(root_dir)
    if not categories:
        print(f"[INFO] {root_dir}/ 下未发现分类子文件夹，"
              "使用整个目录的模板")
        return root_dir

    names = [c[0] for c in categories]

    # 命令行预设优先
    if preset:
        if preset in names:
            print(f"[INFO] 使用指定{noun}: {preset}")
            return f"{root_dir}/{preset}"
        if preset.lower() in ("all", "全部"):
            print(f"[INFO] 使用全部{noun}")
            return root_dir
        print(f"[WARN] 指定的{noun}不存在: {preset}，改为手动选择")

    print("=" * 60)
    print(f"  请选择本次{menu_title}")
    print("=" * 60)
    for i, (name, count) in enumerate(categories, start=1):
        print(f"  [{i}] {name}  ({count} 张模板)")
    print(f"  [0] 全部（加载 {root_dir}/ 下所有分类）")
    print("  [q] 取消启动")
    print("=" * 60)

    while True:
        try:
            raw = input(f"请输入序号 (0-{len(categories)}, q=取消): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[INFO] 已取消选择")
            return None
        if not raw:
            continue
        if raw.lower() in ("q", "quit", "exit", "取消"):
            print("[INFO] 已取消选择")
            return None
        # 支持直接输入分类名
        if raw in names:
            print(f"[INFO] 已选择{noun}: {raw}")
            return f"{root_dir}/{raw}"
        if not raw.isdigit():
            print("[WARN] 输入无效，请输入列表中的序号或分类名")
            continue
        idx = int(raw)
        if idx == 0:
            print("[INFO] 已选择: 全部分类")
            return root_dir
        if 1 <= idx <= len(categories):
            chosen = categories[idx - 1][0]
            print(f"[INFO] 已选择{noun}: {chosen}")
            return f"{root_dir}/{chosen}"
        print("[WARN] 序号超出范围，请重新输入")


def list_monster_categories():
    """列出 monster/ 目录下的怪物分类子文件夹。

    Returns:
        [(category_name, image_count), ...]，按名称排序；无子文件夹时返回 []
    """
    return list_categories(config.MONSTER_DIR)


def select_monster_category(preset=None):
    """交互式选择要检测的怪物分类，返回模板目录名（相对项目根目录）。

    Args:
        preset: 预先指定的分类名（命令行参数），命中则跳过交互

    Returns:
        目录名，例如 "monster/zhu"；若无子文件夹或选择"全部"则返回 "monster"；
        用户输入 q 取消时返回 None
    """
    return select_category(config.MONSTER_DIR, preset,
                           menu_title="要检测的怪物分类", noun="怪物分类")


def list_player_categories():
    """列出 player/ 目录下的玩家职业分类子文件夹。

    Returns:
        [(category_name, image_count), ...]，按名称排序；无子文件夹时返回 []
    """
    return list_categories(config.PLAYER_DIR)


def select_player_category(preset=None):
    """交互式选择要使用的玩家职业，返回模板目录名（相对项目根目录）。

    Args:
        preset: 预先指定的职业名（命令行参数 --player），命中则跳过交互

    Returns:
        目录名，例如 "player/binglei"；若无子文件夹或选择"全部"则返回
        "player"（递归加载所有职业）；用户输入 q 取消时返回 None
    """
    return select_category(config.PLAYER_DIR, preset,
                           menu_title="要使用的玩家职业", noun="玩家职业")
