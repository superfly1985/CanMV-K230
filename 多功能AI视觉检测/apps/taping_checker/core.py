import gc
import os
import time
import json
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
try:
    from ybUtils.YbBuzzer import YbBuzzer
except:
    YbBuzzer = None
import image

CFG_PATH = "/sdcard/configs/taping_checker.json"
DEPLOY_CFG_PATH = "/sdcard/configs/deploy_config_taping.json"
SAVE_BASE = "/data/snapshot/taping_checker/"
AUDIO_DIR = "/sdcard/audio/"

BBOX_PRESET_COLORS = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 127, 255),
    (0, 0, 255),
    (255, 255, 0),
    (255, 0, 255),
    (255, 255, 255),
    (128, 128, 128),
]

BBOX_PRESET_COLORS_RGB565 = []
for _r, _g, _b in BBOX_PRESET_COLORS:
    _rgb565 = ((_r >> 3) << 11) | ((_g >> 2) << 5) | (_b >> 3)
    BBOX_PRESET_COLORS_RGB565.append((_rgb565 & 0xFF, (_rgb565 >> 8) & 0xFF))


try:
    from media.media import MediaManager
except Exception as _e:
    MediaManager = None

try:
    from media.pyaudio import PyAudio, paInt16
except Exception as _e:
    PyAudio = None
    paInt16 = None

try:
    import media.wave as wave
except Exception as _e:
    wave = None

try:
    from ybUtils.YbSpeaker import YbSpeaker
except Exception as _e:
    YbSpeaker = None


class Speaker:
    def __init__(self):
        self.stream = None
        self.p = None
        self.wf = None
        self.spk = None
        self._playing = False
        self._init_speaker()

    def _init_speaker(self):
        if YbSpeaker is not None:
            try:
                self.spk = YbSpeaker()
            except Exception as e:
                self.spk = None
        else:
            self.spk = None

    def play(self, filepath):
        if PyAudio is None or wave is None:
            return False

        try:
            # 初始化媒体管理器（如果未初始化过）
            if MediaManager is not None:
                try:
                    MediaManager.init()
                except Exception as e:
                    pass

            # 打开WAV文件
            self.wf = wave.open(filepath, 'rb')

            # 启用扬声器
            if self.spk is not None:
                try:
                    self.spk.enable()
                except Exception as e:
                    pass

            # 计算chunk大小
            CHUNK = int(self.wf.get_framerate() / 25)

            # 创建PyAudio实例
            self.p = PyAudio()

            # 初始化PyAudio对象
            try:
                self.p.initialize(CHUNK)
            except Exception as e:
                pass

            # 打开音频输出流
            self.stream = self.p.open(
                format=self.p.get_format_from_width(self.wf.get_sampwidth()),
                channels=self.wf.get_channels(),
                rate=self.wf.get_framerate(),
                output=True,
                frames_per_buffer=CHUNK
            )

            # 设置音量
            try:
                self.stream.volume(vol=100)
            except Exception as e:
                pass

            # 播放音频
            self._playing = True
            data = self.wf.read_frames(CHUNK)
            while data and self._playing:
                self.stream.write(data)
                data = self.wf.read_frames(CHUNK)

            # 播放结束后自动释放资源
            self.stop()

            return True
        except Exception as e:
            self.stop()
            return False

    def stop(self):
        self._playing = False
        if self.stream:
            try:
                self.stream.stop_stream()
            except Exception as e:
                pass
            try:
                self.stream.close()
            except Exception as e:
                pass
            self.stream = None
        if self.p:
            try:
                self.p.terminate()
            except Exception as e:
                pass
            self.p = None
        if self.wf:
            try:
                self.wf.close()
            except Exception as e:
                pass
            self.wf = None
        if self.spk:
            try:
                self.spk.disable()
            except Exception as e:
                pass

    def deinit(self):
        self.stop()


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
        return sorted([name for name in os.listdir(directory) if name.endswith(".kmodel")], reverse=True)
    except Exception:
        return []


