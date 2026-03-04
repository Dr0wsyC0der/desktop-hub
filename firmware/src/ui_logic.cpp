#include "ui_logic.h"
#include "ws_client.h"
#include "device_control.h"
#include "led_effects.h"
#include "weather.h"
#include "bus_schedule.h"
#include "helpers.h"
#include <WiFi.h>
#include <ui.h>
#include <LittleFS.h>
#include <FS.h>
#include "bme_manager.h"

#define BUTTON_PIN 4

// --- Переменные для кнопки ---
volatile bool btnPressedFlag = false;
volatile unsigned long lastBtnIntTime = 0;

static lv_img_dsc_t gif_factory_dsc;  // Статическая, чтобы не пропадала
static uint8_t *gif_buffer = nullptr; // Буфер для одного кадра
static int current_anim_frame = 0;

void IRAM_ATTR isrButton()
{
    unsigned long now = millis();
    if (now - lastBtnIntTime > 50)
    { // Антидребезг
        btnPressedFlag = true;
        lastBtnIntTime = now;
    }
}

void initButton()
{
    pinMode(BUTTON_PIN, INPUT_PULLUP);
    attachInterrupt(BUTTON_PIN, isrButton, FALLING);
}

// --- УМНОЕ ПЕРЕКЛЮЧЕНИЕ ЭКРАНОВ ---
void switchScreen(ScreenID screen, bool reverse)
{
    if (screen == SCREEN_4 && !appState.pcConnected)
    {
        Serial.println("[UI] Access denied to Screen 4: PC not connected");
        playSound(200, 100);
        return;
    }

    if (screen == SCREEN_2 && !appState.screen2Active)
        return;

    if (xSemaphoreTake(uiMutex, portMAX_DELAY) == pdTRUE)
    {
        // Выбираем тип анимации в зависимости от направления
        // Если новый экран больше текущего — сдвиг влево (вперед)
        // Если меньше — сдвиг вправо (назад)
        lv_scr_load_anim_t animType = (screen > appState.currentScreen) != reverse
                                          ? LV_SCR_LOAD_ANIM_MOVE_LEFT
                                          : LV_SCR_LOAD_ANIM_MOVE_RIGHT;

        // lv_scr_load_anim_t animType = LV_SCR_LOAD_ANIM_FADE_ON;

        // Для системных экранов (громкость SCREEN_2) лучше использовать FADE (плавное появление)
        if (screen == SCREEN_2)
        {
            // Открываем громкость — сверху вниз
            animType = LV_SCR_LOAD_ANIM_MOVE_BOTTOM;
        }
        else if (appState.currentScreen == SCREEN_2)
        {
            // Закрываем громкость — уезжает вверх
            animType = LV_SCR_LOAD_ANIM_MOVE_TOP;
        }

        if (screen == SCREEN_7)
        {
            animType = LV_SCR_LOAD_ANIM_MOVE_TOP;
        }
        else if (appState.currentScreen == SCREEN_7)
        {
            animType = LV_SCR_LOAD_ANIM_MOVE_BOTTOM;
        }

        appState.previousScreen = appState.currentScreen;
        appState.currentScreen = screen;

        // Определяем целевой объект
        lv_obj_t *targetScreen = nullptr;
        if (screen == SCREEN_1)
            targetScreen = ui_Screen1;
        else if (screen == SCREEN_2)
            targetScreen = ui_Screen2;
        else if (screen == SCREEN_3)
            targetScreen = ui_Screen3;
        else if (screen == SCREEN_4)
            targetScreen = ui_Screen4;
        else if (screen == SCREEN_6)
            targetScreen = ui_Screen6;
        else if (screen == SCREEN_7)
            targetScreen = ui_Screen7;

        if (targetScreen)
        {
            // Загружаем с анимацией: экран, эффект, время (мс), задержка, авто-удаление (false)
            lv_scr_load_anim(targetScreen, animType, 200, 0, false);
        }
        if (screen == SCREEN_1)
        {
            startAnimation();
        }
        else
        {
            stopAnimation();
        }

        // МГНОВЕННОЕ ОБНОВЛЕНИЕ ДАННЫХ
        updateTimeDisplay();
        if (screen == SCREEN_1)
        {
            updateWeatherDisplay();
            updateConnectionStatus();
        }
        else if (screen == SCREEN_3)
        {
            updateBusScheduleDisplay();
        }
        else if (screen == SCREEN_4)
        {
            updateScreen4();
        }
        else if (screen == SCREEN_6)
        {
            updateScreen6();
        }

        xSemaphoreGive(uiMutex);
    }

    // Логика работы с ПК (оставляем без изменений)
    if (screen == SCREEN_4 && appState.pcConnected)
    {
        sendWebSocketMessage("{\"type\":\"pc_load\",\"action\":\"start\"}");
        pcLoadData.active = true;
    }
    if (appState.previousScreen == SCREEN_4 && screen != SCREEN_4)
    {
        sendWebSocketMessage("{\"type\":\"pc_load\",\"action\":\"stop\"}");
        pcLoadData.active = false;
    }
}

