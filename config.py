"""
全局参数配置文件（统一配置中心）。

所有可调参数从 TOML 配置读取（带中文注释，可直接编辑）。
模块仍通过 ``import config`` 引用，例如 ``config.MATCH_THRESHOLD``，
保持与旧版 config.py 完全兼容的模块级属性访问方式。

配置文件查找顺序：
1. ``config.toml``（与程序同一目录，用户可编辑）——存在则直接加载；
2. ``config.default.toml``（内置默认配置模板）——不存在 config.toml 时，
   复制一份为 config.toml 并加载（首次运行自动生成，方便直接编辑调参）。

路径约定：
- 脚本方式运行：BASE_DIR = config.py 所在目录（项目根目录）
- 打包成 exe 运行：BASE_DIR = exe 所在目录

所有输出图片（detect_live.png / debug_*.png 等）写入 BASE_DIR；
模板目录（monster/、player/）解析使用 ``resource_dir()``：
优先用 BASE_DIR 下的同名目录（exe 场景可放 exe 旁覆盖/新增模板），
否则回退到打包进 exe 的默认资源（PyInstaller _MEIPASS）。
"""

import os
import sys

import numpy as np
from pynput.keyboard import Key

import tomllib


# ---------------------------------------------------------------------- #
#  路径
# ---------------------------------------------------------------------- #

def _is_frozen():
    """是否已打包为 exe（PyInstaller 会设置 sys.frozen）。"""
    return getattr(sys, "frozen", False)


# 项目根目录：脚本方式为本文件目录；exe 方式为 exe 所在目录。
# 模板目录、输出图片、config.toml 均以此为基准。
BASE_DIR = (os.path.dirname(os.path.abspath(sys.executable))
            if _is_frozen() else os.path.dirname(os.path.abspath(__file__)))

# 用户可编辑配置文件路径
CONFIG_PATH = os.path.join(BASE_DIR, "config.toml")

# 内置默认配置模板路径（打包进 exe / 随项目分发）
_DEFAULT_CONFIG = os.path.join(
    getattr(sys, "_MEIPASS", BASE_DIR) if _is_frozen()
    else os.path.dirname(os.path.abspath(__file__)),
    "config.default.toml")


# ---------------------------------------------------------------------- #
#  类型转换
# ---------------------------------------------------------------------- #

def _to_region(v):
    """屏幕区域 (left, top, width, height) 转为 4 元组。"""
    return tuple(int(x) for x in v)


def _to_scales(v):
    """多尺度缩放列表转为 float 列表。"""
    return [float(x) for x in v]


def _to_color(v):
    """HSV 颜色范围 [H, S, V] 转为 uint8 ndarray（供 cv2.inRange 使用）。"""
    return np.array([int(x) for x in v], dtype=np.uint8)


def _to_key(v):
    """功能键名（如 "f9"）转为 pynput Key 对象。"""
    return getattr(Key, str(v).strip().lower())


# ---------------------------------------------------------------------- #
#  参数表：[(TOML节, TOML键, 全局变量名, 转换函数或 None)]
# ---------------------------------------------------------------------- #

