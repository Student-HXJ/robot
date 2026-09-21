"""
怪物检测模块（检测门面 + 独立检测命令行）。

组装 PlayerDetector / AttackDistance / TemplateLoader / ScreenCapture，
对外提供一次完整检测 ``detect_once()``，内部完成：
1. 按配置检测区域截取游戏画面（固定区域，不做动态调整）
2. 玩家位置检测（委托 PlayerDetector，按职业加载 player/<职业>/ 模板）
3. 紫框范围内怪物检测（模板匹配 + 多尺度 + 镜像）
4. 面积/置信度过滤 + 攻击距离判定（委托 attack_distance）
5. 怪物按距离升序排列

同时提供独立检测线程（F9 启停、F8 退出）与校准模式。

视觉标注（detect_live.png）：
- 绿色框   = 玩家检测框
- 红色十字 = 玩家中心
- 紫色框   = 怪物监控范围（固定为整个检测区域，不随玩家移动）
- 红色框   = 检测到的怪物
- 黄色框   = 在攻击距离内（与玩家 X 距离 <= 阈值）的怪物

注意：本模块保持 print() 日志风格（独立工具），不混用 logging。
"""

import os
import threading
import time

import cv2

import config
from core import attack_distance
from core.player_detector import PlayerDetector
from core.screencap import ScreenCapture
from core.template_matcher import (TemplateLoader, match_templates, non_max_suppression,
                                   select_monster_category, select_player_category)


