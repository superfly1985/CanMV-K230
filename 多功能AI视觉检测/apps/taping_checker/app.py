import lvgl as lv
from base_app import BaseApp
from apps.taping_checker.core import *
from libs.PlatTasks import DetectionApp
from libs.Utils import read_json
import time, gc, _thread

class App(BaseApp):
    def __init__(self, app_manager):
        try:
            with open("/sdcard/apps/taping_checker/icon.png", 'rb') as f:
                img_data = f.read()
                icon_img = lv.img_dsc_t({'data_size': len(img_data), 'data': img_data})
        except:
            icon_img = None
        try:
            with open("/sdcard/apps/taping_checker/dock_icon.png", 'rb') as f:
                dock_data = f.read()
                self.dock_icon = lv.img_dsc_t({'data_size': len(dock_data), 'data': dock_data})
        except:
            self.dock_icon = None
        super().__init__(app_manager, name="胶带检测", icon=icon_img)
        self.pl = app_manager.pl
        self.config = app_manager.config
        self.detector = None
        self.is_running = False
        self.gpio = None
        self.speaker = None
        self.buzzer = None
        self.cfg_mgr = None
        self.run_dir = ""
        self.seq_num = 1
        self.saved_msg_text = ""
        self.saved_msg_until_ms = 0
        self.saving_busy = False
        self.alarm_active = False
        self.alarm_remaining = 0
        self.alarm_next_ms = 0
        self.target_since_ms = 0
        self.red_on_until_ms = 0
        self.last_trigger_ms_map = {p: 0 for p in [26, 34, 35, 43]}
        self.in_state_map = {p: 0 for p in [26, 34, 35, 43]}
        self.in_since_map = {p: 0 for p in [26, 34, 35, 43]}
        self.captured_high_map = {p: False for p in [26, 34, 35, 43]}
        self.hold_until_ms = {p: 0 for p in [26, 34, 35, 43]}
        self.debounce_ms = 75
        self.min_interval_ms = 500
        self.unstable_inputs = {34, 35}
        self.stretch_ms = 120
        self.config_open = False
        self.model_open = False
        self.auth_panel_open = False
        self.auth_mode = ""
        self.auth_target = ""
        self.auth_input = ""
        self.auth_fail_count = 0
        self.auth_locked_until_ms = 0
        self.auth_suppress_until_ms = 0
        self.tmp_conf = 0.4
        self.tmp_hold = 0
        self.tmp_buzzer = False
        self.model_list = []
        self.model_sel_idx_tmp = -1
        self.model_page = 0
        self.model_switch_pending_name = None
        self.layout = {
            'cfg_box': (450, 40, 110, 80),
            'model_box': (80, 40, 110, 80),
            'panel': (90, 50, 460, 420),
            'model_panel': (60, 40, 540, 420),
            'btn_save_offset': (40, -90, 180, 80),
            'btn_cancel_offset': (-220, -90, 180, 80),
            'btn_text_offset': (10, 10),
            'font_md': 26,
            'font_lg': 28,
            'rect_thick': 2,
            'panel_border': 3,
            'inner_fill_thick': 1,
            'panel_title_offset': (16, 8),
            'btn_font': 26,
            'ctrl_w': 60,
            'ctrl_h': 44,
            'model_row_gap': 8,
            'model_list_top': 70,
            'model_nav_offset': 180,
        }

    def initialize(self):
        self.is_running = True
        self.cfg_mgr = ConfigManager()
        self._load_deploy_config()
        self.speaker = Speaker(self.cfg_mgr.conf)
        self.buzzer = YbBuzzer()
        self.gpio = GPIOController()
        self.gpio.reset_outputs()
        self.gpio.set_green(True)
        self._init_detector()
        self._init_session()
        self.tmp_conf = float(self.confidence_threshold)
        self.tmp_hold = int(self.alarm_trigger_hold_ms)
        self.tmp_buzzer = bool(self.cfg_mgr.get("buzzer_enable", False))
        _thread.start_new_thread(self.main_loop, ())

    def _load_deploy_config(self):
        candidate_json = ["/sdcard/mp_detect_garbage/deploy_config_taping.json"]
        deploy_conf = None
        for p in candidate_json:
            if _exists(p):
                deploy_conf = read_json(p)
                break
        if deploy_conf is None:
            deploy_conf = {}
        self.labels = deploy_conf.get("categories", ["no_taping"])
        self.nms_threshold = deploy_conf.get("nms_threshold", 0.5)
        self.model_input_size = deploy_conf.get("img_size", [320, 320])
        self.nms_option = deploy_conf.get("nms_option", False)
        self.model_type = deploy_conf.get("model_type", "AnchorBaseDet")
        self.anchors = []
        if self.model_type == "AnchorBaseDet":
            self.anchors = deploy_conf["anchors"][0] + deploy_conf["anchors"][1] + deploy_conf["anchors"][2]
        self.confidence_threshold = self.cfg_mgr.get("confidence_threshold", deploy_conf.get("confidence_threshold", 0.4))
        self.alarm_trigger_hold_ms = self.cfg_mgr.get("alarm_trigger_hold_ms", 0)
        self.speaker_enable = self.cfg_mgr.get("speaker_enable", True)
        self.sound_policy = self.cfg_mgr.get("sound_policy", "speaker")
        self.password_hash = self.cfg_mgr.get("password_hash", "")
        self.password_salt = self.cfg_mgr.get("password_salt", "")
        self.model_name = self.cfg_mgr.get("model_name", KMODEL_NAME)
        self.kmodel_path = KMODEL_DIR + self.model_name
        if not _exists(self.kmodel_path):
            self.model_name = KMODEL_NAME
            self.kmodel_path = KMODEL_DIR + KMODEL_NAME

    def _init_detector(self):
        self.detector = Detector(
            self.kmodel_path, self.labels, self.model_input_size, self.anchors,
            self.model_type, self.confidence_threshold, self.nms_threshold,
            [640, 480], self.pl.get_display_size(), debug_mode=0
        )

    def _init_session(self):
        boot_seq = _load_boot_seq()
        self.run_dir = "DIR%06d" % boot_seq
        ensure_dir(SAVE_BASE + self.run_dir + "/")
        _save_boot_seq(boot_seq + 1)
        self.seq_num = _load_seq(self.run_dir)

    def _play_speaker(self, name):
        if not self.speaker_enable:
            return
        if not _policy_speaker(self.sound_policy):
            return
        paths = {
            "success": AUDIO_DIR + "siren.wav",
            "auth_ok": AUDIO_DIR + "siren.wav",
            "alarm": AUDIO_DIR + "siren.wav",
        }
        p = paths.get(name, "")
        if not p:
            return
        for pp in [p, AUDIO_ALT_DIR + p.split("/")[-1]]:
            try:
                self.speaker.play(pp)
                break
            except:
                pass

    def main_loop(self):
        while self.is_running:
            try:
                self._process_frame()
                time.sleep_ms(10)
            except Exception as e:
                print("main_loop error:", e)
                time.sleep_ms(100)

    def _process_frame(self):
        img = self.pl.get_frame()
        boxes = self.detector.run(img)
        self.detector.draw_result(self.pl.osd_img, boxes)
        self._draw_ui()
        self._update_alarm(boxes)
        self._update_gpio(boxes)
        self._update_inputs()
        self._update_messages()
        self.pl.show_image()
        if self.model_switch_pending_name:
            self._do_model_switch()
        gc.collect()

    def _draw_ui(self):
        l = self.layout
        cbx = l['cfg_box']
        self.pl.osd_img.draw_rectangle(cbx[0], cbx[1], cbx[2], cbx[3], color=(255,127,0), thickness=l['rect_thick'])
        tw = l['font_md'] * 2
        self.pl.osd_img.draw_string_advanced(cbx[0]+(cbx[2]-tw)//2, cbx[1]+(cbx[3]-l['font_md'])//2, l['font_md'], "配置", color=(255,127,0))
        mbx = l['model_box']
        self.pl.osd_img.draw_rectangle(mbx[0], mbx[1], mbx[2], mbx[3], color=(255,127,0), thickness=l['rect_thick'])
        tw2 = l['font_md'] * 2
        self.pl.osd_img.draw_string_advanced(mbx[0]+(mbx[2]-tw2)//2, mbx[1]+(mbx[3]-l['font_md'])//2, l['font_md'], "模型", color=(255,127,0))
        if self.config_open:
            self._draw_config_panel()
        if self.model_open:
            self._draw_model_panel()
        if self.auth_panel_open:
            self._draw_auth_panel()

    def _draw_config_panel(self):
        l = self.layout
        px, py, pw, ph = l['panel']
        self.pl.osd_img.draw_rectangle(px, py, pw, ph, color=(255,127,0), thickness=l['panel_border'])
        self.pl.osd_img.draw_rectangle(px+2, py+2, pw-4, ph-4, color=(0,0,0), thickness=l['inner_fill_thick'], fill=True)
        ptx, pty = l['panel_title_offset']
        self.pl.osd_img.draw_string_advanced(px+ptx, py+pty, l['font_md'], "设置", color=(255,127,0))
        self.pl.osd_img.draw_rectangle(px+pw-160, py+20, 140, l['ctrl_h'], color=(0,191,255), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+pw-160+l['btn_text_offset'][0], py+20+l['btn_text_offset'][1], l['btn_font'], "设置密码", color=(0,191,255))
        self.pl.osd_img.draw_string_advanced(px+20, py+60, l['font_md'], "置信度: %.2f" % self.tmp_conf, color=(0,191,255))
        self.pl.osd_img.draw_string_advanced(px+20, py+130, l['font_md'], "报警持续ms: %d" % self.tmp_hold, color=(0,191,255))
        cw, ch = l['ctrl_w'], l['ctrl_h']
        for rx, ry, txt in [(px+40, py+90, "-"), (px+pw-40-cw, py+90, "+"), (px+40, py+160, "-"), (px+pw-40-cw, py+160, "+")]:
            self.pl.osd_img.draw_rectangle(rx, ry, cw, ch, color=(0,255,127), thickness=l['rect_thick'])
            tw = l['font_md'] * len(txt)
            self.pl.osd_img.draw_string_advanced(rx+(cw-tw)//2, ry+(ch-l['font_md'])//2, l['font_md'], txt, color=(0,255,127))
        sdx, sdy, sdw, sdh = l['btn_save_offset']
        bz_y = min(py+260, py+ph+sdy - ch - 20)
        self.pl.osd_img.draw_string_advanced(px+20, bz_y-40, l['font_md'], "蜂鸣器", color=(255,127,0))
        self.pl.osd_img.draw_rectangle(px+40, bz_y, 140, ch, color=(0,255,127), thickness=l['rect_thick'], fill=self.tmp_buzzer)
        self.pl.osd_img.draw_rectangle(px+200, bz_y, 140, ch, color=(255,0,0), thickness=l['rect_thick'], fill=(not self.tmp_buzzer))
        self.pl.osd_img.draw_string_advanced(px+40+l['btn_text_offset'][0], bz_y+l['btn_text_offset'][1], l['btn_font'], "开启", color=(0,255,127))
        self.pl.osd_img.draw_string_advanced(px+200+l['btn_text_offset'][0], bz_y+l['btn_text_offset'][1], l['btn_font'], "关闭", color=(255,0,0))
        cdx, cdy, cdw, cdh = l['btn_cancel_offset']
        btx, bty = l['btn_text_offset']
        self.pl.osd_img.draw_rectangle(px+sdx, py+ph+sdy, sdw, sdh, color=(0,255,127), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+sdx+btx, py+ph+sdy+bty, l['btn_font'], "保存", color=(0,255,127))
        self.pl.osd_img.draw_rectangle(px+pw+cdx, py+ph+cdy, cdw, cdh, color=(255,0,0), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+pw+cdx+btx, py+ph+cdy+bty, l['btn_font'], "取消", color=(255,0,0))

    def _draw_model_panel(self):
        l = self.layout
        px, py, pw, ph = l['model_panel']
        self.pl.osd_img.draw_rectangle(px, py, pw, ph, color=(255,127,0), thickness=l['panel_border'])
        self.pl.osd_img.draw_rectangle(px+2, py+2, pw-4, ph-4, color=(0,0,0), thickness=l['inner_fill_thick'], fill=True)
        ptx, pty = l['panel_title_offset']
        self.pl.osd_img.draw_string_advanced(px+ptx, py+pty, l['font_md'], "选择模型", color=(255,127,0))
        ch = l['ctrl_h']
        nav_y = py + ph - l['model_nav_offset']
        row_h = ch + l['model_row_gap']
        start_y = py + l['model_list_top']
        max_items = max(1, (nav_y - 10 - start_y) // row_h)
        start_idx = self.model_page * max_items
        end_idx = start_idx + max_items
        for i, name in enumerate(self.model_list[start_idx:end_idx]):
            yy = start_y + i * row_h
            selected = (start_idx + i == self.model_sel_idx_tmp)
            color_sel = (0,255,127) if selected else (128,128,128)
            self.pl.osd_img.draw_rectangle(px+40, yy, pw-80, ch, color=color_sel, thickness=l['rect_thick'])
            self.pl.osd_img.draw_string_advanced(px+52, yy+(ch-l['font_md'])//2, l['font_md'], name, color=color_sel)
        self.pl.osd_img.draw_rectangle(px+40, nav_y, 100, ch, color=(0,191,255), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+60, nav_y+10, l['btn_font'], "上一页", color=(0,191,255))
        self.pl.osd_img.draw_rectangle(px+pw-140, nav_y, 100, ch, color=(0,191,255), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+pw-120, nav_y+10, l['btn_font'], "下一页", color=(0,191,255))
        sdx, sdy, sdw, sdh = l['btn_save_offset']
        cdx, cdy, cdw, cdh = l['btn_cancel_offset']
        btx, bty = l['btn_text_offset']
        self.pl.osd_img.draw_rectangle(px+sdx, py+ph+sdy, sdw, sdh, color=(0,255,127), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+sdx+btx, py+ph+sdy+bty, l['btn_font'], "保存", color=(0,255,127))
        self.pl.osd_img.draw_rectangle(px+pw+cdx, py+ph+cdy, cdw, cdh, color=(255,0,0), thickness=l['rect_thick'])
        self.pl.osd_img.draw_string_advanced(px+pw+cdx+btx, py+ph+cdy+bty, l['btn_font'], "取消", color=(255,0,0))

    def _draw_auth_panel(self):
        l = self.layout
        px, py, pw, ph = l['panel']
        self.pl.osd_img.draw_rectangle(px, py, pw, ph, color=(255,127,0), thickness=l['panel_border'])
        self.pl.osd_img.draw_rectangle(px+2, py+2, pw-4, ph-4, color=(0,0,0), thickness=l['inner_fill_thick'], fill=True)
        title = "授权" if self.auth_mode == "enter" else "设置密码"
        ptx, pty = l['panel_title_offset']
        self.pl.osd_img.draw_string_advanced(px+ptx, py+pty, l['font_md'], title, color=(255,127,0))
        if self.auth_mode == "enter" and (not self.password_hash):
            self.pl.osd_img.draw_rectangle(px+pw-160, py+20, 140, l['ctrl_h'], color=(0,191,255), thickness=l['rect_thick'])
            self.pl.osd_img.draw_string_advanced(px+pw-160+l['btn_text_offset'][0], py+20+l['btn_text_offset'][1], l['btn_font'], "设置密码", color=(0,191,255))
        mask = "*" * len(self.auth_input)
        font_sz = l['font_md']
        safe_margin = 36
        ch2 = l['ctrl_h'] + 8
        gap = 26
        ky_default = py + 120
        ky_max = py + ph - safe_margin - ch2 - 3 * (ch2 + gap)
        ky_calc = min(ky_default, ky_max)
        mask_y_base = py + pty + font_sz + 12
        mask_y = min(mask_y_base, ky_calc - 10 - font_sz)
        self.pl.osd_img.draw_string_advanced(px+20, mask_y, font_sz, mask, color=(0,191,255))
        cw, ch = l['ctrl_w'] + 12, l['ctrl_h'] + 8
        kx = px + 80
        ky = min(ky_default, ky_max)
        nums = ["1","2","3","4","5","6","7","8","9"]
        for i, v in enumerate(nums):
            gx = kx + (i % 3) * (cw + gap)
            gy = ky + (i // 3) * (ch + gap)
            self.pl.osd_img.draw_rectangle(gx, gy, cw, ch, color=(0,255,127), thickness=l['rect_thick'])
            tw = l['btn_font'] * len(v)
            self.pl.osd_img.draw_string_advanced(gx+(cw-tw)//2, gy+(ch-l['btn_font'])//2, l['btn_font'], v, color=(0,255,127))
        self.pl.osd_img.draw_rectangle(kx, ky+3*(ch+gap), cw, ch, color=(255,0,0), thickness=l['rect_thick'])
        tw_del = l['btn_font'] * 2
        self.pl.osd_img.draw_string_advanced(kx+(cw-tw_del)//2, ky+3*(ch+gap)+(ch-l['btn_font'])//2, l['btn_font'], "删除", color=(255,0,0))
        self.pl.osd_img.draw_rectangle(kx+(cw+gap), ky+3*(ch+gap), cw, ch, color=(0,255,127), thickness=l['rect_thick'])
        tw_zero = l['btn_font'] * 1
        self.pl.osd_img.draw_string_advanced(kx+(cw+gap)+(cw-tw_zero)//2, ky+3*(ch+gap)+(ch-l['btn_font'])//2, l['btn_font'], "0", color=(0,255,127))
        self.pl.osd_img.draw_rectangle(kx+2*(cw+gap), ky+3*(ch+gap), cw, ch, color=(0,191,255), thickness=l['rect_thick'])
        tw_ok = l['btn_font'] * 2
        self.pl.osd_img.draw_string_advanced(kx+2*(cw+gap)+(cw-tw_ok)//2, ky+3*(ch+gap)+(ch-l['btn_font'])//2, l['btn_font'], "确认", color=(0,191,255))
        self.pl.osd_img.draw_rectangle(px+pw-40-cw, py+60, cw, ch, color=(255,0,0), thickness=l['rect_thick'])
        tw_cancel = l['btn_font'] * 2
        self.pl.osd_img.draw_string_advanced(px+pw-40-cw+(cw-tw_cancel)//2, py+60+(ch-l['btn_font'])//2, l['btn_font'], "取消", color=(255,0,0))

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
            self._play_speaker("alarm")
        if self.alarm_active:
            now_ms = time.ticks_ms()
            if time.ticks_diff(now_ms, self.alarm_next_ms) >= 0:
                if self.cfg_mgr.get("buzzer_enable", False) and self.buzzer:
                    self.buzzer.on(2000, 50, 0.2)
                self.alarm_remaining -= 1
                if self.alarm_remaining > 0:
                    self.alarm_next_ms = time.ticks_add(now_ms, 500)
                else:
                    self.alarm_active = False

    def _update_gpio(self, boxes):
        self.gpio.set_green(True)
        self.gpio.set_yellow(self.config_open)
        now_red = time.ticks_ms()
        has_target = False
        if boxes:
            for b in boxes:
                if float(b[1]) >= self.confidence_threshold:
                    has_target = True
                    break
        if has_target:
            self.red_on_until_ms = time.ticks_add(now_red, 2000)
        self.gpio.set_red(time.ticks_diff(self.red_on_until_ms, now_red) >= 0)

    def _update_inputs(self):
        now3 = time.ticks_ms()
        inputs = self.gpio.read_inputs()
        for p, raw in inputs.items():
            if raw and (p in self.unstable_inputs):
                self.hold_until_ms[p] = time.ticks_add(now3, self.stretch_ms)
            val = raw or ((p in self.unstable_inputs) and time.ticks_diff(self.hold_until_ms.get(p, 0), now3) >= 0)
            if val:
                if self.in_state_map[p] == 0:
                    self.in_state_map[p] = 1
                    self.in_since_map[p] = now3
                    self.captured_high_map[p] = False
                else:
                    if (not self.captured_high_map[p]) and time.ticks_diff(now3, self.in_since_map[p]) >= self.debounce_ms and time.ticks_diff(now3, self.last_trigger_ms_map[p]) >= self.min_interval_ms:
                        if p == 43:
                            self._do_capture(now3)
                        self.captured_high_map[p] = True
            else:
                self.in_state_map[p] = 0
                self.captured_high_map[p] = False

    def _do_capture(self, now3):
        try:
            rgb_img = self.pl.sensor.snapshot(chn=CAM_CHN_ID_1)
            path, fname = save_photo(rgb_img, self.run_dir, self.seq_num)
            if path:
                self.saved_msg_text = "Saved: %s" % path
                self.saved_msg_until_ms = time.ticks_add(now3, 5000)
                self.seq_num += 1
                _save_seq(self.run_dir, self.seq_num)
                self._play_speaker("success")
                if self.cfg_mgr.get("buzzer_enable", False) and self.buzzer:
                    self.buzzer.on(2000, 50, 0.2)
            else:
                self.saved_msg_text = "Save failed: PIC%06d.jpg" % self.seq_num
                self.saved_msg_until_ms = time.ticks_add(now3, 5000)
            self.last_trigger_ms_map[43] = now3
        except Exception as e:
            print("do_capture error:", e)

    def _update_messages(self):
        now4 = time.ticks_ms()
        if self.saving_busy:
            bottom_y = 480 - self.layout['font_lg'] - 6
            self.pl.osd_img.draw_string_advanced(20, bottom_y, self.layout['font_lg'], "保存中……", color=(255,127,0))
        elif self.saved_msg_until_ms:
            if time.ticks_diff(now4, self.saved_msg_until_ms) >= 0:
                self.saved_msg_until_ms = 0
            elif not self.config_open:
                bottom_y = 480 - self.layout['font_lg'] - 6
                self.pl.osd_img.draw_string_advanced(20, bottom_y, self.layout['font_lg'], self.saved_msg_text, color=(255, 0, 0))

    def _do_model_switch(self):
        try:
            new_name = self.model_switch_pending_name
            new_path = KMODEL_DIR + new_name
            self.detector.switch_model(new_path, new_name, self.cfg_mgr.conf)
            self.model_name = new_name
            self.kmodel_path = new_path
            self.saved_msg_text = "模型: %s" % new_name
            self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)
        except Exception as e:
            print("model switch error:", e)
        self.saving_busy = False
        self.model_switch_pending_name = None

    def on_touch(self, x, y):
        if self.saving_busy:
            return
        l = self.layout
        def in_rect(rx, ry, rw, rh):
            return x >= rx and x <= rx+rw and y >= ry and y <= ry+rh
        if (not self.config_open) and (not self.model_open) and in_rect(*l['model_box']):
            if time.ticks_diff(self.auth_locked_until_ms, time.ticks_ms()) >= 0:
                self.saved_msg_text = "授权锁定"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)
            else:
                self._open_auth("model")
        elif not self.config_open and in_rect(*l['cfg_box']):
            if time.ticks_diff(self.auth_locked_until_ms, time.ticks_ms()) >= 0:
                self.saved_msg_text = "授权锁定"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)
            else:
                self._open_auth("config")
        elif self.config_open:
            self._handle_config_touch(x, y, in_rect)
        elif self.auth_panel_open:
            self._handle_auth_touch(x, y, in_rect)
        elif self.model_open:
            self._handle_model_touch(x, y, in_rect)

    def _open_auth(self, target):
        self.auth_panel_open = True
        self.auth_target = target
        self.auth_mode = "enter"
        self.auth_input = ""
        self.auth_suppress_until_ms = time.ticks_add(time.ticks_ms(), 150)

    def _handle_config_touch(self, x, y, in_rect):
        l = self.layout
        px, py, pw, ph = l['panel']
        cw, ch = l['ctrl_w'], l['ctrl_h']
        c_minus = (px+40, py+90, cw, ch)
        c_plus  = (px+pw-40-cw, py+90, cw, ch)
        h_minus = (px+40, py+160, cw, ch)
        h_plus  = (px+pw-40-cw, py+160, cw, ch)
        sdx, sdy, sdw, sdh = l['btn_save_offset']
        bz_y = min(py+260, py+ph+sdy - ch - 20)
        on_rect = (px+40, bz_y, 140, ch)
        off_rect = (px+200, bz_y, 140, ch)
        cdx, cdy, cdw, cdh = l['btn_cancel_offset']
        save_box = (px+sdx, py+ph+sdy, sdw, sdh)
        cancel_box = (px+pw+cdx, py+ph+cdy, cdw, cdh)
        set_pwd_box = (px+pw-160, py+20, 140, ch)
        if in_rect(*c_minus):
            self.tmp_conf = max(0.0, round(self.tmp_conf - 0.05, 2))
        elif in_rect(*c_plus):
            self.tmp_conf = min(1.0, round(self.tmp_conf + 0.05, 2))
        elif in_rect(*h_minus):
            self.tmp_hold = max(0, self.tmp_hold - 10)
        elif in_rect(*h_plus):
            self.tmp_hold = min(10000, self.tmp_hold + 10)
        elif in_rect(*on_rect):
            self.tmp_buzzer = True
        elif in_rect(*off_rect):
            self.tmp_buzzer = False
        elif in_rect(*set_pwd_box):
            if time.ticks_diff(self.auth_locked_until_ms, time.ticks_ms()) >= 0:
                self.saved_msg_text = "授权锁定"
                self.saved_msg_until_ms = time.ticks_add(time.ticks_ms(), 3000)
            else:
                self._open_auth("config")
                self.auth_mode = "set"
        elif in_rect(*save_box):
            self.confidence_threshold = float(self.tmp_conf)
            self.alarm_trigger_hold_ms = int(self.tmp_hold)
            self.cfg_mgr.set("buzzer_enable", self.tmp_buzzer)
            self.cfg_mgr.set("confidence_threshold", self.confidence_threshold)
            self.cfg_mgr.set("alarm_trigger_hold_ms", self.alarm_trigger_hold_ms)
            self.config_open = False
            self.detector.confidence_threshold = self.confidence_threshold
        elif in_rect(*cancel_box):
            self.config_open = False

    def _handle_auth_touch(self, x, y, in_rect):
        l = self.layout
        px, py, pw, ph = l['panel']
        cw, ch = l['ctrl_w'] + 12, l['ctrl_h'] + 8
        gap = 26
        kx = px + 80
        safe_margin = 36
        ky_default = py + 120
        ky_max = py + ph - safe_margin - ch - 3 * (ch + gap)
        ky = min(ky_default, ky_max)
        set_box3 = (px + pw - 160, py + 20, 140, ch)
        grid = []
        nums = ["1","2","3","4","5","6","7","8","9"]
        for i, v in enumerate(nums):
            gx = kx + (i % 3) * (cw + gap)
            gy = ky + (i // 3) * (ch + gap)
            grid.append(((gx, gy, cw, ch), v))
        zero_box = (kx + (cw + gap), ky + 3 * (ch + gap), cw, ch)
        del_box = (kx, ky + 3 * (ch + gap), cw, ch)
        ok_box = (kx + 2 * (cw + gap), ky + 3 * (ch + gap), cw, ch)
        cancel_box2 = (px + pw - 40 - cw, py + 60, cw, ch)
        handled = False
        if time.ticks_diff(self.auth_suppress_until_ms, time.ticks_ms()) >= 0:
            handled = True
        if (self.auth_mode == "enter") and (not self.password_hash) and in_rect(*set_box3):
            self.auth_mode = "set"
            self.auth_input = ""
            handled = True
        for rect, v in grid:
            if in_rect(*rect):
                if len(self.auth_input) < 12:
                    self.auth_input += v
                    handled = True
                    break
        if not handled and in_rect(*zero_box):
            if len(self.auth_input) < 12:
                self.auth_input += "0"
                handled = True
        if not handled and in_rect(*del_box):
            self.auth_input = self.auth_input[:-1]
            handled = True
        if not handled and in_rect(*cancel_box2):
            self.auth_panel_open = False
            handled = True
        if not handled and in_rect(*ok_box):
            nowx = time.ticks_ms()
            if self.auth_mode == "enter":
                if not self.password_hash:
                    self.auth_mode = "set"
                    self.auth_input = ""
                    self.saved_msg_text = "请设置密码"
                    self.saved_msg_until_ms = time.ticks_add(nowx, 2000)
                else:
                    hh = _hash_pwd(self.auth_input, self.password_salt or "")
                    if hh == self.password_hash:
                        self.auth_fail_count = 0
                        self.saved_msg_text = "授权成功"
                        self.saved_msg_until_ms = time.ticks_add(nowx, 2000)
                        self._play_speaker("auth_ok")
                        self.auth_panel_open = False
                        if self.auth_target == "model":
                            self.model_list = sorted(_list_kmodels(KMODEL_DIR), reverse=True)
                            self.model_page = 0
                            if self.model_list:
                                try:
                                    self.model_sel_idx_tmp = self.model_list.index(self.model_name)
                                except ValueError:
                                    self.model_sel_idx_tmp = 0
                            else:
                                self.model_sel_idx_tmp = -1
                            self.model_open = True
                        elif self.auth_target == "config":
                            self.config_open = True
                            self.tmp_conf = float(self.confidence_threshold)
                            self.tmp_hold = int(self.alarm_trigger_hold_ms)
                            self.tmp_buzzer = bool(self.cfg_mgr.get("buzzer_enable", False))
                    else:
                        self.auth_fail_count += 1
                        if self.auth_fail_count >= 5:
                            self.auth_locked_until_ms = time.ticks_add(nowx, 300000)
                            self.saved_msg_text = "授权锁定"
                            self.saved_msg_until_ms = time.ticks_add(nowx, 3000)
                            self.auth_panel_open = False
                        else:
                            self.saved_msg_text = "密码错误"
                            self.saved_msg_until_ms = time.ticks_add(nowx, 2000)
            elif self.auth_mode == "set":
                if self.auth_input:
                    salt = str(time.ticks_ms())
                    hh = _hash_pwd(self.auth_input, salt)
                    self.password_salt = salt
                    self.password_hash = hh
                    self.cfg_mgr.set("password_salt", salt)
                    self.cfg_mgr.set("password_hash", hh)
                    self.saved_msg_text = "密码已设置"
                    self.saved_msg_until_ms = time.ticks_add(nowx, 2000)
                    self.auth_panel_open = False

    def _handle_model_touch(self, x, y, in_rect):
        l = self.layout
        px, py, pw, ph = l['model_panel']
        ch = l['ctrl_h']
        sdx, sdy, sdw, sdh = l['btn_save_offset']
        cdx, cdy, cdw, cdh = l['btn_cancel_offset']
        save_box = (px+sdx, py+ph+sdy, sdw, sdh)
        cancel_box = (px+pw+cdx, py+ph+cdy, cdw, cdh)
        nav_y = py + ph - l['model_nav_offset']
        row_h = ch + l['model_row_gap']
        start_y = py + l['model_list_top']
        max_items = max(1, (nav_y - 10 - start_y) // row_h)
        start_idx = self.model_page * max_items
        end_idx = start_idx + max_items
        for i, name in enumerate(self.model_list[start_idx:end_idx]):
            yy = start_y + i * row_h
            rect = (px+40, yy, pw-80, ch)
            if in_rect(*rect):
                self.model_sel_idx_tmp = start_idx + i
        prev_rect = (px+40, nav_y, 100, ch)
        next_rect = (px+pw-140, nav_y, 100, ch)
        if in_rect(*prev_rect):
            if self.model_page > 0:
                self.model_page -= 1
        elif in_rect(*next_rect):
            total_pages = (len(self.model_list) + max_items - 1) // max_items
            if self.model_page + 1 < total_pages:
                self.model_page += 1
        elif in_rect(*save_box):
            if self.model_sel_idx_tmp >= 0 and self.model_sel_idx_tmp < len(self.model_list):
                self.model_switch_pending_name = self.model_list[self.model_sel_idx_tmp]
                self.saving_busy = True
            self.model_open = False
        elif in_rect(*cancel_box):
            self.model_open = False

    def deinitialize(self):
        self.is_running = False
        time.sleep_ms(200)
        if self.detector:
            self.detector.deinit()
            self.detector = None
        if self.gpio:
            self.gpio.reset_outputs()
            self.gpio = None
        self.buzzer = None
        self.speaker = None
        gc.collect()
