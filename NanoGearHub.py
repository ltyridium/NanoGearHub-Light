import requests
import struct
import time
import threading
import io
import tkinter as tk
from tkinter import ttk, colorchooser


# test in IOT 版本：0.1.5
# test in 固件版本：ID3502_V801

# ================= 风格常量 =================
COLOR_BG = "#121212"
COLOR_PANEL = "#1E1E1E"
COLOR_ACCENT = "#66CCFF"  # 青色
COLOR_SUCCESS = "#00FF7F" # 亮绿
COLOR_ERROR = "#FF4B2B"   # 亮红
COLOR_TEXT = "#E0E0E0"
FONT_MAIN = ("Consolas", 10)
FONT_BOLD = ("Consolas", 11, "bold")
FONT_HEADER = ("Consolas", 14, "bold")

# ================= 灯效模式定义 =================
MAIN_LIGHT_MODES = {
    0: "关闭 (Off)", 1: "常亮 (Static)", 2: "呼吸 (Breath)", 3: "霓虹 (Neon)",
    4: "波浪 (Wave)", 5: "涟漪 (Ripple)", 6: "雨滴 (Raindrop)", 7: "蛇行 (Snake)",
    8: "随动 (Press)", 9: "聚合 (Converage)", 10: "正弦波 (Sine)",
    11: "万花筒 (Kaleido)", 12: "繁星 (Starry)", 13: "自定义图 (UserPic)",
    16: "绚烂 (Dazzle)", 17: "下雨 (Rain)", 18: "流星 (Meteor)", 25: "自定义色"
}

SIDE_LIGHT_MODES = {
    0: "关闭", 1: "常亮", 2: "呼吸", 3: "霓虹", 4: "波浪", 5: "蛇行", 6: "律动2"
}

# ================= 协议底层核心 (保持原有稳健逻辑) =================

class GrpcStreamBuffer:
    def __init__(self):
        self.buffer = bytearray()
    def add(self, chunk):
        self.buffer.extend(chunk)
    def read_frame(self):
        if len(self.buffer) < 5: return None
        flag, length = struct.unpack(">BI", self.buffer[:5])
        if len(self.buffer) < 5 + length: return None
        frame_data = self.buffer[5:5+length]
        self.buffer = self.buffer[5+length:]
        return frame_data

class ProtoReader:
    def __init__(self, data):
        self.stream = io.BytesIO(data)
        self.end = len(data)
    def read_varint(self):
        shift, result = 0, 0
        while True:
            b = self.stream.read(1)
            if not b: return None
            i = ord(b)
            result |= (i & 0x7f) << shift
            shift += 7
            if not (i & 0x80): break
        return result
    def read_field(self):
        if self.stream.tell() >= self.end: return None, None, None
        tag = self.read_varint()
        if tag is None: return None, None, None
        return tag >> 3, tag & 0x07, self
    def read_value(self, wire_type):
        if wire_type == 0: return self.read_varint()
        elif wire_type == 2:
            length = self.read_varint()
            return self.stream.read(length)
        return None

def make_proto(field, value):
    header = []
    tag = (field << 3) | 2
    while True:
        header.append((tag & 0x7f) | 0x80 if tag > 127 else tag)
        tag >>= 7
        if tag == 0: break
    length = len(value)
    while True:
        header.append((length & 0x7f) | 0x80 if length > 127 else length)
        length >>= 7
        if length == 0: break
    return bytes(header) + value

def make_varint_bytes(val):
    out = []
    while True:
        out.append((val & 0x7f) | 0x80 if val > 127 else val)
        val >>= 7
        if val == 0: break
    return bytes(out)

def make_grpc_frame(data):
    return struct.pack(">BI", 0, len(data)) + data

GLOBAL_STATE = {
    "iot_session": None, "hid_session": None, "device_path": None,
    "iot_connected": False, "hid_connected": False
}

