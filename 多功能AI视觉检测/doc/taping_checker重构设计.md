# taping_checker 重构设计文档

## 1. 概述

将原版 `taping_checker 稳定版.py`（1016行单文件）重构为 AppManager+BaseApp 架构下的独立应用，UI风格统一为LVGL，显示架构采用VIDEO+OSD方案。

## 2. 功能确认清单

### 2.1 保留功能

| 编号 | 功能 | 修改说明 |
|------|------|---------|
| F1 | AI推理引擎 | 保留，代码结构不变 |
| F2 | 检测框绘制 | **修改**：bbox颜色按类别可配置，预制5种类别颜色 |
| F3 | 报警逻辑 | 保留，3次蜂鸣循环 |
| F4 | 三色灯控制 | **修改**：只保留黄灯IO33和红灯IO42，删除绿灯IO32 |
| F5 | IO输入防抖 | **修改**：只保留IO34和IO35作为输入，删除IO26和IO43 |
| F6 | IO34触发拍照 | **新增**：IO34低电平触发拍照（原版IO43功能迁移） |
| F8 | 会话目录管理 | 保留 |
| F9 | 多路径回退保存 | 保留 |
| F10 | 保存提示 | 保留 |
| F11 | 蜂鸣器报警 | 保留，与Speaker互斥，由sound_mode配置项控制 |
| F12 | Speaker音频播放 | **恢复保留**：AudioModule优先→I2S回退，播放WAV文件，与蜂鸣器互斥 |
| F13 | 声音策略 | **修改**：改为三选一互斥模式（buzzer/speaker/mute），不再用both/seq |
| F14 | 拍照成功蜂鸣 | **修改**：只响一声（区别于报警3声），遵循sound_mode设定 |
| F15 | 配置按钮 | 保留，改为LVGL按钮 |
| F16 | 模型按钮 | 保留，改为LVGL按钮 |
| F17 | 配置面板 | 保留，改为LVGL弹窗 |
| F18 | 模型选择面板 | **修改**：从配置的model_dir目录扫描kmodel文件 |
| F19 | 授权密码面板 | 保留，改为LVGL数字键盘弹窗 |
| F22 | 首帧触控抑制 | 保留（LVGL事件天然解决，但面板切换时需加延迟） |
| F23 | 用户配置文件 | 保留，路径 `/sdcard/configs/taping_checker.json` |
| F24 | 部署配置文件 | 保留，路径改为 `/sdcard/configs/deploy_config_taping.json`（与用户配置同目录） |
| F25 | 模型热切换 | 保留 |
| F26 | 模型目录配置 | **新增**：可配置模型搜索目录，默认`/sdcard/` |

### 2.2 删除功能

| 编号 | 功能 | 删除原因 |
|------|------|---------|
| F7 | IO35触发拍照 | 用户确认只保留IO34拍照 |
| F20 | 密码设置模式(FNV-1a哈希) | 改为明文存储 |
| F21 | 授权锁定(5次错误锁定5分钟) | 用户未选择保留 |

### 2.3 修改要点

| 项目 | 原版 | 重构后 |
|------|------|--------|
| 密码存储 | FNV-1a哈希+盐 | 明文存入配置文件 |
| 输入IO | IO26/34/35/43 | 仅IO34/35 |
| 输出IO | 绿IO32/黄IO33/红IO42 | 仅黄IO33/红IO42 |
| 拍照触发 | IO43高电平 | IO34低电平 |
| 拍照蜂鸣 | 与报警相同 | 只响一声，遵循sound_mode |
| 声音模式 | buzzer/speaker/both/seq | 三选一：buzzer/speaker/mute |
| bbox颜色 | 固定红色 | 按类别0-4可配置，预制5种颜色 |
| 模型目录 | 固定/sdcard/mp_detect_garbage/ | 可配置，默认/sdcard/ |
| 部署配置路径 | /sdcard/mp_detect_garbage/ | /sdcard/configs/ |
| 显示架构 | OSD叠加 | VIDEO层(摄像头)+OSD层(UI) |
| UI框架 | OSD手绘 | LVGL控件+OSD叠加层 |