// --- ОБРАБОТКА НАЖАТИЙ (ЖЕЛЕЗНАЯ ЛОГИКА) ---
// void handleButtonPress()
// {
//     static int clickCount = 0;
//     static unsigned long lastClickTime = 0;
//     const unsigned long clickTimeout = 300; // Ждем 300мс после клика
//     unsigned long now = millis();
//     static unsigned long pressStartTime = 0;
//     static bool longPressHandled = false;

//     // ---- LONG PRESS detection ----
//     if (digitalRead(BUTTON_PIN) == LOW)
//     {
//         if (pressStartTime == 0)
//             pressStartTime = millis();

//         if (!longPressHandled && millis() - pressStartTime > 2000)
//         {
//             Serial.println("[BUTTON] Long press detected");

//             forceWebSocketReconnect();

//             longPressHandled = true;
//         }
//     }
//     else
//     {
//         pressStartTime = 0;
//         longPressHandled = false;
//     }

//     // 1. Фиксируем нажатие из прерывания
//     if (btnPressedFlag)
//     {
//         btnPressedFlag = false;
//         clickCount++;
//         lastClickTime = now;
//         Serial.printf("[BUTTON] Click #%d\n", clickCount);
//     }

//     // 2. Если серия кликов завершена (прошло время ожидания)
//     if (clickCount > 0 && (now - lastClickTime > clickTimeout))
//     {

//         if (clickCount == 1)
//         {
//             // ОДИН КЛИК: Листаем экраны вперед
//             if (appState.currentScreen == SCREEN_1)
//                 switchScreen(SCREEN_3);
//             else if (appState.currentScreen == SCREEN_3)
//                 switchScreen(SCREEN_4);
//             else if (appState.currentScreen == SCREEN_4)
//                 switchScreen(SCREEN_6);
//             else
//                 switchScreen(SCREEN_1);
//         }
//         else if (clickCount == 2)
//         {
//             // ДВА КЛИКА: Быстрый возврат на главный
//             if (appState.currentScreen == SCREEN_6)
//                 switchScreen(SCREEN_4);
//             else if (appState.currentScreen == SCREEN_4)
//                 switchScreen(SCREEN_3);
//             else if (appState.currentScreen == SCREEN_3)
//                 switchScreen(SCREEN_1);
//             else if (appState.currentScreen == SCREEN_1)
//                 switchScreen(SCREEN_6);
//         }
//         else if (clickCount >= 3)
//         {
//             // ТРИ КЛИКА: Смена подсветки
//             appState.ledMode++;
//             if (appState.ledMode > 7)
//                 appState.ledMode = 1;
//             setLedMode(appState.ledMode); // Функция из led_effects.cpp
//             Serial.printf("[LED] New Mode: %d\n", appState.ledMode);
//         }

//         clickCount = 0; // Обнуляем счетчик
//     }
// }

// void handleButtonPress()
// {
//     static int clickCount = 0;
//     static unsigned long lastClickTime = 0;
//     const unsigned long clickTimeout = 300;
//     unsigned long now = millis();

//     static unsigned long pressStartTime = 0;
//     static bool longPressHandled = false;

//     // ---- LONG PRESS detection ----
//     if (digitalRead(BUTTON_PIN) == LOW)
//     {
//         if (pressStartTime == 0)
//             pressStartTime = millis();

//         if (!longPressHandled && millis() - pressStartTime > 2000)
//         {
//             Serial.println("[BUTTON] Long press detected");

//             forceWebSocketReconnect();

//             longPressHandled = true;

//             // 💥 ВАЖНО: сбрасываем клики
//             clickCount = 0;
//             btnPressedFlag = false;
//         }
//     }
//     else
//     {
//         pressStartTime = 0;
//         longPressHandled = false;
//     }

