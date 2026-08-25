"""
自动校准模块。

怪物检测区域（DETECT_REGION）在启动时校准：
1. 用 Win32 枚举窗口，按标题关键字找到游戏窗口当前位置；
2. 按「参考窗口位置（config.CALIB_REF_WINDOW）」与实际窗口位置的几何关系
   （平移 + 等比缩放），自动调整 DETECT_REGION 的屏幕坐标。

HP/MP 血条区域（HP_BAR_REGION / MP_BAR_REGION）改在按 F10 开启加血加蓝时
校准（calibrate_hpmp()）：按当前窗口几何调整后，再按屏幕颜色直接定位两条
血条（窗口化→全屏时 HUD 不随窗口线性缩放，线性变换的坐标会偏移），并做颜色
识别校验，保证检测框坐标在真正开始监控时才确定，避免启动时窗口未就绪/被移动
导致失效。

这样游戏窗口移动/缩放后无需手动改配置：窗口平移可精确跟随，窗口缩放按
比例近似。若严重不对齐，校验阶段会提示重新校准（calibrate_hpmp.py）。

所有输出走 print()（与 monster_detect / 启动横幅一致）。
"""

import cv2
import numpy as np

import config
from core.hpmp_monitor import calc_bar_percent
from core.win_window import find_game_window, activate_game_window

