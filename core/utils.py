"""
通用工具函数：随机抖动、日志初始化、项目路径拼接。

GameBot 及其子系统（怪物跟踪 / HP/MP / 喂宠物）统一使用
``setup_logging()`` 返回的日志器；独立检测工具（monster_detector）
保持使用 print() 输出，互不混用。
"""

import logging
import os
import random
import sys

from config import BASE_DIR


def jitter(base, jitter):
    """在 base ± jitter 范围内随机取值，下限 0.001。

    Args:
        base: 基准时长（秒）
        jitter: 抖动幅度（±秒）
    """
    return max(0.001, base + random.uniform(-jitter, jitter))


def setup_logging():
    """配置日志：仅输出到控制台（不再写文件）。

    Returns:
        logging.Logger: 名为 "GameBot" 的日志器
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("GameBot")


def project_path(*parts):
    """基于项目根目录拼接路径。

    所有模板目录、输出图片（detect_live.png / calibration_detect.png /
    debug_*.png 等）都应通过此函数得到绝对路径，确保文件落在项目根目录
    而非模块所在子目录。

    Args:
        *parts: 相对路径的各段

    Returns:
        str: BASE_DIR 下的绝对路径
    """
    return os.path.join(BASE_DIR, *parts)
