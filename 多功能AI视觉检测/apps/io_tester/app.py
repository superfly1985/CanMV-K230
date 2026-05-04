import lvgl as lv
from base_app import BaseApp
from apps.io_tester.core import GPIOController, OUTPUT_PINS, INPUT_PINS
import time, gc

class App(BaseApp):
    def __init__(self, app_manager):
        try:
            with open("/sdcard/apps/io_tester/icon.png", 'rb') as f:
                img_data = f.read()
                icon_img = lv.img_dsc_t({'data_size': len(img_data), 'data': img_data})
        except:
            icon_img = None
        try:
            with open("/sdcard/apps/io_tester/dock_icon.png", 'rb') as f:
                dock_data = f.read()
                self.dock_icon = lv.img_dsc_t({'data_size': len(dock_data), 'data': dock_data})
        except:
            self.dock_icon = None
        super().__init__(app_manager, name="IO测试", icon=icon_img)
        self.pl = app_manager.pl
        self.is_running = False
        self.gpio = None
        self.out_btns = {}
        self.in_labels = {}
        self.content_area = None
        self._lv_timer = None

    def initialize(self):
        self.is_running = True
        self.gpio = GPIOController()
        self._create_ui()
        self._lv_timer = lv.timer_create(self._timer_update, 300, None)

    def _create_ui(self):
        self.content_area = lv.obj(self.screen)
        self.content_area.set_size(self.disp_w, self.disp_h - 60)
        self.content_area.set_pos(0, 60)
        self.content_area.set_style_bg_color(lv.color_hex(0xFFFFFF), 0)
        self.content_area.set_style_bg_opa(255, 0)
        self.content_area.set_style_border_width(0, 0)
        self.content_area.set_style_pad_all(10, 0)
        self.content_area.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

        font = self.app_manager.font_16

        out_label = lv.label(self.content_area)
        out_label.set_text("输出控制")
        out_label.set_style_text_color(lv.color_hex(0xE65100), 0)
        out_label.set_style_text_font(font, 0)
        out_label.set_pos(10, 5)

        for i, name in enumerate(OUTPUT_PINS):
            row = lv.obj(self.content_area)
            row.set_size(self.disp_w - 30, 50)
            row.set_pos(5, 30 + i * 55)
            row.set_style_bg_color(lv.color_hex(0xF5F5F5), 0)
            row.set_style_bg_opa(255, 0)
            row.set_style_border_width(0, 0)
            row.set_style_radius(10, 0)
            row.set_style_pad_all(0, 0)
            row.clear_flag(lv.obj.FLAG.CLICKABLE)
            row.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

            pin_label = lv.label(row)
            pin_label.set_text(name)
            pin_label.set_style_text_color(lv.color_hex(0x333333), 0)
            pin_label.set_style_text_font(font, 0)
            pin_label.align(lv.ALIGN.LEFT_MID, 15, 0)

            btn = lv.btn(row)
            btn.set_size(100, 36)
            btn.align(lv.ALIGN.RIGHT_MID, -10, 0)
            btn.set_style_radius(8, 0)
            btn.set_style_text_font(font, 0)

            state = self.gpio.out_state.get(name)
            self._set_btn_style(btn, state)
            btn_label = lv.label(btn)
            btn_label.set_text("ON" if state else "OFF")
            btn_label.center()
            btn.add_event(lambda e, n=name: self._on_toggle(n), lv.EVENT.CLICKED, None)
            self.out_btns[name] = btn

        y_in_start = 30 + len(OUTPUT_PINS) * 55 + 15

        in_label = lv.label(self.content_area)
        in_label.set_text("输入状态")
        in_label.set_style_text_color(lv.color_hex(0xE65100), 0)
        in_label.set_style_text_font(font, 0)
        in_label.set_pos(10, y_in_start)

        for i, name in enumerate(INPUT_PINS):
            row = lv.obj(self.content_area)
            row.set_size(self.disp_w - 30, 50)
            row.set_pos(5, y_in_start + 25 + i * 55)
            row.set_style_bg_color(lv.color_hex(0xF5F5F5), 0)
            row.set_style_bg_opa(255, 0)
            row.set_style_border_width(0, 0)
            row.set_style_radius(10, 0)
            row.set_style_pad_all(0, 0)
            row.clear_flag(lv.obj.FLAG.CLICKABLE)
            row.set_scrollbar_mode(lv.SCROLLBAR_MODE.OFF)

            pin_label = lv.label(row)
            pin_label.set_text(name)
            pin_label.set_style_text_color(lv.color_hex(0x333333), 0)
            pin_label.set_style_text_font(font, 0)
            pin_label.align(lv.ALIGN.LEFT_MID, 15, 0)

            val_label = lv.label(row)
            val_label.set_style_text_font(font, 0)
            val_label.align(lv.ALIGN.RIGHT_MID, -15, 0)
            self.in_labels[name] = val_label

        self._update_input_labels()

    def _set_btn_style(self, btn, state):
        if state:
            btn.set_style_bg_color(lv.color_hex(0x4CAF50), 0)
            btn.set_style_bg_grad_color(lv.color_hex(0x388E3C), 0)
        else:
            btn.set_style_bg_color(lv.color_hex(0x9E9E9E), 0)
            btn.set_style_bg_grad_color(lv.color_hex(0x757575), 0)
        btn.set_style_bg_grad_dir(lv.GRAD_DIR.VER, 0)

    def _on_toggle(self, name):
        new_state = self.gpio.toggle_output(name)
        if new_state is not None:
            btn = self.out_btns.get(name)
            if btn:
                self._set_btn_style(btn, new_state)
                btn_label = btn.get_child(0)
                btn_label.set_text("ON" if new_state else "OFF")

    def _update_input_labels(self):
        if not self.gpio:
            return
        inputs = self.gpio.read_all_inputs()
        for name, label in self.in_labels.items():
            val = inputs.get(name)
            if val is None:
                label.set_text("未连接")
                label.set_style_text_color(lv.color_hex(0x9E9E9E), 0)
            elif val == 1:
                label.set_text("高电平")
                label.set_style_text_color(lv.color_hex(0x2E7D32), 0)
            else:
                label.set_text("低电平")
                label.set_style_text_color(lv.color_hex(0xC62828), 0)

    def _timer_update(self, timer):
        try:
            self._update_input_labels()
        except Exception as e:
            print("lv_timer_update error:", e)

    def deinitialize(self):
        self.is_running = False
        if self._lv_timer is not None:
            try:
                lv.timer_delete(self._lv_timer)
            except:
                pass
            self._lv_timer = None
        if self.gpio:
            self.gpio.reset_outputs()
            self.gpio = None
        self.out_btns = {}
        self.in_labels = {}
        self.content_area = None
        gc.collect()
