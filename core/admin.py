"""
管理员提权模块。

游戏以管理员身份运行时，普通权限进程的模拟按键/截屏会被 UIPI 拦截，
因此所有入口脚本启动时都必须先调用 ``ensure_admin()``。
"""

import ctypes
import os
import sys


def ensure_admin():
    """确保以管理员权限运行；提权后切换回脚本所在目录。

    若当前已是管理员：切换工作目录到脚本所在目录后直接返回。
    否则通过 ShellExecuteW("runas", ...) 以管理员身份重新启动自身并退出当前进程。
    """
    if ctypes.windll.shell32.IsUserAnAdmin():
        os.chdir(os.path.dirname(os.path.abspath(sys.argv[0])))
        return
    script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
    # 以 python.exe 重新启动自身：脚本路径必须作为第一个参数传给解释器。
    params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, script_dir, 1)
    sys.exit(0)
