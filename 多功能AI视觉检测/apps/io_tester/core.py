try:
    import machine
except:
    machine = None

try:
    import time
except:
    time = None

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

LOG_FILE = "/sdcard/audio_debug.log"

def _log(msg):
    try:
        t = time.ticks_ms() if time else 0
        line = "[{:08d}] {}\n".format(t, msg)
        with open(LOG_FILE, "a") as f:
            f.write(line)
    except Exception as e:
        pass

_log("=== audio module loading start ===")

try:
    from media.media import MediaManager
    _log("import MediaManager SUCCESS")
except Exception as _e:
    _log("import MediaManager failed: " + str(_e))
    MediaManager = None

try:
    from media.pyaudio import PyAudio, paInt16
    _log("import PyAudio SUCCESS")
except Exception as _e:
    _log("import PyAudio failed: " + str(_e))
    PyAudio = None
    paInt16 = None

try:
    import media.wave as wave
    _log("import wave SUCCESS")
except Exception as _e:
    _log("import wave failed: " + str(_e))
    wave = None

try:
    from ybUtils.YbSpeaker import YbSpeaker
    _log("import YbSpeaker SUCCESS")
except Exception as _e:
    _log("import YbSpeaker failed: " + str(_e))
    YbSpeaker = None

_log("=== audio module loading end ===")

OUTPUT_PINS = {
    "IO42": 42,
    "IO33": 33,
}

INPUT_PINS = {
    "IO34": 34,
    "IO35": 35,
}

AUDIO_DIR = "/sdcard/audio/"


class GPIOController:
    def __init__(self):
        self.out_map = {}
        self.in_map = {}
        self.out_state = {}
        self._init_outputs()
        self._init_inputs()

    def _init_outputs(self):
        if not machine:
            return
        for name, pin_num in OUTPUT_PINS.items():
            try:
                p = machine.Pin(pin_num, machine.Pin.OUT)
                p.value(0)
                self.out_map[name] = p
                self.out_state[name] = False
            except Exception as e:
                print("init output", name, e)
                self.out_map[name] = None
                self.out_state[name] = None

    def _init_inputs(self):
        if not machine:
            return
        for name, pin_num in INPUT_PINS.items():
            try:
                p = machine.Pin(pin_num, machine.Pin.IN, machine.Pin.PULL_DOWN)
                self.in_map[name] = p
            except Exception:
                try:
                    p = machine.Pin(pin_num, machine.Pin.IN)
                    self.in_map[name] = p
                except Exception as e:
                    print("init input", name, e)
                    self.in_map[name] = None

    def toggle_output(self, name):
        p = self.out_map.get(name)
        if p is None:
            return None
        current = self.out_state.get(name, False)
        new_state = not current
        try:
            p.value(1 if new_state else 0)
            self.out_state[name] = new_state
            return new_state
        except Exception as e:
            print("toggle", name, e)
            return None

    def read_input(self, name):
        p = self.in_map.get(name)
        if p is None:
            return None
        try:
            return p.value()
        except Exception:
            return None

    def read_all_inputs(self):
        result = {}
        for name in INPUT_PINS:
            result[name] = self.read_input(name)
        return result

    def reset_outputs(self):
        for name in OUTPUT_PINS:
            p = self.out_map.get(name)
            if p:
                try:
                    p.value(0)
                    self.out_state[name] = False
                except:
                    pass


