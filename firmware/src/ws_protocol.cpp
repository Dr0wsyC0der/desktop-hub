#include "ws_protocol.h"
#include "app_state.h"
#include "device_control.h"
#include "bus_schedule.h"
#include "ui_logic.h"
#include "helpers.h"
#include "led_effects.h"
#include "weather.h"
#include "ota_manager.h"
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <HTTPClient.h>
#include <ui.h>
#include "ws_client.h"
#include <Preferences.h>
#include <math.h>
#include <stdlib.h>

namespace
{
    bool otaCallbackRegistered = false;

    bool parseLedColorValue(JsonVariantConst value, uint32_t &outColor)
    {
        if (value.is<const char *>())
        {
            String color = value.as<String>();
            color.trim();

            if (color.startsWith("#"))
            {
                color.remove(0, 1);
            }
            else if (color.startsWith("0x") || color.startsWith("0X"))
            {
                color.remove(0, 2);
            }

            if (color.length() != 6)
            {
                return false;
            }

            char *end = nullptr;
            unsigned long parsed = strtoul(color.c_str(), &end, 16);
            if (end == color.c_str() || *end != '\0')
            {
                return false;
            }

            outColor = parsed & 0xFFFFFF;
            return true;
        }

        if (value.is<uint32_t>() || value.is<unsigned long>() || value.is<int>())
        {
            outColor = value.as<uint32_t>() & 0xFFFFFF;
            return true;
        }

        return false;
    }

    bool parseFloatValue(JsonVariantConst value, float &outValue)
    {
        if (value.is<float>() || value.is<double>() || value.is<int>() || value.is<long>())
        {
            outValue = value.as<float>();
            return true;
        }

        if (value.is<const char *>())
        {
            String raw = value.as<String>();
            raw.trim();
            if (raw.length() == 0)
            {
                return false;
            }

            char *end = nullptr;
            float parsed = strtof(raw.c_str(), &end);
            if (end == raw.c_str() || *end != '\0')
            {
                return false;
            }

            outValue = parsed;
            return true;
        }

        return false;
    }

    bool tryParseFloatFromKey(JsonDocument &doc, const char *key, float &outValue)
    {
        if (!doc.containsKey(key))
        {
            return false;
        }
        return parseFloatValue(doc[key], outValue);
    }

    void onOtaEvent(int progress, const char *stage, const char *message)
    {
        DynamicJsonDocument response(256);
        response["type"] = "ota_status";
        response["stage"] = stage;
        response["progress"] = progress;

        if (message && message[0] != '\0')
        {
            response["message"] = message;
        }

        String out;
        serializeJson(response, out);
        sendWebSocketMessage(out);
    }
}

void processWebSocketMessage(const String &message)
{
    DynamicJsonDocument doc(2048);
    DeserializationError error = deserializeJson(doc, message);

    if (error)
    {
        Serial.print("[WS] JSON parse error: ");
        Serial.println(error.c_str());
        return;
    }

    processJSONCommand(doc);
}

