# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

python env robot

## Overview

A MapleStory (冒险岛) game automation bot. **Pure image recognition — no game memory reads.** Pipeline: `mss` screen capture → OpenCV template matching → `pydirectinput` simulated keys. All entry scripts are **Windows-only** (use `ctypes.windll`, `pydirectinput`, `mss`) and **must run as administrator** (see "Admin elevation" below). All code comments, logs, and UI text are in Chinese — keep that convention.

There is **no test suite and no linter**. Install manually: `pip install opencv-python mss numpy pydirectinput pynput matplotlib`.

The code is modular: every responsibility is its own class in its own file under `core/`, and **all tunable parameters live in `config.toml`** with Chinese comments (loaded by `config.py`). Modules import `config` — tune parameters in one place.

## Modules

| Path | Purpose |
| ---- | ------- |
| `game_bot.py` | Main bot entry (`GameBot`): assembles detection + key simulation + HP/MP monitoring + pet feeding, drives the decision loop. F9 start/stop, F10 HP/MP+pet, F8 quit. |
| `monster_detect.py` | Standalone detection CLI entry → `core/monster_detector.py::main()`. F9 toggles detection, F8 quits (reuses the functional control keys). |
| `calibrate_hpmp.py` | Utility to interactively pick the detect/HP/MP screen regions (switches the game window to the front, grabs the fullscreen, drag-selects regions), save verification PNGs (`debug_detect.png` / `debug_hp_mask.png` / `debug_mp_mask.png` / `debug_regions_overview.png`) to judge recognition correctness, and write the coordinates back into `config.toml` (`[detect] detect_region`, `[hpmp] hp_bar_region`/`mp_bar_region`). |
| `config.py` | **Config loader** — loads all tunable parameters from `config.toml` (TOML, Chinese comments) and exposes them as module attributes (`config.X`); auto-generates `config.toml` from the bundled `config.default.toml` when missing; handles exe-packaged paths (`BASE_DIR`, `resource_dir()`). |
| `config.toml` | **User-editable config file** (the file to tune). Sections: `[path] [detect] [match] [monster_filter] [attack] [control_keys] [action_keys] [operation] [hpmp] [window]`. Must sit next to the exe/project root. |
| `config.default.toml` | Built-in default config template (bundled into the exe) — copied to `config.toml` on first run. |
| `core/admin.py` | `ensure_admin()` — UIPI admin elevation. |
| `core/win_window.py` | Win32 窗口工具：`find_game_window` / `find_game_window_hwnd` / `bring_to_front` / `activate_game_window`，供 calibrate_hpmp 与 screencap 共用。 |
| `core/utils.py` | `jitter()`, `setup_logging()`, `project_path()`. |
| `core/screencap.py` | `ScreenCapture` — mss wrapper (region grab, idempotent `close()`); 每次抓图前先把游戏窗口切到前台（全屏时避免抓到桌面/被遮挡窗口，句柄缓存）。 |
| `core/key_control.py` | `KeyControl` — pydirectinput wrapper; sole owner of the physical held-direction key `held_move_key`. |
| `core/template_matcher.py` | `TemplateLoader`, `match_templates()`, `non_max_suppression()`, monster category selection. |
| `core/player_detector.py` | `PlayerDetector` — player template matching. |
| `core/attack_distance.py` | `distance()` / `in_range()` pure functions (attack distance calc). |
| `core/monster_detector.py` | `MonsterDetector` — detection facade (fixed `detect_region` capture, purple ROI, annotate, calibrate, standalone CLI `main()`). |
| `core/monster_tracker.py` | `MonsterTracker` — approach / five-zone patrol / stuck-reverse state machine. |
| `core/hpmp_monitor.py` | `HPMPMonitor` — HP/MP bar recognition + potion keys, own thread. Also exports pure `calc_bar_percent()`. |
| `core/pet_feeder.py` | `PetFeeder` — pet feeding on a timer, own thread. |

## Commands