_SCHEMA = [
    # ---- [path] 路径 ----
    ("path", "monster_dir", "MONSTER_DIR", None),
    ("path", "player_dir", "PLAYER_DIR", None),

    # ---- [detect] 截图区域（检测条） ----
    ("detect", "detect_region", "DETECT_REGION", _to_region),
    ("detect", "detect_interval", "DETECT_INTERVAL", None),
    ("detect", "detect_side_margin", "DETECT_SIDE_MARGIN", None),
    ("detect", "monster_detect_y_tolerance", "MONSTER_DETECT_Y_TOLERANCE",
     None),
    ("detect", "strip_y_pad", "STRIP_Y_PAD", None),
    ("detect", "player_detect_x_shrink", "PLAYER_DETECT_X_SHRINK", None),
    ("detect", "player_cache_ttl", "PLAYER_CACHE_TTL", None),
    ("detect", "player_top_gap", "PLAYER_TOP_GAP", None),
    ("detect", "keep_centered_middle_fraction", "KEEP_CENTERED_MIDDLE_FRACTION",
     None),

    # ---- [match] 模板匹配 ----
    ("match", "match_threshold", "MATCH_THRESHOLD", None),
    ("match", "player_match_threshold", "PLAYER_MATCH_THRESHOLD", None),
    ("match", "template_scales", "TEMPLATE_SCALES", _to_scales),
    ("match", "nms_distance", "NMS_DISTANCE", None),
    ("match", "monster_confirm_distance", "MONSTER_CONFIRM_DISTANCE", None),

    # ---- [monster_filter] 怪物过滤 ----
    ("monster_filter", "monster_min_area", "MONSTER_MIN_AREA", None),
    ("monster_filter", "monster_confirm_score", "MONSTER_CONFIRM_SCORE",
     None),

    # ---- [attack] 攻击距离判定 ----
    ("attack", "attack_radius", "ATTACK_RADIUS", None),
    ("attack", "attack_distance_threshold", "ATTACK_DISTANCE_THRESHOLD",
     None),
    ("attack", "attack_center_offset", "ATTACK_CENTER_OFFSET", None),

    # ---- [control_keys] 功能控制键 ----
    ("control_keys", "key_toggle_bot", "KEY_TOGGLE_BOT", _to_key),
    ("control_keys", "key_toggle_hpmp", "KEY_TOGGLE_HPMP", _to_key),
    ("control_keys", "key_quit", "KEY_QUIT", _to_key),

    # ---- [action_keys] 操作键名（传给 pydirectinput） ----
    ("action_keys", "key_attack", "KEY_ATTACK", None),
    ("action_keys", "key_pickup", "KEY_PICKUP", None),
    ("action_keys", "key_feed_pet", "KEY_FEED_PET", None),
    ("action_keys", "key_hp_potion", "KEY_HP_POTION", None),
    ("action_keys", "key_mp_potion", "KEY_MP_POTION", None),
    ("action_keys", "key_left", "KEY_LEFT", None),
    ("action_keys", "key_right", "KEY_RIGHT", None),

    # ---- [operation] 操作参数（按键时长与随机抖动） ----
    ("operation", "pydirectinput_pause", "PYDIRECTINPUT_PAUSE", None),
    ("operation", "press_delay", "PRESS_DELAY", None),
    ("operation", "press_jitter", "PRESS_JITTER", None),
    ("operation", "dir_hold", "DIR_HOLD", None),
    ("operation", "dir_hold_jitter", "DIR_HOLD_JITTER", None),
    ("operation", "attack_interval", "ATTACK_INTERVAL", None),
    ("operation", "attack_jitter", "ATTACK_JITTER", None),
    ("operation", "pickup_count", "PICKUP_COUNT", None),
    ("operation", "pickup_interval", "PICKUP_INTERVAL", None),
    ("operation", "move_stuck_check_interval", "MOVE_STUCK_CHECK_INTERVAL",
     None),
    ("operation", "move_stuck_threshold", "MOVE_STUCK_THRESHOLD", None),
    ("operation", "stuck_reverse_hold_time", "STUCK_REVERSE_HOLD_TIME", None),
    ("operation", "potion_cooldown", "POTION_COOLDOWN", None),
    ("operation", "feed_pet_interval", "FEED_PET_INTERVAL", None),
    ("operation", "log_frame_interval", "LOG_FRAME_INTERVAL", None),

    # ---- [hpmp] HP/MP 监控参数 ----
    ("hpmp", "hp_bar_region", "HP_BAR_REGION", _to_region),
    ("hpmp", "mp_bar_region", "MP_BAR_REGION", _to_region),
    ("hpmp", "hp_color_lower", "HP_COLOR_LOWER", _to_color),
    ("hpmp", "hp_color_upper", "HP_COLOR_UPPER", _to_color),
    ("hpmp", "hp_color_lower2", "HP_COLOR_LOWER2", _to_color),
    ("hpmp", "hp_color_upper2", "HP_COLOR_UPPER2", _to_color),
    ("hpmp", "mp_color_lower", "MP_COLOR_LOWER", _to_color),
    ("hpmp", "mp_color_upper", "MP_COLOR_UPPER", _to_color),
    ("hpmp", "hp_threshold", "HP_THRESHOLD", None),
    ("hpmp", "mp_threshold", "MP_THRESHOLD", None),
    ("hpmp", "hp_mp_check_interval", "HP_MP_CHECK_INTERVAL", None),
    ("hpmp", "save_hp_mp_debug", "SAVE_HP_MP_DEBUG", None),

    # ---- [window] 游戏窗口识别 ----
    ("window", "game_window_keyword", "GAME_WINDOW_KEYWORD", None),
]


