"""
智能游戏机器人（主决策循环 + 命令行入口）。

组装各核心模块：ScreenCapture / KeyControl / MonsterDetector /
MonsterTracker / HPMPMonitor / PetFeeder / AuxSkillCaster，由单一决策循环驱动：
1. 检测怪物：有怪物时攻击/追怪优先于五分段寻路
2. 怪物在攻击距离内 → 转身面向怪物方向攻击（绝不朝反方向攻击）
3. 怪物在攻击距离外 → 移动靠近（持续按住方向键）
4. 无怪物 → 五分段寻路（禁区判定 + 沿持久方向巡逻）
5. HP <= 阈值按键 9 补血，MP <= 阈值按键 0 补蓝
6. 每 FEED_PET_INTERVAL 自动喂食宠物
7. 每 SKILL_MOVE_INTERVAL / SKILL_ATTACK_SPEED_INTERVAL 自动施放辅助技能

按键说明：
  F9 启动/停止机器人；F10 开启/关闭 HP/MP 监控 + 喂食宠物；
  F11 开启/关闭辅助技能（移动加速 a / 攻击加速 s）；
  F8 退出。攻击 X | 补HP 9 | 补MP 0 | 喂宠物 8。
"""

import ctypes
import sys
import threading
import time

from pynput.keyboard import Listener

import config
from core import utils
from core.admin import ensure_admin
from core.aux_skill import AuxSkillCaster
from core.hpmp_monitor import HPMPMonitor
from core.key_control import KeyControl
from core.monster_detector import MonsterDetector
from core.monster_tracker import MonsterTracker
from core.pet_feeder import PetFeeder
from core.screencap import ScreenCapture
from core.template_matcher import select_monster_category