```bash
# Run the bot with a fixed monster category (skips the interactive menu)
python game_bot.py --monster zhu
python game_bot.py --monster all        # all categories under monster/

# Run detection standalone (F9 toggles detection, F8 quits)
python monster_detect.py --monster zhu
python monster_detect.py --calibrate     # save calibration_detect.png with boxes drawn

# Calibrate detect/HP/MP regions + save verification PNGs (writes the values into config.toml)
python calibrate_hpmp.py

# Package into a single exe (uses robot/ venv, install PyInstaller first)
robot/Scripts/python.exe -m pip install pyinstaller
robot/Scripts/python.exe build_exe.py
```

If no `--monster` is given, the program shows an interactive category menu at startup. Monster categories are subfolders of `monster/` (e.g. `monster/zhu`).

### Packaged exe (cross-device usage)
`build_exe.py` produces `dist/` — a complete distributable: `game_bot.exe` (onefile, bundles Python + deps + default templates) plus an editable `config.toml`, `monster/`, `player/` beside it. Copy the whole `dist/` folder to any Windows device and run `game_bot.exe` (it auto-elevates via `ensure_admin()`). At runtime `config.py` resolves `BASE_DIR` to the exe's folder: the exe-side `config.toml` / `monster/` / `player/` take precedence, falling back to the bundled `_MEIPASS` copies, so templates/config can be tuned or added without rebuilding.

## Architecture

### Parameters (`config.toml` via `config.py`)
All tunable values are centralized in **`config.toml`** (Chinese comments): screenshot/detect regions, template-match thresholds & scales, attack-distance constants, key mappings, operation delays/jitter, stuck-detection, HP/MP bar regions and HSV colors, pet-feeding interval. `config.py` parses it with stdlib `tomllib` and exposes every value as a module attribute (`config.X`), so modules keep importing `config` unchanged. Types are converted on load: regions → 4-tuples, colors → `np.uint8` arrays, `key_toggle_*` strings → `pynput` `Key` objects; `ALL_KEYS` / `SPACE_KEYS` are derived. **`BASE_DIR` is the project root — every path (template dirs, output PNGs) is resolved against it, so modules can safely live in `core/`.** Don't reintroduce `os.path.dirname(os.path.abspath(__file__))` in `core/` files for project paths; use `config.BASE_DIR` or `core/utils.project_path()`. Template dirs use `config.resource_dir(name)` (exe-side override → bundled `_MEIPASS` fallback). **`detect_region` / `hp_bar_region` / `mp_bar_region` are absolute screen coordinates set in `config.toml` via `calibrate_hpmp.py`.** There is no runtime auto-calibration — the bot reads these coordinates directly from `config.toml`. To change them, run `calibrate_hpmp.py`, box-select the regions, and paste the printed values into `[detect]` / `[hpmp]`. The `[window] game_window_keyword` is used by `core/screencap.py` to bring the game window to the foreground before each capture. Set `save_hp_mp_debug = true` in `[hpmp]` to dump `debug_hp*.png` / `debug_mp*.png` for troubleshooting.

