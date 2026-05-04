import gc
import os
import time
import json
from ybUtils.YbBuzzer import YbBuzzer
import aicube
import nncase_runtime as nn
import ulab.numpy as np
try:
    import ustruct as struct
except:
    import struct
try:
    import machine
except:
    machine = None
import image

KMODEL_DIR = "/sdcard/kmodel/taping_checker/"
KMODEL_NAME = "bset_no_taping_v2.kmodel"
CFG_PATH = "/sdcard/configs/taping_checker.json"
SAVE_BASE = "/data/snapshot/taping_checker/"
AUDIO_DIR = "/sdcard/audio/"
AUDIO_ALT_DIR = "audio_siren/"

def _policy_buzzer(policy):
    return policy in ("buzzer", "both", "seq")

def _policy_speaker(policy):
    return policy in ("speaker", "both", "seq")

class Speaker:
    def __init__(self, conf=None):
        self.conf = conf or {}
        self.i2s = None
        self.audio_mod = None
        try:
            import audio
            try:
                self.audio_mod = audio.AudioModule(0, 16000)
            except:
                self.audio_mod = None
        except:
            self.audio_mod = None
        if self.audio_mod is None:
            try:
                import machine
                i2s_id = int(self.conf.get("i2s_id", 0))
                pins = self.conf.get("i2s_pins", {})
                sck = pins.get("sck", None)
                ws = pins.get("ws", None)
                sd = pins.get("sd", None)
                if sck is not None and ws is not None and sd is not None:
                    self.i2s = machine.I2S(i2s_id, mode=machine.I2S.TX, bits=16, format=machine.I2S.MONO, rate=16000, sck=machine.Pin(sck), ws=machine.Pin(ws), sd=machine.Pin(sd))
            except:
                self.i2s = None

    def _wav_info(self, f):
        f.seek(0)
        if f.read(4) != b"RIFF":
            return None
        _ = f.read(4)
        if f.read(4) != b"WAVE":
            return None
        if f.read(4) != b"fmt ":
            return None
        fmt_size = struct.unpack("<I", f.read(4))[0]
        fmt = f.read(fmt_size)
        if len(fmt) < 16:
            return None
        audio_fmt, channels, sample_rate, byte_rate, block_align, bits = struct.unpack("<HHIIHH", fmt[:16])
        if f.read(4) != b"data":
            return None
        data_size = struct.unpack("<I", f.read(4))[0]
        data_offset = f.tell()
        return {"fmt": audio_fmt, "channels": channels, "rate": sample_rate, "bits": bits, "data_size": data_size, "data_offset": data_offset}

    def play(self, path):
        try:
            with open(path, "rb") as f:
                info = self._wav_info(f)
                if not info:
                    return
                if self.audio_mod:
                    try:
                        self.audio_mod.play_wav_file(path)
                        return
                    except:
                        pass
                if not self.i2s:
                    return
                if info["bits"] != 16 or info["channels"] != 1:
                    return
                try:
                    import machine
                    self.i2s = machine.I2S(self.i2s.id if hasattr(self.i2s, "id") else 0, mode=machine.I2S.TX, bits=16, format=machine.I2S.MONO, rate=int(info["rate"]), sck=self.i2s.sck if hasattr(self.i2s, "sck") else None, ws=self.i2s.ws if hasattr(self.i2s, "ws") else None, sd=self.i2s.sd if hasattr(self.i2s, "sd") else None)
                except:
                    pass
                f.seek(info["data_offset"])
                bufsize = 4096
                while bufsize > 0:
                    b = f.read(bufsize)
                    if not b:
                        break
                    try:
                        self.i2s.write(b)
                    except:
                        break
        except:
            pass

def ensure_dir(directory):
    if not directory or directory == '/':
        return
    directory = directory.rstrip('/')
    try:
        os.stat(directory)
        return
    except OSError:
        if '/' in directory:
            parent = directory[:directory.rindex('/')]
            if parent and parent != directory:
                ensure_dir(parent)
        try:
            os.mkdir(directory)
        except OSError:
            try:
                os.stat(directory)
            except:
                pass

def save_photo(img, run_dir, seq_num):
    fname = "PIC%06d.jpg" % seq_num
    bases = ["/data/snapshot/", "/sdcard/snapshot/"]
    for base in bases:
        try:
            ensure_dir(base + run_dir + "/")
            path = base + run_dir + "/" + fname
            if not img:
                continue
            try:
                img.save(path)
            except Exception:
                try:
                    if hasattr(img, "compress"):
                        buf = img.compress(quality=85)
                        with open(path, "wb") as f:
                            f.write(buf)
                    else:
                        raise
                except Exception:
                    try:
                        bmp_path = base + run_dir + ("/PIC%06d.bmp" % seq_num)
                        img.save(bmp_path)
                        path = bmp_path
                    except Exception:
                        continue
            try:
                os.stat(path)
                return path, fname
            except OSError:
                continue
        except Exception:
            continue
    return None, fname