void processJSONCommand(JsonDocument &doc)
{
    String type = doc["type"] | "";

    if (type == "volume")
    {
        // Достаем значение из глубины: payload -> value
        int volValue = doc["value"] | 0;
        handleVolumeCommand(volValue);
        return; // Выходим, так как команда обработана
    }
    if (type == "schedule")
    {
        // Берем мьютекс, так как обновление расписания трогает UI (создает объекты)
        if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
        {
            // Извлекаем объект payload (в нем лежат today и tomorrow)
            JsonObject schedulePayload = doc["payload"];
            handleBusScheduleCommand(schedulePayload);
            xSemaphoreGive(uiMutex);
        }
        return;
    }
    if (type == "music")
    {
        String name = doc["name"] | "";
        String author = doc["author"] | "";

        if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
        {
            if (ui_songname)
            {
                String formatted = "-" + name + "-";
                lv_label_set_text(ui_songname, formatted.c_str());
                lv_label_set_long_mode(ui_songname, LV_LABEL_LONG_SCROLL_CIRCULAR);
                lv_obj_set_style_anim_speed(ui_songname, 30, 0);
            }

            if (ui_songauthor)
            {
                lv_label_set_text(ui_songauthor, author.c_str());
                lv_label_set_long_mode(ui_songauthor, LV_LABEL_LONG_SCROLL_CIRCULAR);
                lv_obj_set_style_anim_speed(ui_songauthor, 30, 0);
            }

            xSemaphoreGive(uiMutex);
        }

        appState.screen7Active = true;
        appState.screen7StartTime = millis();

        switchScreen(SCREEN_7);
    }

    // --- СТАРЫЙ ФОРМАТ (для совместимости) ---
    else if (type == "pc_load")
    {
        handlePcLoadCommand(doc);
    }
    else if (type == "set_color")
    {
        if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
        {
            handleSetColorCommand(doc);
            xSemaphoreGive(uiMutex);
        }
    }
    else if (type == "settings")
    {
        handleSettingsCommand(doc);
    }
    else if (type == "led" || type == "led_state" || type == "lighting")
    {
        handleLedStateCommand(doc);
    }
    else if (type == "ota")
    {
        handleOtaCommand(doc);
    }
    else if (type == "get_schedule_data")
    {
        DynamicJsonDocument response(256);
        response["type"] = "schedule_date";
        response["date"] = busScheduleData.scheduleDate;

        String out;
        serializeJson(response, out);
        sendWebSocketMessage(out);
    }
    else if (type == "set_gif")
    {
        // 1. ОСТАНАВЛИВАЕМ ПЛЕЙБЕК, ЧТОБЫ ОСВОБОДИТЬ /anim.bin
        stopAnimation();

        if (animFile)
        {
            animFile.close(); // ГАРАНТИРОВАННО ЗАКРЫВАЕМ
        }

        // Теперь LittleFS даст его удалить

        // 1. Считываем параметры
        appState.animFrames = doc["frames"] | 0;
        appState.animWidth = doc["width"] | 0;
        appState.animHeight = doc["height"] | 0;
        appState.animTotalSize = doc["total_size"] | 0;
        appState.animDelay = doc["delay"] | 100;

        Preferences prefs;
        prefs.begin("deskhub", false);

        prefs.putInt("animWidth", appState.animWidth);
        prefs.putInt("animHeight", appState.animHeight);
        prefs.putInt("animFrames", appState.animFrames);
        prefs.putInt("animDelay", appState.animDelay);

        prefs.end();

        // RGB565 = 2 байта на пиксель
        appState.animFrameSize = appState.animWidth * appState.animHeight * 2;
        appState.animReceivedBytes = 0;

        if (appState.animFrames <= 0 || appState.animWidth <= 0 || appState.animHeight <= 0 || appState.animTotalSize == 0)
        {
            Serial.printf("[Anim] Invalid metadata: frames=%d size=%dx%d total=%u\n",
                          appState.animFrames,
                          appState.animWidth,
                          appState.animHeight,
                          appState.animTotalSize);
            appState.animReceiving = false;
            appState.isDataLoading = false;
            updateConnectionStatus();
            return;
        }

        Serial.printf("[Anim] Start: %d frames, %dx%d, total %d bytes\n",
                      appState.animFrames, appState.animWidth, appState.animHeight, appState.animTotalSize);

        // 2. Подготовка файла
        if (LittleFS.exists("/anim.bin"))
            LittleFS.remove("/anim.bin");

        animFile = LittleFS.open("/anim.bin", "w", true);

        if (!animFile)
        {
            Serial.println("[Anim] Failed to create file!");
            return;
        }

        // 3. Включаем режим приема бинарных данных
        appState.animReceiving = true;
        appState.isDataLoading = true;
        updateConnectionStatus();
    }
    else if (type == "factory_reset")
    {
        Serial.println("[WS] Factory reset requested!");

        // Очищаем Preferences
        Preferences prefs;
        prefs.begin("deskhub", false);
        prefs.clear();
        prefs.end();

        // Удаляем файлы с флэша
        LittleFS.remove("/bus_schedule.json");
        LittleFS.remove("/anim.bin");

        Serial.println("[WS] Settings cleared. Restarting...");
        delay(500);
        ESP.restart();
    }
}