### Template-based detection
- Templates live in folders, not code: `monster/<category>/` holds monster crops, `player/` holds player crops. Adding a monster type = create a subfolder and drop PNGs in. `TemplateLoader` pre-scales every template by `TEMPLATE_SCALES` and horizontally mirrors it (`with_mirror=True`), so both facing directions are covered at match time.
- Hardcoded screen geometry: tuned for a 3440×1440 display with the game in the right half. `MonsterDetector` captures the fixed `detect_region` from `config.toml` directly (no dynamic strip following the player's Y), detects the player across the full region width (`PlayerDetector`, only a small edge margin `PLAYER_DETECT_X_SHRINK`), then matches monsters only in the **purple ROI** (player Y ± `ATTACK_RADIUS`), with a fallback to the full region for oversized templates; `y_offset` reconciles ROI-local coords back to region coords. A monster is `in_range` when `abs(cx - pcx) <= ATTACK_DISTANCE_THRESHOLD` (`core/attack_distance.py`). Annotated `detect_live.png` uses color-coded boxes: green=player, red cross=player center, purple=monitor range, red=monster, yellow=in-range.
- `MonsterDetector` keeps its own standalone CLI (`main()`) and detection thread; `GameBot` drives it synchronously via `detect_once()` per frame.

### Bot decision loop (`game_bot.py`)
- `GameBot` builds one `ScreenCapture` (shared by detection and HP/MP), one `KeyControl` (sole owner of `held_move_key`), plus `MonsterDetector`, `MonsterTracker`, `HPMPMonitor`, `PetFeeder`. `stop()` does both `tracker.reset()` (state) and `keys.release_all()` (physical keys).
- Monster category is resolved once at startup (`select_monster_category` via CLI flag or menu); F9 later just toggles the running bot, never re-prompts.
- Per-frame logic: detect monsters first — **monsters take priority over five-zone patrol** (forbidden-zone centering is NOT run when any monster is present). With monsters: if any `in_range` (X distance ≤ `ATTACK_DISTANCE_THRESHOLD`), attack via `attack_toward` which first turns to face the monster (releases the current held direction, holds the monster's direction for `ATTACK_TURN_DELAY` seconds to complete the turn, then attacks — never attacks facing the wrong way); otherwise **hold** a direction key toward the nearest monster. With no monsters: run five-zone patrol — the detect region is split into 5 equal horizontal zones, zones 1 & 5 are forbidden; when the player box edge touches a forbidden-zone boundary, immediately reverse and patrol along the persistent `_phase_dir` direction (keep the exit-facing after chasing; reverse only at the forbidden-zone boundary or on stuck); plus pick up (Z) every `PICKUP_INTERVAL`. Stuck detection (`check_stuck_and_reverse`) reverses when the move-check-period travel is below `MOVE_STUCK_THRESHOLD` (default 10px). `MonsterTracker` owns that stuck-detection state machine — do not reintroduce a per-frame baseline refresh (that was a fixed bug). `MonsterTracker` must not mirror the held-key state; it reads `keys.held_move_key` only.
- Key bindings are in `config.toml` (`[control_keys]` / `[action_keys]`): attack `x`, pickup `z`, HP potion `9`, MP potion `0`, feed pet `8`, left/right direction keys (no jump key). `monster_detect.py` reuses `[control_keys]` (F9 toggle, F8 quit). Everything user-facing is a key in `config.toml` with a Chinese comment.

### HP/MP monitoring and pet feeding are decoupled from the bot
- F10 toggles `HPMPMonitor` + `PetFeeder` threads (both together), independent of F9's start/stop. `HPMPMonitor` samples `HP_BAR_REGION` / `MP_BAR_REGION` (absolute screen coords), computes bar percent via HSV color thresholds, and presses 9/0 when below `HP_THRESHOLD` (50%) / `MP_THRESHOLD` (50%), respecting `POTION_COOLDOWN`. Set `save_hp_mp_debug = true` in `config.toml` (`[hpmp]`) to dump `debug_hp*.png` / `debug_mp*.png` for troubleshooting.

### Admin elevation
`game_bot.py`, `core/monster_detector.py::main()`, and `calibrate_hpmp.py` call `ensure_admin()` at startup: if not elevated, they relaunch themselves via `ShellExecuteW("runas", ...)` and exit. This is required because the game runs as administrator and UIPI drops simulated input from non-elevated processes — don't remove it.

### Dependency direction (acyclic)
`config.py → core/{admin,utils,screencap,key_control,template_matcher,player_detector,attack_distance,monster_detector,monster_tracker,hpmp_monitor,pet_feeder} → game_bot.py`. Rules: `core/` modules must **not** import `game_bot.py`; `core/monster_tracker.py` must **not** import `core/monster_detector.py` (player coords are passed in as `cur`); `core/key_control.py` must **not** import `core/monster_tracker.py`. Logging: `MonsterDetector` keeps `print()` output (standalone tool); `GameBot` subsystems use `logging` via `utils.setup_logging()`.