class SpeakerController:
    def __init__(self):
        self.stream = None
        self.p = None
        self.wf = None
        self.spk = None
        self._playing = False
        _log("SpeakerController __init__")
        self._init_speaker()

    def _init_speaker(self):
        _log("_init_speaker start")
        _log("YbSpeaker is None: " + str(YbSpeaker is None))
        if YbSpeaker is not None:
            try:
                _log("Creating YbSpeaker instance...")
                self.spk = YbSpeaker()
                _log("YbSpeaker initialized SUCCESS")
            except Exception as e:
                _log("init YbSpeaker FAILED: " + str(e))
                self.spk = None
        else:
            _log("YbSpeaker not available, skip")

    def play_wav(self, filename):
        _log("play_wav called, filename: " + str(filename))
        _log("PyAudio is None: " + str(PyAudio is None))
        _log("wave is None: " + str(wave is None))
        _log("MediaManager is None: " + str(MediaManager is None))
        _log("YbSpeaker is None: " + str(YbSpeaker is None))
        _log("self.spk is None: " + str(self.spk is None))

        if PyAudio is None:
            _log("ERROR: PyAudio not available")
            return False
        if wave is None:
            _log("ERROR: wave module not available")
            return False

        filepath = AUDIO_DIR + filename
        _log("full filepath: " + filepath)

        try:
            # 检查文件是否存在
            import os
            try:
                stat = os.stat(filepath)
                _log("file exists, size: " + str(stat[6]))
            except Exception as e:
                _log("file NOT FOUND: " + str(e))
                return False

            # 初始化媒体管理器（如果未初始化过）
            if MediaManager is not None:
                _log("calling MediaManager.init()...")
                try:
                    MediaManager.init()
                    _log("MediaManager.init() SUCCESS")
                except Exception as e:
                    _log("MediaManager.init() FAILED: " + str(e))
                    _log("MediaManager may already be initialized, continuing...")

            # 打开WAV文件
            _log("opening wave file...")
            self.wf = wave.open(filepath, 'rb')
            _log("wave.open() SUCCESS")

            # 打印WAV信息
            _log("WAV info - channels: " + str(self.wf.get_channels()))
            _log("WAV info - sampwidth: " + str(self.wf.get_sampwidth()))
            _log("WAV info - framerate: " + str(self.wf.get_framerate()))

            # 启用扬声器
            if self.spk is not None:
                try:
                    _log("enabling YbSpeaker...")
                    self.spk.enable()
                    _log("YbSpeaker.enable() SUCCESS")
                except Exception as e:
                    _log("YbSpeaker.enable() FAILED: " + str(e))

            # 计算chunk大小
            CHUNK = int(self.wf.get_framerate() / 25)
            _log("CHUNK size: " + str(CHUNK))

            # 创建PyAudio实例
            _log("creating PyAudio instance...")
            self.p = PyAudio()
            _log("PyAudio() SUCCESS")

            # 初始化PyAudio对象
            _log("initializing PyAudio with CHUNK=" + str(CHUNK) + "...")
            try:
                self.p.initialize(CHUNK)
                _log("PyAudio.initialize() SUCCESS")
            except Exception as e:
                _log("PyAudio.initialize() FAILED: " + str(e))

            # 打开音频输出流
            _log("opening audio output stream...")
            self.stream = self.p.open(
                format=self.p.get_format_from_width(self.wf.get_sampwidth()),
                channels=self.wf.get_channels(),
                rate=self.wf.get_framerate(),
                output=True,
                frames_per_buffer=CHUNK
            )
            _log("p.open() SUCCESS")

            # 设置音量
            try:
                self.stream.volume(vol=100)
                _log("stream.volume(100) set")
            except Exception as e:
                _log("stream.volume() failed: " + str(e))

            # 播放音频
            _log("starting playback loop...")
            self._playing = True
            frame_count = 0
            data = self.wf.read_frames(CHUNK)
            while data and self._playing:
                self.stream.write(data)
                frame_count += 1
                if frame_count % 25 == 0:
                    _log("playing... frame_count: " + str(frame_count))
                data = self.wf.read_frames(CHUNK)
            _log("playback loop finished, total frames: " + str(frame_count))

            # 播放结束后自动释放资源
            _log("auto releasing resources after playback...")
            self.stop()

            return True
        except Exception as e:
            _log("play_wav ERROR: " + str(e))
            import sys
            try:
                sys.print_exception(e)
            except:
                pass
            # 异常时也要释放资源
            self.stop()
            return False

    def stop(self):
        _log("stop called")
        self._playing = False
        if self.stream:
            try:
                self.stream.stop_stream()
                _log("stream.stop_stream() called")
            except Exception as e:
                _log("stream.stop_stream() error: " + str(e))
            try:
                self.stream.close()
                _log("stream.close() called")
            except Exception as e:
                _log("stream.close() error: " + str(e))
            self.stream = None
        if self.p:
            try:
                self.p.terminate()
                _log("p.terminate() called")
            except Exception as e:
                _log("p.terminate() error: " + str(e))
            self.p = None
        if self.wf:
            try:
                self.wf.close()
                _log("wf.close() called")
            except Exception as e:
                _log("wf.close() error: " + str(e))
            self.wf = None
        if self.spk:
            try:
                self.spk.disable()
                _log("spk.disable() called")
            except Exception as e:
                _log("spk.disable() error: " + str(e))
        # 注意：不要调用 MediaManager.deinit()，因为视频层还在使用
        # MediaManager.deinit() 会释放视频缓冲区，导致黑屏