//     // ❗ Если был long press — обычные клики игнорируем
//     if (longPressHandled)
//         return;

//     // 1. Фиксируем нажатие из прерывания
//     // 1. Фиксируем нажатие из прерывания
//     if (btnPressedFlag)
//     {
//         btnPressedFlag = false;
//         // ← НЕ считаем клик пока кнопка зажата
//         if (digitalRead(BUTTON_PIN) == HIGH)
//         {
//             clickCount++;
//             lastClickTime = now;
//             Serial.printf("[BUTTON] Click #%d\n", clickCount);
//         }
//     }

//     // 2. Если серия кликов завершена
//     if (clickCount > 0 && (now - lastClickTime > clickTimeout))
//     {
//         if (clickCount == 1)
//         {
//             if (appState.currentScreen == SCREEN_1)
//                 switchScreen(SCREEN_3);
//             else if (appState.currentScreen == SCREEN_3)
//                 switchScreen(SCREEN_4);
//             else if (appState.currentScreen == SCREEN_4)
//                 switchScreen(SCREEN_6);
//             else
//                 switchScreen(SCREEN_1);
//         }
//         else if (clickCount == 2)
//         {
//             if (appState.currentScreen == SCREEN_6)
//                 switchScreen(SCREEN_4);
//             else if (appState.currentScreen == SCREEN_4)
//                 switchScreen(SCREEN_3);
//             else if (appState.currentScreen == SCREEN_3)
//                 switchScreen(SCREEN_1);
//             else if (appState.currentScreen == SCREEN_1)
//                 switchScreen(SCREEN_6, true); // ← вот тут reverse=true → RIGHT
//         }
//         else if (clickCount >= 3)
//         {
//             appState.ledMode++;
//             if (appState.ledMode > 7)
//                 appState.ledMode = 1;

//             setLedMode(appState.ledMode);
//             Serial.printf("[LED] New Mode: %d\n", appState.ledMode);
//         }

//         clickCount = 0;
//     }
// }

void handleButtonPress()
{
    static int clickCount = 0;
    static unsigned long lastClickTime = 0;
    const unsigned long clickTimeout = 300;
    unsigned long now = millis();

    static unsigned long pressStartTime = 0;
    static bool buttonWasPressed = false;
    static bool longPressHandled = false;

    bool buttonDown = (digitalRead(BUTTON_PIN) == LOW);

    // Кнопка нажата
    if (buttonDown && !buttonWasPressed)
    {
        buttonWasPressed = true;
        pressStartTime = now;
        longPressHandled = false;
        btnPressedFlag = false; // сбрасываем флаг прерывания
    }

    // Кнопка удерживается — проверяем long press
    if (buttonDown && buttonWasPressed && !longPressHandled)
    {
        if (now - pressStartTime > 2000)
        {
            Serial.println("[BUTTON] Long press detected");
            playSound(1000, 150);
            forceWebSocketReconnect();
            longPressHandled = true;
            clickCount = 0; // сбрасываем клики
        }
    }

    // Кнопка отпущена
    if (!buttonDown && buttonWasPressed)
    {
        buttonWasPressed = false;

        // Считаем клик только если не было long press
        if (!longPressHandled)
        {
            clickCount++;
            lastClickTime = now;
            Serial.printf("[BUTTON] Click #%d\n", clickCount);
        }
    }

    // Серия кликов завершена
    if (clickCount > 0 && (now - lastClickTime > clickTimeout))
    {
        if (clickCount == 1)
        {
            if (appState.sleepEnabled && appState.isSleepingNow)
            {
                triggerSleepScreenPreview(5000);
            }
            else
            {
                if (appState.currentScreen == SCREEN_1)
                    switchScreen(SCREEN_3);
                else if (appState.currentScreen == SCREEN_3)
                    switchScreen(SCREEN_4);
                else if (appState.currentScreen == SCREEN_4)
                    switchScreen(SCREEN_6);
                else
                    switchScreen(SCREEN_1);
            }
        }
        else if (clickCount == 2)
        {
            if (appState.currentScreen == SCREEN_6)
                switchScreen(SCREEN_4, true);
            else if (appState.currentScreen == SCREEN_4)
                switchScreen(SCREEN_3, true);
            else if (appState.currentScreen == SCREEN_3)
                switchScreen(SCREEN_1, true);
            else if (appState.currentScreen == SCREEN_1)
                switchScreen(SCREEN_6, true);
        }
        else if (clickCount >= 3)
        {
            appState.ledMode++;
            if (appState.ledMode > 7)
                appState.ledMode = 1;
            setLedMode(appState.ledMode);
            Serial.printf("[LED] New Mode: %d\n", appState.ledMode);
        }

        clickCount = 0;
    }
}