# ================= 监听与业务逻辑 =================

def monitor_iot_thread(app):
    try:
        resp = requests.post("http://127.0.0.1:6015/iot_manager.IotManager/StartClientMonitoring",
            data=make_grpc_frame(b''),
            headers={"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"},
            stream=True, timeout=None)
        buf = GrpcStreamBuffer()
        for chunk in resp.iter_content(chunk_size=None):
            buf.add(chunk)
            while True:
                frame = buf.read_frame()
                if not frame: break
                reader = ProtoReader(frame)
                while True:
                    fn, wt, _ = reader.read_field()
                    if fn is None: break
                    val = reader.read_value(wt)
                    if fn == 1:
                        cr = ProtoReader(val)
                        while True:
                            cfn, cwt, _ = cr.read_field()
                            if cfn is None: break
                            cval = cr.read_value(cwt)
                            if cfn == 2:
                                GLOBAL_STATE["iot_session"] = cval.decode()
                                GLOBAL_STATE["iot_connected"] = True
                                app.terminal_print(f"CORE.IOT_LINK_ESTABLISHED: {GLOBAL_STATE['iot_session'][:16]}...", COLOR_ACCENT)
    except Exception as e: app.terminal_print(f"ERR.IOT_LINK_FAILED: {e}", COLOR_ERROR)

def monitor_hid_thread(app):
    filter_data = b'\x08' + make_varint_bytes(12625) + b'\x10' + make_varint_bytes(20558)
    req_data = make_proto(1, filter_data)
    try:
        resp = requests.post("http://127.0.0.1:3838/hid.HidService/StartDeviceMonitoring",
            data=make_grpc_frame(req_data),
            headers={"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"},
            stream=True, timeout=None)
        buf = GrpcStreamBuffer()
        for chunk in resp.iter_content(chunk_size=None):
            buf.add(chunk)
            while True:
                frame = buf.read_frame()
                if not frame: break
                reader = ProtoReader(frame)
                while True:
                    fn, wt, _ = reader.read_field()
                    if fn is None: break
                    val = reader.read_value(wt)
                    if fn == 1:
                        cr = ProtoReader(val)
                        while True:
                            cfn, cwt, _ = cr.read_field()
                            if cfn is None: break
                            cval = cr.read_value(cwt)
                            if cfn == 2: GLOBAL_STATE["hid_session"] = cval.decode()
                    if fn == 2:
                        dr = ProtoReader(val)
                        while True:
                            dfn, dwt, _ = dr.read_field()
                            if dfn is None: break
                            dval = dr.read_value(dwt)
                            if dfn == 1:
                                der = ProtoReader(dval)
                                while True:
                                    efn, ewt, _ = der.read_field()
                                    if efn is None: break
                                    eval_ = der.read_value(ewt)
                                    if efn == 2:
                                        hdr = ProtoReader(eval_)
                                        path, up, u = "", 0, 0
                                        while True:
                                            hfn, hwt, _ = hdr.read_field()
                                            if hfn is None: break
                                            hval = hdr.read_value(hwt)
                                            if hfn == 1: path = hval.decode()
                                            if hfn == 7: up = hval
                                            if hfn == 8: u = hval
                                        if up == 65535 and u == 2:
                                            GLOBAL_STATE["device_path"] = path
                                            GLOBAL_STATE["hid_connected"] = True
                                            app.terminal_print(f"HW.HID_DEVICE_ATTACHED: {path[-30:]}", COLOR_SUCCESS)
    except Exception as e: app.terminal_print(f"ERR.HID_LINK_FAILED: {e}", COLOR_ERROR)

# ================= GUI 设计层 =================

