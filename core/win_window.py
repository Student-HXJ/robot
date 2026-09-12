"""Win32 窗口工具：按标题关键字查找游戏窗口并切到前台。

抓图前需要把全屏游戏切到前台，避免抓到桌面/被遮挡窗口。窗口查找与激活
逻辑集中在此，供校准工具（calibrate_detect / calibrate_hpmp，经
core/region_calib.py）与截屏（screencap）共用，
避免多处重复 EnumWindows。

所有函数 Windows-only（ctypes.windll）。
"""

import ctypes
from ctypes import wintypes


def _set_dpi_aware():
    """让进程 DPI 感知，使 GetWindowRect 返回物理像素坐标。

    否则在系统显示缩放（如 150%）下，GetWindowRect 返回「逻辑坐标」，会与
    mss 截屏的「物理坐标」错位，导致自动校准按错误比例缩放血条/检测区域。
    （实测 150% 缩放下 GetWindowRect 报 1707x1067，mss 报 2560x1600。）
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


_set_dpi_aware()


def _enumerate(keyword):
    """枚举可见窗口，返回标题匹配关键字且面积最大者的 (hwnd, rect)。

    Args:
        keyword: 窗口标题子串关键字（config.GAME_WINDOW_KEYWORD）

    Returns:
        (hwnd, (left, top, width, height))；找不到返回 (None, None)。
    """
    user32 = ctypes.windll.user32
    best_hwnd = None
    best_rect = None
    best_area = 0

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        nonlocal best_hwnd, best_rect, best_area
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
        area = w * h
        if area > best_area:
            best_hwnd, best_area = hwnd, area
            best_rect = (rect.left, rect.top, w, h)
        return True

    user32.EnumWindows(_cb, 0)
    return best_hwnd, best_rect


def find_game_window(keyword):
    """按标题关键字查找游戏窗口，返回 (left, top, width, height) 或 None。

    用 GetWindowRect 取窗口外框坐标（屏幕绝对像素坐标，与 mss 截屏口径一致）。
    有多个匹配时取面积最大的窗口，避免误匹配到浏览器标签等。
    """
    _, rect = _enumerate(keyword)
    return rect


def find_game_window_hwnd(keyword):
    """按标题关键字查找游戏窗口句柄，返回 HWND 或 None。"""
    hwnd, _ = _enumerate(keyword)
    return hwnd


def bring_to_front(hwnd):
    """把已找到的窗口切到前台（最小化先还原 SW_RESTORE）。

    Args:
        hwnd: 窗口句柄；None 时直接返回 False

    Returns:
        bool: 是否找到并尝试置前（失败静默返回 False，不影响调用方）
    """
    if not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        return bool(user32.SetForegroundWindow(hwnd))
    except Exception:
        return False


def activate_game_window(keyword):
    """按标题关键字把游戏窗口切到前台，返回是否成功置前。

    每次调用都会重新枚举窗口（开销略大），适合低频调用（校准/启动）；
    高频抓图场景请用 find_game_window_hwnd + bring_to_front 缓存句柄。
    """
    hwnd = find_game_window_hwnd(keyword)
    if hwnd is None:
        return False
    return bring_to_front(hwnd)