// --- ОБНОВЛЕНИЕ ТЕКСТА И ВРЕМЕНИ ---
void updateTimeDisplay()
{
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
        return;

    appState.timeValid = true;
    char buf[12];

    // Обновляем часы/минуты/секунды в зависимости от активного экрана
    if (appState.currentScreen == SCREEN_1)
    {
        if (ui_main_hours)
        {
            snprintf(buf, sizeof(buf), "%02d", timeinfo.tm_hour);
            lv_label_set_text(ui_main_hours, buf);
        }
        if (ui_main_minute)
        {
            snprintf(buf, sizeof(buf), "%02d", timeinfo.tm_min);
            lv_label_set_text(ui_main_minute, buf);
        }
        if (ui_main_seconds)
        {
            snprintf(buf, sizeof(buf), "%02d", timeinfo.tm_sec);
            lv_label_set_text(ui_main_seconds, buf);
        }
        if (ui_date)
            lv_label_set_text(ui_date, formatDate(&timeinfo).c_str());
        if (ui_day)
            lv_label_set_text(ui_day, formatDay(&timeinfo).c_str());
    }
    else
    {
        // На остальных экранах (3 и 4) обычно маленькие часы
        if (ui_hours)
        {
            snprintf(buf, sizeof(buf), "%02d", timeinfo.tm_hour);
            lv_label_set_text(ui_hours, buf);
        }
        if (ui_minutes)
        {
            snprintf(buf, sizeof(buf), "%02d", timeinfo.tm_min);
            lv_label_set_text(ui_minutes, buf);
        }
    }
}

void updateScreen1()
{
    if (appState.currentScreen != SCREEN_1)
        return;

    updateConnectionStatus();

    // Чередование IP и погоды внизу экрана раз в 5 секунд
    static unsigned long lastToggleTime = 0;
    static bool toggleStatus = true;
    if (millis() - lastToggleTime > 5000)
    {
        lastToggleTime = millis();
        if (ui_other_weather && appState.wifiConnected)
        {
            if (toggleStatus)
            {
                char buf[32];
                snprintf(buf, sizeof(buf), "Feels like %.0f°C", weatherData.feelsLike);
                lv_label_set_text(ui_other_weather, buf);
            }
            else
            {
                lv_label_set_text(ui_other_weather, WiFi.localIP().toString().c_str());
            }
            toggleStatus = !toggleStatus;
        }
    }
}

void updateScreen3()
{
    if (appState.currentScreen != SCREEN_3)
        return;
    // Можно добавить динамическое обновление таймера "через сколько минут автобус"
    // Но пока просто вызываем отрисовку данных
    updateBusScheduleDisplay();
}

void updateScreen4()
{
    // 1. Проверяем, что мы на 4 экране и данные активны
    if (appState.currentScreen != SCREEN_4 || !pcLoadData.active)
        return;

    // 2. ВСЕГДА проверяем существование объектов перед использованием
    // Анимация полосок
    if (ui_cpu_bar)
        lv_bar_set_value(ui_cpu_bar, pcLoadData.cpu, LV_ANIM_ON);
    if (ui_gpu_bar)
        lv_bar_set_value(ui_gpu_bar, pcLoadData.gpu, LV_ANIM_ON);
    if (ui_ram_bar)
        lv_bar_set_value(ui_ram_bar, pcLoadData.ram, LV_ANIM_ON);

    // Текстовые проценты
    char buf[16];
    if (ui_cpulabel)
    {
        snprintf(buf, sizeof(buf), "%d%%", pcLoadData.cpu);
        lv_label_set_text(ui_cpulabel, buf);
    }
    if (ui_gpulabel)
    {
        snprintf(buf, sizeof(buf), "%d%%", pcLoadData.gpu);
        lv_label_set_text(ui_gpulabel, buf);
    }
    if (ui_ramlabel)
    {
        snprintf(buf, sizeof(buf), "%d%%", pcLoadData.ram);
        lv_label_set_text(ui_ramlabel, buf);
    }
}