## 3. 架构设计

### 3.1 文件结构

```
apps/taping_checker/
├── app.py          # LVGL界面 + 主循环 + 事件处理
├── core.py         # Detector / GPIOController / ConfigManager / 工具函数
└── (无变更)        # 不新增文件
```

### 3.2 显示架构

```
┌─────────────────────────────────┐
│  VIDEO层 (VIDEO1)               │  ← 摄像头画面，硬件旋转
│  绑定sensor ch0，自动显示        │
├─────────────────────────────────┤
│  OSD层 (OSD0)                   │  ← 检测框 + 状态信息
│  RGB565，色键透明               │
├─────────────────────────────────┤
│  LVGL层                         │  ← 标题栏 + 按钮 + 弹窗
│  BGRA8888，透明背景             │
└─────────────────────────────────┘
```

**关键点：**
- VIDEO1层绑定sensor ch0，硬件旋转显示摄像头画面（解决ST7701撕裂问题）
- OSD0层用于绘制检测框和状态文字（AI推理结果叠加）
- LVGL层用于按钮、面板等交互控件
- 主循环在独立线程运行，与LVGL事件循环并行

### 3.3 类设计

#### core.py

```python
class Detector:
    """AI推理引擎，封装KPU+AI2D+aicube"""
    - __init__(kmodel_path, labels, model_input_size, anchors, ...)
    - run(img) -> boxes
    - draw_result(osd_img, boxes, bbox_colors)  # 按类别颜色绘制
    - switch_model(new_path, new_name, config_mgr)
    - deinit()

class GPIOController:
    """GPIO控制，只管理黄灯IO33、红灯IO42、输入IO34/35"""
    - lamp_pins = {'yellow': 33, 'red': 42}
    - input_pins = [34, 35]
    - set_yellow(on) / set_red(on)
    - read_inputs() -> {pin: value}
    - reset_outputs()

class Speaker:
    """音频播放，AudioModule优先→I2S回退"""
    - __init__()
    - play(wav_path)  # 播放WAV文件
    - deinit()

class ConfigManager:
    """配置管理，明文密码"""
    - conf dict
    - get(key, default) / set(key, value) / save()
    - _ensure_defaults()  # 自动补全默认值

# 预制bbox颜色（类别0-4）
BBOX_PRESET_COLORS = [
    (255, 0, 0),     # 类别0: 红色
    (0, 255, 0),     # 类别1: 绿色
    (0, 127, 255),   # 类别2: 橙色
    (0, 0, 255),     # 类别3: 蓝色
    (255, 255, 0),   # 类别4: 青色
]

# 工具函数
save_photo(img, run_dir, seq_num) -> (path, fname)
ensure_dir(directory)
_load_boot_seq() / _save_boot_seq(n)
_load_seq(dd) / _save_seq(dd, n)
_list_kmodels(directory) -> [name]
_scan_model_dirs(base="/sdcard/") -> [dir_path]
_exists(p) -> bool
_pad_param(input_size, output_size) -> (top, bottom, left, right)
```

#### app.py

```python
class App(BaseApp):
    """胶带检测应用"""
    
    # LVGL界面
    - _create_title_bar()     # 标题栏 + 返回按钮 + 配置/模型按钮
    - _create_config_dialog() # 配置弹窗（置信度、报警持续、声音模式、bbox颜色、密码）
    - _create_model_dialog()  # 模型选择弹窗
    - _create_auth_dialog()   # 授权密码弹窗（数字键盘）
    
    # 核心循环
    - initialize()            # 初始化Detector/GPIO/会话，启动主循环线程
    - _camera_loop()          # 阻塞式主循环：get_frame→run→draw_result→update_alarm→update_gpio→update_inputs
    - deinitialize()          # 清理资源
    
    # 业务逻辑
    - _update_alarm(boxes)    # 报警判定+声音（根据sound_mode选择buzzer/speaker/mute）
    - _play_alarm_sound()    # 按sound_mode播放报警声
    - _play_capture_sound()  # 按sound_mode播放拍照提示声（1声）
    - _update_gpio(boxes)     # 黄灯/红灯控制
    - _update_inputs()        # IO34/35防抖+IO34拍照触发
    - _do_capture()           # 拍照保存
    - _do_model_switch()      # 模型热切换
```

