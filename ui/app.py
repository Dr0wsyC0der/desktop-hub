import asyncio
import base64
import colorsys
import io
import json
import re
import urllib.error
import urllib.request

import flet as ft
from PIL import Image, ImageOps


API_BASE = "http://127.0.0.1:8787/api"

SCREEN_ELEMENTS = {
    "screen1": [
        ("background", "Background"),
        ("city", "City"),
        ("region", "Region"),
        ("main_hours", "Hours"),
        ("main_minute", "Minutes"),
        ("main_seconds", "Seconds"),
        ("date", "Date"),
        ("day", "Weekday"),
        ("simb_weather", "Weather icon"),
        ("templabel", "Temperature"),
        ("hmlabel", "Humidity"),
        ("other_weather", "Extra weather"),
    ],
    "screen2": [
        ("background", "Background"),
        ("title", "Title"),
        ("subtitle", "Subtitle"),
        ("value_primary", "Primary value"),
        ("value_secondary", "Secondary value"),
    ],
    "screen3": [
        ("background", "Background"),
        ("bus_name", "Bus number"),
        ("bus_time", "Bus time"),
        ("bus_stop", "Stop name"),
    ],
}

LED_EFFECTS = [
    ("1", "1 - Static"),
    ("2", "2 - Breathing"),
    ("3", "3 - Comet"),
    ("4", "4 - Rainbow pong"),
    ("5", "5 - Rainbow"),
    ("6", "6 - Fire"),
    ("7", "7 - Matrix"),
]
LED_MODES_WITH_COLOR = {"1", "2", "3"}
HEX_PATTERN = re.compile(r"^#?[0-9A-Fa-f]{6}$")


def api_request(path: str, method: str = "GET", data: dict | None = None):
    body = None
    headers = {"Content-Type": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(f"{API_BASE}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=8) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def normalize_led_mode(value) -> str:
    legacy_map = {
        "static": "1",
        "breath": "2",
        "breathing": "2",
        "comet": "3",
        "rainbow_pong": "4",
        "rainbow-pong": "4",
        "rainbow": "5",
        "fire": "6",
        "matrix": "7",
    }
    if value is None:
        return "5"
    as_str = str(value).strip().lower()
    if as_str in legacy_map:
        return legacy_map[as_str]
    if as_str in {key for key, _ in LED_EFFECTS}:
        return as_str
    return "5"


def mode_supports_color(value) -> bool:
    return normalize_led_mode(value) in LED_MODES_WITH_COLOR


def clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, int(value)))


def rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{clamp_int(r, 0, 255):02X}{clamp_int(g, 0, 255):02X}{clamp_int(b, 0, 255):02X}"


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    cleaned = value.strip().lstrip("#")
    if len(cleaned) != 6:
        raise ValueError("HEX must contain 6 chars")
    return int(cleaned[0:2], 16), int(cleaned[2:4], 16), int(cleaned[4:6], 16)


def ensure_four_sources(raw_sources) -> list[dict[str, str]]:
    sources: list[dict[str, str]] = []
    for source in raw_sources or []:
        if isinstance(source, dict):
            sources.append(
                {
                    "url": str(source.get("url", "")).strip(),
                    "stop_name": str(source.get("stop_name", source.get("name", ""))).strip(),
                    "bus_number": str(source.get("bus_number", source.get("name", ""))).strip(),
                }
            )
        elif isinstance(source, str):
            sources.append({"url": source.strip(), "stop_name": "", "bus_number": ""})

    while len(sources) < 4:
        sources.append({"url": "", "stop_name": "", "bus_number": ""})
    return sources[:4]


def parse_telemetry(last_message: str) -> str:
    if not last_message:
        return "No telemetry yet"

    try:
        payload = json.loads(last_message)
    except Exception:
        return "Last ESP message is not JSON"

    if payload.get("type") == "pc_load":
        cpu = payload.get("cpu", "-")
        gpu = payload.get("gpu", "-")
        ram = payload.get("ram", "-")
        return f"CPU: {cpu}% | GPU: {gpu}% | RAM: {ram}%"

    msg_type = payload.get("type")
    if msg_type:
        return f"Message type: {msg_type}"

    return "JSON message received"


def pick_file_with_dialog(title: str, file_types: list[tuple[str, str]]) -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        try:
            path = filedialog.askopenfilename(title=title, filetypes=file_types)
        finally:
            root.destroy()
        return str(path or "").strip()
    except Exception:
        return ""


