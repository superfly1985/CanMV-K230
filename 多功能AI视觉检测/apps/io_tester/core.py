try:
    import machine
except:
    machine = None

OUTPUT_PINS = {
    "IO42": 42,
    "IO33": 33,
}

INPUT_PINS = {
    "IO34": 34,
    "IO35": 35,
}

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
