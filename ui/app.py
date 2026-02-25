import json
import asyncio
import urllib.error
import urllib.request

import flet as ft


API_BASE = "http://127.0.0.1:8787/api"
ELEMENTS = ["city", "time", "weather", "bus", "music", "load"]
GIF_PRESETS = ["metro_loop.gif", "weather_splash.gif", "retro_scan.gif"]


def api_request(path: str, method: str = "GET", data: dict | None = None):
    body = None
    headers = {"Content-Type": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(f"{API_BASE}{path}", data=body, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=4) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def main(page: ft.Page):
    page.title = "ESP32 S3 Control Hub"
    page.theme_mode = ft.ThemeMode.DARK
    page.padding = 16
    page.bgcolor = "#0D1117"
    page.window_width = 1280
    page.window_height = 840

    status_text = ft.Text("ESP: неизвестно", size=16, weight=ft.FontWeight.W_600)
    status_dot = ft.Container(width=12, height=12, border_radius=6, bgcolor=ft.Colors.GREY_500)
    progress_text = ft.Text("")
    progress_bar = ft.ProgressBar(width=320, value=0)

    current_hex = ft.Text("#FFAA00", weight=ft.FontWeight.BOLD)
    selected_element = ft.Dropdown(label="Элемент", value=ELEMENTS[0], options=[ft.dropdown.Option(e) for e in ELEMENTS])

    red = ft.Slider(min=0, max=255, divisions=255, value=255, label="R: {value}")
    green = ft.Slider(min=0, max=255, divisions=255, value=170, label="G: {value}")
    blue = ft.Slider(min=0, max=255, divisions=255, value=0, label="B: {value}")
    color_preview = ft.Container(width=180, height=64, border_radius=12, bgcolor="#FFAA00")

    brightness = ft.Slider(label="Яркость", min=0, max=100, divisions=100, value=70)
    backlight = ft.Slider(label="Подсветка", min=0, max=100, divisions=100, value=70)
    auto_brightness = ft.Switch(label="Автояркость", value=True)
    lighting_mode = ft.Dropdown(label="Режим подсветки", value="static", options=[
        ft.dropdown.Option("static", "Статичный"),
        ft.dropdown.Option("breath", "Дыхание"),
        ft.dropdown.Option("rainbow", "Радуга"),
    ])

    wifi_ssid = ft.TextField(label="Wi‑Fi SSID")
    wifi_password = ft.TextField(label="Wi‑Fi пароль", password=True, can_reveal_password=True)
    weather_api_key = ft.TextField(label="API ключ погоды")
    weather_lat = ft.TextField(label="Широта", value="55.7558")
    weather_lon = ft.TextField(label="Долгота", value="37.6173")
    weather_timeout = ft.TextField(label="Таймаут погоды (сек)", value="1800")
    display_on = ft.TextField(label="Время включения экрана", value="07:00")
    display_off = ft.TextField(label="Время отключения экрана", value="23:00")
    schedule_hours = ft.TextField(label="Расписание на сколько часов вперёд", value="4")
    schedule_sources = ft.TextField(label="Источники расписания (JSON массив ссылок)", multiline=True, min_lines=2)

    gif_dropdown = ft.Dropdown(label="Выбор GIF", value=GIF_PRESETS[0], options=[ft.dropdown.Option(g) for g in GIF_PRESETS])
    frame_checks = ft.Column(scroll=ft.ScrollMode.ADAPTIVE, height=160)

    tabs_controls: list[ft.Control] = []

    def call_api(path: str, method: str = "GET", data: dict | None = None):
        try:
            return api_request(path, method, data)
        except urllib.error.HTTPError as e:
            raise RuntimeError(e.read().decode("utf-8") or str(e))
        except Exception as e:
            raise RuntimeError(str(e))

    def toast(message: str, ok: bool = True):
        page.snack_bar = ft.SnackBar(ft.Text(message), bgcolor=ft.Colors.GREEN_700 if ok else ft.Colors.RED_700)
        page.snack_bar.open = True
        page.update()

    def sync_color(_=None):
        hex_color = f"#{int(red.value):02X}{int(green.value):02X}{int(blue.value):02X}"
        current_hex.value = hex_color
        color_preview.bgcolor = hex_color
        page.update()

    red.on_change = sync_color
    green.on_change = sync_color
    blue.on_change = sync_color

    def load_settings():
        try:
            data = call_api("/settings")
        except RuntimeError:
            return

        wifi = data.get("wifi", {})
        weather = data.get("weather", {})
        display = data.get("display", {})
        schedule = data.get("schedule", {})

        wifi_ssid.value = wifi.get("ssid", "")
        wifi_password.value = wifi.get("password", "")
        weather_api_key.value = weather.get("api_key", "")
        weather_lat.value = str(weather.get("latitude", ""))
        weather_lon.value = str(weather.get("longitude", ""))
        weather_timeout.value = str(weather.get("timeout_sec", 1800))
        brightness.value = display.get("brightness", 70)
        backlight.value = display.get("backlight", 70)
        auto_brightness.value = display.get("auto_brightness", True)
        lighting_mode.value = display.get("mode", "static")
        display_on.value = display.get("on_time", "07:00")
        display_off.value = display.get("off_time", "23:00")
        schedule_hours.value = str(schedule.get("hours_ahead", 4))
        schedule_sources.value = json.dumps(schedule.get("sources", []), ensure_ascii=False, indent=2)

    def refresh_status():
        try:
            data = call_api("/status")
        except RuntimeError:
            status_text.value = "ESP: backend недоступен"
            status_dot.bgcolor = ft.Colors.RED_600
            for c in tabs_controls:
                c.disabled = True
            page.update()
            return

        connected = data.get("esp_connected", False)
        status_text.value = "ESP: подключена" if connected else "ESP: не подключена"
        status_dot.bgcolor = ft.Colors.GREEN_500 if connected else ft.Colors.ORANGE_500

        gif_state = data.get("gif_transfer", {})
        progress_text.value = gif_state.get("message", "")
        progress_bar.value = gif_state.get("progress", 0) / 100

        for c in tabs_controls:
            c.disabled = not connected

        page.update()

    def send_color(_):
        payload = {
            "screen": "screen1",
            "element": selected_element.value,
            "color": current_hex.value,
        }
        try:
            call_api("/esp/color", "POST", payload)
            toast("Цвет отправлен")
        except RuntimeError as e:
            toast(f"Ошибка: {e}", ok=False)

    def send_display(_):
        payload = {
            "brightness": int(brightness.value),
            "backlight": int(backlight.value),
            "mode": lighting_mode.value,
            "auto_brightness": auto_brightness.value,
        }
        try:
            call_api("/esp/display", "POST", payload)
            toast("Настройки экрана отправлены")
        except RuntimeError as e:
            toast(f"Ошибка: {e}", ok=False)

    def populate_frames(_=None):
        frame_checks.controls.clear()
        for i in range(1, 21):
            frame_checks.controls.append(ft.Checkbox(label=f"Кадр {i}: удалить"))
        page.update()

    def send_gif(_):
        remove_frames = [idx + 1 for idx, c in enumerate(frame_checks.controls) if c.value]
        payload = {"name": gif_dropdown.value, "remove_frames": remove_frames}
        try:
            call_api("/esp/gif", "POST", payload)
            toast("GIF отправка запущена")
        except RuntimeError as e:
            toast(f"Ошибка: {e}", ok=False)

    def save_all_settings(_):
        try:
            sources = json.loads(schedule_sources.value or "[]")
            payload = {
                "wifi": {"ssid": wifi_ssid.value, "password": wifi_password.value},
                "weather": {
                    "api_key": weather_api_key.value,
                    "latitude": weather_lat.value,
                    "longitude": weather_lon.value,
                    "timeout_sec": int(weather_timeout.value or 1800),
                },
                "display": {
                    "brightness": int(brightness.value),
                    "backlight": int(backlight.value),
                    "mode": lighting_mode.value,
                    "auto_brightness": auto_brightness.value,
                    "on_time": display_on.value,
                    "off_time": display_off.value,
                },
                "schedule": {
                    "hours_ahead": int(schedule_hours.value or 4),
                    "sources": sources,
                },
            }
            call_api("/settings", "PUT", payload)
            toast("Все настройки сохранены")
        except Exception as e:
            toast(f"Ошибка сохранения: {e}", ok=False)

    device_card = ft.Container(
        width=500,
        height=320,
        border_radius=24,
        padding=20,
        gradient=ft.LinearGradient(["#1F2937", "#111827"]),
        content=ft.Stack([
            ft.Container(width=460, height=260, top=10, left=0, border_radius=16, bgcolor="#0B1220"),
            ft.Container(width=280, height=160, top=60, left=90, border_radius=12, bgcolor="#1D4ED8"),
            ft.Text("ESP32 S3 DISPLAY", top=22, left=140, color=ft.Colors.BLUE_100, size=20, weight=ft.FontWeight.BOLD),
            ft.Container(width=70, height=12, top=240, left=195, border_radius=6, bgcolor="#374151"),
        ]),
    )

    home_tab = ft.Column([
        ft.Row([status_dot, status_text], alignment=ft.MainAxisAlignment.CENTER),
        ft.Container(height=16),
        ft.Row([device_card], alignment=ft.MainAxisAlignment.CENTER),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    color_tab = ft.Column([
        ft.Text("Цвета элементов", size=22, weight=ft.FontWeight.BOLD),
        selected_element,
        ft.Row([red, green, blue]),
        ft.Row([color_preview, current_hex]),
        ft.ElevatedButton("Применить цвет", icon=ft.Icons.PALETTE, on_click=send_color),
    ], scroll=ft.ScrollMode.AUTO)

    gif_tab = ft.Column([
        ft.Text("GIF анимации", size=22, weight=ft.FontWeight.BOLD),
        gif_dropdown,
        ft.ElevatedButton("Сгенерировать список кадров", on_click=populate_frames, icon=ft.Icons.ANIMATION),
        frame_checks,
        ft.ElevatedButton("Отправить GIF", icon=ft.Icons.UPLOAD_FILE, on_click=send_gif),
        progress_text,
        progress_bar,
    ], scroll=ft.ScrollMode.AUTO)

    display_tab = ft.Column([
        ft.Text("Экран и подсветка", size=22, weight=ft.FontWeight.BOLD),
        brightness,
        backlight,
        lighting_mode,
        auto_brightness,
        ft.ElevatedButton("Отправить настройки экрана", icon=ft.Icons.TUNE, on_click=send_display),
    ], scroll=ft.ScrollMode.AUTO)

    settings_tab = ft.Column([
        ft.Text("Системные настройки", size=22, weight=ft.FontWeight.BOLD),
        wifi_ssid,
        wifi_password,
        weather_api_key,
        ft.Row([weather_lat, weather_lon, weather_timeout]),
        ft.Row([display_on, display_off, schedule_hours]),
        schedule_sources,
        ft.ElevatedButton("Сохранить все настройки", icon=ft.Icons.SAVE, on_click=save_all_settings),
    ], scroll=ft.ScrollMode.AUTO)

    tabs_controls.extend([color_tab, gif_tab, display_tab, settings_tab])

    tabs = ft.Tabs(
        selected_index=0,
        animation_duration=200,
        tabs=[
            ft.Tab(text="Главная", icon=ft.Icons.HOME, content=home_tab),
            ft.Tab(text="Цвета", icon=ft.Icons.PALETTE, content=color_tab),
            ft.Tab(text="GIF", icon=ft.Icons.MOVIE, content=gif_tab),
            ft.Tab(text="Экран", icon=ft.Icons.LIGHT_MODE, content=display_tab),
            ft.Tab(text="Настройки", icon=ft.Icons.SETTINGS, content=settings_tab),
        ],
        expand=1,
    )

    page.add(tabs)

    load_settings()
    populate_frames()
    sync_color()
    refresh_status()

    async def polling_loop():
        while True:
            refresh_status()
            await asyncio.sleep(1.2)

    page.run_task(polling_loop)


ft.app(target=main)
