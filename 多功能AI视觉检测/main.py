import lvgl as lv
import utime as time
from media.display import *
from media.media import *
import os, sys, gc
from machine import TOUCH
import uctypes
from machine import Timer
import _thread
from libs.PipeLine import PipeLine
from ybUtils.Configuration import Configuration
from ybUtils.YbRGB import YbRGB
from base_app import BaseApp

import machine

start_time = time.ticks_ms()
DISPLAY_WIDTH = ALIGN_UP(640, 16)
DISPLAY_HEIGHT = 480

config = None
YbRGB = YbRGB()
pl = None

LOG_FILE = "/sdcard/boot_log.txt"

def log_print(*args):
    msg = " ".join(str(a) for a in args)
    print(msg)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")
    except:
        pass

def debug_print(*args):
    msg = "[DEBUG] " + " ".join(str(a) for a in args)
    print(msg)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(msg + "\n")
    except:
        pass

def display_init():
    global pl, config
    try:
        t = time.ticks_ms()
        YbRGB.show_rgb((82, 139, 255))
        display_mode = "lcd"
        display_size = [DISPLAY_WIDTH, 480]
        rgb888p_size = [640, 480]
        pl = PipeLine(rgb888p_size=rgb888p_size, display_size=display_size, display_mode=display_mode, osd_layer_num=4)
        pl.create(ch1_frame_size=[config.get_section("sensor")["ch1_width"], config.get_section("sensor")["ch1_height"]])
        print("display_init: ", time.ticks_diff(time.ticks_ms(), t))
    except Exception as e:
        debug_print("display_init", e)

def display_deinit():
    try:
        global pl
        pl.destroy()
        time.sleep_ms(50)
    except Exception as e:
        debug_print("display_deinit", e)

def disp_drv_flush_cb(disp_drv, area, color):
    global disp_img1, disp_img2
    try:
        if disp_drv.flush_is_last() == True:
            if disp_img1.virtaddr() == uctypes.addressof(color.__dereference__()):
                Display.show_image(disp_img1)
            else:
                Display.show_image(disp_img2)
        disp_drv.flush_ready()
    except Exception as e:
        debug_print("disp_drv_flush_cb", e)

class touch_screen():
    def __init__(self):
        self.state = lv.INDEV_STATE.RELEASED
        self.indev_drv = lv.indev_create()
        self.indev_drv.set_type(lv.INDEV_TYPE.POINTER)
        self.indev_drv.set_read_cb(self.callback)
        self.touch = TOUCH(0)

    def callback(self, driver, data):
        x, y, state = 0, 0, lv.INDEV_STATE.RELEASED
        tp = self.touch.read(1)
        if len(tp):
            x, y, event = tp[0].x, tp[0].y, tp[0].event
            if event == 2 or event == 3:
                state = lv.INDEV_STATE.PRESSED
        data.point = lv.point_t({'x': x, 'y': y})
        data.state = state

def lvgl_init():
    t = time.ticks_ms()
    global disp_img1, disp_img2, global_touch_dev
    lv.init()
    disp_drv = lv.disp_create(DISPLAY_WIDTH, DISPLAY_HEIGHT)
    disp_drv.set_flush_cb(disp_drv_flush_cb)
    disp_img1 = image.Image(DISPLAY_WIDTH, DISPLAY_HEIGHT, image.BGRA8888)
    disp_img2 = image.Image(DISPLAY_WIDTH, DISPLAY_HEIGHT, image.BGRA8888)
    disp_drv.set_draw_buffers(disp_img1.bytearray(), disp_img2.bytearray(), disp_img1.size()*5, lv.DISP_RENDER_MODE.FULL)
    global_touch_dev = touch_screen()
    print("lvgl_init: ", time.ticks_diff(time.ticks_ms(), t))

def lvgl_deinit():
    try:
        global disp_img1, disp_img2
        lv.deinit()
        del disp_img1
        del disp_img2
    except Exception as e:
        debug_print("lvgl_deinit", e)

def create_black_frosted_style():
    style_black_frosted = lv.style_t()
    style_black_frosted.init()
    style_black_frosted.set_bg_color(lv.color_make(20, 20, 20))
    style_black_frosted.set_bg_grad_color(lv.color_make(40, 40, 40))
    style_black_frosted.set_bg_grad_dir(lv.GRAD_DIR.VER)
    style_black_frosted.set_bg_grad_stop(128)
    style_black_frosted.set_bg_dither_mode(lv.DITHER.ORDERED)
    style_black_frosted.set_radius(0)
    style_black_frosted.set_shadow_width(10)
    style_black_frosted.set_shadow_color(lv.color_make(0, 0, 0))
    style_black_frosted.set_shadow_opa(40)
    style_black_frosted.set_shadow_ofs_x(0)
    style_black_frosted.set_shadow_ofs_y(4)
    style_black_frosted.set_shadow_spread(0)
    return style_black_frosted