def _load_boot_seq():
    try:
        with open(SAVE_BASE + "boot_seq.txt", "r") as f:
            n = int(f.read().strip())
            if n >= 1:
                return n
    except Exception:
        pass
    return 1

def _save_boot_seq(n):
    try:
        with open(SAVE_BASE + "boot_seq.txt", "w") as f:
            f.write(str(int(n)))
    except Exception:
        pass

def _load_seq(dd):
    try:
        with open(SAVE_BASE + dd + "/seq.txt", "r") as f:
            n = int(f.read().strip())
            if n >= 1:
                return n
    except Exception:
        pass
    return 1

def _save_seq(dd, n):
    try:
        with open(SAVE_BASE + dd + "/seq.txt", "w") as f:
            f.write(str(int(n)))
    except Exception:
        pass

def _list_kmodels(directory):
    try:
        return [name for name in os.listdir(directory) if name.endswith(".kmodel")]
    except Exception:
        return []

def _hash_pwd(s, salt):
    h = 2166136261
    for c in (salt + s):
        h ^= ord(c)
        h = (h * 16777619) & 0xffffffff
    return "%08x" % h

def _exists(p):
    try:
        os.stat(p)
        return True
    except OSError:
        return False

def _pad_param(input_size, output_size):
    rw = output_size[0] / input_size[0]
    rh = output_size[1] / input_size[1]
    r = rw if rw < rh else rh
    nw = int(r * input_size[0])
    nh = int(r * input_size[1])
    dw = (output_size[0] - nw) / 2
    dh = (output_size[1] - nh) / 2
    top = int(round(dh - 0.1))
    bottom = int(round(dh + 0.1))
    left = int(round(dw - 0.1))
    right = int(round(dw + 0.1))
    return top, bottom, left, right

class Detector:
    def __init__(self, kmodel_path, labels, model_input_size, anchors, model_type, confidence_threshold, nms_threshold, rgb888p_size, display_size, debug_mode=0):
        self.kmodel_path = kmodel_path
        self.labels = labels
        self.model_input_size = model_input_size
        self.anchors = anchors
        self.model_type = model_type
        self.confidence_threshold = confidence_threshold
        self.nms_threshold = nms_threshold
        self.rgb888p_size = rgb888p_size
        self.display_size = display_size
        self.debug_mode = debug_mode
        self.strides = [8, 16, 32]
        self.kpu = nn.kpu()
        self.kpu.load_kmodel(kmodel_path)
        self.ai2d = nn.ai2d()
        self.ai2d.set_dtype(nn.ai2d_format.NCHW_FMT, nn.ai2d_format.NCHW_FMT, np.uint8, np.uint8)
        top, bottom, left, right = _pad_param(rgb888p_size, model_input_size)
        self.ai2d.set_pad_param(True, [0, 0, 0, 0, top, bottom, left, right], 0, [114, 114, 114])
        self.ai2d.set_resize_param(True, nn.interp_method.tf_bilinear, nn.interp_mode.half_pixel)
        self.ai2d_builder = self.ai2d.build([1, 3, rgb888p_size[1], rgb888p_size[0]], [1, 3, model_input_size[1], model_input_size[0]])
        data = np.ones((1, 3, model_input_size[1], model_input_size[0]), dtype=np.uint8)
        self.ai2d_output_tensor = nn.from_numpy(data)
        from libs.PlatTasks import DetectionApp
        self.det_app = DetectionApp("video", kmodel_path, labels, model_input_size, anchors, model_type, confidence_threshold, nms_threshold, rgb888p_size, display_size, debug_mode=debug_mode)
        self.det_app.config_preprocess()

    def run(self, img):
        if hasattr(img, "to_numpy_ref"):
            frame = img.to_numpy_ref()
        else:
            frame = img
        if hasattr(frame, "shape"):
            in_tensor = nn.from_numpy(frame)
            self.ai2d_builder.run(in_tensor, self.ai2d_output_tensor)
            self.kpu.set_input_tensor(0, self.ai2d_output_tensor)
            self.kpu.run()
            outs = []
            for i in range(self.kpu.outputs_size()):
                od = self.kpu.get_output_tensor(i)
                arr = od.to_numpy()
                try:
                    s = arr.shape
                    t = 1
                    for d in s:
                        t *= d
                    arr = arr.reshape((t))
                except:
                    pass
                outs.append(arr)
            boxes = aicube.anchorbasedet_post_process(outs[0], outs[1], outs[2], self.model_input_size, self.rgb888p_size, self.strides, len(self.labels), self.confidence_threshold, self.nms_threshold, self.anchors, False)
        else:
            boxes = []
        return boxes

    def draw_result(self, osd_img, boxes):
        if boxes:
            for b in boxes:
                score = float(b[1])
                if score >= self.confidence_threshold:
                    x, y, w, h = int(b[2]), int(b[3]), int(b[4]), int(b[5])
                    osd_img.draw_rectangle(x, y, w, h, color=(255, 0, 0), thickness=2)
                    osd_img.draw_string_advanced(x, y - 20, 20, "%.2f" % score, color=(255, 0, 0))

    def switch_model(self, new_path, new_name, user_conf):
        self.kpu.load_kmodel(new_path)
        self.det_app.deinit()
        from libs.PlatTasks import DetectionApp
        self.det_app = DetectionApp("video", new_path, self.labels, self.model_input_size, self.anchors, self.model_type, self.confidence_threshold, self.nms_threshold, self.rgb888p_size, self.display_size, debug_mode=self.debug_mode)
        self.det_app.config_preprocess()
        self.kmodel_path = new_path
        user_conf["model_name"] = new_name
        with open(CFG_PATH, "w") as f:
            f.write(json.dumps(user_conf))

    def deinit(self):
        try:
            self.det_app.deinit()
        except:
            pass
        try:
            del self.kpu
        except:
            pass
        gc.collect()

