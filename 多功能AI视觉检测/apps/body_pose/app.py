from base_app import BaseApp
from media.display import Display
from media.sensor import CAM_CHN_ID_0
from media.media import *
import image
import gc
import time
from apps.body_pose.core.person_keypoint_detect import BodyPoseDemo, ConfigManager

try:
    from machine import TOUCH
    tp = TOUCH(0)
except:
    tp = None

LAYOUT = {
    'font_md': 22,
    'font_lg': 26,
    'btn_font': 22,
    'ctrl_w': 70,
    'ctrl_h': 48,
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
    'panel_bg': (20, 25, 40),
    'item_bg': (30, 38, 55),
    'card_bg': (30, 38, 55),
    'card_border': (60, 70, 90),
    'card_icon_detect': (40, 200, 120),
    'card_icon_setting': (0, 180, 255),
}

class App(BaseApp):
    def __init__(self, app_manager):
        super().__init__(app_manager, name="人体姿态", icon=None)
        try:
            with open("/sdcard/apps/body_pose/dock_icon.png", 'rb') as f:
                dock_data = f.read()
                self.dock_icon_data = dock_data
        except:
            self.dock_icon_data = None
        try:
            with open("/sdcard/apps/body_pose/icon.png", 'rb') as f:
                icon_data = f.read()
                self.icon_data = icon_data
        except:
            self.icon_data = None
        self.pl = app_manager.pl
        self.is_running = False
        self.demo = None
        self.cfg_mgr = None
        self._ui_img = None
        self.panel = None
        self._tmp_conf = 0.2
        self._tmp_nms = 0.5
        self._touch_last_ms = 0
        self._touch_debounce_ms = 200

    def launch(self):
        self.initialize()

    def initialize(self):
        self.is_running = True
        self.cfg_mgr = ConfigManager()
        self._camera_loop()
        self.app_manager.go_home()

    def _camera_loop(self):
        if image is None or Display is None:
            return

        sensor_bind_info = self.pl.sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
        Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)

        self._ui_img = image.Image(640, 480, image.ARGB8888)
        self._ui_img.clear()
        self._draw_title_bar(self._ui_img)
        Display.show_image(self._ui_img, 0, 0, Display.LAYER_OSD0)

        confidence_threshold = self.cfg_mgr.get("confidence_threshold", 0.2)
        nms_threshold = self.cfg_mgr.get("nms_threshold", 0.5)

        try:
            self.demo = BodyPoseDemo(self.pl)
            self.demo.exce_demo_init(confidence_threshold, nms_threshold)
        except Exception as e:
            self._show_error("模型加载失败: %s" % str(e))
            self._cleanup()
            return

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
                    if img is not None:
                        res = self.demo.person_kp.run(img)
                        self._ui_img.clear()
                        self.demo.person_kp.draw_result_direct(self._ui_img, res)
                        self._draw_title_bar(self._ui_img)
                else:
                    self._ui_img.clear()
                    self._ui_img.draw_rectangle(0, 50, 640, 430, color=LAYOUT['panel_bg'], thickness=1, fill=True)
                    panel_titles = {
                        "menu": "设置",
                        "detect": "检测设置",
                    }
                    self._draw_title_bar(self._ui_img, panel_titles.get(self.panel, "设置"))
                    if self.panel == "menu":
                        self._draw_settings_menu(self._ui_img)
                    elif self.panel == "detect":
                        self._draw_detect_panel(self._ui_img)

                Display.show_image(self._ui_img, 0, 0, Display.LAYER_OSD0)
                was_panel = is_panel
                gc.collect()
                time.sleep_ms(10)
            except Exception as e:
                time.sleep_ms(100)

        self._cleanup()

    def _draw_title_bar(self, ui_img, title="人体姿态检测"):
        ui_img.draw_rectangle(0, 0, 640, 50, color=LAYOUT['title_bg'], thickness=1, fill=True)
        ui_img.draw_line(0, 49, 640, 49, color=LAYOUT['title_line'], thickness=1)
        # 返回按钮 - 箭头样式
        ui_img.draw_line(30, 14, 14, 25, color=LAYOUT['text_white'], thickness=4)
        ui_img.draw_line(14, 25, 30, 36, color=LAYOUT['text_white'], thickness=4)
        # 标题
        title_x = 260
        if len(title) > 6:
            title_x = 220
        ui_img.draw_string_advanced(title_x, 16, 16, title, color=LAYOUT['text_white'])
        # 设置按钮（仅主界面显示）
        if self.panel is None:
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
            ("detect", "检测设置", "置信度/NMS阈值", LAYOUT['card_icon_detect']),
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

    def _draw_detect_panel(self, ui_img):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        bar_w = rx - pad - 20 - 2 * cw - 20

        # 置信度阈值
        ui_img.draw_string_advanced(pad, ty, LAYOUT['font_md'], "置信度阈值: %.2f" % self._tmp_conf, color=LAYOUT['text_dim'])
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

        # 分隔线
        ui_img.draw_line(pad, ty + 85, 640 - pad, ty + 85, color=LAYOUT['divider'], thickness=1)

        # NMS阈值
        nms_y = ty + 95
        ui_img.draw_string_advanced(pad, nms_y, LAYOUT['font_md'], "NMS阈值: %.2f" % self._tmp_nms, color=LAYOUT['text_dim'])
        ui_img.draw_rectangle(pad + 10, nms_y + 30, cw, ch, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(pad + 10, nms_y + 30, cw, ch, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(pad + 10 + (cw - LAYOUT['font_md']) // 2, nms_y + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "-", color=LAYOUT['text_white'])
        bar_x2 = pad + 10 + cw + 10
        ui_img.draw_rectangle(bar_x2, nms_y + 38, bar_w, 12, color=LAYOUT['bar_bg'], thickness=1, fill=True)
        fill_w2 = max(1, int(bar_w * self._tmp_nms))
        ui_img.draw_rectangle(bar_x2, nms_y + 38, fill_w2, 12, color=LAYOUT['bar_fg'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, nms_y + 30, cw, ch, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(rx - 10, nms_y + 30, cw, ch, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(rx - 10 + (cw - LAYOUT['font_md']) // 2, nms_y + 30 + (ch - LAYOUT['font_md']) // 2, LAYOUT['font_md'], "+", color=LAYOUT['text_white'])

        # 保存/取消按钮
        btn_y = LAYOUT['bottom_y']
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(160, btn_y, 140, 48, color=LAYOUT['confirm'], thickness=1)
        ui_img.draw_string_advanced(195, btn_y + 12, LAYOUT['btn_font'], "保存", color=LAYOUT['text_white'])
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger_dark'], thickness=1, fill=True)
        ui_img.draw_rectangle(340, btn_y, 140, 48, color=LAYOUT['danger'], thickness=1)
        ui_img.draw_string_advanced(375, btn_y + 12, LAYOUT['btn_font'], "取消", color=LAYOUT['text_white'])

    @staticmethod
    def _in_rect(x, y, rx, ry, rw, rh):
        return rx <= x <= rx + rw and ry <= y <= ry + rh

    def _handle_touch(self, x, y):
        if self.panel == "detect":
            self._handle_detect_touch(x, y)
        elif self.panel == "menu":
            self._handle_menu_touch(x, y)
        else:
            if x < 100 and y < 50:
                self.is_running = False
            elif 547 <= x <= 643 and 0 <= y <= 50:
                self.panel = "menu"

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
        cards = ["detect"]
        for i, key in enumerate(cards):
            col = i % 2
            row = i // 2
            cx = pad + col * (cw + gap)
            cy = ty + row * (ch + gap)
            if self._in_rect(x, y, cx - te, cy - te, cw + 2 * te, ch + 2 * te):
                if key == "detect":
                    self._open_detect_panel()
                return

    def _open_detect_panel(self):
        self._tmp_conf = float(self.cfg_mgr.get("confidence_threshold", 0.2))
        self._tmp_nms = float(self.cfg_mgr.get("nms_threshold", 0.5))
        self.panel = "detect"

    def _handle_detect_touch(self, x, y):
        pad = LAYOUT['pad']
        ty = LAYOUT['top_y']
        cw, ch = LAYOUT['ctrl_w'], LAYOUT['ctrl_h']
        rx = 640 - pad - cw
        te = LAYOUT['touch_expand']

        if x < 100 and y < 50:
            self.panel = "menu"
            return

        # 置信度 -
        if self._in_rect(x, y, pad + 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_conf = max(0.05, min(1.0, round(self._tmp_conf - 0.05, 2)))
            return
        # 置信度 +
        if self._in_rect(x, y, rx - 10 - te, ty + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_conf = max(0.05, min(1.0, round(self._tmp_conf + 0.05, 2)))
            return

        # NMS -
        nms_y = ty + 95
        if self._in_rect(x, y, pad + 10 - te, nms_y + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_nms = max(0.05, min(1.0, round(self._tmp_nms - 0.05, 2)))
            return
        # NMS +
        if self._in_rect(x, y, rx - 10 - te, nms_y + 30 - te, cw + 2 * te, ch + 2 * te):
            self._tmp_nms = max(0.05, min(1.0, round(self._tmp_nms + 0.05, 2)))
            return

        # 保存
        btn_y = LAYOUT['bottom_y']
        if self._in_rect(x, y, 160 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.cfg_mgr.set("confidence_threshold", self._tmp_conf)
            self.cfg_mgr.set("nms_threshold", self._tmp_nms)
            # 重新初始化模型
            try:
                self.demo = BodyPoseDemo(self.pl)
                self.demo.exce_demo_init(self._tmp_conf, self._tmp_nms)
            except:
                pass
            self.panel = None
            return
        # 取消
        if self._in_rect(x, y, 340 - te, btn_y - te, 140 + 2 * te, 48 + 2 * te):
            self.panel = None
            return

    def _show_error(self, msg):
        try:
            self._ui_img = image.Image(640, 480, image.ARGB8888)
            self._ui_img.clear()
            self._ui_img.draw_string_advanced(100, 200, 24, msg, color=(255, 0, 0))
            Display.show_image(self._ui_img, 0, 0, Display.LAYER_OSD0)
            start = time.ticks_ms()
            while time.ticks_diff(time.ticks_ms(), start) < 3000:
                if tp:
                    pts = tp.read(1)
                    if len(pts) and pts[0].event == TOUCH.EVENT_DOWN:
                        break
                time.sleep_ms(50)
        except:
            pass

    def _cleanup(self):
        self.is_running = False
        self.demo = None
        self.panel = None
        gc.collect()
        try:
            Display.unbind_layer(Display.LAYER_VIDEO1)
        except:
            pass
        try:
            clr = image.Image(640, 480, image.ARGB8888)
            clr.clear()
            Display.show_image(clr, 0, 0, Display.LAYER_OSD0)
        except:
            pass

    def deinitialize(self):
        self.is_running = False
        self.demo = None
        self.panel = None
        gc.collect()
