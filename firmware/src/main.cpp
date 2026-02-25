#include <Arduino.h>
#include <lvgl.h>
#include <LovyanGFX.hpp>
#include <ui.h>
#include <WiFi.h>
#include <Preferences.h>
#include <WebServer.h>
#include <ArduinoJson.h>
#include <time.h>
#include <ArduinoOTA.h>
#include <LittleFS.h>
#include <freertos/semphr.h>
#include <Adafruit_BME280.h>
#include <Wire.h>

#include "app_state.h"
#include "ws_client.h"
#include "ws_protocol.h"
#include "led_effects.h"
#include "bus_schedule.h"
#include "weather.h"
#include "device_control.h"
#include "ui_logic.h"
#include "helpers.h"
#include "bme_manager.h"

Adafruit_BME280 bme;
bool bmeInitialized = false;

// Глобальный мьютекс
SemaphoreHandle_t uiMutex;

void handleRoot();
void handleConfig();

hw_timer_t *lv_tick_hw_timer = NULL;

void IRAM_ATTR lv_tick_cb()
{
  lv_tick_inc(1);
}

TaskHandle_t lvglTaskHandle;

void lvglTask(void *pvParameters)
{
  while (1)
  {
    if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
    {
      lv_timer_handler();
      xSemaphoreGive(uiMutex);
    }
    vTaskDelay(pdMS_TO_TICKS(5));
  }
}

// --- НОВАЯ ЗАДАЧА ДЛЯ ПОГОДЫ ---
// Она работает в фоне и не тормозит кнопку
void weatherTask(void *pvParameters)
{
  vTaskDelay(pdMS_TO_TICKS(2000));
  while (1)
  {
    // Обновляем погоду раз в 10 минут, но только если есть WiFi
    if (appState.wifiConnected)
    {
      // updateWeather делает HTTP запрос - это долго, поэтому делаем это БЕЗ мьютекса UI
      // Но внутри updateWeather мы пишем в структуру weatherData.
      // В идеале нужен мьютекс данных, но пока просто аккуратно.
      updateWeather();

      // А вот обновить дисплей нужно с мьютексом
      if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
      {
        updateWeatherDisplay();
        xSemaphoreGive(uiMutex);
      }
    }
    // Спим 10 минут (600000 мс)
    vTaskDelay(pdMS_TO_TICKS(600000));
  }
}
// -------------------------------

// Display configuration
static const uint16_t screenWidth = 240;
static const uint16_t screenHeight = 240;
static lv_disp_draw_buf_t draw_buf;
static lv_color_t *buf1;
static lv_color_t *buf2;
bool webServerRunning = false;

class LGFX : public lgfx::LGFX_Device
{
public:
  lgfx::Panel_ST7789 _panel_instance;
  lgfx::Bus_SPI _bus_instance;
  LGFX(void)
  {
    {
      auto cfg = _bus_instance.config();
      cfg.spi_host = SPI2_HOST;
      cfg.spi_mode = 0;
      cfg.freq_write = 80000000;
      cfg.freq_read = 16000000;
      cfg.spi_3wire = true;
      cfg.use_lock = true;
      cfg.dma_channel = SPI_DMA_CH_AUTO;
      cfg.pin_sclk = 12;
      cfg.pin_mosi = 11;
      cfg.pin_miso = -1;
      cfg.pin_dc = 6;
      _bus_instance.config(cfg);
      _panel_instance.setBus(&_bus_instance);
    }
    {
      auto cfg = _panel_instance.config();
      cfg.pin_cs = 10;
      cfg.pin_rst = 7;
      cfg.panel_width = 240;
      cfg.panel_height = 240;
      cfg.invert = true;
      cfg.rgb_order = false;
      _panel_instance.config(cfg);
    }
    setPanel(&_panel_instance);
  }
};
LGFX tft;
WebServer server(80);