void updateScreen6()
{
    if (appState.currentScreen != SCREEN_6)
        return;

    if (!bmeInitialized)
        return;

    static unsigned long lastUpdate = 0;
    if (millis() - lastUpdate < 1000)
        return;
    lastUpdate = millis();

    float temp = bme.readTemperature();
    float hum = bme.readHumidity();
    float pressurePa = bme.readPressure();
    float pressureMmHg = pressurePa / 133.322;

    char buf[20];

    if (ui_hometemp)
    {
        snprintf(buf, sizeof(buf), "%.1fC", temp);
        lv_label_set_text(ui_hometemp, buf);
    }
    if (ui_homehum)
    {
        snprintf(buf, sizeof(buf), "%.0f%%", hum);
        lv_label_set_text(ui_homehum, buf);
    }
    if (ui_homeprs)
    {
        snprintf(buf, sizeof(buf), "%.0fmmHg", pressureMmHg);
        lv_label_set_text(ui_homeprs, buf);
    }
}

void handleScreen2Timeout()
{
    if (appState.screen2Active && (millis() - appState.screen2StartTime > 2500))
    {
        appState.screen2Active = false;
        stopVolumeMode();
        switchScreen(appState.previousScreen);
    }
}

void handleScreen7Timeout()
{
    if (appState.screen7Active &&
        (millis() - appState.screen7StartTime > 2500))
    {
        appState.screen7Active = false;
        switchScreen(appState.previousScreen);
    }
}

// void anim_timer_cb(lv_timer_t *t)
// {
//     // Если качаем файл - не трогаем экран
//     if (appState.animReceiving)
//         return;

//     File f = LittleFS.open("/anim.bin", "r");
//     if (!f)
//         return;

//     // Считаем размер кадра (80*80*2 = 12800 байт)
//     size_t frameSize = appState.animWidth * appState.animHeight * 2;
//     if (frameSize == 0)
//     {
//         f.close();
//         return;
//     }

//     // 2. Выделяем буфер, если еще не выделен
//     if (gif_buffer == nullptr)
//     {
//         gif_buffer = (uint8_t *)malloc(frameSize);
//         if (!gif_buffer)
//         {
//             Serial.println("[Anim] ERROR: RAM full!");
//             f.close();
//             return;
//         }
//     }

//     // 3. Читаем кадр
//     if (current_anim_frame >= appState.animFrames)
//         current_anim_frame = 0;

//     f.seek(current_anim_frame * frameSize);
//     f.read(gif_buffer, frameSize);
//     f.close();
//     if (current_anim_frame == 0)
//     {
//         Serial.printf("First bytes: %02X %02X %02X %02X\n",
//                       gif_buffer[0],
//                       gif_buffer[1],
//                       gif_buffer[2],
//                       gif_buffer[3]);
//     }

//     // 2. ЖЕСТКО прописываем параметры (не полагаясь только на переменную)
//     gif_factory_dsc.header.always_zero = 0;
//     gif_factory_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;

//     gif_factory_dsc.data_size = frameSize;
//     gif_factory_dsc.data = gif_buffer;

//     // 3. Вывод в консоль для финальной проверки параметров
//     if (current_anim_frame == 0)
//     {
//         Serial.printf("VERIFY: W=%d, H=%d, CF=%d, Size=%d\n",
//                       gif_factory_dsc.header.w,
//                       gif_factory_dsc.header.h,
//                       gif_factory_dsc.header.cf,
//                       gif_factory_dsc.data_size);
//     }
//     gif_factory_dsc.header.always_zero = 0;
//     gif_factory_dsc.header.w = appState.animWidth;
//     gif_factory_dsc.header.h = appState.animHeight;
//     gif_factory_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
//     gif_factory_dsc.data_size = frameSize;
//     gif_factory_dsc.data = gif_buffer;

//     // if (xSemaphoreTake(uiMutex, (TickType_t)10) == pdTRUE)
//     // {
//     //     if (ui_gif != nullptr)
//     //     {
//     //         lv_img_set_src(ui_gif, &gif_factory_dsc);
//     //         lv_obj_set_size(ui_gif, appState.animWidth, appState.animHeight);
//     //         lv_img_set_zoom(ui_gif, 256);
//     //         lv_obj_clear_flag(ui_gif, LV_OBJ_FLAG_HIDDEN);
//     //     }
//     //     xSemaphoreGive(uiMutex);
//     // }
//     if (ui_gif != nullptr)
//     {
//         lv_img_set_src(ui_gif, &gif_factory_dsc);
//         lv_refr_now(NULL);
//         lv_obj_set_size(ui_gif, appState.animWidth, appState.animHeight);
//         lv_obj_clear_flag(ui_gif, LV_OBJ_FLAG_HIDDEN);
//     }

