#include "device_control.h"
#include "app_state.h"
#include <Preferences.h>
#include <ui.h>
#include <FastLED.h>
#include "led_effects.h"
#include <Arduino.h>

#define BUZZER_PIN 8
#define BACKLIGHT_PIN 3

Preferences preferences;
static float smoothedFactor = -1.0f; // -1 = не инициализирован

void initDeviceControl()
{
    pinMode(BUZZER_PIN, OUTPUT);
    pinMode(BACKLIGHT_PIN, OUTPUT);
    digitalWrite(BUZZER_PIN, LOW);

    // Настраиваем аппаратный PWM (LEDC)
    ledcSetup(0, 5000, 8); // канал 0, 5 кГц, 8 бит
    ledcAttachPin(BACKLIGHT_PIN, 0);
    ledcWrite(0, 255); // стартовая яркость

    preferences.begin("deskhub", false);
    loadSettings();
}

void setScreenBrightness(int brightness)
{
    appState.screenBrightness = constrain(brightness, 0, 255);
    ledcWrite(0, appState.screenBrightness);
}

void playSound(int frequency, int duration)
{
    if (appState.buzzerVolume == 0)
        return;

    int halfPeriod = 1000000 / frequency / 2;
    int cycles = (duration * 1000) / (halfPeriod * 2);

    for (int i = 0; i < cycles; i++)
    {
        digitalWrite(BUZZER_PIN, HIGH);
        delayMicroseconds(halfPeriod);
        digitalWrite(BUZZER_PIN, LOW);
        delayMicroseconds(halfPeriod);

        if (appState.buzzerVolume < 100)
        {
            int skipCycles = map(100 - appState.buzzerVolume, 0, 100, 0, cycles / 4);
            for (int j = 0; j < skipCycles && i < cycles; j++)
            {
                i++;
            }
        }
    }
}

void saveSettings()
{
    preferences.putInt("screenBright", appState.screenBrightness);
    preferences.putBool("autoBrightness", appState.autoBrightness);
    preferences.putInt("buzzerVolume", appState.buzzerVolume);
    preferences.putInt("ledMode", appState.defaultLedMode);
    preferences.putInt("ledBrightness", appState.ledBrightness);
    preferences.putInt("autoLedMin", appState.autoLedMin);
    preferences.putInt("autoLedMax", appState.autoLedMax);
    preferences.putBool("sleepEnabled", appState.sleepEnabled);
    preferences.putInt("sleepStartH", appState.sleepStartHour);
    preferences.putInt("sleepStartM", appState.sleepStartMinute);
    preferences.putInt("sleepEndH", appState.sleepEndHour);
    preferences.putInt("sleepEndM", appState.sleepEndMinute);
}

void loadSettings()
{
    appState.screenBrightness = preferences.getInt("screenBright", 200);
    appState.autoBrightness = preferences.getBool("autoBrightness", false);
    appState.buzzerVolume = preferences.getInt("buzzerVolume", 60);
    appState.defaultLedMode = preferences.getInt("ledMode", 5);
    appState.ledBrightness = preferences.getInt("ledBrightness", 120);
    appState.ledMode = appState.defaultLedMode;
    appState.autoLedMin = preferences.getInt("autoLedMin", 10);
    appState.autoLedMax = preferences.getInt("autoLedMax", 255);
    appState.sleepEnabled = preferences.getBool("sleepEnabled", false);
    appState.sleepStartHour = preferences.getInt("sleepStartH", 22);
    appState.sleepStartMinute = preferences.getInt("sleepStartM", 0);
    appState.sleepEndHour = preferences.getInt("sleepEndH", 7);
    appState.sleepEndMinute = preferences.getInt("sleepEndM", 0);

    setScreenBrightness(appState.screenBrightness);
}

