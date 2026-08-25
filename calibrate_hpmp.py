"""HP/MP 血条区域校准工具。

用法：
    python calibrate_hpmp.py

运行后会：
  1. 截取全屏并显示（matplotlib 窗口）
  2. 让你依次用鼠标拖拽框选 HP 血条区域、MP 血条区域
  3. 把区域截图保存为 debug_hp.png / debug_mp.png 供核对
  4. 打印推荐的 HP_BAR_REGION / MP_BAR_REGION 坐标（left, top, width, height）

若没有 GUI 环境（如远程/无显示器），会自动改用全屏 + 鼠标坐标打印方式。
"""

import os
import sys
import traceback

import numpy as np
import mss
import cv2

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def grab_fullscreen():
    with mss.mss() as sct:
        mon = sct.monitors[0]  # 全屏
        shot = sct.grab(mon)
        img = np.array(shot)[:, :, :3]
        img = np.ascontiguousarray(img)
    return img  # BGR


def save_debug(img, bar_type):
    path = os.path.join(SCRIPT_DIR, f"debug_{bar_type}.png")
    cv2.imwrite(path, img)
    print(f"[INFO] 已保存 {path} ({img.shape[1]}x{img.shape[0]})")


def try_gui_select(full_img):
    """尝试用 matplotlib 交互框选；成功返回 (hp_region, mp_region)，失败返回 None。"""
    try:
        import matplotlib
        matplotlib.use("TkAgg")
        import matplotlib.pyplot as plt
        from matplotlib.widgets import RectangleSelector
    except Exception as e:
        print(f"[WARN] 无法加载 GUI 框选（{e}），改用坐标输入方式")
        return None

    regions = {}
    order = [("hp", "HP"), ("mp", "MP")]

    for key, label in order:
        fig, ax = plt.subplots(figsize=(12, 7))
        # BGR -> RGB 显示
        ax.imshow(cv2.cvtColor(full_img, cv2.COLOR_BGR2RGB))
        ax.set_title(f"拖拽框选 {label} 血条区域，框好后关闭窗口（或按 Enter）")
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
        crop = full_img[top:top + h, left:left + w]
        save_debug(crop, key)

    return regions


def manual_select(full_img):
    """无 GUI 时，让用户根据屏幕坐标手动输入。"""
    h, w = full_img.shape[:2]
    print(f"[INFO] 全屏尺寸: {w} x {h}")
    print("请在游戏里把血条位置记下来，或直接输入屏幕坐标（左上角原点）。")
    regions = {}
    for key, label in [("hp", "HP"), ("mp", "MP")]:
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
        crop = full_img[top:top + hh, left:left + ww]
        save_debug(crop, key)
    return regions


def main():
    print("=" * 60)
    print("  HP/MP 血条校准工具")
    print("=" * 60)
    print("[INFO] 请在游戏窗口处于正常显示状态时运行本工具")

    full = grab_fullscreen()
    full_path = os.path.join(SCRIPT_DIR, "debug_fullscreen.png")
    cv2.imwrite(full_path, full)
    print(f"[INFO] 全屏已保存: {full_path}（可打开查看血条位置）")

    regions = try_gui_select(full)
    if regions is None:
        regions = manual_select(full)

    if not regions:
        print("[WARN] 未获取任何区域")
        return

    print()
    print("=" * 60)
    print("  校准结果（复制到 config.toml 的 [hpmp] 节 hp_bar_region / mp_bar_region）")
    print("  同时把当前游戏窗口位置填入 [auto_calibrate] 节的 ref_window = [left, top, width, height]")
    print("=" * 60)
    for key, (left, top, w, h) in regions.items():
        print(f"  {key.upper()}_BAR_REGION = ({left}, {top}, {w}, {h})")
    print("=" * 60)
    print("已生成 debug_hp.png / debug_mp.png，请核对其中的血条是否完整、颜色正常。")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