// void handleVolumeCommand(int volume)
// {
//     appState.volumeLevel = constrain(volume, 0, 100);
//     appState.volumeModeActive = true;
//     appState.previousScreen = appState.currentScreen;

//     // switchScreen внутри берет мьютекс, так что здесь не надо
//     switchScreen(SCREEN_2);

//     appState.screen2Active = true;
//     appState.screen2StartTime = millis();

//     // А вот тут ручное обновление UI, нужен мьютекс
//     if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
//     {
//         if (ui_soundbar)
//         {
//             lv_bar_set_value(ui_soundbar, appState.volumeLevel, LV_ANIM_ON);
//         }
//         if (ui_volume_value)
//         {
//             char buf[10];
//             snprintf(buf, sizeof(buf), "%d%%", appState.volumeLevel);
//             lv_label_set_text(ui_volume_value, buf);
//         }
//         xSemaphoreGive(uiMutex);
//     }

//     playSound(800, 50);
// }

void handleVolumeCommand(int volume)
{
    // Если это только что пришедший сигнал громкости (первый в серии)
    if (!appState.volumeModeActive)
    {
        startVolumeMode(volume);
        appState.previousScreen = appState.currentScreen; // Запоминаем текущий экран
    }

    appState.volumeLevel = constrain(volume, 0, 100);
    appState.screen2StartTime = millis(); // Обновляем таймер, чтобы экран не закрылся раньше времени

    // Переключаем экран на SCREEN_2 (где полоска громкости)
    if (appState.currentScreen != SCREEN_2)
    {
        switchScreen(SCREEN_2);
        appState.screen2Active = true;
    }

    // Обновляем визуальные элементы (бар и цифры)
    if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
    {
        if (ui_soundbar)
            lv_bar_set_value(ui_soundbar, appState.volumeLevel, LV_ANIM_ON);
        if (ui_volume_value)
        {
            char buf[10];
            snprintf(buf, sizeof(buf), "%d%%", appState.volumeLevel);
            lv_label_set_text(ui_volume_value, buf);
        }
        xSemaphoreGive(uiMutex);
    }
}

void handleBusScheduleCommand(JsonObject doc)
{
    // Эта функция вызывается внутри мьютекса из processJSONCommand
    busScheduleData.today.clear();
    busScheduleData.tomorrow.clear();

    if (doc.containsKey("date"))
    {
        busScheduleData.scheduleDate = doc["date"].as<String>();
    }

    if (doc.containsKey("today"))
    {
        JsonArray todayArray = doc["today"];
        for (JsonObject bus : todayArray)
        {
            BusSchedule busSchedule;
            busSchedule.name = bus["name"] | "";
            busSchedule.url = bus["url"] | "";
            busSchedule.stopName = bus["stop_name"] | "";

            JsonArray timesArray = bus["times"];
            for (String time : timesArray)
            {
                busSchedule.times.push_back(time);
            }
            busScheduleData.today.push_back(busSchedule);
        }
    }

    if (doc.containsKey("tomorrow"))
    {
        JsonArray tomorrowArray = doc["tomorrow"];
        for (JsonObject bus : tomorrowArray)
        {
            BusSchedule busSchedule;
            busSchedule.name = bus["name"] | "";
            busSchedule.url = bus["url"] | "";
            busSchedule.stopName = bus["stop_name"] | "";

            JsonArray timesArray = bus["times"];
            for (String time : timesArray)
            {
                busSchedule.times.push_back(time);
            }
            busScheduleData.tomorrow.push_back(busSchedule);
        }
    }

    busScheduleData.hasData = true;
    busScheduleData.lastDay = -1;
    saveBusScheduleToFlash();
    updateBusScheduleDisplay();
}

