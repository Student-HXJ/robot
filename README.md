# 冒险岛机器人

MapleStory（冒险岛）游戏自动化机器人。**纯图像识别，不读取游戏内存**：
`mss` 屏幕截图 → OpenCV 模板匹配 → `pydirectinput` 模拟按键。

> ⚠️ **仅支持 Windows**，且必须**以管理员身份**运行（游戏以管理员运行时，
> UIPI 会拦截非管理员进程的模拟输入/截屏）。

## 项目结构

```
robot/
├── config.py                 # 配置加载器（从 config.toml 读取，暴露为 config.X）
├── config.toml               # 用户可编辑配置（调参改这里，带中文注释）
├── config.default.toml       # 内置默认配置模板（打包进 exe，首次运行生成 config.toml）
├── game_bot.py               # 主机器人入口（F9 启停 / F10 血蓝+喂宠 / F8 退出）
├── monster_detect.py         # 独立检测入口（F9 启停 / F8 退出，与功能控制键一致）
├── calibrate_hpmp.py         # 检测框/血条/蓝条区域校准 + 存图校验工具
├── build_exe.py              # 打包脚本（PyInstaller 生成 dist/game_bot.exe）
├── core/                     # 核心模块，每个职责一个类一个文件
│   ├── admin.py              # 管理员提权
│   ├── utils.py              # 随机抖动 / 日志 / 路径
│   ├── screencap.py          # ScreenCapture 屏幕截图
│   ├── key_control.py        # KeyControl 按键模拟
│   ├── template_matcher.py   # TemplateLoader 模板加载与匹配
│   ├── player_detector.py    # PlayerDetector 玩家检测
│   ├── attack_distance.py    # 攻击距离计算（纯函数）
│   ├── monster_detector.py   # MonsterDetector 怪物检测
│   ├── monster_tracker.py    # MonsterTracker 怪物跟踪（靠近/卡住脱困）
│   ├── hpmp_monitor.py       # HPMPMonitor 加血加蓝
│   └── pet_feeder.py         # PetFeeder 喂宠物
├── monster/                  # 怪物模板（按分类分子文件夹）
└── player/                   # 玩家模板
```

## 安装

```bash
pip install opencv-python mss numpy pydirectinput pynput matplotlib
```

## 运行

```bash
# 启动主机器人（可选 --monster 固定分类，跳过交互菜单）
python game_bot.py --monster zhu
python game_bot.py --monster all

# 单独运行检测（观察识别效果，F9 启停，F8 退出）
python monster_detect.py --monster zhu

# 校准检测框/血条/蓝条区域 + 存图校验（自动把坐标写入 config.toml 的 [detect] / [hpmp] 节）
python calibrate_hpmp.py
```

不传 `--monster` 时，程序启动会列出 `monster/` 下的分类让你选择；
传 `--monster all` 表示加载全部分类。

## 操作说明

| 按键 | 功能 |
| ---- | ---- |
| `F9` | 启动 / 停止机器人 |
| `F10` | 开启 / 关闭 HP/MP 监控 + 喂食宠物（独立于 F9） |
| `F8` | 退出程序 |

游戏内操作键：攻击 `X` · 捡东西 `Z` · 补HP `9` · 补MP `0` · 喂宠物 `8`（无跳跃键）

行为逻辑：
1. 检测怪物，移动到怪物附近攻击
2. 怪物在攻击距离内 → 朝其方向攻击
3. 怪物超出攻击距离 → 按住方向键靠近
4. 无怪物 → 每 2 秒捡东西 / 随机移动防掉线
5. HP ≤ 50% 自动按 `9` 补血；MP ≤ 50% 自动按 `0` 补蓝（受 F10 控制）
6. 每 20 分钟自动喂食宠物（受 F10 控制）

## 配置

所有参数集中在 **`config.toml`**（TOML 格式，带中文注释），调整后无需改动代码：
检测区域、模板匹配阈值、攻击距离判定、按键映射、操作延迟与抖动、
卡住检测参数、HP/MP 血条区域与 HSV 颜色阈值、喂食间隔等。
`config.py` 负责加载并把参数暴露为 `config.X`，模块无需改动。

> 若 `config.toml` 缺失，程序会从内置的 `config.default.toml` 自动生成一份，
> 方便直接编辑调参。

**区域坐标校准**：检测框 / 血条 / 蓝条区域坐标都通过 `python calibrate_hpmp.py`
手动框选确定：脚本会把游戏窗口切到前台、截全屏，让你依次框选检测区域、
HP 血条、MP 蓝条，并生成 `debug_*_mask.png` 等校验图供核对。框选完成后
脚本会自动把坐标写回 `config.toml` 的 `[detect]` / `[hpmp]` 节，重启机器人
后生效。游戏窗口移动/换设备/改分辨率后需重新校准。`[window] game_window_keyword`
仅用于抓图前把游戏窗口切到前台。

## 打包成 exe（跨 Windows 设备使用）

```bash
robot/Scripts/python.exe -m pip install pyinstaller   # 仅需一次
robot/Scripts/python.exe build_exe.py
```

打包产物在 **`dist/`**，即完整发布包：

```
dist/
├── game_bot.exe       # 单文件主程序（含 Python 运行时 + 全部依赖 + 内置模板）
├── config.toml        # 可编辑配置
├── monster/           # 怪物模板（可新增分类，无需重新打包）
└── player/            # 玩家模板
```

把整个 `dist/` 文件夹拷贝到任意 Windows 设备即可使用（运行 `game_bot.exe`，
首次会弹 UAC 自动以管理员身份运行）。程序优先使用 exe 旁边的
`config.toml` / `monster/` / `player/`，缺失时才回退到 exe 内置资源。

## 故障排查

- **模板加载为 0 / 检测不到怪物**：确认 `monster/<分类>/` 下有 PNG，且
  输出图片（`detect_live.png`）落在项目根目录。
- **血条识别不准**：在 `config.toml` 的 `[hpmp]` 节把 `save_hp_mp_debug = true`，
  查看生成的 `debug_hp*.png` / `debug_mp*.png` 排查颜色阈值。
- **按键无效**：确认已以管理员身份运行（程序启动时会自动提权）。
