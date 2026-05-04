import lvgl as lv
from base_app import BaseApp
from ybUtils.modal_dialog import ModalDialog
from apps.picture_get.core import save_photo, ensure_dir, _load_boot_seq, _save_boot_seq, _load_seq, _save_seq, SAVE_BASE
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


class App(BaseApp):
    def __init__(self, app_manager):
        try:
            with open("/sdcard/apps/picture_get/icon.png", 'rb') as f:
                img_data = f.read()
                icon_img = lv.img_dsc_t({
                    'data-size': len(img_data),
                    'data': img_data
                })
        except:
            icon_img = None
        try:
            with open("/sdcard/apps/picture_get/dock_icon.png", 'rb') as f:
                dock_data = f.read()
                self.dock_icon = lv.img_dsc_t({
                    'data-size': len(dock_data),
                    'data': dock_data
                })
        except:
            self.dock_icon = None

        super().__init__(app_manager, name="按键拍照", icon=icon_img)
        self.pl = app_manager.pl
        self.is_running = False
        self.run_dir = ""
        self.seq_num = 1
        self.min_interval_ms = 500
        self.last_trigger_ms = 0
        self.debounce_ms = 75
        self.io34 = None
        self.io34_last_stable = 1
        self.io34_since_ms = 0

    def launch(self):
        self.screen = lv.obj()
        self.screen.set_style_text_font(self.app_manager.font_16, 0)
        self._create_title_bar()
        self.model_dialog = ModalDialog(self.screen, font_16=self.app_manager.font_16)
        lv.scr_load(self.screen)
        self.initialize()

    def initialize(self):
        self.is_running = True
        boot_seq = _load_boot_seq()
        self.run_dir = "DIR%06d" % boot_seq
        ensure_dir(SAVE_BASE + self.run_dir + "/")
        _save_boot_seq(boot_seq + 1)
        self.seq_num = _load_seq(self.run_dir)

        if machine:
            try:
                self.io34 = machine.Pin(34, machine.Pin.IN, machine.Pin.PULL_UP)
            except:
                try:
                    self.io34 = machine.Pin(34, machine.Pin.IN)
                except:
                    self.io34 = None
            self.io34_last_stable = self._read_io34()

        self._camera_loop()
        self.app_manager.go_home()

    def _read_io34(self):
        if self.io34 is None:
            return 1
        try:
            return self.io34.value()
        except:
            return 1

    def _draw_ui_overlay(self, ui_img, status_text="", status_is_red=False):
        ui_img.clear()

        ui_img.draw_rectangle(0, 0, 640, 60, color=(17, 7, 4), thickness=1, fill=True)
        ui_img.draw_line(0, 59, 640, 59, color=(200, 200, 200), thickness=1)

        ui_img.draw_string_advanced(12, 18, 24, "<", color=(255, 255, 255))
        ui_img.draw_string_advanced(260, 18, 16, "按键拍照", color=(255, 255, 255))

        ui_img.draw_rectangle(10, 70, 620, 30, color=(245, 245, 245), thickness=1, fill=True)
        ui_img.draw_string_advanced(20, 76, 16, "目录: %s  |  IO34低电平触发" % self.run_dir, color=(51, 51, 51))

        btn_cx = 580
        btn_cy = 270
        btn_r = 35
        ui_img.draw_circle(btn_cx, btn_cy, btn_r, color=(200, 0, 0), thickness=3)
        ui_img.draw_circle(btn_cx, btn_cy, btn_r - 4, color=(220, 30, 30), thickness=3, fill=True)

        if status_text:
            tw = len(status_text) * 9
            sx = max(10, (540 - tw) // 2)
            txt_color = (255, 50, 50) if status_is_red else (255, 255, 255)
            ui_img.draw_rectangle(sx - 8, 440, tw + 16, 30, color=(0, 0, 0), thickness=1, fill=True)
            ui_img.draw_string_advanced(sx, 446, 16, status_text, color=txt_color)

    def _camera_loop(self):
        if image is None or Display is None:
            return

        sensor_bind_info = self.pl.sensor.bind_info(x=0, y=0, chn=CAM_CHN_ID_0)
        Display.bind_layer(**sensor_bind_info, layer=Display.LAYER_VIDEO1)

        ui_img = image.Image(640, 480, image.RGB565)
        status_text = ""
        status_until_ms = 0

        self._draw_ui_overlay(ui_img)
        Display.show_image(ui_img, 0, 0, Display.LAYER_OSD0)

        while self.is_running:
            try:
                if tp:
                    point = tp.read(1)
                    if len(point):
                        pt = point[0]
                        if pt.event == TOUCH.EVENT_DOWN:
                            if pt.x < 100 and pt.y < 60:
                                self.is_running = False
                                break
                            elif (pt.x - 580) ** 2 + (pt.y - 270) ** 2 <= 40 ** 2:
                                now = time.ticks_ms()
                                if time.ticks_diff(now, self.last_trigger_ms) >= self.min_interval_ms:
                                    fname = self._do_capture(now)
                                    status_text = "拍照成功 %s" % fname if fname else "拍照失败"
                                    status_until_ms = time.ticks_add(now, 3000)
                                    self._draw_ui_overlay(ui_img, status_text, status_is_red=True)
                                    Display.show_image(ui_img, 0, 0, Display.LAYER_OSD0)

                if self.io34 is not None:
                    now = time.ticks_ms()
                    current = self._read_io34()
                    if current != self.io34_last_stable:
                        if self.io34_since_ms == 0:
                            self.io34_since_ms = now
                        elif time.ticks_diff(now, self.io34_since_ms) >= self.debounce_ms:
                            self.io34_last_stable = current
                            self.io34_since_ms = 0
                            if current == 0 and time.ticks_diff(now, self.last_trigger_ms) >= self.min_interval_ms:
                                fname = self._do_capture(now)
                                status_text = "拍照成功 %s" % fname if fname else "拍照失败"
                                status_until_ms = time.ticks_add(now, 3000)
                                self._draw_ui_overlay(ui_img, status_text, status_is_red=True)
                                Display.show_image(ui_img, 0, 0, Display.LAYER_OSD0)
                    else:
                        self.io34_since_ms = 0

                now_ms = time.ticks_ms()
                if status_text and time.ticks_diff(now_ms, status_until_ms) > 0:
                    status_text = ""
                    self._draw_ui_overlay(ui_img)
                    Display.show_image(ui_img, 0, 0, Display.LAYER_OSD0)

                time.sleep_ms(10)
            except Exception as e:
                time.sleep_ms(100)

        try:
            Display.unbind_layer(Display.LAYER_VIDEO1)
            clr = image.Image(640, 480, image.RGB565)
            clr.clear()
            Display.show_image(clr, 0, 0, Display.LAYER_OSD0)
        except:
            pass

    def _do_capture(self, now):
        fname = None
        try:
            img = self.pl.sensor.snapshot(chn=CAM_CHN_ID_1)
            path, fname = save_photo(img, self.run_dir, self.seq_num)
            if path:
                fname = "PIC%06d.jpg" % self.seq_num
                self.seq_num += 1
                _save_seq(self.run_dir, self.seq_num)
            self.last_trigger_ms = now
        except:
            pass
        return fname

    def deinitialize(self):
        self.is_running = False
        try:
            Display.unbind_layer(Display.LAYER_VIDEO1)
        except:
            pass
        try:
            if Display and image:
                clr = image.Image(640, 480, image.RGB565)
                clr.clear()
                Display.show_image(clr, 0, 0, Display.LAYER_OSD0)
        except:
            pass
        self.io34 = None
        gc.collect()