//     current_anim_frame++;
// }

// void startAnimation()
// {
//     if (appState.animWidth == 0 || appState.animHeight == 0)
//     {
//         Serial.println("[Anim] ERROR: Invalid dimensions!");
//         return;
//     }
//     // Очищаем старый таймер
//     if (animTimer)
//     {
//         lv_timer_del(animTimer);
//         animTimer = nullptr;
//     }

//     // Очищаем старый буфер, если размеры изменились
//     if (gif_buffer)
//     {
//         free(gif_buffer);
//         gif_buffer = nullptr;
//     }

//     // Сбрасываем кэш LVGL
//     lv_img_cache_invalidate_src(NULL);

//     // Запуск таймера
//     animTimer = lv_timer_create(anim_timer_cb, appState.animDelay, NULL);

//     Serial.println("[Anim] Playback started");
// }
// void anim_timer_cb(lv_timer_t *t)
// {
//     if (appState.animReceiving)
//         return;

//     size_t frameSize = appState.animWidth * appState.animHeight * 2;
//     if (frameSize == 0)
//         return;

//     if (gif_buffer == nullptr)
//     {
//         gif_buffer = (uint8_t *)malloc(frameSize);
//         if (!gif_buffer)
//             return;
//     }

//     File f = LittleFS.open("/anim.bin", "r");
//     if (!f)
//         return;

//     if (current_anim_frame >= appState.animFrames)
//         current_anim_frame = 0;

//     f.seek(current_anim_frame * frameSize);
//     f.read(gif_buffer, frameSize);
//     f.close();

//     gif_factory_dsc.header.always_zero = 0;
//     gif_factory_dsc.header.w = appState.animWidth;
//     gif_factory_dsc.header.h = appState.animHeight;
//     gif_factory_dsc.header.cf = LV_IMG_CF_TRUE_COLOR;
//     gif_factory_dsc.data_size = frameSize;
//     gif_factory_dsc.data = gif_buffer;

//     if (ui_gif)
//     {
//         lv_img_set_src(ui_gif, &gif_factory_dsc); // оставляем
//         lv_obj_set_size(ui_gif, appState.animWidth, appState.animHeight);
//         lv_obj_clear_flag(ui_gif, LV_OBJ_FLAG_HIDDEN);
//         // УБРАЛИ lv_refr_now(NULL);
//     }

//     current_anim_frame++;
// }
// void startAnimation()
// {
//     if (appState.animWidth == 0 || appState.animHeight == 0)
//         return;

//     if (animTimer)
//     {
//         lv_timer_del(animTimer);
//         animTimer = nullptr;
//     }

//     if (gif_buffer)
//     {
//         free(gif_buffer);
//         gif_buffer = nullptr;
//     }

//     animTimer = lv_timer_create(anim_timer_cb, appState.animDelay, NULL);

//     Serial.println("[Anim] Playback started");
// }

// Добавьте в начало файла
static lv_obj_t *gif_canvas = nullptr;
static uint8_t *canvas_buffer = nullptr;
static lv_color_t *frame_buffer = nullptr;
static File anim_playback_file;
static bool anim_playback_opened = false;

static void closeAnimPlaybackFile()
{
    if (anim_playback_opened)
    {
        anim_playback_file.close();
        anim_playback_opened = false;
    }
}

void anim_timer_cb(lv_timer_t *t)
{
    if (appState.currentScreen != SCREEN_1)
        return;

    if (appState.animReceiving)
        return;

    size_t frameSize = appState.animWidth * appState.animHeight * 2;
    if (frameSize == 0)
        return;

    if (!anim_playback_opened)
    {
        anim_playback_file = LittleFS.open("/anim.bin", "r");
        if (!anim_playback_file)
            return;
        anim_playback_opened = true;
    }

    if (!frame_buffer)
    {
        frame_buffer = (lv_color_t *)malloc(frameSize);
        if (!frame_buffer)
        {
            closeAnimPlaybackFile();
            return;
        }
    }

    if (current_anim_frame >= appState.animFrames)
    {
        current_anim_frame = 0;
        anim_playback_file.seek(0);
    }

    // Читаем напрямую в буфер canvas
    size_t bytesRead = anim_playback_file.read((uint8_t *)frame_buffer, frameSize);

    if (bytesRead != frameSize)
    {
        closeAnimPlaybackFile();
        current_anim_frame = 0;
        return;
    }

    // ПРЯМАЯ ЗАПИСЬ в canvas (без промежуточных копирований!)
    if (gif_canvas)
    {
        lv_canvas_set_buffer(gif_canvas, frame_buffer,
                             appState.animWidth, appState.animHeight,
                             LV_IMG_CF_TRUE_COLOR);
    }

    current_anim_frame++;
}