class AppManager:
    def __init__(self, config, pipeline):
        self.apps = {}
        self.home_screen = None
        self.home_screen_width = 640
        self.current_app = None
        self.dock_apps = []
        self.config = config
        self.pl = pipeline
        self.text_config = None
        self.font_16 = None
        self.icon_size = 115
        self.icon_spacing_x = 30
        self.icon_spacing_y = 40
        self.grid_start_x = 40
        self.grid_start_y = 140
        self.icons_per_row = 4
        self.rows_per_page = 1
        self.apps_per_page = self.icons_per_row * self.rows_per_page

    def initialize(self):
        try:
            self.font_16 = lv.font_yb_cn_16
            self.home_screen = lv.obj()
            self.home_screen.set_size(self.home_screen_width, 480)

            # 桌面背景壁纸
            self.wallpaper = None
            try:
                with open("/sdcard/wallpaper.png", 'rb') as f:
                    wp_data = f.read()
                    wp_img_dsc = lv.img_dsc_t({
                        'data_size': len(wp_data),
                        'data': wp_data
                    })
                    self.wallpaper = lv.img(self.home_screen)
                    self.wallpaper.set_src(wp_img_dsc)
                    self.wallpaper.set_size(self.home_screen_width, 480)
                    self.wallpaper.set_pos(0, 0)
            except Exception as e:
                debug_print("load wallpaper", e)

            # 如果没有壁纸或加载失败，使用默认黑色背景
            if self.wallpaper is None:
                style = create_black_frosted_style()
                self.home_screen.add_style(style, 0)

            self.app_container = lv.obj(self.home_screen)
            self.app_container.set_size(lv.pct(100), lv.pct(100))
            self.app_container.set_pos(0, 0)
            self.app_container.set_style_bg_opa(0, 0)
            self.app_container.set_style_border_width(0, 0)
            self.app_container.set_style_pad_all(0, 0)
            self.app_container.clear_flag(lv.obj.FLAG.CLICKABLE)
            self.app_container.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

            # Dock栏已移除

            self.scan_apps()
            log_print("scan_apps done, apps loaded:", len(self.apps))
            lv.scr_load(self.home_screen)
        except Exception as e:
            debug_print("initialize", e)
            import io
            buf = io.StringIO()
            sys.print_exception(e, buf)
            debug_print(buf.getvalue())
        finally:
            YbRGB.show_rgb((0,0,0))

    def scan_apps(self):
        try:
            app_dirs = []
            try:
                app_list = os.listdir("/sdcard/apps")
                log_print("raw app_list:", app_list)
                for item in app_list:
                    try:
                        os.listdir(f"/sdcard/apps/{item}")
                        if not item.startswith("__"):
                            app_dirs.append(item)
                    except Exception as e:
                        pass
            except Exception as e:
                debug_print("scan_app_dirs", e)

            allowed_apps = ["taping_checker", "picture_get", "io_tester", "body_pose"]
            app_dirs = [d for d in app_dirs if d in allowed_apps]
            log_print("filtered app_dirs:", app_dirs)

            app_order = {}
            try:
                with open("/sdcard/configs/app_order.json", 'r') as f:
                    import json
                    app_order = json.load(f)
            except Exception as e:
                debug_print("load_app_order", e)

            ordered_apps = []
            for app_dir in app_dirs:
                order = app_order.get(app_dir, 100)
                ordered_apps.append({"dir": app_dir, "order": order})
            ordered_apps.sort(key=lambda x: (x['order'], x['dir']))

            for app_info in ordered_apps:
                app_dir = app_info['dir']
                try:
                    import_cmd = f"from apps.{app_dir}.app import App as CurrentApp"
                    log_print("loading:", import_cmd)
                    exec(import_cmd, globals())
                    app_instance = CurrentApp(self)
                    self.register_app(app_instance)
                    log_print("loaded app:", app_instance.name)
                except Exception as e:
                    import io
                    buf = io.StringIO()
                    sys.print_exception(e, buf)
                    log_print("load app", app_dir, "error:", buf.getvalue())

            # Dock栏已移除，所有应用只显示在桌面网格中

        except Exception as e:
            debug_print("scan_apps", e)

    def register_app(self, app):
        try:
            if app.name in self.apps:
                app.name = f"{app.name}_{len(self.apps)}"
            self.apps[app.name] = app
            self.create_app_icon(app)
        except Exception as e:
            debug_print("register_app", e)

    def _load_icon(self, app, attr_name):
        try:
            if not hasattr(app, attr_name):
                return None
            data = getattr(app, attr_name)
            if data is None:
                return None
            if isinstance(data, bytes):
                return lv.img_dsc_t({
                    'data_size': len(data),
                    'data': data
                })
            return data
        except Exception as e:
            debug_print("_load_icon", e)
            return None

    def _set_icon_bg(self, icon, img_dsc, fallback_color=(0x5AC8FA, 0x2196F3)):
        if img_dsc:
            icon.set_style_bg_opa(0, 0)
            icon.set_style_bg_img_src(img_dsc, 0)
        else:
            icon.set_style_bg_color(lv.color_hex(fallback_color[0]), 0)
            icon.set_style_bg_grad_color(lv.color_hex(fallback_color[1]), 0)
            icon.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)

    def create_app_icon(self, app):
        try:
            app_index = len(self.apps) - 1
            col = app_index % self.icons_per_row
            row = app_index // self.icons_per_row
            icon_x = self.grid_start_x + col * (self.icon_size + self.icon_spacing_x)
            icon_y = self.grid_start_y + row * (self.icon_size + self.icon_spacing_y)

            icon = lv.btn(self.app_container)
            icon.set_size(self.icon_size, self.icon_size)
            icon.set_pos(icon_x, icon_y)
            icon.set_style_radius(18, 0)

            img_dsc = self._load_icon(app, 'icon_data')
            if img_dsc is None:
                img_dsc = self._load_icon(app, 'icon')
            ios_colors = [
                (0x5AC8FA, 0x2196F3),
                (0x4CD964, 0x43A047),
                (0xFF9500, 0xFB8C00),
                (0xFF3B30, 0xE53935),
                (0x5856D6, 0x3F51B5),
            ]
            color_index = app_index % len(ios_colors)
            self._set_icon_bg(icon, img_dsc, ios_colors[color_index])

            icon.set_style_shadow_width(3, 0)
            icon.set_style_shadow_opa(80, 0)
            icon.set_style_shadow_ofs_y(2, 0)
            icon.set_style_shadow_color(lv.color_hex(0x000000), 0)
            icon.add_event(lambda e: self.launch_app(app.name), lv.EVENT.CLICKED, None)
            app.icon_btn = icon

            label = lv.label(self.app_container)
            label.set_text(app.name)
            label.set_style_text_color(lv.color_hex(0x000000), 0)
            label.set_style_text_font(self.font_16, 0)
            label.set_width(self.icon_size)
            label.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
            label.set_pos(icon_x, icon_y + self.icon_size + 7)
        except Exception as e:
            debug_print("create_app_icon", e)

    def launch_app(self, app_name):
        try:
            if app_name in self.apps:
                self.current_app = self.apps[app_name]
                self.current_app.on_icon_clicked()
        except Exception as e:
            debug_print("launch_app", e)

    def go_home(self):
        try:
            if self.current_app:
                self.current_app.deinitialize()
                self.current_app = None
            lv.scr_load(self.home_screen)
        except Exception as e:
            debug_print("go_home", e)

def main():
    global config, pl
    try:
        log_print("=== BOOT START ===")
        config = Configuration.load_from_file('/sdcard/configs/sys_config.json')
        log_print("config loaded")
        display_init()
        log_print("display_init done, pl=", pl)
        lvgl_init()
        log_print("lvgl_init done")
        if pl is not None:
            app_manager = AppManager(config, pl)
            log_print("AppManager created")
            app_manager.initialize()
            log_print("AppManager initialized")
            lv.refr_now(None)
            log_print("home screen loaded")
        else:
            log_print("pl is None, exit")
            return

        gc_counter = 0
        while True:
            refresh_time = lv.task_handler()
            time.sleep_ms(max(refresh_time, 10))
            gc_counter += 1
            if gc_counter >= 100000:
                gc.collect()
                gc_counter = 0
    except Exception as e:
        import io
        buf = io.StringIO()
        sys.print_exception(e, buf)
        err_msg = buf.getvalue()
        debug_print("main exception:")
        debug_print(err_msg)

def start():
    main()

if __name__ == "__main__":
    start()