# 原始坐标快照：调整区域始终以「配置原始坐标」换算（不依赖上次调整后的值），
# 保证同一区域可重复校准（幂等，结果一致）。否则 F10 重复开关时会对已调整
# 过的坐标二次变换，导致漂移。
_ORIG_DETECT_REGION = config.DETECT_REGION
_ORIG_HP_BAR_REGION = config.HP_BAR_REGION
_ORIG_MP_BAR_REGION = config.MP_BAR_REGION


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

    注意：每次变换都以参考窗口（ref_window）与当前窗口的几何关系、从「配置
    原始坐标」（模块加载时的快照）换算，不依赖上次调整后的值。因此同一区域
    可重复调用（幂等，结果一致）：F10 重复开关、窗口移动后再次校准都不会
    二次变换。启动时只调检测区域、F10 时只调血条区域，二者互不干扰。
    """
    ref_rect = config.CALIB_REF_WINDOW
    if include_detect:
        config.DETECT_REGION = _transform(*_ORIG_DETECT_REGION, ref_rect,
                                          cur_rect)
    if include_hpmp:
        config.HP_BAR_REGION = _transform(*_ORIG_HP_BAR_REGION, ref_rect,
                                          cur_rect)
        config.MP_BAR_REGION = _transform(*_ORIG_MP_BAR_REGION, ref_rect,
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


def _locate_bars(cap=None):
    """在当前屏幕上按颜色定位 HP(红)/MP(蓝) 血条，返回 (hp_region, mp_region)。

    游戏窗口化→全屏时 HUD 布局不随窗口线性缩放，线性变换得到的血条坐标会
    偏移（尤其 X，本次实测偏移 ~140px）。此函数以线性变换后的血条 Y 为锚抓
    一条水平带，按「饱和像素 + 色相」识别连续的红色段（HP 条轨道）与蓝色段
    （MP 条轨道），返回紧贴血条的检测框。HP/MP 轨道通常等宽，两条宽度取
    较大者（任一条当前填满即可给出完整轨道宽度；填充自左端起，左边缘即轨道
    左边缘）。识别失败返回 (None, None)，调用方回退到线性变换的近似区域。

    Args:
        cap: 复用的 ScreenCapture；为 None 时自建并在返回前释放。

    Returns:
        ((hp_l, hp_t, hp_w, hp_h), (mp_l, mp_t, mp_w, mp_h)) 或 (None, None)
    """
    from core.screencap import ScreenCapture
    own_cap = cap is None
    cap = cap or ScreenCapture()
    try:
        mw, mh = cap.primary_size()
        # 锚：线性变换后的 HP 条区域（Y 相对接近真实，用于限定搜索带高度）
        hint_top = config.HP_BAR_REGION[1]
        hint_h = config.HP_BAR_REGION[3]
        pad = max(20, hint_h * 2)
        band_top = max(0, hint_top - pad)
        band_h = min(hint_h + pad * 2, mh - band_top)
        if band_h <= 10:
            return None, None
        img = cap.grab_region((0, band_top, mw, band_h))
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.int16)
        H, S, V = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
        sat = (S > 60) & (V > 80)  # 饱和像素（血条轨道/填充为高饱和色）
        col_count = np.count_nonzero(sat, axis=0)
        thr = max(8, int(band_h * 0.2))
        cols = np.where(col_count > thr)[0]
        runs = []
        for c in cols:
            if runs and c == runs[-1][1] + 1:
                runs[-1] = (runs[-1][0], c)
            else:
                runs.append((c, c))

        # 按色相把足够宽的连续段分类为红（HP）/蓝（MP）
        red_runs, blue_runs = [], []
        for a, b in runs:
            if b - a + 1 < 40:
                continue
            pix = sat[:, a:b + 1]
            hh = H[:, a:b + 1][pix]
            n = max(1, hh.size)
            red_frac = ((hh < 12) | (hh > 170)).sum() / n
            blue_frac = ((hh >= 90) & (hh <= 140)).sum() / n
            if red_frac > 0.5:
                red_runs.append((a, b))
            elif blue_frac > 0.5:
                blue_runs.append((a, b))

        # 选相邻最近的红/蓝对（HP/MP 条永远相邻），间距过大视为误识别
        best = None
        for ra, rb in red_runs:
            for ba, bb in blue_runs:
                gap = (ba - rb) if ba > rb else (ra - bb)
                if best is None or gap < best[0]:
                    best = (gap, (ra, rb), (ba, bb))
        if best is None or best[0] > 120:
            return None, None
        _, red_run, blue_run = best

        def bar_rect(a, b):
            """取 run 列范围内饱和像素的实心主带（排除条上方/下方孤立标签行）。"""
            cnt = np.count_nonzero(sat[:, a:b + 1], axis=1)
            over = cnt > (b - a + 1) * 0.4
            row_runs = []
            start = None
            for i, ok in enumerate(over):
                if ok and start is None:
                    start = i
                elif not ok and start is not None:
                    row_runs.append((start, i - 1))
                    start = None
            if start is not None:
                row_runs.append((start, len(over) - 1))
            if not row_runs:
                return None
            r0, r1 = max(row_runs, key=lambda r: r[1] - r[0] + 1)
            return (int(a), int(band_top + r0), int(b - a + 1),
                    int(r1 - r0 + 1))

        hp_region = bar_rect(*red_run)
        mp_region = bar_rect(*blue_run)
        if hp_region is None or mp_region is None:
            return None, None
        # HP/MP 轨道通常等宽：若某条当前填充较少被检测成窄条，用较宽一条的
        # 宽度补齐（填充自左端起，左边缘即轨道左边缘）
        track_w = max(hp_region[2], mp_region[2])
        hp_region = (hp_region[0], hp_region[1], track_w, hp_region[3])
        mp_region = (mp_region[0], mp_region[1], track_w, mp_region[3])
        return hp_region, mp_region
    except Exception as e:
        print(f"[WARN] 血条自动定位失败（{e}），使用线性变换近似区域")
        return None, None
    finally:
        if own_cap and cap is not None:
            cap.close()


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

    # 全屏时抓图前先把游戏窗口切到前台，避免抓到桌面/被遮挡窗口
    activate_game_window(config.GAME_WINDOW_KEYWORD)
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

    # 全屏时抓图前先把游戏窗口切到前台，避免抓到桌面/被遮挡窗口
    activate_game_window(config.GAME_WINDOW_KEYWORD)
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

    # 屏幕定位：窗口化→全屏时 HUD 不随窗口线性缩放，线性变换坐标会偏移。
    # 在变换后血条 Y 附近按颜色直接定位两条血条并覆盖，识别失败回退变换结果。
    hp_region, mp_region = _locate_bars()
    if hp_region is not None and mp_region is not None:
        config.HP_BAR_REGION = hp_region
        config.MP_BAR_REGION = mp_region
        print("[INFO] 自动校准（F10）：已按屏幕颜色定位血条")
        print(f"[INFO]   HP 区域 = {config.HP_BAR_REGION}")
        print(f"[INFO]   MP 区域 = {config.MP_BAR_REGION}")
    else:
        print("[INFO] 自动校准（F10）：屏幕定位血条失败，使用线性变换近似区域")

    hp_pct, mp_pct = verify_hpmp()
    print(f"[INFO] 自动校准（F10）：血条校验 HP={hp_pct:.1f}%  "
          f"MP={mp_pct:.1f}%")
    if hp_pct <= 0 and mp_pct <= 0:
        print("[WARN] 自动校准（F10）：血条区域未识别到颜色。可能原因：未进入"
              "游戏地图、窗口被遮挡、或窗口缩放后布局不对。请进图后重试，或运行 "
              "calibrate_hpmp.py 重新校准并更新 config.toml 的 ref_window。")
    return True, adjusted, hp_pct, mp_pct
