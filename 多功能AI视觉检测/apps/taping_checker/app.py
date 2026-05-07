from base_app import BaseApp
from apps.taping_checker.core import (
    Detector, GPIOController, ConfigManager, Speaker,
    save_photo, ensure_dir, _load_boot_seq, _save_boot_seq,
    _load_seq, _save_seq, _list_kmodels, _scan_model_dirs, _exists,
    BBOX_PRESET_COLORS, CFG_PATH, DEPLOY_CFG_PATH, SAVE_BASE, AUDIO_DIR
)
from libs.Utils import read_json
from ybUtils.YbBuzzer import YbBuzzer
import time, gc

try:
    from media.sensor import *
except:
    pass
try:
    from media.display import Display
except:
    Display = None
try:
    from media.media import *
except:
    pass
try:
    from machine import TOUCH
    tp = TOUCH(0)
except:
    tp = None
try:
    import machine
except:
    machine = None
try:
    import image
except:
    image = None

LAYOUT = {
    'font_md': 22,
    'font_lg': 26,
    'btn_font': 22,
    'rect_thick': 2,
    'ctrl_w': 70,
    'ctrl_h': 48,
    'model_row_gap': 8,
    'panel_bg': (20, 25, 40),
    'pad': 40,
    'top_y': 58,
    'bottom_y': 410,
    'touch_expand': 8,
    'title_bg': (20, 25, 40),
    'title_line': (60, 70, 90),
    'primary': (0, 180, 255),
    'primary_dark': (0, 120, 180),
    'confirm': (40, 200, 120),
    'confirm_dark': (20, 140, 80),
    'danger': (220, 60, 60),
    'danger_dark': (160, 40, 40),
    'text_white': (255, 255, 255),
    'text_dim': (160, 170, 190),
    'text_dark': (80, 90, 110),
    'divider': (50, 60, 80),
    'bar_bg': (40, 50, 70),
    'bar_fg': (0, 180, 255),
    'item_bg': (30, 38, 55),
    'item_sel': (0, 120, 200),
    'card_bg': (30, 38, 55),
    'card_border': (60, 70, 90),
    'card_icon_model': (0, 180, 255),
    'card_icon_detect': (40, 200, 120),
    'card_icon_alarm': (255, 180, 0),
    'card_icon_auth': (220, 60, 60),
}

BBOX_PRESET_COLORS = [
    (255, 0, 0), (0, 255, 0), (0, 100, 255), (255, 255, 0),
    (0, 255, 255), (255, 0, 255), (255, 165, 0), (255, 255, 255),
]


