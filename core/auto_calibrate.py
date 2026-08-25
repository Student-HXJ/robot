"""
自动校准模块。

怪物检测区域（DETECT_REGION）在启动时校准：
1. 用 Win32 枚举窗口，按标题关键字找到游戏窗口当前位置；
2. 按「参考窗口位置（config.CALIB_REF_WINDOW）」与实际窗口位置的几何关系
   （平移 + 等比缩放），自动调整 DETECT_REGION 的屏幕坐标。

HP/MP 血条区域（HP_BAR_REGION / MP_BAR_REGION）改在按 F10 开启加血加蓝时
校准（calibrate_hpmp()）：按当前窗口几何重新调整血条坐标并做颜色识别校验，
保证检测框坐标在真正开始监控时才确定，避免启动时窗口未就绪/被移动导致失效。

这样游戏窗口移动/缩放后无需手动改配置：窗口平移可精确跟随，窗口缩放按
比例近似。若严重不对齐，校验阶段会提示重新校准（calibrate_hpmp.py）。

所有输出走 print()（与 monster_detect / 启动横幅一致）。
"""

import ctypes
from ctypes import wintypes

import config
from core.hpmp_monitor import calc_bar_percent


def find_game_window(keyword):
    """按标题关键字查找游戏窗口，返回 (left, top, width, height) 或 None。

    用 GetWindowRect 取窗口外框坐标（与 config.ref_window 的标定口径一致）。
    有多个匹配时取面积最大的窗口，避免误匹配到浏览器标签等。
    """
    user32 = ctypes.windll.user32
    candidates = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if keyword and keyword.lower() not in buf.value.lower():
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        w, h = rect.right - rect.left, rect.bottom - rect.top
        if w > 0 and h > 0:
            candidates.append((rect.left, rect.top, w, h))
        return True

    user32.EnumWindows(_cb, 0)
    if not candidates:
        return None
    return max(candidates, key=lambda r: r[2] * r[3])


def _transform(left, top, w, h, ref_rect, cur_rect):
    """把参考窗口下的坐标/尺寸变换到当前窗口几何（平移 + 等比缩放）。

    Args:
        left, top, w, h: 参考窗口下的区域 (left, top, width, height)
        ref_rect: 参考窗口 (left, top, width, height)
        cur_rect: 当前窗口 (left, top, width, height)

    Returns:
        当前窗口下的 (left, top, width, height)
    """
    ref_l, ref_t, ref_w, ref_h = ref_rect
    cur_l, cur_t, cur_w, cur_h = cur_rect
    if ref_w <= 0 or ref_h <= 0:
        return (left, top, w, h)
    sx = cur_w / ref_w
    sy = cur_h / ref_h
    return (
        round(cur_l + (left - ref_l) * sx),
        round(cur_t + (top - ref_t) * sy),
        max(1, round(w * sx)),
        max(1, round(h * sy)),
    )


def adjust_regions(cur_rect, include_detect=True, include_hpmp=True):
    """按当前窗口几何调整区域（直接更新 config 全局变量，后续读取即生效）。

    Args:
        cur_rect: 当前窗口 (left, top, width, height)
        include_detect: 是否调整检测区域 DETECT_REGION（F9 追怪用）
        include_hpmp: 是否调整血条区域 HP_BAR_REGION / MP_BAR_REGION
                      （F10 加血加蓝用）

    注意：每次变换都以参考窗口（ref_window）与当前窗口的几何关系从 config
    原始坐标换算，同一区域只能调整一次（重复调用会二次变换）。因此启动时只调
    检测区域、F10 时只调血条区域，二者互不重叠。
    """
    ref_rect = config.CALIB_REF_WINDOW
    if include_detect:
        config.DETECT_REGION = _transform(*config.DETECT_REGION, ref_rect,
                                          cur_rect)
    if include_hpmp:
        config.HP_BAR_REGION = _transform(*config.HP_BAR_REGION, ref_rect,
                                          cur_rect)
        config.MP_BAR_REGION = _transform(*config.MP_BAR_REGION, ref_rect,
                                          cur_rect)