class RGBColorPicker:
    PALETTE_SIZE = 250

    def __init__(self, page: ft.Page, title: str, initial_hex: str = "#FFAA00"):
        self.page = page
        self.title = title
        self._on_change = None
        self._syncing_inputs = False

        r, g, b = hex_to_rgb(initial_hex)
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)

        self.palette_marker = ft.Container(
            width=16,
            height=16,
            border_radius=8,
            border=ft.Border.all(2, "#FFFFFF"),
            bgcolor="transparent",
            ignore_interactions=True,
            shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color="#66000000"),
        )
        self.value_marker = ft.Container(
            width=20,
            height=20,
            border_radius=10,
            border=ft.Border.all(2, "#FFFFFF"),
            bgcolor="transparent",
            ignore_interactions=True,
            shadow=ft.BoxShadow(spread_radius=1, blur_radius=4, color="#66000000"),
        )

        self.value_gradient = ft.Container(
            width=34,
            height=self.PALETTE_SIZE,
            border_radius=12,
            gradient=ft.LinearGradient(
                begin=ft.Alignment(0, -1),
                end=ft.Alignment(0, 1),
                colors=["#FFAA00", "#000000"],
            ),
        )

        self.hex_field = ft.TextField(label="HEX", value=initial_hex.upper(), width=120, dense=True)
        self.mode_dropdown = ft.Dropdown(
            label="Color mode",
            value="RGB",
            width=120,
            dense=True,
            options=[ft.dropdown.Option("RGB", "RGB")],
        )
        self.red_field = ft.TextField(label="R", value=str(r), width=120, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        self.green_field = ft.TextField(label="G", value=str(g), width=120, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        self.blue_field = ft.TextField(label="B", value=str(b), width=120, dense=True, keyboard_type=ft.KeyboardType.NUMBER)
        self.preview = ft.Container(width=120, height=46, border_radius=10, bgcolor=initial_hex, border=ft.Border.all(1, "#D9DFEA"))

        self.hex_field.on_change = self._on_hex_input
        self.red_field.on_change = self._on_rgb_input
        self.green_field.on_change = self._on_rgb_input
        self.blue_field.on_change = self._on_rgb_input

        self.palette_area = ft.GestureDetector(
            drag_interval=16,
            on_tap_down=self._on_palette_event,
            on_pan_start=self._on_palette_event,
            on_pan_update=self._on_palette_event,
            content=ft.Stack(
                controls=[
                    ft.Container(
                        width=self.PALETTE_SIZE,
                        height=self.PALETTE_SIZE,
                        border_radius=14,
                        gradient=ft.LinearGradient(
                            begin=ft.Alignment(-1, 0),
                            end=ft.Alignment(1, 0),
                            colors=["#FF0000", "#FFFF00", "#00FF00", "#00FFFF", "#0000FF", "#FF00FF", "#FF0000"],
                        ),
                    ),
                    ft.Container(
                        width=self.PALETTE_SIZE,
                        height=self.PALETTE_SIZE,
                        border_radius=14,
                        gradient=ft.LinearGradient(
                            begin=ft.Alignment(0, -1),
                            end=ft.Alignment(0, 1),
                            colors=["#00FFFFFF", "#FFFFFFFF"],
                        ),
                    ),
                ]
            ),
        )

        self.value_area = ft.GestureDetector(
            drag_interval=16,
            on_tap_down=self._on_value_event,
            on_pan_start=self._on_value_event,
            on_pan_update=self._on_value_event,
            content=self.value_gradient,
        )

        self.root = ft.Container(
            padding=16,
            border_radius=16,
            bgcolor="#FFFFFF",
            border=ft.Border.all(1, "#E2E8F0"),
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=18, color="#140F172A", offset=ft.Offset(0, 6)),
            content=ft.Column(
                [
                    ft.Text(self.title, size=18, weight=ft.FontWeight.W_700, color="#1F2937"),
                    ft.Row(
                        [
                            ft.Stack(
                                controls=[
                                    self.palette_area,
                                    self.palette_marker,
                                ],
                                width=self.PALETTE_SIZE,
                                height=self.PALETTE_SIZE,
                            ),
                            ft.Stack(
                                controls=[
                                    self.value_area,
                                    self.value_marker,
                                ],
                                width=34,
                                height=self.PALETTE_SIZE,
                            ),
                            ft.Column(
                                [
                                    self.hex_field,
                                    self.mode_dropdown,
                                    self.red_field,
                                    self.green_field,
                                    self.blue_field,
                                    self.preview,
                                ],
                                spacing=8,
                                horizontal_alignment=ft.CrossAxisAlignment.START,
                            ),
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                ],
                spacing=12,
            ),
        )

        self._render(False)

    def set_on_change(self, callback):
        self._on_change = callback

    def set_hex(self, value: str, notify: bool = False):
        if not HEX_PATTERN.match(value or ""):
            return
        r, g, b = hex_to_rgb(value)
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        self._render(notify)

    def get_hex(self) -> str:
        r, g, b = self._rgb()
        return rgb_to_hex(r, g, b)

    def set_disabled(self, disabled: bool):
        self.root.disabled = disabled

    def _rgb(self) -> tuple[int, int, int]:
        r, g, b = colorsys.hsv_to_rgb(self.h, self.s, self.v)
        return round(r * 255), round(g * 255), round(b * 255)

    def _event_xy(self, event, fallback_x: float, fallback_y: float) -> tuple[float, float]:
        local_position = getattr(event, "local_position", None)
        if local_position is not None:
            pos_x = getattr(local_position, "x", None)
            pos_y = getattr(local_position, "y", None)
            if pos_x is not None and pos_y is not None:
                return float(pos_x), float(pos_y)

        local_x = getattr(event, "local_x", None)
        local_y = getattr(event, "local_y", None)
        if local_x is not None and local_y is not None:
            return float(local_x), float(local_y)

        if local_x is None:
            local_x = fallback_x + float(getattr(event, "delta_x", 0.0) or 0.0)
        if local_y is None:
            local_y = fallback_y + float(getattr(event, "delta_y", 0.0) or 0.0)

        return float(local_x), float(local_y)

    def _on_palette_event(self, event):
        fallback_x = self.h * (self.PALETTE_SIZE - 1)
        fallback_y = (1.0 - self.s) * (self.PALETTE_SIZE - 1)
        x, y = self._event_xy(event, fallback_x, fallback_y)
        x = max(0.0, min(self.PALETTE_SIZE - 1, x))
        y = max(0.0, min(self.PALETTE_SIZE - 1, y))

        self.h = x / (self.PALETTE_SIZE - 1)
        self.s = 1.0 - (y / (self.PALETTE_SIZE - 1))
        self._render(True)

    def _on_value_event(self, event):
        fallback_y = (1.0 - self.v) * (self.PALETTE_SIZE - 1)
        _, y = self._event_xy(event, 0.0, fallback_y)
        y = max(0.0, min(self.PALETTE_SIZE - 1, y))

        self.v = 1.0 - (y / (self.PALETTE_SIZE - 1))
        self._render(True)

    def _on_hex_input(self, _event):
        if self._syncing_inputs:
            return
        value = (self.hex_field.value or "").strip()
        if not HEX_PATTERN.match(value):
            return
        self.set_hex(value, notify=True)

    def _on_rgb_input(self, _event):
        if self._syncing_inputs:
            return
        try:
            r = clamp_int(int(self.red_field.value), 0, 255)
            g = clamp_int(int(self.green_field.value), 0, 255)
            b = clamp_int(int(self.blue_field.value), 0, 255)
        except Exception:
            return
        self.h, self.s, self.v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        self._render(True)

    def _render(self, notify: bool):
        r, g, b = self._rgb()
        hex_value = rgb_to_hex(r, g, b)
        full_r, full_g, full_b = colorsys.hsv_to_rgb(self.h, self.s, 1.0)
        full_hex = rgb_to_hex(round(full_r * 255), round(full_g * 255), round(full_b * 255))

        self._syncing_inputs = True
        self.hex_field.value = hex_value
        self.red_field.value = str(r)
        self.green_field.value = str(g)
        self.blue_field.value = str(b)
        self.preview.bgcolor = hex_value
        self._syncing_inputs = False

        palette_x = self.h * (self.PALETTE_SIZE - 1)
        palette_y = (1.0 - self.s) * (self.PALETTE_SIZE - 1)
        self.palette_marker.left = max(0.0, min(self.PALETTE_SIZE - 16, palette_x - 8))
        self.palette_marker.top = max(0.0, min(self.PALETTE_SIZE - 16, palette_y - 8))

        value_y = (1.0 - self.v) * (self.PALETTE_SIZE - 1)
        self.value_marker.left = 7
        self.value_marker.top = max(0.0, min(self.PALETTE_SIZE - 20, value_y - 10))
        self.value_gradient.gradient = ft.LinearGradient(
            begin=ft.Alignment(0, -1),
            end=ft.Alignment(0, 1),
            colors=[full_hex, "#000000"],
        )

        if notify and self._on_change:
            self._on_change(hex_value)

        try:
            self.root.update()
        except Exception:
            try:
                self.page.update()
            except Exception:
                pass


def main(page: ft.Page):
    page.title = "ESP32 S3 Control Hub"
    page.theme_mode = ft.ThemeMode.LIGHT
    page.padding = 16
    page.bgcolor = "#EEF3FA"
    page.window_width = 1360
    page.window_height = 900

    status_text = ft.Text("ESP: unknown", size=16, weight=ft.FontWeight.W_600, color="#111827")
    status_dot = ft.Container(width=12, height=12, border_radius=6, bgcolor=ft.Colors.GREY_500)

    telemetry_text = ft.Text("No telemetry yet", color="#374151")
    last_message_text = ft.Text("-", size=12, color="#4B5563", max_lines=3, overflow=ft.TextOverflow.ELLIPSIS)
    home_gif_progress_text = ft.Text("GIF: idle", color="#1F2937")
    home_gif_progress_bar = ft.ProgressBar(value=0)
    home_ota_progress_text = ft.Text("OTA: idle", color="#1F2937")
    home_ota_progress_bar = ft.ProgressBar(value=0)
    gif_progress_text = ft.Text("GIF: idle", color="#1F2937")
    gif_progress_bar = ft.ProgressBar(value=0)
    ota_progress_text = ft.Text("OTA: idle", color="#1F2937")
    ota_progress_bar = ft.ProgressBar(value=0)
    settings_summary = ft.Text("Settings snapshot will appear here", color="#374151")

    screen_dropdown = ft.Dropdown(
        label="Screen",
        value="screen1",
        options=[ft.dropdown.Option(key, key) for key in SCREEN_ELEMENTS.keys()],
        width=240,
    )
    element_dropdown = ft.Dropdown(label="Element", width=300)

    element_picker = RGBColorPicker(page, title="Element color")
    backlight_picker = RGBColorPicker(page, title="Backlight mode color", initial_hex="#33CCFF")

    screen_brightness = ft.Slider(label="Screen brightness: {value}", min=0, max=255, divisions=255, value=180)
    screen_weather_dependent = ft.Switch(label="Brightness depends on weather", value=False)

    backlight_brightness = ft.Slider(label="Backlight brightness: {value}", min=0, max=255, divisions=255, value=180)
    backlight_mode = ft.Dropdown(
        label="Backlight mode",
        value="5",
        options=[ft.dropdown.Option(key, text) for key, text in LED_EFFECTS],
        width=280,
    )
    backlight_weather_dependent = ft.Switch(label="Brightness depends on weather", value=False)

    weather_api_key = ft.TextField(label="Weather API key")
    weather_lat = ft.TextField(label="Latitude", value="55.7558")
    weather_lon = ft.TextField(label="Longitude", value="37.6173")
    weather_timeout = ft.TextField(label="Weather request timeout (sec)", value="1800")
    display_on = ft.TextField(label="Display on time", value="07:00")
    display_off = ft.TextField(label="Display off time", value="23:00")
    ws_port = ft.TextField(label="WS port (restart backend after change)", value="8765", width=280, keyboard_type=ft.KeyboardType.NUMBER)

    schedule_start = ft.TextField(label="Schedule from", value="07:30", width=220)
    schedule_end = ft.TextField(label="Schedule to", value="19:30", width=220)

    schedule_sources_controls = []
    for index in range(4):
        url = ft.TextField(label=f"Source {index + 1} URL", expand=True)
        stop_name = ft.TextField(label="Stop name", width=220)
        bus_number = ft.TextField(label="Bus number", width=180)
        schedule_sources_controls.append({"url": url, "stop_name": stop_name, "bus_number": bus_number})

    gif_file_text = ft.Text("GIF file not selected", color="#334155")
    gif_picker_button = ft.Button("Select GIF")
    gif_send_button = ft.Button("Upload GIF to ESP", icon=ft.Icons.UPLOAD_FILE)
    gif_editor_status = ft.Text("Select GIF to load frames", color="#64748B")
    gif_frames_grid = ft.ResponsiveRow(
        columns=12,
        spacing=10,
        run_spacing=10,
    )
    gif_frames_panel = ft.Container(
        height=430,
        padding=10,
        border_radius=12,
        border=ft.Border.all(1, "#D5DEEA"),
        bgcolor="#F8FAFC",
        content=ft.Column([gif_frames_grid], scroll=ft.ScrollMode.AUTO, spacing=0),
    )
    gif_frame_checks: list[ft.Checkbox] = []
    selected_gif_path = {"path": ""}
    gif_loading = {"value": False}

    ota_url = ft.TextField(label="Firmware URL", hint_text="https://example.com/firmware.bin")
    ota_warning_text = ft.Text("Device will download firmware by URL after confirmation.", color="#64748B")
    ota_flash_button = ft.Button("Flash firmware", icon=ft.Icons.SYSTEM_UPDATE_ALT)
    factory_reset_warning_text = ft.Text(
        "\u0421\u0431\u0440\u043e\u0441 \u0432\u0435\u0440\u043d\u0435\u0442 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 ESP \u043a \u0437\u0430\u0432\u043e\u0434\u0441\u043a\u0438\u043c.",
        color="#64748B",
    )
    factory_reset_button = ft.Button(
        "\u0421\u0431\u0440\u043e\u0441 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043a",
        icon=ft.Icons.RESTART_ALT,
    )

    action_controls: list[ft.Control] = []

    def card(title: str, content: ft.Control):
        return ft.Container(
            bgcolor="#FFFFFF",
            border_radius=16,
            padding=16,
            border=ft.Border.all(1, "#E2E8F0"),
            shadow=ft.BoxShadow(spread_radius=0, blur_radius=16, color="#120F172A", offset=ft.Offset(0, 5)),
            content=ft.Column([ft.Text(title, size=16, weight=ft.FontWeight.W_600), content], spacing=10),
        )

    def call_api(path: str, method: str = "GET", data: dict | None = None):
        try:
            return api_request(path, method, data)
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode("utf-8") or str(e))
        except Exception as e:
            raise RuntimeError(str(e))

    def toast(message: str, ok: bool = True):
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor="#15803D" if ok else "#B91C1C")
        page.snack_bar.open = True
        page.update()

    def update_settings_summary():
        settings_summary.value = (
            f"Display: {int(screen_brightness.value)} "
            f"(weather={screen_weather_dependent.value}) | "
            f"Backlight: mode {backlight_mode.value}, {int(backlight_brightness.value)} "
            f"(weather={backlight_weather_dependent.value}) | "
            f"Schedule: {schedule_start.value or '-'} - {schedule_end.value or '-'}"
        )

    def update_element_options(event=None):
        selected = getattr(event, "data", None) if event is not None else None
        current_screen = str(selected or screen_dropdown.value or "screen1")
        screen_dropdown.value = current_screen
        options = SCREEN_ELEMENTS.get(current_screen, [])
        element_dropdown.options = [ft.dropdown.Option(key, text) for key, text in options]

        if not options:
            element_dropdown.value = None
        elif element_dropdown.value not in {k for k, _ in options}:
            element_dropdown.value = options[0][0]

        page.update()

    def toggle_screen_manual(_=None):
        screen_brightness.disabled = screen_weather_dependent.value
        update_settings_summary()
        page.update()

    def toggle_backlight_manual(_=None):
        backlight_brightness.disabled = backlight_weather_dependent.value
        update_settings_summary()
        page.update()

    def toggle_backlight_color(event=None):
        selected = getattr(event, "data", None) if event is not None else None
        if selected not in (None, ""):
            backlight_mode.value = str(selected)
        backlight_picker.root.visible = mode_supports_color(backlight_mode.value)
        update_settings_summary()
        page.update()

    screen_dropdown.on_select = update_element_options
    screen_dropdown.on_change = update_element_options
    screen_weather_dependent.on_change = toggle_screen_manual
    backlight_weather_dependent.on_change = toggle_backlight_manual
    backlight_mode.on_select = toggle_backlight_color
    backlight_mode.on_change = toggle_backlight_color

    element_picker.set_on_change(lambda _color: None)
    backlight_picker.set_on_change(lambda _color: None)

    def send_color(_):
        if not element_dropdown.value:
            toast("Select element first", ok=False)
            return

        payload = {
            "screen": screen_dropdown.value,
            "element": element_dropdown.value,
            "color": element_picker.get_hex(),
        }
        try:
            call_api("/esp/color", "POST", payload)
            toast("Color applied")
        except RuntimeError as e:
            toast(f"Color error: {e}", ok=False)

    def send_display(_):
        payload = {
            "brightness": int(screen_brightness.value),
            "weather_dependent": bool(screen_weather_dependent.value),
        }
        try:
            call_api("/esp/display", "POST", payload)
            toast("Screen settings sent")
        except RuntimeError as e:
            toast(f"Screen settings error: {e}", ok=False)

    def send_backlight(_):
        payload = {
            "brightness": int(backlight_brightness.value),
            "mode": backlight_mode.value,
            "led_mode": int(normalize_led_mode(backlight_mode.value)),
            "weather_dependent": bool(backlight_weather_dependent.value),
        }
        if mode_supports_color(backlight_mode.value):
            payload["color"] = backlight_picker.get_hex()

        try:
            call_api("/esp/backlight", "POST", payload)
            toast("Backlight settings sent")
        except RuntimeError as e:
            toast(f"Backlight settings error: {e}", ok=False)

    def extract_gif_frames(path: str):
        previews: list[str] = []
        with Image.open(path) as gif:
            total = getattr(gif, "n_frames", 1)
            for idx in range(total):
                gif.seek(idx)
                frame = gif.convert("RGB")
                thumb = ImageOps.fit(frame, (104, 104), Image.Resampling.LANCZOS)
                buffer = io.BytesIO()
                thumb.save(buffer, format="JPEG", quality=72, optimize=True)
                previews.append(base64.b64encode(buffer.getvalue()).decode("ascii"))
        return previews

    def render_frames_grid(previews: list[str]):
        gif_frames_grid.controls.clear()
        gif_frame_checks.clear()

        for i, image_b64 in enumerate(previews, start=1):
            checkbox = ft.Checkbox(label=f"Frame {i}", value=True)
            gif_frame_checks.append(checkbox)
            gif_frames_grid.controls.append(
                ft.Container(
                    col={"sm": 6, "md": 4, "lg": 3},
                    padding=10,
                    border_radius=12,
                    border=ft.Border.all(1, "#D5DEEA"),
                    bgcolor="#FFFFFF",
                    content=ft.Column(
                        [
                            ft.Image(src=f"data:image/jpeg;base64,{image_b64}", fit=ft.BoxFit.COVER, width=132, height=132, border_radius=10),
                            checkbox,
                        ],
                        spacing=8,
                    ),
                )
            )

        gif_editor_status.value = f"Frames loaded: {len(previews)}. Uncheck frames you want to remove."
        page.update()

    async def load_gif_frames_task(path: str):
        try:
            previews = await asyncio.to_thread(extract_gif_frames, path)
            if not previews:
                gif_editor_status.value = "No frames found in GIF"
                page.update()
                return
            render_frames_grid(previews)
            toast(f"GIF loaded: {len(previews)} frames")
        except Exception as e:
            gif_editor_status.value = f"GIF parse error: {e}"
            toast(f"GIF parse error: {e}", ok=False)
            page.update()
        finally:
            gif_loading["value"] = False
            gif_picker_button.disabled = False
            page.update()

    def apply_gif_file(path: str):
        selected_gif_path["path"] = path
        gif_file_text.value = str(path)
        gif_loading["value"] = True
        gif_picker_button.disabled = True
        gif_frame_checks.clear()
        gif_frames_grid.controls.clear()
        gif_editor_status.value = "Loading GIF frames..."
        async def _task():
            await load_gif_frames_task(path)
        page.run_task(_task)
        page.update()

    def pick_gif(_):
        if gif_loading["value"]:
            return
        selected = pick_file_with_dialog("Select GIF file", [("GIF files", "*.gif")])
        if not selected:
            return
        apply_gif_file(selected)

    gif_picker_button.on_click = pick_gif

    def send_gif(_):
        if not selected_gif_path["path"]:
            toast("Select GIF file first", ok=False)
            return
        if not gif_frame_checks:
            toast("No frames detected", ok=False)
            return

        remove_frames = [index + 1 for index, checkbox in enumerate(gif_frame_checks) if not checkbox.value]
        payload = {
            "name": selected_gif_path["path"],
            "remove_frames": remove_frames,
        }

        try:
            call_api("/esp/gif", "POST", payload)
            toast("GIF transfer started")
        except RuntimeError as e:
            toast(f"GIF transfer error: {e}", ok=False)

    gif_send_button.on_click = send_gif

    def send_ota(_):
        url = (ota_url.value or "").strip()
        if not url:
            toast("Enter firmware URL first", ok=False)
            return

        def close_dialog(_event=None):
            page.pop_dialog()
            page.update()

        def confirm_ota(_event=None):
            close_dialog()
            try:
                call_api("/esp/command", "POST", {"type": "ota", "url": url})
                toast("OTA command sent")
            except RuntimeError as e:
                toast(f"OTA error: {e}", ok=False)

        warning_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Warning before OTA"),
            content=ft.Text(
                "Before flashing, ensure stable power supply and move device closer to router."
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.TextButton("OK", on_click=confirm_ota),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(warning_dialog)

    ota_flash_button.on_click = send_ota

    def send_factory_reset(_):
        def close_dialog(_event=None):
            page.pop_dialog()
            page.update()

        def confirm_reset(_event=None):
            close_dialog()
            try:
                call_api("/esp/command", "POST", {"type": "factory_reset"})
                toast("Factory reset command sent")
            except RuntimeError as e:
                toast(f"Factory reset error: {e}", ok=False)

        warning_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("\u041f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u0435"),
            content=ft.Text(
                "\u0411\u0443\u0434\u0443\u0442 \u0441\u0431\u0440\u043e\u0448\u0435\u043d\u044b \u0432\u0441\u0435 \u043d\u0430\u0441\u0442\u0440\u043e\u0439\u043a\u0438 ESP. \u041f\u0440\u043e\u0434\u043e\u043b\u0436\u0438\u0442\u044c?"
            ),
            actions=[
                ft.TextButton("Cancel", on_click=close_dialog),
                ft.TextButton("OK", on_click=confirm_reset),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(warning_dialog)

    factory_reset_button.on_click = send_factory_reset

    def load_settings():
        try:
            data = call_api("/settings")
        except RuntimeError:
            return

        weather = data.get("weather", {})
        display = data.get("display", {})
        backlight = data.get("backlight", {})
        schedule = data.get("schedule", {})
        ota = data.get("ota", {})
        network = data.get("network", {})

        weather_api_key.value = weather.get("api_key", "")
        weather_lat.value = str(weather.get("latitude", ""))
        weather_lon.value = str(weather.get("longitude", ""))
        weather_timeout.value = str(weather.get("timeout_sec", 1800))

        screen_brightness.value = int(display.get("brightness", 180))
        screen_weather_dependent.value = bool(display.get("weather_dependent", display.get("auto_brightness", False)))

        backlight_brightness.value = int(backlight.get("brightness", display.get("backlight", 180)))
        backlight_mode.value = normalize_led_mode(backlight.get("mode", backlight.get("led_mode", display.get("mode", "5"))))
        backlight_weather_dependent.value = bool(backlight.get("weather_dependent", False))

        display_on.value = str(display.get("on_time", "07:00"))
        display_off.value = str(display.get("off_time", "23:00"))
        ws_port.value = str(network.get("ws_port", 8765))

        schedule_start.value = str(schedule.get("start_time", "07:30"))
        schedule_end.value = str(schedule.get("end_time", "19:30"))

        source_values = ensure_four_sources(schedule.get("sources", []))
        for source_controls, source_data in zip(schedule_sources_controls, source_values):
            source_controls["url"].value = source_data.get("url", "")
            source_controls["stop_name"].value = source_data.get("stop_name", "")
            source_controls["bus_number"].value = source_data.get("bus_number", "")

        try:
            element_picker.set_hex(display.get("accent_color", "#FFAA00"))
        except Exception:
            element_picker.set_hex("#FFAA00")

        try:
            backlight_picker.set_hex(backlight.get("color", "#33CCFF"))
        except Exception:
            backlight_picker.set_hex("#33CCFF")

        ota_url.value = str(ota.get("url", ""))

        toggle_screen_manual()
        toggle_backlight_manual()
        toggle_backlight_color()
        update_settings_summary()
        page.update()

    def collect_schedule_sources() -> list[dict[str, str]]:
        return [
            {
                "url": row["url"].value.strip(),
                "stop_name": row["stop_name"].value.strip(),
                "bus_number": row["bus_number"].value.strip(),
            }
            for row in schedule_sources_controls
        ]

    def save_all_settings(_):
        try:
            ws_port_value = int((ws_port.value or "8765").strip())
        except Exception:
            ws_port_value = 8765

        payload = {
            "weather": {
                "api_key": weather_api_key.value,
                "latitude": weather_lat.value,
                "longitude": weather_lon.value,
                "timeout_sec": int(weather_timeout.value or 1800),
            },
            "display": {
                "brightness": int(screen_brightness.value),
                "weather_dependent": bool(screen_weather_dependent.value),
                "on_time": display_on.value,
                "off_time": display_off.value,
                "accent_color": element_picker.get_hex(),
            },
            "backlight": {
                "brightness": int(backlight_brightness.value),
                "mode": backlight_mode.value,
                "led_mode": int(normalize_led_mode(backlight_mode.value)),
                "weather_dependent": bool(backlight_weather_dependent.value),
                "color": backlight_picker.get_hex() if mode_supports_color(backlight_mode.value) else "",
            },
            "schedule": {
                "start_time": schedule_start.value,
                "end_time": schedule_end.value,
                "sources": collect_schedule_sources(),
            },
            "ota": {
                "url": (ota_url.value or "").strip(),
            },
            "network": {
                "ws_port": max(1, min(ws_port_value, 65535)),
            },
        }

        try:
            result = call_api("/settings", "PUT", payload)
            sent = bool(result.get("sent_to_esp", False))
            esp_connected = bool(result.get("esp_connected", False))
            if sent:
                toast("Settings saved and sent to ESP")
            elif esp_connected:
                toast("Settings saved (no ESP updates needed)")
            else:
                toast("Settings saved locally (ESP offline)")
        except Exception as e:
            toast(f"Save settings error: {e}", ok=False)

    def refresh_status():
        try:
            data = call_api("/status")
        except RuntimeError:
            status_text.value = "ESP: backend unavailable"
            status_dot.bgcolor = ft.Colors.RED_600
            for control in action_controls:
                control.disabled = True
            page.update()
            return

        connected = bool(data.get("esp_connected", False))
        status_text.value = "ESP: connected" if connected else "ESP: disconnected"
        status_dot.bgcolor = ft.Colors.GREEN_500 if connected else ft.Colors.ORANGE_500

        gif_state = data.get("gif_transfer", {})
        gif_message = f"GIF: {gif_state.get('message', 'idle')}"
        gif_value = max(0.0, min(1.0, float(gif_state.get("progress", 0)) / 100.0))
        gif_progress_text.value = gif_message
        gif_progress_bar.value = gif_value
        home_gif_progress_text.value = gif_message
        home_gif_progress_bar.value = gif_value

        ota_state = data.get("ota_transfer", {})
        ota_message = f"OTA: {ota_state.get('message', 'idle')}"
        ota_value = max(0.0, min(1.0, float(ota_state.get("progress", 0)) / 100.0))
        ota_progress_text.value = ota_message
        ota_progress_bar.value = ota_value
        home_ota_progress_text.value = ota_message
        home_ota_progress_bar.value = ota_value

        last_message = str(data.get("last_message") or "")
        last_message_text.value = last_message or "-"
        telemetry_text.value = parse_telemetry(last_message)

        for control in action_controls:
            control.disabled = not connected

        page.update()

    color_apply_button = ft.Button("Apply color", icon=ft.Icons.PALETTE, on_click=send_color)
    screen_apply_button = ft.Button("Apply screen settings", icon=ft.Icons.DISPLAY_SETTINGS, on_click=send_display)
    backlight_apply_button = ft.Button("Apply backlight settings", icon=ft.Icons.LIGHTBULB, on_click=send_backlight)

    home_tab = ft.Column(
        [
            ft.Container(
                padding=16,
                border_radius=16,
                bgcolor="#FFFFFF",
                border=ft.Border.all(1, "#E2E8F0"),
                shadow=ft.BoxShadow(spread_radius=0, blur_radius=14, color="#110F172A", offset=ft.Offset(0, 5)),
                content=ft.Row(
                    [
                        status_dot,
                        status_text,
                        ft.VerticalDivider(width=16, color="#00000000"),
                        ft.TextButton("Refresh now", icon=ft.Icons.REFRESH, on_click=lambda _: refresh_status()),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            ft.ResponsiveRow(
                [
                    ft.Container(col={"sm": 12, "md": 6, "lg": 3}, content=card("Telemetry", telemetry_text)),
                    ft.Container(col={"sm": 12, "md": 6, "lg": 3}, content=card("GIF transfer", ft.Column([home_gif_progress_text, home_gif_progress_bar]))),
                    ft.Container(col={"sm": 12, "md": 6, "lg": 3}, content=card("OTA transfer", ft.Column([home_ota_progress_text, home_ota_progress_bar]))),
                    ft.Container(col={"sm": 12, "md": 6, "lg": 3}, content=card("Current setup", settings_summary)),
                ],
                spacing=12,
                run_spacing=12,
            ),
            card("Last ESP message", last_message_text),
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )

    color_tab = ft.Column(
        [
            ft.Text("Screen colors", size=22, weight=ft.FontWeight.BOLD),
            ft.Row([screen_dropdown, element_dropdown], spacing=12),
            element_picker.root,
            color_apply_button,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )

    gif_tab = ft.Column(
        [
            ft.Text("GIF animations", size=22, weight=ft.FontWeight.BOLD),
            ft.Row([gif_picker_button, gif_send_button], spacing=12),
            gif_file_text,
            gif_editor_status,
            gif_frames_panel,
            gif_progress_text,
            gif_progress_bar,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    screen_tab = ft.Column(
        [
            ft.Text("Screen", size=22, weight=ft.FontWeight.BOLD),
            screen_weather_dependent,
            screen_brightness,
            screen_apply_button,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )

    backlight_tab = ft.Column(
        [
            ft.Text("Backlight", size=22, weight=ft.FontWeight.BOLD),
            backlight_mode,
            backlight_weather_dependent,
            backlight_brightness,
            backlight_picker.root,
            backlight_apply_button,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
    )

    sources_cards = []
    for idx, source in enumerate(schedule_sources_controls, start=1):
        sources_cards.append(
            ft.Container(
                padding=12,
                border_radius=12,
                bgcolor="#F8FAFC",
                border=ft.Border.all(1, "#E2E8F0"),
                content=ft.Column(
                    [
                        ft.Text(f"Source {idx}", weight=ft.FontWeight.W_600),
                        source["url"],
                        ft.Row([source["stop_name"], source["bus_number"]], spacing=10),
                    ],
                    spacing=8,
                ),
            )
        )

    settings_tab = ft.Column(
        [
            ft.Text("System settings", size=22, weight=ft.FontWeight.BOLD),
            weather_api_key,
            ft.Row([weather_lat, weather_lon, weather_timeout], spacing=10),
            ft.Row([display_on, display_off, ws_port], spacing=10),
            ft.Text("Schedule window", size=18, weight=ft.FontWeight.W_600),
            ft.Row([schedule_start, schedule_end], spacing=10),
            ft.Text("Schedule sources", size=18, weight=ft.FontWeight.W_600),
            *sources_cards,
            ft.Button("Save all settings", icon=ft.Icons.SAVE, on_click=save_all_settings),
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    ota_tab = ft.Column(
        [
            ft.Text("OTA", size=22, weight=ft.FontWeight.BOLD),
            ota_url,
            ota_warning_text,
            ota_flash_button,
            ota_progress_text,
            ota_progress_bar,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    reset_tab = ft.Column(
        [
            ft.Text("\u0421\u0431\u0440\u043e\u0441", size=22, weight=ft.FontWeight.BOLD),
            factory_reset_warning_text,
            factory_reset_button,
        ],
        spacing=12,
        scroll=ft.ScrollMode.AUTO,
    )

    action_controls.extend(
        [
            ota_flash_button,
            factory_reset_button,
            color_apply_button,
            screen_apply_button,
            backlight_apply_button,
        ]
    )

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=220,
        length=8,
        expand=1,
        content=ft.Column(
            [
                ft.TabBar(
                    scrollable=True,
                    tabs=[
                        ft.Tab(label="Главная", icon=ft.Icons.HOME),
                        ft.Tab(label="Цвета", icon=ft.Icons.PALETTE),
                        ft.Tab(label="GIF", icon=ft.Icons.MOVIE),
                        ft.Tab(label="Экран", icon=ft.Icons.DISPLAY_SETTINGS),
                        ft.Tab(label="Подсветка", icon=ft.Icons.LIGHTBULB),
                        ft.Tab(label="Настройки", icon=ft.Icons.SETTINGS),
                        ft.Tab(label="\u0421\u0431\u0440\u043e\u0441", icon=ft.Icons.RESTART_ALT),
                        ft.Tab(label="OTA", icon=ft.Icons.SYSTEM_UPDATE_ALT),
                    ],
                ),
                ft.TabBarView(
                    controls=[home_tab, color_tab, gif_tab, screen_tab, backlight_tab, settings_tab, reset_tab, ota_tab],
                    expand=True,
                ),
            ],
            spacing=0,
            expand=True,
        ),
    )

    page.add(tabs)

    update_element_options()
    toggle_screen_manual()
    toggle_backlight_manual()
    toggle_backlight_color()
    update_settings_summary()
    load_settings()
    refresh_status()

    async def polling_loop():
        while True:
            refresh_status()
            await asyncio.sleep(1.2)

    page.run_task(polling_loop)


ft.run(main)