void my_disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p)
{
  uint32_t w = (area->x2 - area->x1 + 1);
  uint32_t h = (area->y2 - area->y1 + 1);

  tft.startWrite();
  tft.setAddrWindow(area->x1, area->y1, w, h);
  tft.writePixels((lgfx::rgb565_t *)&color_p->full, w * h);
  tft.endWrite();

  lv_disp_flush_ready(disp);
}

void my_touchpad_read(lv_indev_drv_t *indev_driver, lv_indev_data_t *data)
{
  data->state = LV_INDEV_STATE_REL;
}

void loadConfig()
{
  Preferences prefs;
  prefs.begin("deskhub", true);
  appState.isFirstBoot = prefs.getBool("firstBoot", true);
  if (!appState.isFirstBoot)
  {
    appState.wifiSSID = prefs.getString("wifiSSID", "");
    appState.wifiPassword = prefs.getString("wifiPassword", "");
    appState.pcIP = prefs.getString("pcIP", "");
    appState.openWeatherAPIKey = prefs.getString("weatherKey", "");
    appState.weatherLat = prefs.getFloat("weatherLat", 0.0);
    appState.weatherLon = prefs.getFloat("weatherLon", 0.0);
    appState.useCoordinates = prefs.getBool("useCoords", false);
  }

  appState.animWidth = prefs.getInt("animWidth", 0);
  appState.animHeight = prefs.getInt("animHeight", 0);
  appState.animFrames = prefs.getInt("animFrames", 0);
  appState.animDelay = prefs.getInt("animDelay", 100);
  prefs.end();
}

void setupOTA()
{
  ArduinoOTA.setHostname("deskhub");
  ArduinoOTA.begin();
}

void setupWebServer()
{
  server.on("/", handleRoot);
  server.on("/config", HTTP_POST, handleConfig);
  server.begin();
  webServerRunning = true;
}

void handleRoot()
{
  File file = LittleFS.open("/index.html", "r");
  if (!file)
  {
    server.send(500, "text/plain", "index.html not found");
    return;
  }
  server.streamFile(file, "text/html");
  file.close();
}

void handleConfig()
{
  if (server.hasArg("ssid"))
  {
    appState.wifiSSID = server.arg("ssid");
    appState.wifiPassword = server.arg("password");
    appState.pcIP = server.arg("pcip");
    appState.openWeatherAPIKey = server.arg("weatherkey");
    if (server.hasArg("lat"))
    {
      appState.weatherLat = server.arg("lat").toFloat();
    }
    if (server.hasArg("lon"))
    {
      appState.weatherLon = server.arg("lon").toFloat();
    }

    appState.useCoordinates = true;

    Preferences prefs;
    prefs.begin("deskhub", false);
    prefs.putString("wifiSSID", appState.wifiSSID);
    prefs.putString("wifiPassword", appState.wifiPassword);
    prefs.putString("pcIP", appState.pcIP);
    prefs.putString("weatherKey", appState.openWeatherAPIKey);
    prefs.putFloat("weatherLat", appState.weatherLat);
    prefs.putFloat("weatherLon", appState.weatherLon);
    prefs.putBool("useCoords", appState.useCoordinates);

    prefs.putBool("firstBoot", false);
    prefs.end();

    server.send(200, "text/html", "<h1>Configuration Saved! Restarting...</h1>");
    delay(1000);
    ESP.restart();
  }
  else
  {
    server.send(400, "text/plain", "Bad Request");
  }
}

void time_update_cb(lv_timer_t *timer)
{
  updateTimeDisplay();
}

