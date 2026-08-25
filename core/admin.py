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
    # 打包为 exe 时：sys.executable 即 exe 本体，ShellExecute 的 lpParameters
    # 只需传真正的参数（sys.argv[1:]），不能再带上 exe 路径，否则子进程
    # 命令行会多出重复的 exe 路径，导致 argparse 报"unrecognized arguments"。
    # 脚本方式运行时：python.exe 需要把脚本路径作为第一个参数。
    if getattr(sys, "frozen", False):
        params = " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        params = " ".join(f'"{a}"' for a in sys.argv)
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params,
                                        script_dir, 1)
    sys.exit(0)