void handlePcLoadCommand(JsonDocument &doc)
{
    if (appState.currentScreen == SCREEN_4)
    {
        JsonObject obj = doc.as<JsonObject>();
        pcLoadData.cpu = (int)obj["cpu"];
        pcLoadData.gpu = (int)obj["gpu"];
        pcLoadData.ram = (int)obj["ram"];
        Serial.printf("CPU: %d GPU: %d RAM: %d\n",
                      pcLoadData.cpu,
                      pcLoadData.gpu,
                      pcLoadData.ram);
        pcLoadData.active = true;
        pcLoadData.lastUpdate = millis();
    }
}

void handleSetColorCommand(JsonDocument &doc)
{
    // Вызывается внутри мьютекса
    String screen = doc["screen"] | "";
    String element = doc["element"] | "";
    String colorHex = doc["color"] | "";

    lv_color_t lvColor = hexToColor(colorHex);
    lv_obj_t *target = nullptr;
    if (screen == "screen1")
    {
        if (element == "city")
            target = ui_city;
        else if (element == "region")
            target = ui_region;
        else if (element == "main_hours")
            target = ui_main_hours;
        else if (element == "main_minute")
            target = ui_main_minute;
        else if (element == "main_seconds")
            target = ui_main_seconds;
        else if (element == "date")
            target = ui_date;
        else if (element == "day")
            target = ui_day;
        else if (element == "simb_weather")
            target = ui_simb_weather;
        else if (element == "templabel")
            target = ui_templabel;
        else if (element == "hmlabel")
            target = ui_hmlabel;
        else if (element == "other_weather")
            target = ui_other_weather;
    }
    else if (screen == "screen2")
    {
        if (element == "volume_value")
            target = ui_volume_value;
    }
    else if (screen == "screen3")
    {
        if (element == "hours")
            target = ui_hours;
        else if (element == "minutes")
            target = ui_minutes;
    }
    else if (screen == "screen4")
    {
        if (element == "cpulabel")
            target = ui_cpulabel;
        else if (element == "gpulabel")
            target = ui_gpulabel;
        else if (element == "ramlabel")
            target = ui_ramlabel;
    }

    if (target)
    {
        lv_obj_set_style_text_color(target, lvColor, LV_PART_MAIN);
    }
}