class GeekCommander:
    def __init__(self, root):
        self.root = root
        self.root.title("NanoGearHub-Light")
        self.root.geometry("850x700")
        self.root.configure(bg=COLOR_BG)
        self.current_rgb = (0, 210, 255)
        
        self.setup_styles()
        self.build_ui()
        
        # 启动逻辑
        threading.Thread(target=monitor_iot_thread, args=(self,), daemon=True).start()
        threading.Thread(target=monitor_hid_thread, args=(self,), daemon=True).start()
        threading.Thread(target=self.filter_registration_loop, daemon=True).start()
        self.update_indicators()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('clam')
        style.configure("TFrame", background=COLOR_BG)
        style.configure("Panel.TLabelframe", background=COLOR_PANEL, foreground=COLOR_ACCENT, bordercolor=COLOR_ACCENT)
        style.configure("Panel.TLabelframe.Label", background=COLOR_PANEL, foreground=COLOR_ACCENT, font=FONT_BOLD)

    def build_ui(self):
        # Header
        header = tk.Frame(self.root, bg=COLOR_BG, height=50)
        header.pack(fill="x", padx=20, pady=10)
        tk.Label(header, text="▎NEON PROTOCOL ANALYZER", font=FONT_HEADER, fg=COLOR_TEXT, bg=COLOR_BG).pack(side="left")
        tk.Label(header, text="[DEVICE_MODEL: EW-3151-HID]", font=FONT_MAIN, fg="#666", bg=COLOR_BG).pack(side="left", padx=20)

        # Main Layout: Left (Controls) and Right (Status)
        main_body = tk.Frame(self.root, bg=COLOR_BG)
        main_body.pack(fill="both", expand=True, padx=20)

        left_side = tk.Frame(main_body, bg=COLOR_BG)
        left_side.pack(side="left", fill="both", expand=True)

        # PANEL 1: INPUT SOURCE / STATUS
        p1 = ttk.LabelFrame(left_side, text=" SYSTEM STATUS ", style="Panel.TLabelframe")
        p1.pack(fill="x", pady=5, padx=5)
        
        self.iot_led = tk.Label(p1, text="● IOT_SOCKET", font=FONT_MAIN, fg="#444", bg=COLOR_PANEL)
        self.iot_led.pack(anchor="w", padx=10, pady=2)
        self.hid_led = tk.Label(p1, text="● HID_INTERFACE", font=FONT_MAIN, fg="#444", bg=COLOR_PANEL)
        self.hid_led.pack(anchor="w", padx=10, pady=2)
        self.path_display = tk.Label(p1, text="PATH: NULL", font=FONT_MAIN, fg="#666", bg=COLOR_PANEL)
        self.path_display.pack(anchor="w", padx=10, pady=2)

        # PANEL 2: PARAMETERS
        p2 = ttk.LabelFrame(left_side, text=" LIGHTING CONFIG ", style="Panel.TLabelframe")
        p2.pack(fill="both", expand=True, pady=5, padx=5)

        # Area select
        self.target_area = tk.StringVar(value="main")
        area_f = tk.Frame(p2, bg=COLOR_PANEL)
        area_f.pack(fill="x", padx=10, pady=5)
        tk.Radiobutton(area_f, text="MAIN_KEYS", variable=self.target_area, value="main", bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_BG, activebackground=COLOR_PANEL, font=FONT_MAIN).pack(side="left")
        tk.Radiobutton(area_f, text="SIDE_GLOW", variable=self.target_area, value="side", bg=COLOR_PANEL, fg=COLOR_TEXT, selectcolor=COLOR_BG, activebackground=COLOR_PANEL, font=FONT_MAIN).pack(side="left", padx=10)

        # Mode
        tk.Label(p2, text="MODE_ID:", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w", padx=10)
        self.mode_combo = ttk.Combobox(p2, state="readonly", width=30)
        self.mode_combo.pack(padx=10, pady=5)
        self.update_mode_list()
        self.mode_combo.current(1)

        # Sliders
        tk.Label(p2, text="BRIGHTNESS:", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w", padx=10)
        self.bright = tk.Scale(p2, from_=0, to=4, orient="horizontal", bg=COLOR_PANEL, fg=COLOR_TEXT, highlightthickness=0, troughcolor="#333", activebackground=COLOR_ACCENT)
        self.bright.set(4)
        self.bright.pack(fill="x", padx=10)

        tk.Label(p2, text="SPEED_PULSE:", font=FONT_MAIN, fg=COLOR_ACCENT, bg=COLOR_PANEL).pack(anchor="w", padx=10)
        self.speed = tk.Scale(p2, from_=0, to=4, orient="horizontal", bg=COLOR_PANEL, fg=COLOR_TEXT, highlightthickness=0, troughcolor="#333", activebackground=COLOR_ACCENT)
        self.speed.set(3)
        self.speed.pack(fill="x", padx=10)

        # Buttons
        btn_f = tk.Frame(p2, bg=COLOR_PANEL)
        btn_f.pack(fill="x", padx=10, pady=15)
        
        self.color_btn = tk.Button(btn_f, text="SET_COLOR", font=FONT_BOLD, bg=COLOR_ACCENT, fg=COLOR_BG, activebackground=COLOR_TEXT, width=12, command=self.pick_color)
        self.color_btn.pack(side="left")
        
        tk.Button(btn_f, text="EXECUTE_CMD", font=FONT_BOLD, bg=COLOR_SUCCESS, fg=COLOR_BG, activebackground=COLOR_TEXT, width=15, command=self.send_command).pack(side="right")

        # Bind event to update mode list when area selection changes
        self.target_area.trace_add("write", self.on_area_change)

        # PANEL 3: TERMINAL (The geeky part)
        p3 = ttk.LabelFrame(self.root, text=" SYSTEM LOG / TERMINAL ", style="Panel.TLabelframe")
        p3.pack(fill="both", expand=True, padx=20, pady=10)

        self.terminal = tk.Text(p3, bg="#0A0A0A", fg=COLOR_SUCCESS, font=("Consolas", 9), borderwidth=0, highlightthickness=0)
        self.terminal.pack(fill="both", expand=True, padx=5, pady=5)

        # Init text
        self.terminal_print("System initialized.")
        self.terminal_print("Ready to process device data streams.")

    def on_area_change(self, *args):
        """当区域选择改变时更新模式列表"""
        self.update_mode_list()

    def update_mode_list(self):
        """更新模式下拉列表的内容"""
        if self.target_area.get() == "main":
            values = [f"{k:02d}: {v}" for k, v in MAIN_LIGHT_MODES.items()]
        else:
            values = [f"{k:02d}: {v}" for k, v in SIDE_LIGHT_MODES.items()]
        self.mode_combo['values'] = values
        # 设置默认选中项
        if self.target_area.get() == "main":
            self.mode_combo.current(1)  # 默认选择"常亮"
        else:
            self.mode_combo.current(1)  # 默认选择"常亮"

    def terminal_print(self, msg, color=COLOR_SUCCESS):
        timestamp = time.strftime("%H:%M:%S")
        self.terminal.tag_config(color, foreground=color)
        self.terminal.insert(tk.END, f"[{timestamp}] ", "dim")
        self.terminal.insert(tk.END, f"{msg}\n", color)
        self.terminal.see(tk.END)

    def pick_color(self):
        color = colorchooser.askcolor("#00D2FF")
        if color[1]:
            self.current_rgb = tuple(map(int, color[0]))
            self.color_btn.config(bg=color[1])
            self.terminal_print(f"UI.COLOR_SET: RGB{self.current_rgb}")

    def update_indicators(self):
        if GLOBAL_STATE["iot_connected"]: self.iot_led.config(fg=COLOR_SUCCESS)
        if GLOBAL_STATE["hid_connected"]: 
            self.hid_led.config(fg=COLOR_SUCCESS)
            self.path_display.config(text=f"PATH: ...{GLOBAL_STATE['device_path'][-32:]}")
        self.root.after(1000, self.update_indicators)

    def filter_registration_loop(self):
        while not GLOBAL_STATE["iot_connected"]: time.sleep(0.5)
        report_def = b'\x10\x40'
        dev_filter = b'\x08\x02' + b'\x10' + make_varint_bytes(12625) + b'\x18' + make_varint_bytes(20558)
        dev_filter += b'\x20\x02' + b'\x28\xff\xff\x03' + b'\x30\x02' + make_proto(7, report_def)
        req = make_proto(1, GLOBAL_STATE["iot_session"].encode()) + make_proto(2, dev_filter)
        try:
            requests.post("http://127.0.0.1:6015/iot_manager.IotManager/AddDeviceFilter",
                data=make_grpc_frame(req), headers={"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"})
            self.terminal_print("CORE.FILTER_REGISTERED: VID_3151 PID_504E")
        except: pass

    def send_command(self):
        if not GLOBAL_STATE["hid_connected"]:
            self.terminal_print("ERR.EXECUTION_HALTED: NO_DEVICE", COLOR_ERROR)
            return

        try:
            # 1. 激活控制权
            act_data = make_proto(1, GLOBAL_STATE["device_path"].encode()) + b'\x10\x02' + make_proto(4, GLOBAL_STATE["iot_session"].encode())
            requests.post("http://127.0.0.1:6015/iot_manager.IotManager/ControlDeviceLight",
                         data=make_grpc_frame(act_data), headers={"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"})

            # 2. 构造指令
            mode_idx = int(self.mode_combo.get().split(":")[0])
            is_main = self.target_area.get() == "main"

            # 验证模式索引是否在对应的字典范围内
            if is_main and mode_idx not in MAIN_LIGHT_MODES:
                self.terminal_print(f"ERR.INVALID_MODE: {mode_idx} for main lights", COLOR_ERROR)
                return
            elif not is_main and mode_idx not in SIDE_LIGHT_MODES:
                self.terminal_print(f"ERR.INVALID_MODE: {mode_idx} for side lights", COLOR_ERROR)
                return

            cmd = bytearray(9)
            cmd[0] = 0x07 if is_main else 0x08
            cmd[1] = mode_idx
            cmd[2] = (4 - self.speed.get()) if is_main else self.speed.get()
            cmd[3] = self.bright.get()
            cmd[4] = 0x07 # Default option
            cmd[5], cmd[6], cmd[7] = self.current_rgb
            cmd[8] = (255 - (sum(cmd[:8]) & 0xFF)) & 0xFF

            payload = bytearray(65)
            payload[1:10] = cmd

            # Print HEX to terminal for Geek feel
            hex_str = " ".join([f"{b:02X}" for b in cmd])
            self.terminal_print(f"TX >> CMD_STREAM: {hex_str}")

            req = make_proto(1, GLOBAL_STATE["device_path"].encode()) + make_proto(2, bytes(payload)) + make_proto(4, GLOBAL_STATE["hid_session"].encode())
            res = requests.post("http://127.0.0.1:3838/hid.HidService/SendFeatureReport",
                               data=make_grpc_frame(req), headers={"Content-Type": "application/grpc-web+proto", "X-Grpc-Web": "1"})

            if res.status_code == 200:
                mode_name = MAIN_LIGHT_MODES[mode_idx] if is_main else SIDE_LIGHT_MODES[mode_idx]
                self.terminal_print(f"CORE.TX_SUCCESS: {self.target_area.get()} - {mode_name}", COLOR_ACCENT)
            else:
                self.terminal_print(f"CORE.TX_FAILED: HTTP_{res.status_code}", COLOR_ERROR)
        except Exception as e:
            self.terminal_print(f"ERR.EXCEPTION: {e}", COLOR_ERROR)

if __name__ == "__main__":
    root = tk.Tk()
    app = GeekCommander(root)
    root.mainloop()
