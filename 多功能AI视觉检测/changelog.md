# 变更日志

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