class MonsterDetector:
    """怪物与玩家检测器（检测门面）。

    通过模板匹配在游戏画面中检测玩家和怪物位置，
    判断怪物是否进入玩家攻击范围（X 距离判定）。
    """

    def __init__(self, monster_dir=None, player_dir=None, load_monsters=True, screencap=None):
        """
        Args:
            monster_dir: 怪物模板目录（相对项目根目录），例如 "monster/zhu"。
                         为 None 时使用整个 monster/ 目录（递归加载所有分类）。
            player_dir: 玩家模板目录（相对项目根目录），例如 "player/binglei"
                        （player/ 下的职业子目录）。为 None 时使用整个 player/
                        目录（递归加载所有职业）。
            load_monsters: 是否在构造时就加载怪物模板。传 False 可延迟到
                           实际启动前再调用 set_monster_dir() 选择分类加载。
            screencap: 复用的 ScreenCapture 实例；为 None 时内部自建并拥有
                       （close() 会释放）。由调用方传入时，close() 不释放。
        """
        self.monster_dir = monster_dir or config.MONSTER_DIR
        self.active_event = threading.Event()  # 是否正在检测
        self.stop_event = threading.Event()  # 通知工作线程退出
        self.worker_thread = None
        self._lock = threading.Lock()

        # 截屏：外部传入则共享不释放；否则自建并拥有
        self._cap = screencap
        self._owns_cap = screencap is None
        if self._owns_cap:
            self._cap = ScreenCapture()

        # 帧计数器（用于降低日志频率）
        self._frame_count = 0

        # 检测区域：固定按 config.toml [detect] detect_region 抓图，
        # 不做随玩家上下移动的动态检测框调整（已移除）
        self._detect_region = self._calc_detect_region()

        # 玩家参考位置（检测区域中心）：首次检测前 / 检测失败时的回退值
        self._player_pos = (
            self._detect_region[2] // 2,
            self._detect_region[3] // 2,
        )

        # 实时刷新图路径（项目根目录）
        self._live_frame_path = os.path.join(config.BASE_DIR, "detect_live.png")

        # 加载怪物模板（含镜像，怪物有左右两个朝向）
        self.templates = []
        if load_monsters:
            self.set_monster_dir(self.monster_dir)

        # 玩家检测器（按职业加载玩家模板，含镜像）
        self._player_detector = PlayerDetector(self._detect_region[2], self._detect_region[3], player_dir=player_dir)

        # 最近一次检测的玩家框（供 GameBot 读取玩家中心/位置）
        self._player_box = None  # (x, y, w, h, cx, cy)

        # 玩家位置缓存：检测失败时回退到上次成功位置，而非检测区域中心
        self._last_player = None  # 最近一次成功检测到的玩家完整元组
        self._player_last_seen = 0.0  # 最近一次成功检测到玩家的时间戳
        self._player_known = False  # 玩家位置当前是否可信（本帧检测到或缓存未过期）

    # ------------------------------------------------------------------ #
    #  对外只读状态（供 GameBot 使用）
    # ------------------------------------------------------------------ #

    @property
    def player_box(self):
        """最近一次检测的玩家框 (x, y, w, h, cx, cy)，未检测到玩家时为 None。"""
        return self._player_box

    @property
    def detect_region(self):
        """检测区域 (left, top, width, height)。"""
        return self._detect_region

    @property
    def player_dir(self):
        """当前玩家模板目录（player/ 下的职业子目录）。"""
        return self._player_detector.player_dir

    @property
    def player_templates(self):
        """玩家模板列表（调试/统计用）。"""
        return self._player_detector.templates

    @property
    def player_known(self):
        """玩家位置当前是否可信（本帧检测到或缓存未过期）。"""
        return self._player_known

    def player_cx(self):
        """当前玩家中心 X；检测失败时回退到上次已知位置（缓存）。"""
        pb = self._player_box
        return pb[4] if pb else self._player_pos[0]

    # ------------------------------------------------------------------ #
    #  模板目录（怪物分类 / 玩家职业）
    # ------------------------------------------------------------------ #

    def set_monster_dir(self, monster_dir):
        """切换怪物分类并重新加载模板（可在运行前随时调用）。

        Args:
            monster_dir: 怪物模板目录（相对项目根目录），如 "monster/zhu"；
                         传 config.MONSTER_DIR 时递归加载所有分类。

        Returns:
            加载到的模板数量
        """
        self.monster_dir = monster_dir or config.MONSTER_DIR
        # 选中具体分类时只加载该子目录；选择"全部"时递归加载所有分类
        recursive = (self.monster_dir == config.MONSTER_DIR)
        print(f"[INFO] 怪物模板目录: {self.monster_dir}"
              f"{'（递归所有分类）' if recursive else ''}")
        self.templates = TemplateLoader(self.monster_dir, with_mirror=True, recursive=recursive).load(self._detect_region[2], self._detect_region[3])
        if not self.templates:
            print(f"[WARN] 未加载到任何怪物模板！请检查 "
                  f"{self.monster_dir}/ 目录")

        return len(self.templates)

    def set_player_dir(self, player_dir):
        """切换玩家职业并重新加载模板（可在运行前随时调用）。

        Args:
            player_dir: 玩家模板目录（相对项目根目录），如 "player/binglei"；
                        传 config.PLAYER_DIR 时递归加载所有职业。

        Returns:
            加载到的模板数量
        """
        return self._player_detector.set_player_dir(player_dir)

    def _calc_detect_region(self):
        """计算检测区域（左右各向内收缩 DETECT_SIDE_MARGIN 像素）。"""
        if config.DETECT_REGION is not None:
            return config.DETECT_REGION

    # ------------------------------------------------------------------ #
    #  检测线程控制（独立检测 CLI 使用）
    # ------------------------------------------------------------------ #

    def start(self):
        """启动检测工作线程。"""
        self.stop_event.clear()
        self.active_event.set()
        self.worker_thread = threading.Thread(target=self._detect_loop, daemon=True)
        self.worker_thread.start()

    def stop(self):
        """停止检测工作线程。"""
        self.stop_event.set()
        self.active_event.clear()
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2)
        self.worker_thread = None

    def toggle(self):
        """切换启停状态。"""
        with self._lock:
            if self.active_event.is_set():
                print("[INFO] 停止检测")
                self.stop()
            else:
                print("[INFO] 启动检测")
                self.start()

    # ------------------------------------------------------------------ #
    #  检测核心
    # ------------------------------------------------------------------ #

    def _find_monsters(self, screen_gray, y_offset=0):
        """检测怪物。

        怪物检测在紫色框 ROI（screen_gray）上进行，缩小模板匹配计算量。
        紫色框固定为整个检测区域（不随玩家移动），因此 screen_gray 即整张
        检测区域灰度图，y_offset 恒为 0（保留参数仅为保持接口一致性）。

        Returns:
            怪物列表 [(cx, cy, x, y, w, h, score, name, direction), ...]
        """
        hits = match_templates(screen_gray, self.templates, config.MATCH_THRESHOLD, y_offset=y_offset)
        hits = non_max_suppression(hits, config.NMS_DISTANCE)
        # 紫色框 = 整个检测区域；怪物检测框必须完全在紫框内
        roi_h = screen_gray.shape[0]
        monsters = []
        for h in hits:
            cx, cy, w, hgt, score, name, direction = h
            x, y = cx - w // 2, cy - hgt // 2
            if y < 0 or y + hgt > roi_h:
                continue
            monsters.append((cx, cy, x, y, w, hgt, score, name, direction))
        return monsters

    def detect_once(self, save_annotated=True):
        """执行一次完整检测（玩家 + 怪物 + 攻击范围判断）。

        Args:
            save_annotated: 是否保存标注图到 detect_live.png

        Returns:
            (monsters, nearest)
            monsters: [(cx, cy, x, y, w, h, dist, score, name, direction,
                        in_range), ...] 按 dist 升序
            nearest: monsters[0] 或 None
        """
        # 截图：固定按配置检测区域抓图（不做动态检测框调整）
        color_img = self._cap.grab_region(self._detect_region)
        screen_gray = cv2.cvtColor(color_img, cv2.COLOR_BGR2GRAY)

        # 帧计数（用于降频日志）
        self._frame_count += 1

        # 1. 检测玩家（每帧检测；失败时回退到上次已知位置，避免朝向/距离判断错乱）
        now = time.time()
        player = self._player_detector.find(screen_gray)
        if player is not None:
            self._last_player = player
            self._player_last_seen = now
        # 玩家位置是否仍可信：本帧检测到，或缓存未过期（PLAYER_CACHE_TTL 内）
        self._player_known = ((now - self._player_last_seen) <= config.PLAYER_CACHE_TTL)
        if self._player_known and self._last_player is not None:
            player = self._last_player  # 本帧结果优先；失败则用上次已知位置
        else:
            player = None

        if player is not None:
            pcx, pcy, px, py, pw, ph, pscore = player
            self._player_box = (px, py, pw, ph, pcx, pcy)
        else:
            pcx, pcy = self._player_pos
            self._player_box = None

        # 2. 检测怪物（紫色框固定为整个检测区域，不随玩家 Y 移动）
        #     紫色框 Y 范围 = [0, 检测区域高]（即配置 detect_region 的坐标）
        purple_top = 0
        purple_bottom = screen_gray.shape[0]
        purple_roi = screen_gray
        monsters_raw = self._find_monsters(purple_roi, y_offset=0)

        # 3. 面积+置信度过滤，计算距离和攻击判定
        monsters = []
        for m in monsters_raw:
            cx, cy, x, y, mw, mh, mscore, name, direction = m
            area = mw * mh
            if area < config.MONSTER_MIN_AREA:
                continue
            if mscore < config.MONSTER_CONFIRM_SCORE:
                continue
            dist = attack_distance.distance(cx, pcx)
            # 攻击判定：玩家位置可信 + X 距离 <= 阈值（不做多帧确认）
            in_range = (self._player_known and attack_distance.in_range(cx, pcx))
            monsters.append((cx, cy, x, y, mw, mh, dist, mscore, name, direction, in_range))
        monsters.sort(key=lambda m: m[6])

        # 存图：只保存怪物检测实际处理的紫色框 ROI（与处理区域完全一致，即整个检测区域）
        if save_annotated:
            purple_roi_color = color_img.copy()
            self._annotate(purple_roi_color, player, monsters, y_offset=purple_top)
            cv2.imwrite(self._live_frame_path, purple_roi_color)
        return monsters, (monsters[0] if monsters else None)

    def _annotate(self, color_img, player, monsters, y_offset=0):
        """在截图上画标注。

        所有传入坐标均为"全图（strip）坐标系"，通过 y_offset 统一换算到
        当前绘制底图的坐标系，确保绘制底图（处理区域）与坐标一致。
        """
        det_h, det_w = color_img.shape[:2]
        pcx, pcy = ((player[0], player[1] - y_offset) if player else (self._player_pos[0], self._player_pos[1] - y_offset))

        # 紫色框：怪物监控范围 = 整个检测区域（固定，不随玩家移动）
        cv2.rectangle(color_img, (0, 0), (det_w - 1, det_h - 1), (255, 0, 255), 2)

        # 玩家：绿色检测框 + 红色十字
        if player:
            pcx, pcy, px, py, pw, ph, pscore = player
            py -= y_offset
            pcy -= y_offset
            cv2.rectangle(color_img, (px, py), (px + pw, py + ph), (0, 255, 0), 2)
            cv2.drawMarker(color_img, (pcx, pcy), (0, 0, 255), cv2.MARKER_CROSS, 30, 2)
            cv2.putText(color_img, f"player {pscore:.2f}", (pcx + 15, pcy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # 怪物：红色框（攻击范围内为黄色）
        for m in monsters:
            mcx, mcy, mx, my, mw, mh, mdist, mscore, mname, mdir, in_range = m
            mcy -= y_offset
            my -= y_offset
            color = (0, 255, 255) if in_range else (0, 0, 255)
            cv2.rectangle(color_img, (mx, my), (mx + mw, my + mh), color, 2)
            cv2.drawMarker(color_img, (mcx, mcy), color, cv2.MARKER_CROSS, 20, 2)
            cv2.putText(color_img, f"{int(mdist)}px {mw * mh}{'*' if in_range else ''}", (mcx + 15, mcy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

    def _detect_loop(self):
        """工作线程主循环（独立检测 CLI 使用）。"""
        from datetime import datetime
        while not self.stop_event.is_set():
            try:
                monsters, nearest = self.detect_once(save_annotated=False)
                ts = datetime.now().strftime("%H:%M:%S")
                if nearest:
                    _, _, _, _, _, _, dist, score, name, face_dir, in_range = nearest
                    flag = " [攻击范围]" if in_range else ""
                    print(f"[{ts}] {name}({face_dir}) 距离{dist:.0f}px{flag} "
                          f"置信度={score:.2f} 共{len(monsters)}只")
                else:
                    print(f"[{ts}] 未检测到怪物")
            except Exception as e:
                print(f"[ERROR] 检测异常: {e}")
            time.sleep(config.DETECT_INTERVAL)

    # ------------------------------------------------------------------ #
    #  校准模式
    # ------------------------------------------------------------------ #

    def calibrate(self):
        """校准模式：截图保存检测区域，标注各框位置。"""
        left, top, w, h = self._detect_region
        img = self._cap.grab_region(self._detect_region)
        px, py = self._player_pos

        # 紫色框 = 整个检测区域（固定监控范围，不随玩家移动），与绿色边框重叠
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), (255, 0, 255), 2)
        # 红色十字
        cv2.drawMarker(img, (px + 25, py + 10), (0, 0, 255), cv2.MARKER_CROSS, 40, 3)
        cv2.circle(img, (px + 25, py + 10), 20, (0, 0, 255), 2)
        # 绿色检测区域边框
        cv2.rectangle(img, (0, 0), (w - 1, h - 1), (0, 255, 0), 2)

        out_path = os.path.join(config.BASE_DIR, "calibration_detect.png")
        ok = cv2.imwrite(out_path, img)
        print(f"[校准] 检测区域: {self._detect_region}")
        print(f"[校准] 玩家位置: {self._player_pos}")
        print(f"[校准] 截图保存: {out_path} (成功={ok})")
        print(f"[校准] 紫框=监控范围（固定=整个检测区域）, 红十字=玩家, 绿框=检测区域")
        print(f"[校准] 怪物模板目录: {self.monster_dir}")
        print(f"[校准] 怪物模板数: {len(self.templates)}")
        print(f"[校准] 玩家模板目录: {self.player_dir}")
        print(f"[校准] 玩家模板数: {len(self.player_templates)}")

    def close(self):
        """释放资源（仅释放内部自建的截屏实例）。"""
        if self._owns_cap:
            self._cap.close()


# ---------------------------------------------------------------------- #
#  独立检测命令行入口
# ---------------------------------------------------------------------- #


def main():
    """独立检测 CLI：--monster 选择怪物分类，--player 选择玩家职业，
    --calibrate 校准，F9 启停，F8 退出。"""
    from core.admin import ensure_admin
    ensure_admin()

    import argparse
    parser = argparse.ArgumentParser(description="冒险岛怪物+玩家检测(模板匹配)")
    parser.add_argument("--calibrate", action="store_true", help="校准模式")
    parser.add_argument("--monster", default=None, help="怪物分类名（monster/ 下的子文件夹名），"
                        "如 zhu；传 all 表示全部；不传则启动时交互选择")
    parser.add_argument("--player", default=None, help="玩家职业名（player/ 下的子文件夹名），"
                        "如 binglei；传 all 表示全部；不传则启动时交互选择")
    args = parser.parse_args()

    # 启动时先选择要检测的怪物分类与玩家职业
    monster_dir = select_monster_category(args.monster)
    if monster_dir is None:
        print("[INFO] 已取消，程序退出")
        return
    player_dir = select_player_category(args.player)
    if player_dir is None:
        print("[INFO] 已取消，程序退出")
        return
    detector = MonsterDetector(monster_dir=monster_dir, player_dir=player_dir)
    if args.calibrate:
        detector.calibrate()
        detector.close()
        return

    from pynput.keyboard import Listener

    def on_press(key):
        if key == config.KEY_TOGGLE_BOT:
            detector.toggle()
        elif key == config.KEY_QUIT:
            print("\n[INFO] 退出程序")
            detector.stop()
            return False

    print("=" * 60)
    print("  冒险岛怪物+玩家检测（模板匹配版）")
    print("=" * 60)
    print(f"  - 按 [{config.KEY_TOGGLE_BOT.name.upper()}] 启动/停止检测")
    print(f"  - 按 [{config.KEY_QUIT.name.upper()}] 退出程序")
    print(f"  - 检测区域: {detector.detect_region}")
    print(f"  - 怪物分类: {detector.monster_dir}")
    print(f"  - 怪物模板数: {len(detector.templates)}")
    print(f"  - 玩家职业: {detector.player_dir}")
    print(f"  - 玩家模板数: {len(detector.player_templates)}")
    print(f"  - 攻击半径: {config.ATTACK_RADIUS}px")
    print("=" * 60)

    with Listener(on_press=on_press) as listener:
        listener.join()
    detector.stop()
    detector.close()
    print("[INFO] 程序已退出")


if __name__ == '__main__':
    import sys
    try:
        main()
    except KeyboardInterrupt:
        print("\n[INFO] Ctrl+C 中断，退出程序")
        sys.exit(0)
