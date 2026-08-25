"""HP/MP 血条识别检测脚本（诊断用）。

用途：游戏窗口为全屏时，抓图前先把游戏窗口切到前台（避免抓到桌面或
被遮挡窗口），然后按当前窗口几何校准 HP/MP 血条区域，抓取血条/蓝条
截图保存（debug_hp.png / debug_hp_mask.png / debug_mp.png /
debug_mp_mask.png），并打印识别百分比，供人工核对识别是否准确。

用法：
    python test_hpmp.py

若血条区域已随全屏/窗口缩放偏差较大，可先运行 calibrate_hpmp.py 重新
框选血条区域，并更新 config.toml 的 [hpmp] hp_bar_region / mp_bar_region
与 [auto_calibrate] ref_window。
"""

import config
from core.admin import ensure_admin
from core.auto_calibrate import activate_game_window, calibrate_hpmp
from core.hpmp_monitor import save_bar_debug
from core.screencap import ScreenCapture


def main():
    ensure_admin()
    print("=" * 60)
    print("  HP/MP 血条识别检测")
    print("=" * 60)
    print(f"  - 游戏窗口关键字: {config.GAME_WINDOW_KEYWORD}")
    print(f"  - HP 区域(配置): {config.HP_BAR_REGION}")
    print(f"  - MP 区域(配置): {config.MP_BAR_REGION}")

    # 1. 抓图前先把游戏窗口切到前台（全屏时避免抓到桌面/被遮挡窗口）
    ok = activate_game_window(config.GAME_WINDOW_KEYWORD)
    print(f"  - 激活游戏窗口: {'成功' if ok else '失败（未找到，继续尝试）'}")

    # 2. 按当前窗口几何校准血条区域并做颜色校验
    found, adjusted, hp_pct, mp_pct = calibrate_hpmp()
    print(f"  - 校准: 找到窗口={found} 区域调整={adjusted}")
    print(f"  - 识别: HP={hp_pct:.1f}%  MP={mp_pct:.1f}%")

    # 3. 抓取血条/蓝条区域并保存调试截图（原始图 + 掩膜叠加图）
    cap = ScreenCapture()
    try:
        hp_img = cap.grab_region(config.HP_BAR_REGION)
        mp_img = cap.grab_region(config.MP_BAR_REGION)
        save_bar_debug(hp_img, 'hp', hp_pct)
        save_bar_debug(mp_img, 'mp', mp_pct)
        print(f"  - HP 区域(校准后): {config.HP_BAR_REGION}")
        print(f"  - MP 区域(校准后): {config.MP_BAR_REGION}")

        # 4. 保存底部全景对齐图：把 HP/MP 检测框画在底部条带上，核对框是否对准血条
        import cv2
        mw, mh = cap.primary_size()
        strip_h = 200
        strip_top = max(0, mh - strip_h)
        strip = cap.grab_region((0, strip_top, mw, strip_h))
        for label, r in (("HP", config.HP_BAR_REGION),
                         ("MP", config.MP_BAR_REGION)):
            l, t, w, h = r
            y1 = t - strip_top
            if 0 <= y1 < strip_h:
                cv2.rectangle(strip, (l, y1), (l + w, y1 + h), (0, 255, 0), 2)
                cv2.putText(strip, label, (l + 3, max(10, y1 - 5)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.imwrite("debug_bars_overview.png", strip)

        print("  调试截图已保存（项目根目录）:")
        print("    debug_hp.png / debug_hp_mask.png")
        print("    debug_mp.png / debug_mp_mask.png")
        print("    debug_bars_overview.png  <- 底部全景，绿框=检测框，核对对准")
    finally:
        cap.close()
    print("=" * 60)
    print("  请打开上述截图核对：血条是否完整框住、掩膜是否贴合、百分比是否合理")
    print("  若偏差较大，运行 calibrate_hpmp.py 重新校准并更新 ref_window。")


if __name__ == "__main__":
    import sys
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 中断，退出程序")
        sys.exit(0)
