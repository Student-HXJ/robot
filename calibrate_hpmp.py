"""HP/MP 血条 + 检测区域校准与存图校验工具。

用法：
    python calibrate_hpmp.py

运行后会：
  1. 以管理员权限运行（游戏窗口通常为管理员，否则截图会变黑）
  2. 按 config.toml 的 game_window_keyword 把游戏窗口切到前台
  3. 截取全屏并显示（matplotlib 窗口）
  4. 让你依次用鼠标拖拽框选「检测区域」「HP 血条区域」「MP 血条区域」
  5. 按框选结果存图供人工核对识别是否准确：
       - debug_detect.png                 检测区域裁剪图
       - debug_hp.png / debug_hp_mask.png HP 原图 / 识别掩膜叠加图
       - debug_mp.png / debug_mp_mask.png MP 原图 / 识别掩膜叠加图
       - debug_regions_overview.png       全屏总览（画出三个框，核对是否对准）
  6. 把框选结果写回 config.toml 并打印确认
     （[detect] detect_region 与 [hpmp] hp_bar_region / mp_bar_region）

若没有 GUI 环境（如远程/无显示器），会自动改用全屏 + 鼠标坐标打印方式。
"""

import re
import sys
import time
import traceback

import numpy as np
import mss
import cv2

import config
from core.admin import ensure_admin
from core.win_window import activate_game_window
from core.hpmp_monitor import calc_bar_percent, save_bar_debug
from core.utils import project_path

# 需要框选的区域：(key, 中文标签)。
# detect → [detect] detect_region；hp/mp → [hpmp] hp_bar_region / mp_bar_region。
REGIONS = [
    ("detect", "检测区域"),
    ("hp", "HP 血条"),
    ("mp", "MP 血条"),
]

# 每个 key 对应的 config.toml 变量名（用于打印推荐结果）
OUTPUT_NAMES = {
    "detect": "DETECT_REGION",
    "hp": "HP_BAR_REGION",
    "mp": "MP_BAR_REGION",
}

# 每个 key 的英文标签（matplotlib 窗口标题用；中文标题在部分环境渲染成乱码/方框）
EN_LABELS = {
    "detect": "detection region",
    "hp": "HP bar",
    "mp": "MP bar",
}


def switch_to_game():
    """抓全屏前把游戏窗口切到前台（全屏时避免抓到桌面/被遮挡窗口）。

    关键字取自 config.GAME_WINDOW_KEYWORD（与 screencap 一致）。
    切换失败静默继续（仍会抓屏，只是可能抓到桌面）。
    """
    try:
        keyword = config.GAME_WINDOW_KEYWORD
        if activate_game_window(keyword):
            print(f"[INFO] 已切换到游戏窗口（关键字={keyword}）")
        else:
            print(f"[WARN] 未找到游戏窗口（关键字={keyword}），可能抓到桌面")
        time.sleep(0.5)  # 等窗口真正置前再抓屏
    except Exception as e:
        print(f"[WARN] 切换游戏窗口失败（{e}），继续抓屏")


def grab_fullscreen():
    with mss.mss() as sct:
        mon = sct.monitors[0]  # 全屏
        shot = sct.grab(mon)
        img = np.array(shot)[:, :, :3]
        img = np.ascontiguousarray(img)
    return img  # BGR


def try_gui_select(full_img):
    """尝试用 matplotlib 交互框选；成功返回 {key: region}，失败返回 None。"""
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        from matplotlib.widgets import RectangleSelector
    except Exception as e:
        print(f"[WARN] 无法加载 GUI 框选（{e}），改用坐标输入方式")
        return None

    regions = {}

    for key, label in REGIONS:
        fig, ax = plt.subplots(figsize=(12, 7))
        # BGR -> RGB 显示
        ax.imshow(cv2.cvtColor(full_img, cv2.COLOR_BGR2RGB))
        ax.set_title(f"Drag to select the {EN_LABELS[key]} region, "
                     f"then close the window (or press Enter)")
        rect = {}

        def on_select(eclick, erelease):
            x1, y1 = int(round(eclick.xdata)), int(round(eclick.ydata))
            x2, y2 = int(round(erelease.xdata)), int(round(erelease.ydata))
            left = min(x1, x2)
            top = min(y1, y2)
            w = abs(x2 - x1)
            h = abs(y2 - y1)
            rect["region"] = (left, top, w, h)
            print(f"  {label} 区域: left={left} top={top} w={w} h={h}")

        rs = RectangleSelector(ax,
                               on_select,
                               useblit=True,
                               button=[1],
                               minspanx=5,
                               minspany=5,
                               spancoords="pixels",
                               interactive=True)

        def on_key(event):
            if event.key == "enter":
                plt.close(fig)

        fig.canvas.mpl_connect("key_press_event", on_key)
        plt.show()

        if "region" not in rect:
            print(f"[WARN] 未框选 {label}，跳过")
            continue
        left, top, w, h = rect["region"]
        if w < 5 or h < 5:
            print(f"[WARN] {label} 区域太小，跳过")
            continue
        regions[key] = (left, top, w, h)

    return regions