class App(BaseApp):
    def __init__(self, app_manager):
        super().__init__(app_manager, name="胶带检测", icon=None)
        try:
            with open("/sdcard/apps/taping_checker/dock_icon.png", 'rb') as f:
                dock_data = f.read()
                self.dock_icon_data = dock_data
        except:
            self.dock_icon_data = None
        try:
            with open("/sdcard/apps/taping_checker/icon.png", 'rb') as f:
                icon_data = f.read()
                self.icon_data = icon_data
        except:
            self.icon_data = None
        self.pl = app_manager.pl
        self.is_running = False
        self.detector = None
        self.gpio = None
        self.speaker = None
        self.buzzer = None
        self.cfg_mgr = None
        self.run_dir = ""
        self.seq_num = 1
        self.saved_msg_text = ""
        self.saved_msg_until_ms = 0
        self.alarm_active = False
        self.alarm_remaining = 0
        self.alarm_next_ms = 0
        self.target_since_ms = 0
        self.red_on_until_ms = 0
        self.last_trigger_ms = 0
        self.io34_last_stable = 1
        self.io34_since_ms = 0
        self.debounce_ms = 75
        self.min_interval_ms = 500
        self.model_list = []
        self.model_sel_idx_tmp = -1
        self.model_page = 0
        self.model_switch_pending_name = None
        self.panel = None
        self.auth_mode = ""
        self.auth_input = ""
        self.auth_suppress_until_ms = 0
        self._auth_unlocked_until_ms = 0
        self._touch_last_ms = 0
        self._touch_debounce_ms = 200
        self._tmp_conf = 0.4
        self._tmp_hold = 0
        self._tmp_sound_mode = "buzzer"
        self._tmp_bbox_colors = []
        self._tmp_model_dir = "/sdcard/"
        self._ui_img = None

    def launch(self):
        self.initialize()

    def initialize(self):
        self.is_running = True
        self.cfg_mgr = ConfigManager()
        self._load_deploy_config()
        self.speaker = Speaker()
        try:
            self.buzzer = YbBuzzer()
        except:
            self.buzzer = None
        self.gpio = GPIOController()
        self.gpio.reset_outputs()
        try:
            self._init_detector()
        except Exception as e:
            print("detector init failed:", e)
            self._camera_loop_error("模型加载失败: %s" % str(e))
            return
        self._init_session()
        self._camera_loop()
        self.app_manager.go_home()

    def _camera_loop_error(self, msg):
        if image is None or Display is None:
            return
        err_img = image.Image(640, 480, image.ARGB8888)
        err_img.clear()
        err_img.draw_string_advanced(100, 200, 24, msg, color=(255, 0, 0))
        Display.show_image(err_img, 0, 0, Display.LAYER_OSD0)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 3000:
            if tp:
                pts = tp.read(1)
                if len(pts) and pts[0].event == TOUCH.EVENT_DOWN:
                    break
            time.sleep_ms(50)

    def _load_deploy_config(self):
        deploy_conf = None
        if _exists(DEPLOY_CFG_PATH):
            deploy_conf = read_json(DEPLOY_CFG_PATH)
        if deploy_conf is None:
            candidate = "/sdcard/mp_detect_garbage/deploy_config_taping.json"
            if _exists(candidate):
                deploy_conf = read_json(candidate)
        if deploy_conf is None:
            deploy_conf = {}
        self.labels = deploy_conf.get("categories", ["no_taping"])
        self.nms_threshold = deploy_conf.get("nms_threshold", 0.5)
        self.model_input_size = deploy_conf.get("img_size", [320, 320])
        self.nms_option = deploy_conf.get("nms_option", False)
        self.model_type = deploy_conf.get("model_type", "AnchorBaseDet")
        self.anchors = []
        if self.model_type == "AnchorBaseDet":
            raw_anchors = deploy_conf.get("anchors", None)
            if raw_anchors and len(raw_anchors) >= 3:
                self.anchors = raw_anchors[0] + raw_anchors[1] + raw_anchors[2]
            else:
                self.anchors = [10,16,15,19,10,43,14,31,13,40,16,42,19,41,24,41,32,35]
        self.confidence_threshold = self.cfg_mgr.get("confidence_threshold", deploy_conf.get("confidence_threshold", 0.4))
        self.alarm_trigger_hold_ms = self.cfg_mgr.get("alarm_trigger_hold_ms", 0)
        self.model_name = self.cfg_mgr.get("model_name", "bset_no_taping_v2.kmodel")
        model_dir = self.cfg_mgr.get("model_dir", "/sdcard/")
        self.kmodel_path = model_dir + self.model_name
        if not _exists(self.kmodel_path):
            fallback_dirs = ["/sdcard/kmodel/taping_checker/", "/sdcard/kmodel/", "/sdcard/"]
            found = False
            for d in fallback_dirs:
                p = d + self.model_name
                if _exists(p):
                    self.kmodel_path = p
                    found = True
                    break
            if not found:
                search_dirs = [model_dir] + fallback_dirs
                for d in search_dirs:
                    models = _list_kmodels(d)
                    if models:
                        self.kmodel_path = d + models[0]
                        self.model_name = models[0]
                        found = True
                        break
                if not found:
                    self.kmodel_path = model_dir + self.model_name

    def _init_detector(self):
        self.detector = Detector(
            self.kmodel_path, self.labels, self.model_input_size, self.anchors,
            self.model_type, self.confidence_threshold, self.nms_threshold,
            [640, 480], self.pl.get_display_size(), debug_mode=0
        )

    def _init_session(self):
        boot_seq = _load_boot_seq()
        self.run_dir = "DIR%06d" % boot_seq
        # 注意：不在启动时创建文件夹，延迟到拍照时创建
        _save_boot_seq(boot_seq + 1)
        self.seq_num = 1  # 初始序号，拍照时再从文件加载或创建

    @staticmethod
    def _in_rect(x, y, rx, ry, rw, rh):
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def _draw_title_bar(self, ui_img, title="胶带检测"):
        ui_img.draw_rectangle(0, 0, 640, 50, color=LAYOUT['title_bg'], thickness=1, fill=True)
        ui_img.draw_line(0, 49, 640, 49, color=LAYOUT['title_line'], thickness=1)
        ui_img.draw_line(30, 14, 14, 25, color=LAYOUT['text_white'], thickness=4)
        ui_img.draw_line(14, 25, 30, 36, color=LAYOUT['text_white'], thickness=4)
        ui_img.draw_string_advanced(260, 16, 16, title, color=LAYOUT['text_white'])
        if not self.panel:
            ui_img.draw_rectangle(555, 5, 80, 40, color=LAYOUT['primary_dark'], thickness=1, fill=True)
            ui_img.draw_rectangle(555, 5, 80, 40, color=LAYOUT['primary'], thickness=1)
            ui_img.draw_string_advanced(572, 14, 16, "设置", color=LAYOUT['text_white'])

    def _draw_settings_menu(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw = (640 - 2 * pad - 20) // 2
        ch = 120
        gap = 20
        cards = [
            ("model", "模型管理", "选择/切换模型", LAYOUT['card_icon_model']),
            ("detect", "检测设置", "置信度/BBox颜色", LAYOUT['card_icon_detect']),
            ("alarm", "报警设置", "持续时间/声音", LAYOUT['card_icon_alarm']),
            ("auth", "权限管理", "设置/修改密码", LAYOUT['card_icon_auth']),
        ]
        for i, (key, title, desc, icon_color) in enumerate(cards):
            col = i % 2
            row = i // 2
            cx = pad + col * (cw + gap)
            cy = ty + row * (ch + gap)
            ui_img.draw_rectangle(cx, cy, cw, ch, color=LAYOUT['card_bg'], thickness=1, fill=True)
            ui_img.draw_rectangle(cx, cy, cw, ch, color=LAYOUT['card_border'], thickness=1)
            ui_img.draw_rectangle(cx + 12, cy + 12, 8, 8, color=icon_color, thickness=1, fill=True)
            ui_img.draw_string_advanced(cx + 28, cy + 10, LAYOUT['font_md'], title, color=LAYOUT['text_white'])
            ui_img.draw_string_advanced(cx + 12, cy + 42, 16, desc, color=LAYOUT['text_dim'])

    def _draw_model_panel(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        ch = LAYOUT['ctrl_h']
        btn_y = LAYOUT['bottom_y']
        btn_h = 48

        model_dir = self.cfg_mgr.get("model_dir", "/sdcard/")
        ui_img.draw_string_advanced(pad, ty, LAYOUT['font_md'], "目录: %s (%d个)" % (model_dir, len(self.model_list)), color=LAYOUT['text_dim'])

        list_y = ty + 30
        row_h = ch + LAYOUT['model_row_gap']
        max_items = max(1, (btn_y - 10 - list_y) // row_h)
        start_idx = self.model_page * max_items
        end_idx = start_idx + max_items
        for i, name in enumerate(self.model_list[start_idx:end_idx]):
            yy = list_y + i * row_h
            selected = (start_idx + i == self.model_sel_idx_tmp)
            if selected:
                ui_img.draw_rectangle(pad + 10, yy, 640 - 2 * pad - 20, ch, color=LAYOUT['item_sel'], thickness=1, fill=True)
                ui_img.draw_string_advanced(pad + 22, yy + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "> " + name, color=LAYOUT['text_white'])
            else:
                ui_img.draw_rectangle(pad + 10, yy, 640 - 2 * pad - 20, ch, color=LAYOUT['item_bg'], thickness=1, fill=True)
                ui_img.draw_rectangle(pad + 10, yy, 640 - 2 * pad - 20, ch, color=LAYOUT['text_dark'], thickness=1)
                ui_img.draw_string_advanced(pad + 22, yy + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "  " + name, color=LAYOUT['text_dim'])

        btn_w = (640 - 2 * pad - 30) // 4
        gap = 10
        bx = pad
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['primary_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['primary'], thickness=1)
        ui_img.draw_string_advanced(bx + (btn_w - LAYOUT['btn_font'] * 3) // 2, btn_y + (btn_h - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "上一页", color=LAYOUT['text_white'])
        bx = pad + btn_w + gap
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['primary_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['primary'], thickness=1)
        ui_img.draw_string_advanced(bx + (btn_w - LAYOUT['btn_font'] * 3) // 2, btn_y + (btn_h - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "下一页", color=LAYOUT['text_white'])
        bx = pad + 2 * (btn_w + gap)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(bx + (btn_w - LAYOUT['btn_font'] * 2) // 2, btn_y + (btn_h - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "取消", color=LAYOUT['text_white'])
        bx = pad + 3 * (btn_w + gap)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(bx, btn_y, btn_w, btn_h, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(bx + (btn_w - LAYOUT['btn_font'] * 2) // 2, btn_y + (btn_h - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "保存", color=LAYOUT['text_white'])

    def _draw_detect_panel(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        bar_w = rx - pad - 20 - 2 * cw - 20

        ui_img.draw_string_advanced(pad, ty, LAYOUT['font_md'], "置信度: %.2f" % self._tmp_conf, color=LAYOUT['text_dim'])
        ui_img.draw_rectangle(pad + 10, ty + 30, cw, ch, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(pad + 10, ty + 30, cw, ch, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(pad + 10 + (cw - LAYOUT['font_md']) // 2, ty + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "-", color=LAYOUT['text_white'])
        bar_x = pad + 10 + cw + 10
        ui_img.draw_rectangle(bar_x, ty + 38, bar_w, 12, color=LAYOUT['bar_bg'], thickness=1, fill=True)
        fill_w = max(1, int(bar_w * self._tmp_conf))
        ui_img.draw_rectangle(bar_x, ty + 38, fill_w, 12, color=LAYOUT['bar_fg'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, ty + 30, cw, ch, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, ty + 30, cw, ch, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(rx - 10 + (cw - LAYOUT['font_md']) // 2, ty + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "+", color=LAYOUT['text_white'])

        ui_img.draw_line(pad, ty + 85, 640 - pad, ty + 85, color=LAYOUT['divider'], thickness=1)

        color_y = ty + 95
        ui_img.draw_string_advanced(pad, color_y, LAYOUT['font_md'], "BBox颜色 (点击切换):", color=LAYOUT['text_dim'])
        num_colors = min(5, len(self._tmp_bbox_colors))
        color_block_w = 100
        color_block_h = 50
        color_gap = 10
        total_w = num_colors * color_block_w + (num_colors - 1) * color_gap
        start_x = (640 - total_w) // 2
        label_y = color_y + 28
        block_y = label_y + 24
        for i in range(num_colors):
            bx = start_x + i * (color_block_w + color_gap)
            c = tuple(self._tmp_bbox_colors[i]) if i < len(self._tmp_bbox_colors) else (255, 0, 0)
            label = "第%d种" % (i + 1)
            lw = len(label) * 16
            ui_img.draw_string_advanced(bx + (color_block_w - lw) // 2, label_y, 16, label, color=LAYOUT['text_dim'])
            ui_img.draw_rectangle(bx, block_y, color_block_w, color_block_h, color=c, thickness=1, fill=True)
            ui_img.draw_rectangle(bx, block_y, color_block_w, color_block_h, color=LAYOUT['card_border'], thickness=2)

        btn_y = LAYOUT['bottom_y']
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(195, btn_y + 12, LAYOUT['btn_font'], "保存", color=LAYOUT['text_white'])
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(375, btn_y + 12, LAYOUT['btn_font'], "取消", color=LAYOUT['text_white'])

    def _draw_alarm_panel(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        bar_w = rx - pad - 20 - 2 * cw - 20

        ui_img.draw_string_advanced(pad, ty, LAYOUT['font_md'], "报警持续ms: %d" % self._tmp_hold, color=LAYOUT['text_dim'])
        ui_img.draw_rectangle(pad + 10, ty + 30, cw, ch, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(pad + 10, ty + 30, cw, ch, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(pad + 10 + (cw - LAYOUT['font_md']) // 2, ty + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "-", color=LAYOUT['text_white'])
        bar_x = pad + 10 + cw + 10
        ui_img.draw_rectangle(bar_x, ty + 38, bar_w, 12, color=LAYOUT['bar_bg'], thickness=1, fill=True)
        hold_ratio = min(1.0, self._tmp_hold / 10000.0)
        fill_w = max(1, int(bar_w * hold_ratio))
        ui_img.draw_rectangle(bar_x, ty + 38, fill_w, 12, color=LAYOUT['bar_fg'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, ty + 30, cw, ch, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, ty + 30, cw, ch, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(rx - 10 + (cw - LAYOUT['font_md']) // 2, ty + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "+", color=LAYOUT['text_white'])

        ui_img.draw_line(pad, ty + 85, 640 - pad, ty + 85, color=LAYOUT['divider'], thickness=1)

        sound_y = ty + 95
        ui_img.draw_string_advanced(pad, sound_y, LAYOUT['font_md'], "声音模式:", color=LAYOUT['text_dim'])
        mode_y = sound_y + 30
        modes = [("buzzer", "蜂鸣器", pad + 10), ("speaker", "喇叭", pad + 200), ("mute", "静音", pad + 390)]
        for mode, text, bx in modes:
            is_active = (self._tmp_sound_mode == mode)
            if is_active:
                ui_img.draw_rectangle(bx, mode_y, 150, ch, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
                ui_img.draw_rectangle(bx, mode_y, 150, ch, color=LAYOUT['confirm'], thickness=1)
                ui_img.draw_string_advanced(bx + 15, mode_y + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], text, color=LAYOUT['text_white'])
            else:
                ui_img.draw_rectangle(bx, mode_y, 150, ch, color=LAYOUT['item_bg'], thickness=1, fill=True)
                ui_img.draw_rectangle(bx, mode_y, 150, ch, color=LAYOUT['text_dark'], thickness=1)
                ui_img.draw_string_advanced(bx + 15, mode_y + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], text, color=LAYOUT['text_dim'])

        btn_y = LAYOUT['bottom_y']
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(195, btn_y + 12, LAYOUT['btn_font'], "保存", color=LAYOUT['text_white'])
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(375, btn_y + 12, LAYOUT['btn_font'], "取消", color=LAYOUT['text_white'])

    def _draw_auth_menu(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw = 640 - 2 * pad
        ch = 60
        gap = 16
        items = [
            ("change", "修改密码", LAYOUT['card_icon_auth']),
            ("reset", "恢复默认", LAYOUT['card_icon_alarm']),
        ]
        for i, (key, title, icon_color) in enumerate(items):
            iy = ty + i * (ch + gap)
            ui_img.draw_rectangle(pad, iy, cw, ch, color=LAYOUT['card_bg'], thickness=1, fill=True)
            ui_img.draw_rectangle(pad, iy, cw, ch, color=LAYOUT['card_border'], thickness=1)
            ui_img.draw_rectangle(pad + 14, iy + 14, 8, 8, color=icon_color, thickness=1, fill=True)
            ui_img.draw_string_advanced(pad + 30, iy + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], title, color=LAYOUT['text_white'])

    def _draw_auth_panel(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']

        title_map = {
            "enter": "输入密码",
            "set": "设置新密码",
            "verify_old": "确认原密码",
            "set_new": "输入新密码",
            "verify_reset": "确认密码",
        }
        title = title_map.get(self.auth_mode, "输入密码")
        ui_img.draw_string_advanced(pad, ty, LAYOUT['font_md'], title, color=LAYOUT['primary'])

        if self.auth_mode == "enter" and not self.cfg_mgr.get("password", ""):
            ui_img.draw_rectangle(640 - pad - 140, ty, 140, LAYOUT['ctrl_h'], color=LAYOUT['primary_dark'], thickness=1, fill=True)
            ui_img.draw_rectangle(640 - pad - 140, ty, 140, LAYOUT['ctrl_h'], color=LAYOUT['primary'], thickness=1)
            ui_img.draw_string_advanced(640 - pad - 128, ty + 8, LAYOUT['btn_font'], "设置密码", color=LAYOUT['text_white'])

        mask = "*" * len(self.auth_input)
        ui_img.draw_string_advanced(pad, ty + 40, LAYOUT['font_md'], mask, color=LAYOUT['text_dim'])

        cw, ch = LAYOUT['ctrl_w'] + 12, LAYOUT['ctrl_h'] + 8
        gap = 26
        kx = 140
        ky = ty + 80
        nums = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
        for i, v in enumerate(nums):
            gx = kx + (i % 3) * (cw + gap)
            gy = ky + (i // 3) * (ch + gap)
            ui_img.draw_rectangle(gx, gy, cw, ch, color=LAYOUT['item_bg'], thickness=1, fill=True)
            ui_img.draw_rectangle(gx, gy, cw, ch, color=LAYOUT['primary'], thickness=1)
            tw = LAYOUT['btn_font'] * len(v)
            ui_img.draw_string_advanced(gx + (cw - tw) // 2, gy + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], v, color=LAYOUT['text_white'])

        row3_y = ky + 3 * (ch + gap)
        ui_img.draw_rectangle(kx, row3_y, cw, ch, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(kx, row3_y, cw, ch, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(kx + (cw - LAYOUT['btn_font'] * 2) // 2, row3_y + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "删除", color=LAYOUT['text_white'])
        ui_img.draw_rectangle(kx + (cw + gap), row3_y, cw, ch, color=LAYOUT['item_bg'], thickness=1, fill=True)
        ui_img.draw_rectangle(kx + (cw + gap), row3_y, cw, ch, color=LAYOUT['primary'], thickness=1)
        ui_img.draw_string_advanced(kx + (cw + gap) + (cw - LAYOUT['btn_font']) // 2, row3_y + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "0", color=LAYOUT['text_white'])
        ui_img.draw_rectangle(kx + 2 * (cw + gap), row3_y, cw, ch, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(kx + 2 * (cw + gap), row3_y, cw, ch, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(kx + 2 * (cw + gap) + (cw - LAYOUT['btn_font'] * 2) // 2, row3_y + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "确认", color=LAYOUT['text_white'])

        ui_img.draw_rectangle(640 - pad - cw, ty + 40, cw, ch, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(640 - pad - cw, ty + 40, cw, ch, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(640 - pad - cw + (cw - LAYOUT['btn_font'] * 2) // 2, ty + 40 + (ch - LAYOUT['btn_font']) // 2, LAYOUT['btn_font'], "取消", color=LAYOUT['text_white'])

    def _is_unlocked(self):
        password = self.cfg_mgr.get("password", "")
        if not password:
            return True
        if self._auth_unlocked_until_ms and time.ticks_diff(self._auth_unlocked_until_ms, time.ticks_ms()) > 0:
            return True
        return False

    def _try_open_settings(self):
        if self._is_unlocked():
            self.panel = "menu"
        else:
            self.auth_mode = "enter"
            self.auth_input = ""
            self.auth_suppress_until_ms = time.ticks_add(time.ticks_ms(), 200)
            self.panel = "auth"

    def _handle_touch(self, x, y):
        if self.panel == "auth":
            self._handle_auth_touch(x, y)
        elif self.panel == "auth_menu":
            self._handle_auth_menu_touch(x, y)
        elif self.panel == "model":
            self._handle_model_touch(x, y)
        elif self.panel == "detect":
            self._handle_detect_touch(x, y)
        elif self.panel == "alarm":
            self._handle_alarm_touch(x, y)
        elif self.panel == "menu":
            self._handle_menu_touch(x, y)
        else:
            if x < 100 and y < 50:
                self.is_running = False
            elif 547 <= x <= 643 and 0 <= y <= 50:
                self._try_open_settings()

    def _handle_menu_touch(self, x, y):
        if x < 100 and y < 50:
            self.panel = None
            return
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw = (640 - 2 * pad - 20) // 2
        ch = 120
        gap = 20
        te = LAYOUT['touch_expand']
        cards = ["model", "detect", "alarm", "auth"]
        for i, key in enumerate(cards):
            col = i % 2
            row = i // 2
            cx = pad + col * (cw + gap)
            cy = ty + row * (ch + gap)
            if self._in_rect(x, y, cx - te, cy - te, cw + 2 * te, ch + 2 * te):
                if key == "model":
                    self._open_model_panel()
                elif key == "detect":
                    self._open_detect_panel()
                elif key == "alarm":
                    self._open_alarm_panel()
                elif key == "auth":
                    self._open_auth_panel()
                return

    def _open_model_panel(self):
        model_dir = self.cfg_mgr.get("model_dir", "/sdcard/")
        self.model_list = _list_kmodels(model_dir)
        self.model_page = 0
        current_model = self.cfg_mgr.get("model_name", "")
        self.model_sel_idx_tmp = 0
        if self.model_list:
            try:
                self.model_sel_idx_tmp = self.model_list.index(current_model)
            except ValueError:
                self.model_sel_idx_tmp = 0
        self.panel = "model"

    def _open_detect_panel(self):
        self._tmp_conf = float(self.cfg_mgr.get("confidence_threshold", 0.4))
        raw = self.cfg_mgr.get("bbox_colors", None)
        if raw and isinstance(raw, list):
            self._tmp_bbox_colors = [list(c) for c in raw]
        else:
            self._tmp_bbox_colors = [[255, 0, 0], [0, 255, 0], [0, 100, 255], [255, 255, 0], [0, 255, 255]]
        while len(self._tmp_bbox_colors) < 5:
            self._tmp_bbox_colors.append([255, 0, 0])
        self.panel = "detect"

    def _open_alarm_panel(self):
        self._tmp_hold = int(self.cfg_mgr.get("alarm_trigger_hold_ms", 0))
        self._tmp_sound_mode = self.cfg_mgr.get("sound_mode", "buzzer")
        self.panel = "alarm"

    def _open_auth_panel(self):
        self.panel = "auth_menu"

    def _handle_auth_menu_touch(self, x, y):
        if x < 100 and y < 50:
            self.panel = "menu"
            return
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw = 640 - 2 * pad
        ch = 60
        gap = 16
        te = LAYOUT['touch_expand']
        items = ["change", "reset"]
        for i, key in enumerate(items):
            iy = ty + i * (ch + gap)
            if self._in_rect(x, y, pad - te, iy - te, cw + 2 * te, ch + 2 * te):
                if key == "change":
                    password = self.cfg_mgr.get("password", "")
                    if password:
                        self.auth_mode = "verify_old"
                        self.auth_input = ""
                        self.auth_suppress_until_ms = time.ticks_add(time.ticks_ms(), 200)
                    else:
                        self.auth_mode = "set"
                        self.auth_input = ""
                    self.panel = "auth"
                elif key == "reset":
                    password = self.cfg_mgr.get("password", "")
                    if password:
                        self.auth_mode = "verify_reset"
                        self.auth_input = ""
                        self.auth_suppress_until_ms = time.ticks_add(time.ticks_ms(), 200)
                    else:
                        self._restore_defaults()
                    self.panel = "auth"
                return

    def _handle_model_touch(self, x, y):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        ch = LAYOUT['ctrl_h']
        te = LAYOUT['touch_expand']

        if x < 100 and y < 50:
            self.panel = "menu"
            return

        btn_y = LAYOUT['bottom_y']
        btn_h = 48
        list_y = ty + 30
        row_h = ch + LAYOUT['model_row_gap']
        max_items = max(1, (btn_y - 10 - list_y) // row_h)
        start_idx = self.model_page * max_items
        end_idx = start_idx + max_items

        for i, name in enumerate(self.model_list[start_idx:end_idx]):
            yy = list_y + i * row_h
            if self._in_rect(x, y, pad + 10 - te, yy - te, 640 - 2 * pad - 20 + 2 * te, ch + 2 * te):
                self.model_sel_idx_tmp = start_idx + i
                return

        btn_w = (640 - 2 * pad - 30) // 4
        gap = 10
        bx0 = pad
        if self._in_rect(x, y, bx0 - te, btn_y - te, btn_w + 2 * te, btn_h + 2 * te):
            if self.model_page > 0:
                self.model_page -= 1
            return
        bx1 = pad + btn_w + gap
        if self._in_rect(x, y, bx1 - te, btn_y - te, btn_w + 2 * te, btn_h + 2 * te):
            total_pages = (len(self.model_list) + max_items - 1) // max_items
            if self.model_page + 1 < total_pages:
                self.model_page += 1
            return
        bx2 = pad + 2 * (btn_w + gap)
        if self._in_rect(x, y, bx2 - te, btn_y - te, btn_w + 2 * te, btn_h + 2 * te):
            self.panel = "menu"
            return
        bx3 = pad + 3 * (btn_w + gap)
        if self._in_rect(x, y, bx3 - te, btn_y - te, btn_w + 2 * te, btn_h + 2 * te):
            if 0 <= self.model_sel_idx_tmp < len(self.model_list):
                self.model_switch_pending_name = self.model_list[self.model_sel_idx_tmp]
            self.panel = None
            return

    def _handle_detect_touch(self, x, y):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        te = LAYOUT['touch_expand']

        if x < 100 and y < 50:
            self.panel = "menu"
            return

        if self._in_rect(x, y, pad + 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_conf = max(0.0, min(1.0, round(self._tmp_conf - 0.05, 2)))
            return
        if self._in_rect(x, y, rx - 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_conf = max(0.0, min(1.0, round(self._tmp_conf + 0.05, 2)))
            return

        color_y = ty + 95
        num_colors = min(5, len(self._tmp_bbox_colors))
        color_block_w = 100
        color_block_h = 50
        color_gap = 10
        total_w = num_colors * color_block_w + (num_colors - 1) * color_gap
        start_x = (640 - total_w) // 2
        block_y = color_y + 28 + 24
        for i in range(num_colors):
            bx = start_x + i * (color_block_w + color_gap)
            if self._in_rect(x, y, bx - te, block_y - te, color_block_w + 2 * te, color_block_h + 2 * te):
                cur = tuple(self._tmp_bbox_colors[i]) if i < len(self._tmp_bbox_colors) else (255, 0, 0)
                try:
                    idx = BBOX_PRESET_COLORS.index(cur)
                    self._tmp_bbox_colors[i] = list(BBOX_PRESET_COLORS[(idx + 1) % len(BBOX_PRESET_COLORS)])
                except ValueError:
                    self._tmp_bbox_colors[i] = list(BBOX_PRESET_COLORS[0])
                return

        btn_y = LAYOUT['bottom_y']
        if self._in_rect(x, y, 160 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.cfg_mgr.set("confidence_threshold", self._tmp_conf)
            self.cfg_mgr.set("bbox_colors", self._tmp_bbox_colors)
            self.detector.confidence_threshold = self._tmp_conf
            self.panel = None
            return
        if self._in_rect(x, y, 340 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.panel = "menu"
            return

    def _handle_alarm_touch(self, x, y):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        te = LAYOUT['touch_expand']

        if x < 100 and y < 50:
            self.panel = "menu"
            return

        if self._in_rect(x, y, pad + 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_hold = max(0, min(10000, self._tmp_hold - 10))
            return
        if self._in_rect(x, y, rx - 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_hold = max(0, min(10000, self._tmp_hold + 10))
            return

        sound_y = ty + 95
        mode_y = sound_y + 30
        modes = [("buzzer", pad + 10), ("speaker", pad + 200), ("mute", pad + 390)]
        for mode, bx in modes:
            if self._in_rect(x, y, bx - te, mode_y - te, 150 + 2 * te, ch + 2 * te):
                self._tmp_sound_mode = mode
                return

        btn_y = LAYOUT['bottom_y']
        if self._in_rect(x, y, 160 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.cfg_mgr.set("alarm_trigger_hold_ms", self._tmp_hold)
            self.cfg_mgr.set("sound_mode", self._tmp_sound_mode)
            self.panel = None
            return
        if self._in_rect(x, y, 340 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.panel = "menu"
            return

    def _handle_auth_touch(self, x, y):
        if time.ticks_diff(self.auth_suppress_until_ms, time.ticks_ms()) >= 0:
            return
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'] + 12, LAYOUT['ctrl_h'] + 8
        gap = 26
        kx = 140
        ky = ty + 80
        te = LAYOUT['touch_expand']

        if x < 100 and y < 50:
            if self.auth_mode == "enter":
                self.panel = None
            else:
                self.panel = "auth_menu"
            return

        if self.auth_mode == "enter" and not self.cfg_mgr.get("password", ""):
            if self._in_rect(x, y, 640 - pad - 140 - te, ty - te, 140 + 2 * te, LAYOUT['ctrl_h'] + 2 * te):
                self.auth_mode = "set"
                self.auth_input = ""
                return

        nums = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
        for i, v in enumerate(nums):
            gx = kx + (i % 3) * (cw + gap)
            gy = ky + (i // 3) * (ch + gap)
            if self._in_rect(x, y, gx - te, gy - te, cw + 2 * te, ch + 2 * te):
                if len(self.auth_input) < 12:
                    self.auth_input += v
                return

        row3_y = ky + 3 * (ch + gap)
        if self._in_rect(x, y, kx - te, row3_y - te, cw + 2 * te, ch + 2 * te):
            self.auth_input = self.auth_input[:-1]
            return
        if self._in_rect(x, y, kx + (cw + gap) - te, row3_y - te, cw + 2 * te, ch + 2 * te):
            if len(self.auth_input) < 12:
                self.auth_input += "0"
            return
        if self._in_rect(x, y, kx + 2 * (cw + gap) - te, row3_y - te, cw + 2 * te, ch + 2 * te):
            self._auth_confirm()
            return
        if self._in_rect(x, y, 640 - pad - cw - te, ty + 40 - te, cw + 2 * te, ch + 2 * te):
            if self.auth_mode == "enter":
                self.panel = None
            else:
                self.panel = "auth_menu"
            return

    def _auth_confirm(self):
        password = self.cfg_mgr.get("password", "")
        if self.auth_mode == "enter":
            if not password:
                self.auth_mode = "set"
                self.auth_input = ""
                self.saved_msg_text = "请设置密码"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)
            elif self.auth_input == password:
                self._auth_unlocked_until_ms = time.ticks_add(time.ticks_ms(), 30000)
                self.panel = "menu"
            else:
                self.auth_input = ""
                self.saved_msg_text = "密码错误"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)
        elif self.auth_mode == "verify_old":
            if self.auth_input == password:
                self.auth_mode = "set_new"
                self.auth_input = ""
            else:
                self.auth_input = ""
                self.saved_msg_text = "原密码错误"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)
        elif self.auth_mode == "set_new" or self.auth_mode == "set":
            if self.auth_input:
                self.cfg_mgr.set("password", self.auth_input)
                self.saved_msg_text = "密码已设置"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)
                self.panel = "auth_menu"
        elif self.auth_mode == "verify_reset":
            if self.auth_input == password:
                self._restore_defaults()
                self.panel = "auth_menu"
            else:
                self.auth_input = ""
                self.saved_msg_text = "密码错误"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)

    def _restore_defaults(self):
        self.cfg_mgr.set("confidence_threshold", 0.7)
        self.cfg_mgr.set("alarm_trigger_hold_ms", 80)
        self.cfg_mgr.set("sound_mode", "buzzer")
        self.cfg_mgr.set("bbox_colors", [
            [255, 0, 255], [0, 255, 0], [0, 127, 255], [0, 0, 255], [255, 255, 0]
        ])
        self.cfg_mgr.set("model_dir", "/sdcard/kmodel/taping_checker/")
        self.cfg_mgr.set("model_name", "taping_checker_v13.kmodel")
        self.cfg_mgr.set("password", "1111")
        self.saved_msg_text = "已恢复默认设置"
        self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 2000)

    def _camera_loop(self):
        if image is None or Display is None:
            return

        sensor_bind_info = self.pl.sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
        Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)

        self._ui_img = image.Image(640, 480, image.ARGB8888)
        self._ui_img.clear()
        self._draw_title_bar(self._ui_img)
        Display.show_image(self._ui_img, 0, 0, Display.LAYER_OSD0)

        was_panel = False
        while self.is_running:
            try:
                if tp:
                    pts = tp.read(1)
                    if len(pts):
                        pt = pts[0]
                        if pt.event == TOUCH.EVENT_DOWN:
                            now_ms = time.ticks_ms()
                            if time.ticks_diff(now_ms, self._touch_last_ms) >= self._touch_debounce_ms:
                                self._touch_last_ms = now_ms
                                self._handle_touch(pt.x, pt.y)

                is_panel = self.panel is not None
                if is_panel and not was_panel:
                    try:
                        Display.unbind_layer(Display.LAYER_VIDEO1)
                    except:
                        pass
                elif not is_panel and was_panel:
                    try:
                        sensor_bind_info = self.pl.sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
                        Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)
                    except:
                        pass

                if not is_panel:
                    img = self.pl.get_frame()
                    boxes = self.detector.run(img)
                    bbox_colors = self.cfg_mgr.get("bbox_colors", None)
                    self._ui_img.clear()
                    self.detector.draw_result(self._ui_img, boxes, bbox_colors)
                    self._draw_title_bar(self._ui_img)
                    self._update_alarm(boxes)
                    self._update_io34()
                    self._draw_status_overlay()
                else:
                    boxes = []
                    self._ui_img.clear()
                    self._ui_img.draw_rectangle(0, 50, 640, 430, color=LAYOUT['panel_bg'], thickness=1, fill=True)
                    panel_titles = {
                        "menu": "设置",
                        "model": "模型管理",
                        "detect": "检测设置",
                        "alarm": "报警设置",
                        "auth_menu": "权限管理",
                        "auth": "密码输入",
                    }
                    self._draw_title_bar(self._ui_img, panel_titles.get(self.panel, "设置"))
                    if self.panel == "menu":
                        self._draw_settings_menu(self._ui_img)
                    elif self.panel == "model":
                        self._draw_model_panel(self._ui_img)
                    elif self.panel == "detect":
                        self._draw_detect_panel(self._ui_img)
                    elif self.panel == "alarm":
                        self._draw_alarm_panel(self._ui_img)
                    elif self.panel == "auth_menu":
                        self._draw_auth_menu(self._ui_img)
                    elif self.panel == "auth":
                        self._draw_auth_panel(self._ui_img)

                self._update_gpio(boxes)
                Display.show_image(self._ui_img, 0, 0, Display.LAYER_OSD0)
                was_panel = is_panel

                if self.model_switch_pending_name:
                    self._do_model_switch()
                gc.collect()
                time.sleep_ms(10)
            except Exception as e:
                print("camera_loop error:", e)
                time.sleep_ms(100)

        try:
            Display.unbind_layer(Display.LAYER_VIDEO1)
            clr = image.Image(640, 480, image.ARGB8888)
            clr.clear()
            Display.show_image(clr, 0, 0, Display.LAYER_OSD0)
        except:
            pass

    def _draw_status_overlay(self):
        now = time.ticks_ms()
        if self.saved_msg_until_ms and time.ticks_diff(now, self.saved_msg_until_ms) < 0:
            self._ui_img.draw_rectangle(15, 445, 610, 28, color=(0, 0, 0), thickness=1, fill=True)
            self._ui_img.draw_string_advanced(20, 450, 20, self.saved_msg_text, color=LAYOUT['primary'])

    def _update_alarm(self, boxes):
        has_target = False
        if boxes:
            for b in boxes:
                if float(b[1]) >= self.confidence_threshold:
                    has_target = True
                    break
        if has_target:
            if self.target_since_ms == 0:
                self.target_since_ms = time.ticks_ms()
        else:
            self.target_since_ms = 0
        if has_target and (self.alarm_trigger_hold_ms <= 0 or time.ticks_diff(time.ticks_ms(), self.target_since_ms) >= self.alarm_trigger_hold_ms) and not self.alarm_active:
            self.alarm_active = True
            self.alarm_remaining = 3
            self.alarm_next_ms = time.ticks_ms()
            self._play_alarm_sound()
        if self.alarm_active:
            now_ms = time.ticks_ms()
            if time.ticks_diff(now_ms, self.alarm_next_ms) >= 0:
                self._play_alarm_beep()
                self.alarm_remaining -= 1
                if self.alarm_remaining > 0:
                    self.alarm_next_ms = time.ticks_add(now_ms, 500)
                else:
                    self.alarm_active = False

    def _play_alarm_sound(self):
        now_ms = time.ticks_ms()
        self.red_on_until_ms = time.ticks_add(now_ms, 500)
        sound_mode = self.cfg_mgr.get("sound_mode", "buzzer")
        if sound_mode == "speaker":
            try:
                self.speaker.play(AUDIO_DIR + "siren.wav")
            except:
                pass
        elif sound_mode == "buzzer":
            if self.buzzer:
                try:
                    self.buzzer.on(2000, 50, 0.2)
                except:
                    pass

    def _play_alarm_beep(self):
        now_ms = time.ticks_ms()
        self.red_on_until_ms = time.ticks_add(now_ms, 500)
        sound_mode = self.cfg_mgr.get("sound_mode", "buzzer")
        if sound_mode == "buzzer" and self.buzzer:
            try:
                self.buzzer.on(2000, 50, 0.2)
            except:
                pass

    def _play_capture_sound(self):
        # 拍照音效：始终通过蜂鸣器播放，但受静音模式限制
        sound_mode = self.cfg_mgr.get("sound_mode", "buzzer")
        if sound_mode == "mute":
            # 静音模式：不播放任何拍照音效
            return
        # 非静音模式：始终使用蜂鸣器播放标准提示音（不受报警输出设备影响）
        if self.buzzer:
            try:
                self.buzzer.on(2000, 50, 0.2)
            except:
                pass

    def _update_gpio(self, boxes):
        self.gpio.set_yellow(self.panel is not None)
        now_ms = time.ticks_ms()
        self.gpio.set_red(time.ticks_diff(self.red_on_until_ms, now_ms) >= 0)

    def _update_io34(self):
        if machine is None:
            return
        try:
            io34 = machine.Pin(34, machine.Pin.IN, machine.Pin.PULL_UP)
        except:
            return
        now = time.ticks_ms()
        current = io34.value()
        if current != self.io34_last_stable:
            if self.io34_since_ms == 0:
                self.io34_since_ms = now
            elif time.ticks_diff(now, self.io34_since_ms) >= self.debounce_ms:
                self.io34_last_stable = current
                self.io34_since_ms = 0
                if current == 0 and time.ticks_diff(now, self.last_trigger_ms) >= self.min_interval_ms:
                    self._do_capture(now)
        else:
            self.io34_since_ms = 0

    def _do_capture(self, now):
        try:
            # 首次拍照时加载序号，并创建文件夹
            if self.seq_num == 1:
                self.seq_num = _load_seq(self.run_dir)
            rgb_img = self.pl.sensor.snapshot(chn=CAM_CHN_ID_1)
            path, fname = save_photo(rgb_img, self.run_dir, self.seq_num)
            if path:
                self.saved_msg_text = "Saved: %s" % path
                self.saved_msg_until_ms = time.ticks_add(now, 5000)
                self.seq_num += 1
                _save_seq(self.run_dir, self.seq_num)
                self._play_capture_sound()
            else:
                self.saved_msg_text = "Save failed: PIC%06d.jpg" % self.seq_num
                self.saved_msg_until_ms = time.ticks_add(now, 5000)
            self.last_trigger_ms = now
        except Exception as e:
            print("do_capture error:", e)

    def _do_model_switch(self):
        name = self.model_switch_pending_name
        self.model_switch_pending_name = None
        if not name:
            return
        model_dir = self.cfg_mgr.get("model_dir", "/sdcard/")
        new_path = model_dir + name
        if not _exists(new_path):
            fallback_dirs = ["/sdcard/kmodel/taping_checker/", "/sdcard/kmodel/", "/sdcard/"]
            for d in fallback_dirs:
                p = d + name
                if _exists(p):
                    new_path = p
                    break
        try:
            self.detector.switch_model(new_path, name, self.cfg_mgr)
            self.model_name = name
            self.kmodel_path = new_path
            self.saved_msg_text = "模型: %s" % name
            self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)
        except Exception as e:
            print("model switch error:", e)
            self.saved_msg_text = "模型切换失败"
            self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)

    def deinitialize(self):
        self.is_running = False
        time.sleep_ms(200)
        self.panel = None
        if self.detector:
            self.detector.deinit()
            self.detector = None
        if self.gpio:
            self.gpio.reset_outputs()
            self.gpio = None
        self.buzzer = None
        if self.speaker:
            self.speaker.deinit()
            self.speaker = None
        try:
            Display.unbind_layer(Display.LAYER_VIDEO1)
        except:
            pass
        try:
            if Display and image:
                clr = image.Image(640, 480, image.ARGB8888)
                clr.clear()
                Display.show_image(clr, 0, 0, Display.LAYER_OSD0)
        except:
            pass
        gc.collect()