### 3.4 配置文件格式

`/sdcard/configs/taping_checker.json`:
```json
{
    "confidence_threshold": 0.4,
    "alarm_trigger_hold_ms": 0,
    "sound_mode": "buzzer",
    "password": "",
    "model_name": "bset_no_taping_v2.kmodel",
    "model_dir": "/sdcard/",
    "bbox_colors": [
        [255, 0, 0],
        [0, 255, 0],
        [0, 127, 255],
        [0, 0, 255],
        [255, 255, 0]
    ]
}
```

**配置项说明：**
- `sound_mode`: 三选一互斥
  - `"buzzer"` — 蜂鸣器报警（报警3声，拍照1声）
  - `"speaker"` — Speaker播放WAV（报警3声，拍照1声）
  - `"mute"` — 静音，不播放任何声音
- `bbox_colors`: 类别0-4的bbox颜色，RGB格式，可在配置面板中修改
- `model_dir`: 模型搜索目录，模型选择面板从此目录扫描.kmodel文件，默认`/sdcard/`
  - 配置面板中点击"修改"按钮循环切换包含.kmodel文件的目录
  - 目录列表由`_scan_model_dirs()`动态扫描/sdcard/下两级子目录生成
  - 模型选择面板标题显示当前目录及模型数量

`/sdcard/configs/deploy_config_taping.json`:
```json
{
    "categories": ["no_taping"],
    "nms_threshold": 0.5,
    "img_size": [320, 320],
    "nms_option": false,
    "model_type": "AnchorBaseDet",
    "anchors": [[...], [...], [...]],
    "confidence_threshold": 0.4
}
```

## 4. UI设计

### 4.1 主界面布局 (640x480)

```
┌──────────────────────────────────────┐
│ [←] 胶带检测          [模型][配置]  │ ← LVGL标题栏 (高50px)
├──────────────────────────────────────┤
│                                      │
│  摄像头画面 (VIDEO层)                │
│  + 检测框叠加 (OSD层)               │
│                                      │
│                                      │
│  [状态文字]              [●拍照]     │ ← OSD叠加
│  保存提示文字                        │
└──────────────────────────────────────┘
```

### 4.2 配置弹窗

```
┌──────────────────────────────────┐
│ 设置                     [设置密码] │
├──────────────────────────────────┤
│ 置信度: 0.40    [-] [+]          │
│ 报警持续ms: 0   [-] [+]          │
│ 声音模式: [蜂鸣器] [喇叭] [静音]  │
│ 模型目录: /sdcard/   [修改]       │
│   (点击修改循环切换含模型的目录)   │
│                                  │
│ ── 检测框颜色 ──                 │
│ 类别0: [■]  类别1: [■]           │
│ 类别2: [■]  类别3: [■]           │
│ 类别4: [■]                       │
│ (点击色块循环切换预设颜色)         │
│                                  │
│         [保存]    [取消]          │
└──────────────────────────────────┘
```

**声音模式说明：**
- 蜂鸣器/喇叭/静音三选一，选中项高亮
- 蜂鸣器：硬件蜂鸣器，报警3声，拍照1声
- 喇叭：Speaker播放WAV，报警3声，拍照1声
- 静音：不播放任何声音