def verify_hpmp():
    """对当前血条区域做颜色识别，返回 (hp_pct, mp_pct)。

    区域无效 / 抓屏失败时返回 (0.0, 0.0)。
    """
    try:
        from core.screencap import ScreenCapture
        cap = ScreenCapture()
        try:
            hp_pct = calc_bar_percent(cap.grab_region(config.HP_BAR_REGION),
                                      'hp')
            mp_pct = calc_bar_percent(cap.grab_region(config.MP_BAR_REGION),
                                      'mp')
            return hp_pct, mp_pct
        finally:
            cap.close()
    except Exception as e:
        print(f"[WARN] 自动校准：血条校验失败（{e}）")
        return 0.0, 0.0


def auto_calibrate():
    """启动自动校准：找窗口 → 调整怪物检测区域（DETECT_REGION）。

    HP/MP 血条区域不在启动时校准：改由按 F10 开启加血加蓝时调用
    calibrate_hpmp() 确定（见 game_bot.py 的 toggle_hp_mp）。

    Returns:
        (window_found, regions_adjusted, hp_pct, mp_pct)
    """
    if not config.AUTO_CALIBRATE_ENABLED:
        print("[INFO] 自动校准已关闭，使用配置原始坐标")
        return False, False, 0.0, 0.0

    print(f"[INFO] 自动校准：查找游戏窗口（关键字={config.GAME_WINDOW_KEYWORD}）...")
    rect = find_game_window(config.GAME_WINDOW_KEYWORD)
    if rect is None:
        print(f"[WARN] 自动校准：未找到游戏窗口（关键字="
              f"{config.GAME_WINDOW_KEYWORD}），使用配置原始坐标")
        return False, False, 0.0, 0.0

    ref_rect = config.CALIB_REF_WINDOW
    print(f"[INFO] 自动校准：游戏窗口 {rect}")
    if rect == ref_rect:
        print("[INFO] 自动校准：窗口位置与参考一致，无需调整")
        adjusted = False
    else:
        adjust_regions(rect, include_detect=True, include_hpmp=False)
        adjusted = True
        print("[INFO] 自动校准：已按当前窗口位置调整检测区域")
        print(f"[INFO]   检测区域 = {config.DETECT_REGION}")

    return True, adjusted, 0.0, 0.0


def calibrate_hpmp():
    """按 F10 开启加血加蓝时调用：按当前游戏窗口调整 HP/MP 血条区域并校验。

    血条区域在真正开始监控前才确定，避免启动时窗口未就绪/被移动导致坐标失效。
    DETECT_REGION 已在启动时校准（auto_calibrate），此处只处理
    HP_BAR_REGION / MP_BAR_REGION。

    Returns:
        (window_found, regions_adjusted, hp_pct, mp_pct)
    """
    if not config.AUTO_CALIBRATE_ENABLED:
        print("[INFO] 自动校准已关闭，使用配置原始坐标")
        return False, False, 0.0, 0.0

    print(f"[INFO] 自动校准（F10）：查找游戏窗口（关键字="
          f"{config.GAME_WINDOW_KEYWORD}）...")
    rect = find_game_window(config.GAME_WINDOW_KEYWORD)
    if rect is None:
        print(f"[WARN] 自动校准（F10）：未找到游戏窗口（关键字="
              f"{config.GAME_WINDOW_KEYWORD}），使用配置原始坐标")
        return False, False, 0.0, 0.0

    ref_rect = config.CALIB_REF_WINDOW
    if rect == ref_rect:
        print("[INFO] 自动校准（F10）：窗口位置与参考一致，无需调整")
        adjusted = False
    else:
        adjust_regions(rect, include_detect=False, include_hpmp=True)
        adjusted = True
        print("[INFO] 自动校准（F10）：已按当前窗口位置调整 HP/MP 血条区域")
        print(f"[INFO]   HP 区域 = {config.HP_BAR_REGION}")
        print(f"[INFO]   MP 区域 = {config.MP_BAR_REGION}")

    hp_pct, mp_pct = verify_hpmp()
    print(f"[INFO] 自动校准（F10）：血条校验 HP={hp_pct:.1f}%  "
          f"MP={mp_pct:.1f}%")
    if hp_pct <= 0 and mp_pct <= 0:
        print("[WARN] 自动校准（F10）：血条区域未识别到颜色。可能原因：未进入"
              "游戏地图、窗口被遮挡、或窗口缩放后布局不对。请进图后重试，或运行 "
              "calibrate_hpmp.py 重新校准并更新 config.toml 的 ref_window。")
    return True, adjusted, hp_pct, mp_pct