void handleSettingsCommand(JsonDocument &doc)
{
    bool sleepSettingsUpdated = false;
    bool weatherSettingsChanged = false;
    bool weatherApiChanged = false;
    bool weatherLocationChanged = false;
    bool weatherUseCoordsChanged = false;
    bool weatherTimeoutChanged = false;
    bool weatherShouldRefreshNow = false;

    if (doc.containsKey("screen_brightness"))
    {
        if (!appState.autoBrightness)
        {
            appState.screenBrightness = doc["screen_brightness"];
            setScreenBrightness(appState.screenBrightness);
        }
    }
    if (doc.containsKey("auto_brightness"))
    {
        appState.autoBrightness = doc["auto_brightness"];

        if (!appState.autoBrightness)
        {
            setScreenBrightness(appState.screenBrightness);
            setLedBrightness(appState.ledBrightness);
        }
    }
    if (doc.containsKey("buzzer_volume"))
    {
        appState.buzzerVolume = doc["buzzer_volume"];
    }
    if (doc.containsKey("led_mode"))
    {
        appState.defaultLedMode = doc["led_mode"];
        if (!appState.volumeModeActive)
        {
            setLedMode(appState.defaultLedMode);
        }
    }
    if (doc.containsKey("led_brightness"))
    {
        if (!appState.autoBrightness)
        {
            appState.ledBrightness = doc["led_brightness"];
            setLedBrightness(appState.ledBrightness);
        }
    }
    if (doc.containsKey("led_color") || doc.containsKey("color"))
    {
        uint32_t color = 0;
        JsonVariantConst colorValue = doc.containsKey("led_color") ? doc["led_color"] : doc["color"];
        if (parseLedColorValue(colorValue, color))
        {
            setLedColor(color);
        }
    }
    if (doc.containsKey("auto_gamma"))
        appState.autoBrightnessGamma = doc["auto_gamma"];

    if (doc.containsKey("auto_smoothing"))
        appState.autoBrightnessSmoothing = doc["auto_smoothing"];

    if (doc.containsKey("auto_night_min"))
        appState.autoBrightnessNightMin = doc["auto_night_min"];
    if (doc.containsKey("auto_led_min"))
        appState.autoLedMin = doc["auto_led_min"];
    if (doc.containsKey("auto_led_max"))
        appState.autoLedMax = doc["auto_led_max"];
    if (doc.containsKey("sleep_enabled"))
    {
        appState.sleepEnabled = doc["sleep_enabled"];
        sleepSettingsUpdated = true;
    }

    if (doc.containsKey("sleep_start_hour"))
    {
        appState.sleepStartHour = doc["sleep_start_hour"];
        sleepSettingsUpdated = true;
    }

    if (doc.containsKey("sleep_start_minute"))
    {
        appState.sleepStartMinute = doc["sleep_start_minute"];
        sleepSettingsUpdated = true;
    }

    if (doc.containsKey("sleep_end_hour"))
    {
        appState.sleepEndHour = doc["sleep_end_hour"];
        sleepSettingsUpdated = true;
    }

    if (doc.containsKey("sleep_end_minute"))
    {
        appState.sleepEndMinute = doc["sleep_end_minute"];
        sleepSettingsUpdated = true;
    }

    float incomingLat = appState.weatherLat;
    float incomingLon = appState.weatherLon;
    bool hasLat = tryParseFloatFromKey(doc, "weather_lat", incomingLat) ||
                  tryParseFloatFromKey(doc, "latitude", incomingLat) ||
                  tryParseFloatFromKey(doc, "lat", incomingLat);
    bool hasLon = tryParseFloatFromKey(doc, "weather_lon", incomingLon) ||
                  tryParseFloatFromKey(doc, "longitude", incomingLon) ||
                  tryParseFloatFromKey(doc, "lon", incomingLon);

    if (hasLat && fabsf(incomingLat - appState.weatherLat) > 0.0001f)
    {
        appState.weatherLat = incomingLat;
        weatherSettingsChanged = true;
        weatherLocationChanged = true;
        weatherShouldRefreshNow = true;
    }
    if (hasLon && fabsf(incomingLon - appState.weatherLon) > 0.0001f)
    {
        appState.weatherLon = incomingLon;
        weatherSettingsChanged = true;
        weatherLocationChanged = true;
        weatherShouldRefreshNow = true;
    }

    if (doc.containsKey("weather_api_key"))
    {
        String incomingKey = doc["weather_api_key"] | "";
        if (incomingKey != appState.openWeatherAPIKey)
        {
            appState.openWeatherAPIKey = incomingKey;
            weatherSettingsChanged = true;
            weatherApiChanged = true;
            weatherShouldRefreshNow = true;
        }
    }

    if (doc.containsKey("weather_timeout_sec"))
    {
        int incomingTimeout = constrain((int)(doc["weather_timeout_sec"] | appState.weatherTimeoutSec), 60, 86400);
        if (incomingTimeout != appState.weatherTimeoutSec)
        {
            appState.weatherTimeoutSec = incomingTimeout;
            weatherSettingsChanged = true;
            weatherTimeoutChanged = true;
        }
    }

    if ((hasLat || hasLon) && !appState.useCoordinates)
    {
        appState.useCoordinates = true;
        weatherSettingsChanged = true;
        weatherUseCoordsChanged = true;
        weatherShouldRefreshNow = true;
    }

    if (sleepSettingsUpdated)
    {
        updateSleepMode();
    }

    if (weatherSettingsChanged)
    {
        Preferences prefs;
        prefs.begin("deskhub", false);
        if (weatherApiChanged)
            prefs.putString("weatherKey", appState.openWeatherAPIKey);
        if (weatherLocationChanged)
        {
            prefs.putFloat("weatherLat", appState.weatherLat);
            prefs.putFloat("weatherLon", appState.weatherLon);
        }
        if (weatherUseCoordsChanged)
            prefs.putBool("useCoords", appState.useCoordinates);
        if (weatherTimeoutChanged)
            prefs.putUInt("weatherTimeoutSec", (uint32_t)appState.weatherTimeoutSec);
        prefs.end();

        if (weatherShouldRefreshNow)
        {
            Serial.println("[Weather] Settings changed, refreshing weather now");
            updateWeather();
            if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
            {
                updateWeatherDisplay();
                xSemaphoreGive(uiMutex);
            }
        }
    }

    saveSettings();
}

