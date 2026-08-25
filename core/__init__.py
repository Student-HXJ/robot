"""
core 包：冒险岛机器人核心功能模块。

每个模块只承担一个职责，类/函数名即职责：
- admin          管理员提权
- utils          通用工具（随机抖动 / 日志 / 路径）
- screencap      屏幕截图（ScreenCapture）
- key_control    按键模拟（KeyControl）
- template_matcher 模板加载与匹配（TemplateLoader / match_templates / NMS / 分类选择）
- player_detector  玩家检测（PlayerDetector）
- attack_distance  攻击距离计算（distance / in_range 纯函数）
- monster_detector 怪物检测（MonsterDetector）
- monster_tracker  怪物跟踪（MonsterTracker）
- hpmp_monitor   HP/MP 监控（HPMPMonitor）
- pet_feeder     宠物喂食（PetFeeder）

依赖方向（无环）：config → 底层工具 → 检测/按键 → 组装层（game_bot.py）。
core 包内模块不得反向依赖 game_bot.py。
"""