class GameBot:
    """智能游戏机器人：组装检测、跟踪、监控各模块并驱动决策循环。"""

    def __init__(self, monster_dir=None):
        """
        Args:
            monster_dir: 已确定的怪物分类目录（monster/ 下的子目录名，
                         如 "zhu"）。由程序启动时一次性选择/解析并加载模板，
                         F9 启动机器人时不再交互选择。
        """
        self.log = utils.setup_logging()
        self.active_event = threading.Event()  # 是否正在运行
        self.stop_event = threading.Event()  # 通知工作线程退出
        self.worker_thread = None
        self._lock = threading.Lock()
        self._toggle_lock = threading.Lock()  # 保护 start/stop 状态机

        # 截屏：检测与 HP/MP 共用同一个实例，统一在本类 close() 释放
        self._cap = ScreenCapture()

        # 按键模拟（唯一持有物理按住状态 held_move_key）
        self.keys = KeyControl(log=self.log)

        # HP/MP 监控（F10 开关，默认关闭，与机器人启停完全独立）
        self.hp_mp_enabled = False
        self.hpmp = HPMPMonitor(self._cap, self.keys, log=self.log)

        # 喂食宠物（同受 F10 控制，与 HP/MP 一起开关）
        self.feeder = PetFeeder(self.keys, log=self.log)

        # 辅助技能（F11 开关，默认关闭，与机器人启停完全独立）
        self.aux_skill_enabled = False
        self.aux_skill = AuxSkillCaster(self.keys, log=self.log)

        # 怪物检测器（怪物分类已在程序启动时确定，此处加载模板）
        self.detector = MonsterDetector(monster_dir=config.MONSTER_DIR, load_monsters=False, screencap=self._cap)
        loaded = self.detector.set_monster_dir(monster_dir) if monster_dir else 0
        self.log.info("怪物检测分类: %s（%d 个模板）", monster_dir if monster_dir else "(未指定)", loaded)

        # 怪物跟踪器（靠近/随机移动/卡住反向脱困）
        self.tracker = MonsterTracker(self.keys, log=self.log)

    # ------------------------------------------------------------------ #
    #  toggle 控制（F9）
    # ------------------------------------------------------------------ #

    def start(self):
        """启动机器人工作线程（怪物分类已在程序启动时确定并加载模板）。"""
        with self._toggle_lock:
            if self.worker_thread and self.worker_thread.is_alive():
                return
            self.stop_event.clear()
            self.active_event.set()
            self.worker_thread = threading.Thread(target=self._run_bot, daemon=True)
            self.worker_thread.start()
        # 注意：机器人启动不再联动 HP/MP 监控与喂食宠物，二者完全由 F10 控制

    def stop(self):
        """停止机器人工作线程并释放所有按键。"""
        with self._toggle_lock:
            self.stop_event.set()
            self.active_event.clear()
            if self.worker_thread and self.worker_thread.is_alive():
                self.worker_thread.join(timeout=2)
            self.worker_thread = None
        # 双职责清理：跟踪状态 + 物理按键（防止卡键）
        self.tracker.reset()
        self.keys.release_all()

    def toggle(self):
        """切换启停状态。"""
        if self.active_event.is_set():
            self.log.info("停止机器人")
            self.stop()
        else:
            self.log.info("启动机器人")
            self.start()

    # ------------------------------------------------------------------ #
    #  HP/MP 监控 + 喂食宠物（F10，与机器人启停独立）
    # ------------------------------------------------------------------ #

    def toggle_hp_mp(self):
        """切换 HP/MP 监控 + 喂食宠物开关（F10 统一控制）。

        血条/蓝条坐标由 calibrate_hpmp.py 校准、检测框坐标由 calibrate_detect.py
        校准并写入 config.toml，此处不再做运行时自动校准，直接按配置坐标启动
        监控线程。
        """
        self.hp_mp_enabled = not self.hp_mp_enabled
        if self.hp_mp_enabled:
            self.hpmp.start()
            self.feeder.start()
        else:
            self.hpmp.stop()
            self.feeder.stop()
        status = "开启" if self.hp_mp_enabled else "关闭"
        self.log.info(f"HP/MP 监控 + 喂食宠物: {status}")

    # ------------------------------------------------------------------ #
    #  辅助技能（F11，与机器人启停、HP/MP 监控独立）
    # ------------------------------------------------------------------ #

    def toggle_aux_skill(self):
        """切换辅助技能开关（F11 统一控制移动加速 + 攻击加速）。

        开启后由 AuxSkillCaster 独立线程按 config.toml [aux_skill] 配置的
        间隔定时按键（默认移动加速 a / 200 秒，攻击加速 s / 30 秒）。
        """
        self.aux_skill_enabled = not self.aux_skill_enabled
        if self.aux_skill_enabled:
            self.aux_skill.start()
        else:
            self.aux_skill.stop()
        status = "开启" if self.aux_skill_enabled else "关闭"
        self.log.info(f"辅助技能（移动加速 + 攻击加速）: {status}")

    # ------------------------------------------------------------------ #
    #  怪物检测
    # ------------------------------------------------------------------ #

    def _detect_monsters(self):
        """调用 MonsterDetector.detect_once 检测怪物。

        Returns:
            简化格式 [(cx, cy, dist, direction, name, score, in_range), ...]
        """
        monsters_raw, _ = self.detector.detect_once(save_annotated=False)
        return [(m[0], m[1], m[6], m[9], m[8], m[7], m[10]) for m in monsters_raw]

    def _keep_centered(self, now):
        """五区巡逻禁区判定：玩家框触达检测框最左/最右禁止区域边界时，立即反向。

        把检测框按宽度平均分成 5 块，最左 1/5 与最右 1/5 为禁止区域：玩家框
        左边界触达区块 1 右边界（左分界）按住右、右边界触达区块 5 左边界
        （右分界）按住左，立即反向直到触达另一侧禁止区域；中间 3/5（宽度占比
        keep_centered_middle_fraction，默认 0.6）沿持久方向巡逻移动。
        用玩家框边界而非中心判定，使玩家框不进入禁止区域。仅在无怪物时调用
        （有怪物时攻击/追怪优先，不做禁区回中），是五分段寻路的禁区判定部分；
        玩家位置不可信时跳过。
        """
        if not self.detector.player_known:
            return False
        pb = self.detector.player_box
        if pb is None:
            return False
        px, pw = pb[4], pb[2]
        # 检测坐标系：截图区域即配置检测区域，玩家 X 落在 [0, 宽度] 内
        w = self.detector.detect_region[2]
        # 五区边界 X：中间区域宽度 = 宽度 * keep_centered_middle_fraction，
        # 左/右各留 (1 - 比例)/2 宽度的禁止区域
        left_boundary = w * (1 - config.KEEP_CENTERED_MIDDLE_FRACTION) / 2
        right_boundary = w * (1 + config.KEEP_CENTERED_MIDDLE_FRACTION) / 2
        return self.tracker.keep_centered(now, px, pw, left_boundary, right_boundary)

    # ------------------------------------------------------------------ #
    #  主决策循环
    # ------------------------------------------------------------------ #

    def _run_bot(self):
        """主决策循环。

        每轮执行：
        0. 检测怪物
        1. 有怪物在攻击范围内 → 转身面向怪物攻击（攻击逻辑优先于五分段寻路）
        2. 有怪物但超出范围 → 移动靠近（持续按住方向键）
        3. 无怪物 → 五分段寻路（禁区判定 + 沿持久方向巡逻）
        """
        frame_count = 0

        while not self.stop_event.is_set():
            now = time.time()
            frame_count += 1

            # 1. 检测怪物
            monsters = self._detect_monsters()
            # 日志降频：每 LOG_FRAME_INTERVAL 帧打印一次检测概况
            if frame_count % config.LOG_FRAME_INTERVAL == 0:
                self.log.info(f"检测到 {len(monsters)} 只怪物")

            # 当前玩家位置（检测坐标系），用于卡住检测/居中校正
            pb = self.detector.player_box
            cur = (pb[4], pb[5]) if pb else None

            if monsters:
                # 攻击逻辑优先于五分段寻路：有怪物时不执行禁区回中，
                # 直接攻击或追怪（追怪途中撞墙由卡住检测反向脱困）
                in_range_monsters = [m for m in monsters if m[6]]  # m[6]=in_range
                if in_range_monsters:
                    # 攻击范围内取最近的
                    target = in_range_monsters[0]  # monsters 已按距离排序
                else:
                    # 没有在攻击范围内的，取最近的移动靠近
                    target = monsters[0]

                cx, _, dist, direction, name, score, in_range = target

                if in_range:
                    # 怪物在攻击距离内：转身面向怪物攻击（attack_toward
                    # 内部处理转身/松开当前移动键，确保不朝反方向攻击）
                    px = self.detector.player_cx()
                    self.keys.attack_toward(cx, px, name, direction, dist, score, frame_count)
                else:
                    # 怪物超出攻击距离：持续按住方向键朝怪物移动（不松开）
                    px = self.detector.player_cx()
                    self.tracker.hold_toward(cx, px, now, frame_count, name, dist)
                    # 只要按住方向键就做卡住检测：靠近途中被墙/怪挡住立即反向脱困
                    self.tracker.check_stuck_and_reverse(now, cur)
            else:
                # 无怪物 → 五分段寻路：禁区判定（玩家框触达检测框最左/最右
                # 禁止区域边界立即反向）优先接管移动方向，中间区域沿持久方向
                # 巡逻移动
                centering = self._keep_centered(now)
                if centering:
                    # 回中中：不随机换向，只做卡住检测
                    self.tracker.check_stuck_and_reverse(now, cur)
                else:
                    # 巡逻移动 + 卡住检测（内部自动初始化基准点）
                    self.tracker.idle_wander(now, cur, frame_count)

                    # 已按住方向键则保持不动，不松开
                    time.sleep(0.05)

    def close(self):
        """释放资源。"""
        self.hpmp.stop()
        self.feeder.stop()
        self.aux_skill.stop()
        self.detector.close()  # 共享截屏实例，此处不释放
        self._cap.close()