# ---------------------------------------------------------------------- #
#  加载逻辑
# ---------------------------------------------------------------------- #

def _read_toml(path):
    """读取 TOML 文件，返回 dict。"""
    with open(path, "rb") as f:
        return tomllib.load(f)


def _apply(data):
    """把 TOML 解析结果写入模块全局变量（未出现的键保持默认）。"""
    for section, key, gname, conv in _SCHEMA:
        try:
            val = data[section][key]
        except (KeyError, TypeError):
            continue  # 缺失项使用默认值
        if conv is not None:
            try:
                val = conv(val)
            except Exception as e:
                print(f"[WARN] 配置 {section}.{key} 解析失败（{e}），使用默认值")
                continue
        globals()[gname] = val


def _load_config():
    """加载配置：优先用户 config.toml，其次内置默认模板（并生成 config.toml）。"""
    # 1. 优先读取用户可编辑的 config.toml
    if os.path.exists(CONFIG_PATH):
        try:
            _apply(_read_toml(CONFIG_PATH))
            return
        except Exception as e:
            print(f"[WARN] 配置文件 {CONFIG_PATH} 解析失败（{e}），"
                  "改用默认配置模板重新加载")

    # 2. 用内置默认模板生成 config.toml（首次运行 / 配置损坏时自动重建）
    if os.path.exists(_DEFAULT_CONFIG):
        try:
            data = _read_toml(_DEFAULT_CONFIG)
        except Exception as e:
            print(f"[ERROR] 默认配置模板 {_DEFAULT_CONFIG} 解析失败: {e}")
            raise RuntimeError("内置默认配置模板损坏，程序无法启动") from e
        try:
            with open(_DEFAULT_CONFIG, encoding="utf-8") as src:
                default_text = src.read()
            with open(CONFIG_PATH, "w", encoding="utf-8") as dst:
                dst.write(default_text)
            print(f"[INFO] 未找到配置文件，已生成默认配置: {CONFIG_PATH}")
        except Exception as e:
            print(f"[WARN] 无法写入默认配置文件 {CONFIG_PATH}: {e}"
                  "（使用内置默认配置运行）")
        _apply(data)
        return

    raise RuntimeError(
        f"找不到任何配置（{CONFIG_PATH} 与默认模板均缺失），程序无法启动")


def _apply_derived():
    """计算派生常量（基于已加载的配置值）。"""
    global ALL_KEYS
    # 所有需要释放的按键列表（用于停止时释放全部按键，防止卡键）
    ALL_KEYS = (KEY_ATTACK, KEY_PICKUP, KEY_HP_POTION, KEY_MP_POTION,
                KEY_LEFT, KEY_RIGHT, KEY_FEED_PET)


# ---------------------------------------------------------------------- #
#  资源目录解析（模板目录用，支持 exe 打包）
# ---------------------------------------------------------------------- #

def resource_dir(name):
    """解析模板/资源目录的绝对路径。

    优先使用 BASE_DIR（exe 所在目录/项目根目录）下同名目录，这样 exe
    场景下用户可把 monster/、player/ 放在 exe 旁自由新增/覆盖模板；
    若不存在，回退到打包进 exe 的默认资源（PyInstaller _MEIPASS）。
    """
    ext = os.path.join(BASE_DIR, name)
    if os.path.isdir(ext):
        return ext
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        internal = os.path.join(meipass, name)
        if os.path.isdir(internal):
            return internal
    return ext


# 模块加载时立即应用配置
_load_config()
_apply_derived()
