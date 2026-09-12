"""HP/MP 血条框选校准与存图校验工具。

用法：
    python calibrate_hpmp.py

只负责框选「HP/MP 血条框」并写回 [hpmp] hp_bar_region / mp_bar_region
（检测框请用 calibrate_detect.py）。运行后会：
  1. 以管理员权限运行（游戏窗口通常为管理员，否则截图会变黑）
  2. 按 config.toml 的 game_window_keyword 把游戏窗口切到前台
  3. 截取全屏并显示（matplotlib 窗口）
  4. 让你依次用鼠标拖拽框选「HP 血条区域」「MP 血条区域」
  5. 按框选结果存图供人工核对识别是否准确：
       - debug_hp.png / debug_hp_mask.png HP 原图 / 识别掩膜叠加图
       - debug_mp.png / debug_mp_mask.png MP 原图 / 识别掩膜叠加图
       - debug_regions_overview.png       全屏总览（画出两个框，核对是否对准）
  6. 把框选结果写回 config.toml 的 [hpmp] hp_bar_region / mp_bar_region
     并打印确认

若没有 GUI 环境（如远程/无显示器），会自动改用坐标输入方式。

公共流程（切窗口/抓图/框选/存图/写配置）在 core/region_calib.py 中实现，
与 calibrate_detect.py 共用。
"""

import sys
import traceback

from core import region_calib as rc
from core.admin import ensure_admin

# 本脚本只框选血条/蓝条（按顺序框选）
KEYS = ("hp", "mp")

# 本脚本的总览图片名（未改动，保持与旧版一致）
OVERVIEW_NAME = "debug_regions_overview.png"


def main():
    ensure_admin()
    print("=" * 60)
    print("  HP/MP 血条框选校准与存图校验工具")
    print("=" * 60)
    print("[INFO] 请在游戏窗口处于正常显示状态时运行本工具")
    print("[INFO] 请按顺序框选 HP 血条、MP 血条（尽量只框住条本身，"
          "不要带太多背景，否则百分比会偏低）")

    rc.switch_to_game()

    full = rc.grab_fullscreen()
    rc.save_fullscreen(full)

    regions = rc.select_regions(full, KEYS)
    if not regions:
        print("[WARN] 未获取任何血条区域")
        return

    rc.verify_regions(full, regions, OVERVIEW_NAME)
    rc.write_to_config(regions)

    print()
    print("=" * 60)
    print("  校准结果（已写入 config.toml）")
    print("  [hpmp] hp_bar_region / mp_bar_region  →  血条/蓝条区域")
    print("=" * 60)
    for key, region in regions.items():
        print(f"  {rc.OUTPUT_NAMES[key]} = {rc.format_region(region)}")
    print("=" * 60)
    print("  请打开以下截图判定识别是否正确：")
    print("    debug_hp_mask.png / debug_mp_mask.png  <- 红/蓝高亮即识别到的血条")
    print(f"    {OVERVIEW_NAME}             <- 全屏总览（两个框）")
    print("  坐标已写入 config.toml，重启机器人即可生效。")
    print("  若百分比不合理或框没对准，请重新运行并重新框选。")
    print("  检测框请运行: python calibrate_detect.py")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
