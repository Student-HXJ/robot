"""打包脚本：把主机器人打包成单文件 exe（跨 Windows 设备直接拷贝使用）。

用法：
    robot/Scripts/python.exe build_exe.py

产物：dist/ 目录即为完整发布包：
  - game_bot.exe         单文件主程序（含 Python 运行时 + 全部依赖 + 内置默认模板）
  - config.toml          用户可编辑配置（调参改这里）
  - monster/ player/     模板目录（可新增怪物/玩家模板，无需重新打包）

打包内容说明：
  - 模板 monster/、player/ 与默认配置 config.default.toml 会被打入 exe 作为兜底；
  - 运行时会优先使用 exe 旁边的 config.toml / monster/ / player/（可自由编辑），
    不存在时才回退到 exe 内置资源，因此跨设备拷贝 dist/ 即可使用。
"""

import os
import shutil

import PyInstaller.__main__

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    # --add-data 在 Windows 上以 ";" 分隔 源;目标。
    # 源用绝对路径：加了 --specpath 后相对路径会按 spec 目录解析导致找不到资源。
    sep = os.pathsep
    args = [
        os.path.join(ROOT, "game_bot.py"),
        "--name", "game_bot",
        "--onefile",        # 单文件，方便跨设备拷贝
        "--clean",
        "--noconfirm",
        "--specpath", os.path.join(ROOT, "build", "spec"),  # .spec 不落根目录
        "--add-data", f"{os.path.join(ROOT, 'monster')}{sep}monster",  # 内置怪物模板（兜底）
        "--add-data", f"{os.path.join(ROOT, 'player')}{sep}player",    # 内置玩家模板（兜底）
        "--add-data", f"{os.path.join(ROOT, 'config.default.toml')}{sep}.",  # 内置默认配置模板
    ]
    PyInstaller.__main__.run(args)

    # 把可编辑资源复制到 dist，与 exe 同级
    dist = os.path.join(ROOT, "dist")
    os.makedirs(dist, exist_ok=True)
    for name in ("config.toml", "monster", "player"):
        src = os.path.join(ROOT, name)
        dst = os.path.join(dist, name)
        if os.path.isdir(src):
            shutil.copytree(src, dst, dirs_exist_ok=True)
        elif os.path.isfile(src):
            shutil.copy2(src, dst)

    print("=" * 60)
    print(f"打包完成：{os.path.join(dist, 'game_bot.exe')}")
    print("dist/ 目录即完整发布包，可直接拷贝到任意 Windows 设备使用：")
    print("  - game_bot.exe（以管理员身份运行，或让它自动提权）")
    print("  - config.toml（调参改这里，换设备后记得用 calibrate_hpmp.py 校准血条）")
    print("  - monster/ player/（可自由新增模板）")
    print("=" * 60)


if __name__ == "__main__":
    main()