void handleLedStateCommand(JsonDocument &doc)
{
    int mode = -1;
    int brightness = -1;
    uint32_t color = 0;
    bool hasColor = false;

    if (doc.containsKey("mode"))
    {
        mode = doc["mode"];
    }
    else if (doc.containsKey("led_mode"))
    {
        mode = doc["led_mode"];
    }

    if (doc.containsKey("brightness"))
    {
        brightness = doc["brightness"];
    }
    else if (doc.containsKey("led_brightness"))
    {
        brightness = doc["led_brightness"];
    }

    if (doc.containsKey("color"))
    {
        hasColor = parseLedColorValue(doc["color"], color);
    }
    else if (doc.containsKey("led_color"))
    {
        hasColor = parseLedColorValue(doc["led_color"], color);
    }

    if (mode >= LED_MODE_STATIC && mode <= LED_MODE_MATRIX)
    {
        appState.defaultLedMode = mode;
        if (!appState.volumeModeActive)
        {
            setLedMode(mode);
        }
    }

    if (brightness >= 0)
    {
        appState.ledBrightness = constrain(brightness, 0, 255);
        if (!appState.autoBrightness)
        {
            setLedBrightness(appState.ledBrightness);
        }
    }

    if (hasColor)
    {
        setLedColor(color);
    }

    saveSettings();
}

void handleOtaCommand(JsonDocument &doc)
{
    if (!otaCallbackRegistered)
    {
        setOtaEventCallback(onOtaEvent);
        otaCallbackRegistered = true;
    }

    String url = doc["url"] | "";
    String md5 = doc["md5"] | "";

    if (url.length() == 0)
    {
        onOtaEvent(0, "error", "missing url");
        return;
    }

    requestOtaUpdate(url, md5);
}

void handleGifCommand(JsonDocument &doc)
{
    String url = doc["url"] | "";
    String name = doc["name"] | "";
    if (url.length() == 0 || name.length() == 0)
        return;

    HTTPClient http;
    http.begin(url);
    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK)
    {
        if (LittleFS.exists("/" + name))
        {
            LittleFS.remove("/" + name);
        }

        File file = LittleFS.open("/" + name, "w");
        if (file)
        {
            WiFiClient *stream = http.getStreamPtr();
            uint8_t buff[256] = {0};
            int len = stream->available();

            while (len > 0)
            {
                if (len > 0)
                {
                    size_t bytesToRead = (len > 256) ? 256 : len;
                    int bytesRead = stream->readBytes(buff, bytesToRead);
                    file.write(buff, bytesRead);
                    len = stream->available();
                }
                else
                {
                    len = stream->available();
                }
            }
            file.close();
            Serial.println("GIF downloaded: " + name);
        }
    }
    http.end();
}