void startAnimation()
{
    Serial.println("[Anim] startAnimation called");
    if (!ui_gif)
    {
        Serial.println("[Anim] ui_gif is NULL!");
    }

    if (appState.animWidth == 0 || appState.animHeight == 0)
    {
        Serial.printf("Width=%d Height=%d Frames=%d\n",
                      appState.animWidth,
                      appState.animHeight,
                      appState.animFrames);
        return;
    }

    if (animTimer)
    {
        lv_timer_del(animTimer);
        animTimer = nullptr;
    }
    closeAnimPlaybackFile();

    if (frame_buffer)
    {
        free(frame_buffer);
        frame_buffer = nullptr;
    }

    if (canvas_buffer)
    {
        free(canvas_buffer);
        canvas_buffer = nullptr;
    }

    current_anim_frame = 0;

    // Удаляем старый canvas
    if (gif_canvas)
    {
        lv_obj_del(gif_canvas);
        gif_canvas = nullptr;
    }

    // Создаём canvas
    if (ui_gif)
    {
        lv_obj_t *parent = lv_obj_get_parent(ui_gif);

        // Скрываем ui_gif
        lv_obj_add_flag(ui_gif, LV_OBJ_FLAG_HIDDEN);

        // Создаём canvas
        gif_canvas = lv_canvas_create(parent);

        // ЖЁСТКО прописываем параметры из SquareLine
        lv_obj_set_size(gif_canvas, appState.animWidth, appState.animHeight);
        lv_obj_align(gif_canvas, LV_ALIGN_CENTER, 80, 80); // CENTER с offset x=80, y=80

        // Убираем лишнее
        lv_obj_set_style_pad_all(gif_canvas, 0, 0);
        lv_obj_set_style_border_width(gif_canvas, 0, 0);
        lv_obj_set_style_bg_opa(gif_canvas, LV_OPA_TRANSP, 0);

        // Выделяем буфер
        size_t bufSize = LV_CANVAS_BUF_SIZE_TRUE_COLOR(appState.animWidth, appState.animHeight);
        canvas_buffer = (uint8_t *)malloc(bufSize);

        if (canvas_buffer)
        {
            memset(canvas_buffer, 0, bufSize);
            lv_canvas_set_buffer(gif_canvas, canvas_buffer,
                                 appState.animWidth, appState.animHeight,
                                 LV_IMG_CF_TRUE_COLOR);
            lv_canvas_fill_bg(gif_canvas, lv_color_black(), LV_OPA_COVER);
        }

        Serial.printf("[Canvas] Created at CENTER +80,+80 size %dx%d\n",
                      appState.animWidth, appState.animHeight);
    }

    int delay = max(50, appState.animDelay);
    animTimer = lv_timer_create(anim_timer_cb, delay, NULL);

    anim_timer_cb(animTimer);

    Serial.printf("[Anim] Canvas started: %dx%d, %d frames, %dms\n",
                  appState.animWidth, appState.animHeight,
                  appState.animFrames, delay);
}

void stopAnimation()
{
    if (animTimer)
    {
        lv_timer_del(animTimer);
        animTimer = nullptr;
    }
    closeAnimPlaybackFile();

    if (frame_buffer)
    {
        free(frame_buffer);
        frame_buffer = nullptr;
    }

    if (canvas_buffer)
    {
        free(canvas_buffer);
        canvas_buffer = nullptr;
    }

    if (gif_canvas)
    {
        lv_obj_del(gif_canvas);
        gif_canvas = nullptr;
    }

    // Показываем обратно ui_gif (пустой)
    if (ui_gif)
    {
        lv_obj_clear_flag(ui_gif, LV_OBJ_FLAG_HIDDEN);
    }

    current_anim_frame = 0;
    Serial.println("[Anim] Stopped");
}
