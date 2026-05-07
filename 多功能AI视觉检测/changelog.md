# 变更日志

## v1.0.1 (2026-05-07)

### 新增
- **人体姿态检测** (`body_pose`)：移植自 `ai_body`，基于 YOLOv8-pose 的 17 关键点骨架检测
  - 支持 OSD 实时绘制骨架和关键点
  - 支持置信度阈值 / NMS 阈值调节并持久化保存
  - 设置面板支持保存/取消操作，保存后自动重新加载模型
- **IO 测试** (`io_tester`)：新增扬声器测试功能，支持播放 siren.wav 测试音频
- **音频播放**：集成 YbSpeaker 库，修复喇叭不响问题，支持蜂鸣器/喇叭双输出切换
- **拍照音效**：统一使用蜂鸣器播放，受静音模式限制，不受音频输出设备切换影响

### 优化
- **返回按钮样式统一**：所有 APP（`taping_checker`、`picture_get`、`body_pose`）返回按钮统一为简洁 `<` 箭头样式
- **触摸防抖**：所有 APP 触摸交互增加 200ms 防抖逻辑，防止误触
- **绘制顺序修复**：检测画面绘制后叠加标题栏，确保返回按钮和设置按钮不被遮挡
- **空文件夹问题**：`taping_checker` 和 `picture_get` 延迟目录创建到首次拍照时
- **音频黑屏修复**：移除 `MediaManager.deinit()`，避免第二次播放音频时黑屏

### 架构
- `apps/body_pose/`：人体姿态检测应用（`app.py` + `core/person_keypoint_detect.py`）
- `apps/io_tester/`：IO 测试应用（`app.py` + `core.py`）
- 配置持久化：`/sdcard/configs/body_pose.json` 存储人体姿态检测阈值参数

## v1.0.0 (2026-05-03)

### 新增
- 初始版本发布
- 集成两个核心应用：
  - **胶带检测** (`taping_checker`)：基于 KPU 的 AI 视觉检测，支持 OSD UI、模型切换、配置面板、密码授权、GPIO 报警、按键拍照
  - **按键拍照** (`picture_get`)：支持物理按键 + 屏幕触控双触发拍照，自动序列号管理
- 采用 AppManager + BaseApp 架构，支持桌面图标启动和 Dock 栏快捷入口
- 共享 PipeLine 视频流水线，避免重复初始化摄像头
- 精简系统：删除 WiFi、锁屏、翻页、多语言、状态栏等无关功能

### 架构
- `main.py`：精简版 AppManager，负责 LVGL 初始化、应用扫描、生命周期管理
- `base_app.py`：应用基类（从原 k230 项目复制）
- `apps/taping_checker/`：胶带检测应用（core.py + app.py）
- `apps/picture_get/`：按键拍照应用（core.py + app.py）
- `libs/`：核心库（PipeLine、PlatTasks、AI2D、AIBase、YOLO、Utils）
- `ybUtils/`：硬件工具（YbKey、YbBuzzer、YbRGB、Configuration）
- `configs/`：系统配置 + 用户配置 + 应用排序