def _scan_model_dirs(base="/sdcard/"):
    result = ["/sdcard/"]
    try:
        entries = os.listdir(base)
        for e in entries:
            if e.startswith('.'):
                continue
            full = base + e + "/"
            try:
                os.stat(full)
                has_kmodel = False
                try:
                    for f in os.listdir(full):
                        if f.endswith(".kmodel"):
                            has_kmodel = True
                            break
                except:
                    pass
                if has_kmodel:
                    result.append(full)
                try:
                    sub_entries = os.listdir(full)
                    for se in sub_entries:
                        if se.startswith('.'):
                            continue
                        sub_full = full + se + "/"
                        try:
                            os.stat(sub_full)
                            try:
                                for f in os.listdir(sub_full):
                                    if f.endswith(".kmodel"):
                                        result.append(sub_full)
                                        break
                            except:
                                pass
                        except:
                            pass
                except:
                    pass
            except:
                pass
    except:
        pass
    seen = set()
    unique = []
    for d in result:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


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
            boxes = aicube.anchorbasedet_post_process(outs[0], outs[1], outs[2], self.model_input_size, self.rgb888p_size, self.strides, len(self.labels), self.confidence_threshold, self.nms_threshold, self.anchors, True)
        else:
            boxes = []
        return boxes

    def draw_result(self, osd_img, boxes, bbox_colors=None):
        if not boxes:
            return
        scale_x = self.display_size[0] / self.rgb888p_size[0]
        scale_y = self.display_size[1] / self.rgb888p_size[1]
        for b in boxes:
            score = float(b[1])
            if score < self.confidence_threshold:
                continue
            x1, y1, x2, y2 = int(b[2]), int(b[3]), int(b[4]), int(b[5])
            x = int(x1 * scale_x)
            y = int(y1 * scale_y)
            w = int((x2 - x1) * scale_x)
            h = int((y2 - y1) * scale_y)
            cat_id = int(b[0]) if len(b) > 6 else 0
            if bbox_colors and cat_id < len(bbox_colors):
                color = tuple(bbox_colors[cat_id])
            else:
                color = (255, 0, 0)
            osd_img.draw_rectangle(x, y, w, h, color=color, thickness=2)
            label_text = "%.2f" % score
            if cat_id < len(self.labels):
                label_text = self.labels[cat_id] + " " + label_text
            osd_img.draw_string_advanced(x, y - 20, 20, label_text, color=color)

    def switch_model(self, new_path, new_name, cfg_mgr):
        self.kpu.load_kmodel(new_path)
        try:
            self.det_app.deinit()
        except:
            pass
        from libs.PlatTasks import DetectionApp
        self.det_app = DetectionApp("video", new_path, self.labels, self.model_input_size, self.anchors, self.model_type, self.confidence_threshold, self.nms_threshold, self.rgb888p_size, self.display_size, debug_mode=self.debug_mode)
        self.det_app.config_preprocess()
        self.kmodel_path = new_path
        cfg_mgr.set("model_name", new_name)

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
    LAMP_PINS = {'yellow': 33, 'red': 42}
    INPUT_PINS = [34, 35]

    def __init__(self):
        self.pin_out_map = {}
        self.pin_in_map = {}
        self._configure_outputs()
        self._configure_inputs()

    def _configure_outputs(self):
        self.pin_out_map = {}
        if machine:
            for name, p in self.LAMP_PINS.items():
                try:
                    self.pin_out_map[name] = machine.Pin(p, machine.Pin.OUT)
                except:
                    self.pin_out_map[name] = None

    def _configure_inputs(self):
        self.pin_in_map = {}
        if machine:
            for p in self.INPUT_PINS:
                try:
                    self.pin_in_map[p] = machine.Pin(p, machine.Pin.IN, machine.Pin.PULL_UP)
                except:
                    try:
                        self.pin_in_map[p] = machine.Pin(p, machine.Pin.IN)
                    except:
                        self.pin_in_map[p] = None

    def reset_outputs(self):
        for name in self.LAMP_PINS:
            inst = self.pin_out_map.get(name)
            if inst:
                inst.value(0)

    def set_yellow(self, on):
        inst = self.pin_out_map.get('yellow')
        if inst:
            inst.value(1 if on else 0)

    def set_red(self, on):
        inst = self.pin_out_map.get('red')
        if inst:
            inst.value(1 if on else 0)

    def read_inputs(self):
        result = {}
        for p in self.INPUT_PINS:
            inst = self.pin_in_map.get(p)
            result[p] = inst.value() if inst else 1
        return result


class ConfigManager:
    DEFAULTS = {
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
            [255, 255, 0],
        ],
    }

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
        for k, v in self.DEFAULTS.items():
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