def manual_select(full_img):
    """无 GUI 时，让用户根据屏幕坐标手动输入。"""
    h, w = full_img.shape[:2]
    print(f"[INFO] 全屏尺寸: {w} x {h}")
    print("请在游戏里把区域位置记下来，或直接输入屏幕坐标（左上角原点）。")
    regions = {}
    for key, label in REGIONS:
        raw = input(f"输入 {label} 区域 (left top width height)，留空跳过: ").strip()
        if not raw:
            continue
        try:
            left, top, ww, hh = (int(x) for x in raw.split())
        except ValueError:
            print(f"[WARN] {label} 输入格式错误，跳过")
            continue
        left = max(0, left)
        top = max(0, top)
        ww = min(ww, w - left)
        hh = min(hh, h - top)
        regions[key] = (left, top, ww, hh)
    return regions


def verify_regions(full_img, regions):
    """按框选结果存图校验识别是否准确（对应原 test_hpmp.py 的存图功能）。

    - detect: 保存原始裁剪图 debug_detect.png
    - hp/mp: 用 config.toml 的 HSV 颜色阈值计算百分比，保存原始图 +
      识别掩膜叠加图（debug_hp.png / debug_hp_mask.png 等）
    - 最后在全屏上画出三个框，保存 debug_regions_overview.png 供核对框是否对准
    """
    print()
    print("[INFO] 正在按框选结果存图校验识别 ...")

    colors = {"detect": (0, 255, 255), "hp": (0, 0, 255), "mp": (255, 0, 0)}
    labels = {"detect": "DETECT", "hp": "HP", "mp": "MP"}

    overview = full_img.copy()
    for key, (left, top, w, h) in regions.items():
        crop = full_img[top:top + h, left:left + w]
        if key == "detect":
            cv2.imwrite(project_path("debug_detect.png"), crop)
            print(f"[INFO] 已保存 debug_detect.png（检测区域裁剪图）")
        else:
            pct = calc_bar_percent(crop, key)
            save_bar_debug(crop, key, pct)
            print(f"[INFO] {key.upper()} 识别 = {pct:.1f}%"
                  f"（见 debug_{key}.png / debug_{key}_mask.png）")
            if pct <= 0:
                print(f"[WARN] {key.upper()} 未识别到血条颜色，框选可能没对准，"
                      "请重新框选")
        # 全屏总览上画框
        cv2.rectangle(overview, (left, top), (left + w, top + h), colors[key], 2)
        cv2.putText(overview, labels[key], (left + 3, max(10, top - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, colors[key], 2)

    cv2.imwrite(project_path("debug_regions_overview.png"), overview)
    print("[INFO] 已保存 debug_regions_overview.png（全屏总览，核对框是否对准）")


def write_to_config(regions):
    """把框选结果写回 config.toml 的 [detect]/[hpmp] 节。

    只替换对应 key 的值（detect_region / hp_bar_region / mp_bar_region），
    保留文件里的中文注释与其他配置。找不到 key 或读写失败时打印警告并跳过，
    不阻塞校准流程。

    Returns:
        list: 成功写入的 toml key 列表（如 ['detect_region', 'hp_bar_region']）
    """
    path = config.CONFIG_PATH
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"[WARN] 读取 {path} 失败（{e}），未写入")
        return []

    updated = []
    for key, (left, top, w, h) in regions.items():
        toml_key = OUTPUT_NAMES[key].lower()  # DETECT_REGION -> detect_region
        # 只匹配 "key = [旧值]"，行尾的中文注释保留不动
        pattern = re.compile(rf"^(\s*{toml_key}\s*=\s*)\[[^\]]*\]", re.MULTILINE)

        def repl(m, _left=left, _top=top, _w=w, _h=h):
            return f"{m.group(1)}[{_left}, {_top}, {_w}, {_h}]"

        new_text, n = pattern.subn(repl, text)
        if n == 0:
            print(f"[WARN] 未在 {path} 中找到 {toml_key}，未写入")
            continue
        text = new_text
        updated.append(toml_key)

    if updated:
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            print(f"[WARN] 写入 {path} 失败（{e}）")
            return []
        print(f"[INFO] 已把坐标写入 {path}: {', '.join(updated)}")
    return updated


def main():
    ensure_admin()
    switch_to_game()

    full = grab_fullscreen()
    full_path = project_path("debug_fullscreen.png")
    cv2.imwrite(full_path, full)

    regions = try_gui_select(full)
    if regions is None:
        regions = manual_select(full)

    if not regions:
        print("[WARN] 未获取任何区域")
        return

    verify_regions(full, regions)
    write_to_config(regions)

if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