class GPIOController:
    def __init__(self):
        self.output_active_high = True
        self.lamp_pins = {'green': 32, 'yellow': 33, 'red': 42}
        self.input_pins = [26, 34, 35, 43]
        self.pin_out_map = {}
        self.pin_in_map = {}
        self.configure_outputs()
        self.configure_inputs()

    def _active_level(self):
        return 1 if self.output_active_high else 0

    def _inactive_level(self):
        return 0 if self.output_active_high else 1

    def configure_outputs(self):
        self.pin_out_map = {}
        if machine:
            for name, p in self.lamp_pins.items():
                inst = None
                try:
                    inst = machine.Pin(p, machine.Pin.OUT)
                except:
                    inst = None
                self.pin_out_map[name] = inst

    def configure_inputs(self):
        self.pin_in_map = {}
        if machine:
            for p in self.input_pins:
                inst = None
                try:
                    inst = machine.Pin(p, machine.Pin.IN, machine.Pin.PULL_DOWN)
                except:
                    try:
                        inst = machine.Pin(p, machine.Pin.IN)
                    except:
                        inst = None
                self.pin_in_map[p] = inst

    def reset_outputs(self):
        for name in ('green', 'yellow', 'red'):
            inst = self.pin_out_map.get(name)
            if inst:
                inst.value(self._inactive_level())

    def set_green(self, on):
        inst = self.pin_out_map.get('green')
        if inst:
            inst.value(self._active_level() if on else self._inactive_level())

    def set_yellow(self, on):
        inst = self.pin_out_map.get('yellow')
        if inst:
            inst.value(self._active_level() if on else self._inactive_level())

    def set_red(self, on):
        inst = self.pin_out_map.get('red')
        if inst:
            inst.value(self._active_level() if on else self._inactive_level())

    def read_inputs(self):
        result = {}
        for p in self.input_pins:
            inst = self.pin_in_map.get(p)
            result[p] = inst.value() if inst else 0
        return result

class ConfigManager:
    def __init__(self):
        self.conf = self._load()
        self._ensure_defaults()

    def _load(self):
        try:
            with open(CFG_PATH, "r") as f:
                return json.loads(f.read())
        except:
            return {}

    def _ensure_defaults(self):
        changed = False
        defaults = {
            "speaker_enable": True,
            "sound_policy": "speaker",
            "buzzer_enable": False,
            "password_hash": "",
            "password_salt": "",
            "model_name": KMODEL_NAME,
            "confidence_threshold": 0.4,
            "alarm_trigger_hold_ms": 0,
        }
        for k, v in defaults.items():
            if k not in self.conf:
                self.conf[k] = v
                changed = True
        if changed:
            self.save()

    def save(self):
        try:
            with open(CFG_PATH, "w") as f:
                f.write(json.dumps(self.conf))
        except:
            pass

    def get(self, key, default=None):
        return self.conf.get(key, default)

    def set(self, key, value):
        self.conf[key] = value
        self.save()