// Изменили функцию WiFi - она теперь возвращает bool, а не висит вечно
bool connectWiFi()
{
  if (appState.isFirstBoot || appState.wifiSSID.length() == 0)
  {
    Serial.println("[WiFi] AP mode");
    WiFi.mode(WIFI_AP);
    WiFi.softAP("deskhub", "");
    setupWebServer();
    return false;
  }
  appState.isDataLoading = true;
  updateConnectionStatus();
  WiFi.mode(WIFI_STA);
  IPAddress primaryDNS(8, 8, 8, 8);
  IPAddress secondaryDNS(8, 8, 4, 4);
  WiFi.config(INADDR_NONE, INADDR_NONE, INADDR_NONE,
              primaryDNS, secondaryDNS);
  WiFi.begin(appState.wifiSSID.c_str(),
             appState.wifiPassword.c_str());
  Serial.print("[WiFi] Connecting");
  unsigned long startAttemptTime = millis();
  while (WiFi.status() != WL_CONNECTED &&
         millis() - startAttemptTime < 10000)
  {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  if (WiFi.status() == WL_CONNECTED)
  {
    Serial.println("[WiFi] Connected!");
    appState.wifiConnected = true;
    WiFi.softAPdisconnect(true);
    setupOTA();
    appState.isDataLoading = false;
    updateConnectionStatus();

    // Ждём DNS (не более 10 секунд)
    IPAddress ip;
    int tries = 0;

    while (!WiFi.hostByName("google.com", ip))
    {
      Serial.println("[WiFi] Waiting for DNS...");
      delay(1000);
      tries++;

      if (tries >= 10)
      {
        Serial.println("[WiFi] DNS failed! Restarting...");
        delay(1000);
        ESP.restart();
      }
    }

    Serial.print("[WiFi] DNS OK: ");
    Serial.println(ip);
    return true;
  }

  // ❌ Если не подключились за 10 секунд — перезагрузка
  appState.isDataLoading = false;
  updateConnectionStatus();
  Serial.println("[WiFi] Failed! Restarting...");
  delay(1000);
  ESP.restart();

  return false; // формально, но до сюда не дойдёт
}

void setup()
{
  Serial.begin(115200);
  delay(100); // Небольшая пауза для стабилизации питания

  uiMutex = xSemaphoreCreateMutex();

  if (!LittleFS.begin(true))
    Serial.println("[LittleFS] Mount failed");
  Serial.printf("LittleFS: %u / %u bytes used\n", LittleFS.usedBytes(), LittleFS.totalBytes());

  // 1. Init display
  tft.init();
  tft.setRotation(0);
  tft.setBrightness(255);
  tft.fillScreen(0x0000); // Сразу черный, без красного

  // 2. Init LVGL
  lv_init();

  // Запускаем задачу LVGL сразу, чтобы мы могли рисовать экран загрузки
  // xTaskCreatePinnedToCore(lvglTask, "LVGL", 8192, NULL, 1, &lvglTaskHandle, 1);
  xTaskCreatePinnedToCore(lvglTask, "LVGL", 16384, NULL, 1, &lvglTaskHandle, 1);

  lv_tick_hw_timer = timerBegin(0, 80, true);
  timerAttachInterrupt(lv_tick_hw_timer, &lv_tick_cb, true);
  timerAlarmWrite(lv_tick_hw_timer, 1000, true);
  timerAlarmEnable(lv_tick_hw_timer);

  // Alloc buffers
  // buf1 = (lv_color_t *)heap_caps_malloc(screenWidth * 30 * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  // buf2 = (lv_color_t *)heap_caps_malloc(screenWidth * 30 * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  // lv_disp_draw_buf_init(&draw_buf, buf1, buf2, screenWidth * 30);
  size_t fullBufferSize = screenWidth * screenHeight * sizeof(lv_color_t);

  buf1 = (lv_color_t *)heap_caps_malloc(fullBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  buf2 = (lv_color_t *)heap_caps_malloc(fullBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!buf1 || !buf2)
  {
    Serial.println("Failed to allocate full screen buffer in PSRAM!");
  }
  lv_disp_draw_buf_init(&draw_buf, buf1, buf2, screenWidth * screenHeight);

  static lv_disp_drv_t disp_drv;
  lv_disp_drv_init(&disp_drv);
  disp_drv.hor_res = screenWidth;
  disp_drv.ver_res = screenHeight;
  disp_drv.flush_cb = my_disp_flush;
  disp_drv.draw_buf = &draw_buf;
  lv_disp_drv_register(&disp_drv);

  static lv_indev_drv_t indev_drv;
  lv_indev_drv_init(&indev_drv);
  indev_drv.type = LV_INDEV_TYPE_POINTER;
  indev_drv.read_cb = my_touchpad_read;
  lv_indev_drv_register(&indev_drv);

  loadConfig();

  if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
  {
    ui_init(); // Инициализируем все экраны из ui.c

    // ПРИНУДИТЕЛЬНО ПЕРЕКЛЮЧАЕМ НА SCREEN 5
    // В SquareLine Studio объект обычно называется ui_Screen5
    if (ui_Screen5)
    {
      lv_scr_load(ui_Screen5);
    }
    xSemaphoreGive(uiMutex);
  }

  // --- Выполняем все "тяжелые" инициализации ---
  initDeviceControl();
  extern void initButton();
  initButton();
  initLeds();
  initBusSchedule();
  initWeather();

  // Подключаемся к WiFi (здесь будет пауза до 10 сек, пока висит Screen5)
  connectWiFi();

  if (appState.wifiConnected)
  {
    updateWeather();
  }

  initWebSocketClient();

  Wire.begin(14, 15); // ← свои SDA/SCL

  if (bme.begin(0x76))
  {
    Serial.println("[BME280] Initialized");
    bmeInitialized = true;
  }
  else if (bme.begin(0x77))
  {
    Serial.println("[BME280] Initialized at 0x77");
    bmeInitialized = true;
  }
  else
  {
    Serial.println("[BME280] Not found!");
  }

  // Синхронизируем данные для Screen 1 перед переключением
  if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
  {
    updateTimeDisplay();
    updateWeatherDisplay();
    updateConnectionStatus();

    // === ПЕРЕХОД НА ОСНОВНОЙ ЭКРАН (Screen 1) ===
    // Делаем это с небольшой задержкой или анимацией, чтобы пользователь успел увидеть Splash
    if (!appState.isFirstBoot)
    {
      delay(500);
      if (ui_Screen1)
      {
        lv_scr_load_anim(ui_Screen1, LV_SCR_LOAD_ANIM_FADE_ON, 500, 0, false);
      }
    }
    appState.currentScreen = SCREEN_1;
    startAnimation();

    xSemaphoreGive(uiMutex);
  }

  // Запуск фоновых задач
  xTaskCreatePinnedToCore(weatherTask, "WeatherTask", 4096, NULL, 0, NULL, 0);
  lv_timer_create(time_update_cb, 1000, NULL);

  Serial.println("[Setup] Complete - entering loop");
}

void loop()
{
  handleButtonPress();
  updateWebSocketClient();
  if (!appState.wifiConnected)
  {
    static unsigned long lastRetry = 0;

    if (millis() - lastRetry > 10000)
    {
      connectWiFi();
      lastRetry = millis();
    }
  }

  if (webServerRunning)
    server.handleClient();
  if (appState.wifiConnected)
    ArduinoOTA.handle();

  static unsigned long lastAutoUpdate = 0;
  if (millis() - lastAutoUpdate > 1000)
  {
    updateAutoBrightness();
    lastAutoUpdate = millis();
  }

  updateLeds();
  handleScreen2Timeout();
  handleScreen7Timeout();
  updateSleepMode();

  // Обновляем экраны (UI логику), защищая мьютексом
  static unsigned long lastUiUpdate = 0;
  if (millis() - lastUiUpdate > 500)
  { // Обновляем текст раз в полсекунды
    if (xSemaphoreTake(uiMutex, (TickType_t)10) == pdTRUE)
    {
      if (appState.currentScreen == SCREEN_1)
        updateScreen1();
      if (appState.currentScreen == SCREEN_4)
        updateScreen4();
      if (appState.currentScreen == SCREEN_6)
        updateScreen6();

      xSemaphoreGive(uiMutex);
    }
    lastUiUpdate = millis();
  }
  // Даем процессору немного выдохнуть, чтобы FreeRTOS переключил задачи
  delay(5);
}