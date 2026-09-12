"""检测框（检测区域）框选校准工具。

用法：
    python calibrate_detect.py

只负责框选「检测框」并写回 [detect] detect_region（血条/蓝条请用
calibrate_hpmp.py）。运行后会：
  1. 以管理员权限运行（游戏窗口通常为管理员，否则截图会变黑）
  2. 按 config.toml 的 game_window_keyword 把游戏窗口切到前台
  3. 截取全屏并显示（matplotlib 窗口）
  4. 让你用鼠标拖拽框选「检测区域」（怪物检测 + 五区巡逻共用的区域）
  5. 存图供人工核对：
       - debug_detect.png           检测区域裁剪图
       - debug_detect_overview.png  全屏总览（画出检测框，核对是否对准）
  6. 把结果写回 config.toml 的 [detect] detect_region 并打印确认

若没有 GUI 环境（如远程/无显示器），会自动改用坐标输入方式。

公共流程（切窗口/抓图/框选/存图/写配置）在 core/region_calib.py 中实现，
与 calibrate_hpmp.py 共用。
"""

import sys
import traceback

from core import region_calib as rc
from core.admin import ensure_admin

# 本脚本只框选检测区域
KEYS = ("detect",)

# 本脚本的总览图片名（与 HP/MP 脚本分开，互不覆盖）
OVERVIEW_NAME = "debug_detect_overview.png"


def main():
    ensure_admin()
    print("=" * 60)
    print("  检测框（检测区域）框选校准工具")
    print("=" * 60)
    print("[INFO] 请在游戏窗口处于正常显示状态时运行本工具")
    print("[INFO] 检测框 = 怪物检测与五区巡逻共用的区域，"
          "建议框住屏幕中玩家附近的整条横向活动区")

    rc.switch_to_game()

    full = rc.grab_fullscreen()
    rc.save_fullscreen(full)

    regions = rc.select_regions(full, KEYS)
    if not regions:
        print("[WARN] 未获取检测区域")
        return

    rc.verify_regions(full, regions, OVERVIEW_NAME)
    rc.write_to_config(regions)

    print()
    print("=" * 60)
    print("  校准结果（已写入 config.toml）")
    print("  [detect] detect_region  →  检测区域")
    print("=" * 60)
    for key, region in regions.items():
        print(f"  {rc.OUTPUT_NAMES[key]} = {rc.format_region(region)}")
    print("=" * 60)
    print("  请打开以下截图判定框是否对准：")
    print(f"    {OVERVIEW_NAME}   <- 全屏总览（画出检测框）")
    print("    debug_detect.png         <- 检测区域裁剪图")
    print("  坐标已写入 config.toml，重启机器人即可生效。")
    print("  若框没对准，请重新运行本脚本并重新框选。")
    print("  血条/蓝条请运行: python calibrate_hpmp.py")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