# ---------------------------------------------------------------------- #
#  命令行入口
# ---------------------------------------------------------------------- #


def main():
    ensure_admin()
    print(f"[INFO] 管理员权限: {bool(ctypes.windll.shell32.IsUserAnAdmin())}")

    import argparse
    parser = argparse.ArgumentParser(description="智能游戏机器人")
    parser.add_argument("--monster", default=None, help="怪物分类名（monster/ 下的子文件夹名），如 zhu；"
                        "传 all 表示全部；不传则在程序启动时交互选择")
    args = parser.parse_args()

    # 程序启动时一次性确定怪物分类（命令行指定或交互选择），之后不再询问
    monster_dir = select_monster_category(args.monster)
    if monster_dir is None:
        print("[INFO] 未选择怪物分类，程序退出")
        return

    bot = GameBot(monster_dir=monster_dir)

    def on_press(key):
        if key == config.KEY_TOGGLE_BOT:
            # 放到后台线程执行，避免 toggle/stop 中的 join 阻塞 pynput 监听线程
            threading.Thread(target=bot.toggle, daemon=True).start()
        elif key == config.KEY_TOGGLE_HPMP:
            threading.Thread(target=bot.toggle_hp_mp, daemon=True).start()
        elif key == config.KEY_TOGGLE_AUX_SKILL:
            threading.Thread(target=bot.toggle_aux_skill, daemon=True).start()
        elif key == config.KEY_QUIT:
            print("[INFO] Q 按下，退出程序")
            bot.stop()
            return False

    print("=" * 60)
    print("  智能游戏机器人已启动")
    print("=" * 60)
    print("  - 按 [F9] 启动/停止机器人")
    print("  - 按 [F10] 开启/关闭 HP/MP 监控 + 喂食宠物（独立开关）")
    print("  - 按 [F11] 开启/关闭辅助技能（独立开关）")
    print("  - 按 [F8] 退出程序")
    print(f"  - 攻击: {config.KEY_ATTACK.upper()}")
    print(f"  - 补HP: {config.KEY_HP_POTION} "
          f"(HP<={config.HP_THRESHOLD}%) | "
          f"补MP: {config.KEY_MP_POTION} "
          f"(MP<={config.MP_THRESHOLD}%)")
    print(f"  - 喂食宠物: {config.KEY_FEED_PET} "
          f"(每 {config.FEED_PET_INTERVAL / 60:.0f} 分钟自动按一次)")
    print(f"  - 辅助技能: 移动加速 {config.KEY_SKILL_MOVE} "
          f"(每 {config.SKILL_MOVE_INTERVAL:.0f} 秒) | 攻击加速 "
          f"{config.KEY_SKILL_ATTACK_SPEED} "
          f"(每 {config.SKILL_ATTACK_SPEED_INTERVAL:.0f} 秒)")
    print("  - 移动: 方向键")
    print(f"  - 怪物检测: core/monster_detector.py")
    print(f"  - 怪物分类: {monster_dir}（启动时已确定，F9 不再询问）")
    print(f"  - 匹配阈值: {config.MATCH_THRESHOLD}")
    print(f"  - 五区巡逻: 开启（检测区域均分 5 块，最左/最右 1/5 为禁止区域，"
          f"触达立即反向；中间 "
          f"≈{config.KEEP_CENTERED_MIDDLE_FRACTION * 100:.0f}% 宽度内自由追怪/巡逻）")
    print(f"  - 检测区域: {bot.detector.detect_region}")
    print("=" * 60)

    with Listener(on_press=on_press) as listener:
        listener.join()
    bot.stop()
    bot.close()
    print("[INFO] 程序已退出")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 中断，退出程序")
        sys.exit(0)