**bbox颜色设置说明：**
- 预制颜色循环：红→绿→橙→蓝→青→黄→紫→白→红...
- 点击色块切换到下一个颜色
- 颜色实时预览在色块上

### 4.3 模型选择弹窗

```
┌──────────────────────────────────┐
│ 选择模型  目录: /sdcard/ (3个)   │
├──────────────────────────────────┤
│ ▸ bset_no_taping_v2.kmodel      │
│   bset_no_taping_v3.kmodel      │
│   ...                            │
│                                  │
│  [上一页]          [下一页]      │
│         [保存]    [取消]          │
└──────────────────────────────────┘
```

**说明：**
- 标题栏显示当前扫描的模型目录及模型数量
- 列表内容来自 `model_dir` 配置项下的 `.kmodel` 文件
- 若目录下无模型文件，列表为空，用户需先在配置面板修改模型目录

### 4.4 授权密码弹窗

```
┌──────────────────────────────────┐
│ 授权                     [取消]  │
├──────────────────────────────────┤
│ 密码: ****                       │
│                                  │
│  [1] [2] [3]                    │
│  [4] [5] [6]                    │
│  [7] [8] [9]                    │
│  [删除] [0] [确认]              │
└──────────────────────────────────┘
```

## 5. 主循环流程

```python
def _camera_loop(self):
    while self.is_running:
        img = self.pl.get_frame()
        boxes = self.detector.run(img)
        bbox_colors = self.cfg_mgr.get("bbox_colors", BBOX_PRESET_COLORS)
        self.detector.draw_result(self.pl.osd_img, boxes, bbox_colors)  # 按类别颜色绘制
        self._update_alarm(boxes)
        self._update_gpio(boxes)
        self._update_inputs()
        self._update_status_text()  # OSD层画状态文字
        self.pl.show_image()        # 刷新OSD层
        if self.model_switch_pending:
            self._do_model_switch()
        gc.collect()
```

## 6. 关键技术点

### 6.1 VIDEO层摄像头显示
- 主循环中不调用 `Display.show_image()` 显示摄像头画面
- VIDEO1层在main.py初始化时已绑定sensor ch0，自动显示
- 只需通过OSD层叠加检测框和状态文字

### 6.2 LVGL与主循环并行
- 主循环在 `_thread` 中运行
- LVGL事件在主线程处理
- 共享状态通过标志位传递（config_open, model_open等）
- LVGL按钮事件设置标志位，主循环读取标志位决定行为

### 6.3 OSD层与LVGL层共存
- LVGL背景透明，VIDEO层透过来
- OSD0层RGB565，色键(0,0,0)透明
- 检测框和状态文字画在OSD0层
- LVGL按钮/面板在最上层

### 6.4 IO34低电平触发拍照
- IO34配置为PULL_UP输入
- 检测到低电平→防抖75ms→触发拍照
- 最小间隔500ms防止重复触发

### 6.5 模型目录动态扫描
- `_scan_model_dirs(base="/sdcard/")` 扫描base目录下两级子目录
- 只返回包含 `.kmodel` 文件的目录
- 始终包含 `/sdcard/` 作为第一项（根目录）
- 配置面板"修改"按钮循环切换扫描到的目录
- 模型选择面板从 `model_dir` 配置项读取目录并列出该目录下的 `.kmodel` 文件
- 模型热切换时优先从 `model_dir` 查找，找不到则回退到预设目录

## 7. 实施步骤

1. 重写 `core.py`：精简Detector/GPIOController/ConfigManager，保留Speaker，删除密码哈希，新增bbox颜色支持
2. 重写 `app.py`：
   - LVGL界面：标题栏+按钮+弹窗（含声音模式三选一+bbox颜色配置）
   - 主循环：VIDEO+OSD架构
   - 事件处理：LVGL事件驱动
   - 声音系统：根据sound_mode选择buzzer/speaker/mute
3. 更新配置文件：`configs/taping_checker.json`（新增sound_mode和bbox_colors）
4. 测试验证