void updateConnectionStatus()
{
    if (ui_wifi_icon)
    {
        lv_obj_set_style_img_opa(ui_wifi_icon, appState.wifiConnected ? 255 : 0, LV_PART_MAIN);
    }
    if (ui_pc_icon)
    {
        lv_obj_set_style_img_opa(ui_pc_icon, appState.pcConnected ? 255 : 0, LV_PART_MAIN);
    }
    if (ui_loadspin)
    {
        if (appState.isDataLoading)
            lv_obj_clear_flag(ui_loadspin, LV_OBJ_FLAG_HIDDEN);
        else
            lv_obj_add_flag(ui_loadspin, LV_OBJ_FLAG_HIDDEN);
    }
}

void updateAutoBrightness()
{
    if (true)
        return;
    if (!appState.autoBrightness)
        return;
    if (appState.isSleepingNow)
        return;

    int raw = 0;
    for (int i = 0; i < 4; i++)
        raw += analogRead(appState.ldrPin);
    raw /= 4;

    // Игнорируем явно недостоверные значения (артефакт WiFi-активности)
    if (raw >= 4000)
    {
        Serial.printf("[LDR] Skipped bad reading: %d\n", raw);
        return; // не обновляем smoothedFactor, оставляем последнее хорошее значение
    }

    float normalized = 1.0f - constrain((float)raw / 4095.0f, 0.0f, 1.0f);
    float gammaCorrected = pow(normalized, appState.autoBrightnessGamma);

    if (smoothedFactor < 0.0f)
        smoothedFactor = gammaCorrected;
    else
        smoothedFactor += appState.autoBrightnessSmoothing * (gammaCorrected - smoothedFactor);

    int screenValue = (int)(appState.autoBrightnessMin +
                            smoothedFactor * (appState.autoBrightnessMax - appState.autoBrightnessMin));
    screenValue = constrain(screenValue, appState.autoBrightnessMin, appState.autoBrightnessMax);
    ledcWrite(0, screenValue);

    int ledValue = (int)(appState.autoLedMin +
                         smoothedFactor * (appState.autoLedMax - appState.autoLedMin));
    ledValue = constrain(ledValue, appState.autoLedMin, appState.autoLedMax);
    FastLED.setBrightness(ledValue);
    // ↓ БЕЗ ЭТОГО яркость не применяется!
    FastLED.show();

    // Логирование — раз в 2 секунды
    static unsigned long lastLog = 0;
    if (millis() - lastLog > 2000)
    {
        lastLog = millis();
        Serial.printf("[LDR] raw=%d norm=%.3f gamma=%.3f smooth=%.3f screen=%d led=%d\n",
                      raw, normalized, gammaCorrected, smoothedFactor, screenValue, ledValue);
    }
}

void updateSleepMode()
{
    if (!appState.sleepEnabled || !appState.timeValid)
        return;

    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
        return;

    int nowMinutes = timeinfo.tm_hour * 60 + timeinfo.tm_min;
    int startMinutes = appState.sleepStartHour * 60 + appState.sleepStartMinute;
    int endMinutes = appState.sleepEndHour * 60 + appState.sleepEndMinute;

    bool shouldSleep;

    // если период через полночь
    if (startMinutes > endMinutes)
    {
        shouldSleep = (nowMinutes >= startMinutes || nowMinutes < endMinutes);
    }
    else
    {
        shouldSleep = (nowMinutes >= startMinutes && nowMinutes < endMinutes);
    }

    if (shouldSleep && !appState.isSleepingNow)
    {
        Serial.println("[Sleep] Entering sleep mode");
        appState.isSleepingNow = true;

        ledcWrite(0, 0); // гасим экран напрямую
        FastLED.setBrightness(0);
        FastLED.show();
    }
    else if (!shouldSleep && appState.isSleepingNow)
    {
        Serial.println("[Sleep] Leaving sleep mode");
        appState.isSleepingNow = false;

        // Восстанавливаем: если автояркость — она сама обновится в следующем цикле,
        // если ручная — ставим сохранённые значения
        if (!appState.autoBrightness)
        {
            setScreenBrightness(appState.screenBrightness);
            setLedBrightness(appState.ledBrightness);
        }
        // else: smoothedFactor уже актуален, updateAutoBrightness сам применит значения
    }
}
