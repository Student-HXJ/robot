"""独立怪物+玩家检测命令行入口（薄包装）。

用法：
    python monster_detect.py --monster zhu
    python monster_detect.py --calibrate

完整逻辑见 core/monster_detector.py 的 main()：F9 开关检测、F8 退出。
"""

import sys

from core.monster_detector import main

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 中断，退出程序")
        sys.exit(0)
