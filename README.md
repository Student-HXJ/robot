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
├── game_bot.py               # 主机器人入口（F9 启停 / F10 血蓝+喂宠 / F11 辅助技能 / F8 退出）
├── calibrate_detect.py       # 检测框框选校准 + 存图校验工具
├── calibrate_hpmp.py         # HP/MP 血条框选校准 + 存图校验工具
├── core/                     # 核心模块，每个职责一个类一个文件
│   ├── admin.py              # 管理员提权
│   ├── utils.py              # 随机抖动 / 日志 / 路径
│   ├── win_window.py         # Win32 窗口查找与置前
│   ├── region_calib.py       # 区域框选校准公共逻辑（两个 calibrate_* 共用）
│   ├── screencap.py          # ScreenCapture 屏幕截图
│   ├── key_control.py        # KeyControl 按键模拟
│   ├── template_matcher.py   # TemplateLoader 模板加载与匹配
│   ├── player_detector.py    # PlayerDetector 玩家检测
│   ├── attack_distance.py    # 攻击距离计算（纯函数）
│   ├── monster_detector.py   # MonsterDetector 怪物检测
│   ├── monster_tracker.py    # MonsterTracker 怪物跟踪（靠近/卡住脱困）
│   ├── hpmp_monitor.py       # HPMPMonitor 加血加蓝
│   ├── pet_feeder.py         # PetFeeder 喂宠物
│   └── aux_skill.py          # AuxSkillCaster 辅助技能（移动加速/攻击加速）
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

# 校准检测框（写入 config.toml 的 [detect] detect_region）
python calibrate_detect.py

# 校准 HP/MP 血条框 + 存图校验（写入 config.toml 的 [hpmp] 节）
python calibrate_hpmp.py
```

不传 `--monster` 时，程序启动会列出 `monster/` 下的分类让你选择；
传 `--monster all` 表示加载全部分类。

## 操作说明

| 按键 | 功能 |
| ---- | ---- |
| `F9` | 启动 / 停止机器人 |
| `F10` | 开启 / 关闭 HP/MP 监控 + 喂食宠物（独立于 F9） |
| `F11` | 开启 / 关闭辅助技能：移动加速 `a`（每 200 秒）+ 攻击加速 `s`（每 30 秒）（独立于 F9/F10） |
| `F8` | 退出程序 |

游戏内操作键：攻击 `X` · 补HP `9` · 补MP `0` · 喂宠物 `8` · 辅助技能 `A`/`S`（无跳跃键）

行为逻辑：
1. 检测怪物，移动到怪物附近攻击
2. 怪物在攻击距离内 → 朝其方向攻击
3. 怪物超出攻击距离 → 按住方向键靠近
4. 无怪物 → 五分段寻路巡逻（禁区反向 + 随机移动防掉线）
5. HP ≤ 50% 自动按 `9` 补血；MP ≤ 50% 自动按 `0` 补蓝（受 F10 控制）
6. 每 20 分钟自动喂食宠物（受 F10 控制）
7. 每 200 秒自动按 `A` 施放移动加速、每 30 秒自动按 `S` 施放攻击加速（受 F11 控制）

## 配置

所有参数集中在 **`config.toml`**（TOML 格式，带中文注释），调整后无需改动代码：
检测区域、模板匹配阈值、攻击距离判定、按键映射、操作延迟与抖动、
卡住检测参数、HP/MP 血条区域与 HSV 颜色阈值、喂食间隔、辅助技能间隔等。
`config.py` 负责加载并把参数暴露为 `config.X`，模块无需改动。

**辅助技能**：`[aux_skill]` 节配置移动加速/攻击加速的施放间隔
（`skill_move_interval` 默认 200 秒、`skill_attack_speed_interval` 默认 30 秒），
技能键在 `[action_keys]` 的 `key_skill_move`（默认 `a`）/ `key_skill_attack_speed`
（默认 `s`），开关键在 `[control_keys]` 的 `key_toggle_aux_skill`（默认 `f11`）。
间隔填 `0` 或负数表示禁用该技能。

**区域坐标校准**：检测框与血条/蓝条区域坐标分别通过两个脚本手动框选确定，
两个脚本都会把游戏窗口切到前台、截全屏，让你拖拽框选并生成校验图供核对，
框选完成后自动把坐标写回 `config.toml`，重启机器人后生效：

- `python calibrate_detect.py` —— 只框选**检测框**（怪物检测 + 五区巡逻共用），
  写入 `[detect] detect_region`，校验图 `debug_detect.png` /
  `debug_detect_overview.png`。
- `python calibrate_hpmp.py` —— 只框选 **HP / MP 血条框**，写入 `[hpmp]` 的
  `hp_bar_region` / `mp_bar_region`，校验图 `debug_hp_mask.png` /
  `debug_mp_mask.png` / `debug_regions_overview.png`。

游戏窗口移动/换设备/改分辨率后需重新校准。`[window] game_window_keyword`
仅用于抓图前把游戏窗口切到前台。

## 故障排查

- **模板加载为 0 / 检测不到怪物**：确认 `monster/<分类>/` 下有 PNG，且
  输出图片（`detect_live.png`）落在项目根目录。
- **血条识别不准**：在 `config.toml` 的 `[hpmp]` 节把 `save_hp_mp_debug = true`，
  查看生成的 `debug_hp*.png` / `debug_mp*.png` 排查颜色阈值。
- **按键无效**：确认已以管理员身份运行（程序启动时会自动提权）。
