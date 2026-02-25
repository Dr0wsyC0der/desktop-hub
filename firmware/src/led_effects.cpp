// #include "led_effects.h"
// #include "app_state.h"
// #include <FastLED.h>

// #define LED_PIN 2
// #define NUM_LEDS 7

// CRGB leds[NUM_LEDS];
// unsigned long lastLedUpdate = 0;
// int runningDotPos = 0;
// int pingPongPos = 0;
// int pingPongDir = 1;
// uint8_t rainbowHue = 0;

// // Forward declarations for helper update functions (defined below)
// static void updateVolumeLeds();
// static void updateStaticLeds();
// static void updateBreathingLeds();
// static void updateRunningDotLeds();
// static void updatePingPongLeds();
// static void updateGradientLeds();

// void initLeds()
// {
//     FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
//     FastLED.setBrightness(appState.ledBrightness);
//     FastLED.clear();
//     FastLED.show();
// }

// void updateLeds()
// {
//     unsigned long now = millis();
//     if (now - lastLedUpdate < 30)
//         return;
//     lastLedUpdate = now;

//     if (appState.volumeModeActive)
//     {
//         updateVolumeLeds();
//     }
//     else
//     {
//         switch (appState.ledMode)
//         {
//         case LED_MODE_STATIC:
//             updateStaticLeds();
//             break;
//         case LED_MODE_BREATHING:
//             updateBreathingLeds();
//             break;
//         case LED_MODE_RUNNING_DOT:
//             updateRunningDotLeds();
//             break;
//         case LED_MODE_PINGPONG:
//             updatePingPongLeds();
//             break;
//         case LED_MODE_GRADIENT:
//             updateGradientLeds();
//             break;
//         default:
//             break;
//         }
//     }

//     FastLED.show();
// }

// void updateVolumeLeds()
// {
//     int ledsToLight = map(appState.volumeLevel, 0, 100, 0, NUM_LEDS);
//     CRGB color;

//     if (appState.volumeLevel < 33)
//     {
//         color = CRGB::Green;
//     }
//     else if (appState.volumeLevel < 66)
//     {
//         color = CRGB::Yellow;
//     }
//     else
//     {
//         color = CRGB::Red;
//     }

//     for (int i = 0; i < NUM_LEDS; i++)
//     {
//         leds[i] = (i < ledsToLight) ? color : CRGB::Black;
//     }
// }

// void updateStaticLeds()
// {
//     CRGB color;
//     color.r = (appState.ledColor >> 16) & 0xFF;
//     color.g = (appState.ledColor >> 8) & 0xFF;
//     color.b = appState.ledColor & 0xFF;

//     fill_solid(leds, NUM_LEDS, color);
// }

// void updateBreathingLeds()
// {
//     CRGB color;
//     color.r = (appState.ledColor >> 16) & 0xFF;
//     color.g = (appState.ledColor >> 8) & 0xFF;
//     color.b = appState.ledColor & 0xFF;

//     uint8_t brightness = beatsin8(2, 50, 255);
//     fill_solid(leds, NUM_LEDS, color);
//     for (int i = 0; i < NUM_LEDS; i++)
//     {
//         leds[i].fadeToBlackBy(255 - brightness);
//     }
// }

// void updateRunningDotLeds()
// {
//     FastLED.clear();

//     CRGB color;
//     color.r = (appState.ledColor >> 16) & 0xFF;
//     color.g = (appState.ledColor >> 8) & 0xFF;
//     color.b = appState.ledColor & 0xFF;

//     leds[runningDotPos] = color;
//     runningDotPos = (runningDotPos + 1) % NUM_LEDS;
// }

// void updatePingPongLeds()
// {
//     FastLED.clear();

//     CRGB color;
//     color.r = (appState.ledColor >> 16) & 0xFF;
//     color.g = (appState.ledColor >> 8) & 0xFF;
//     color.b = appState.ledColor & 0xFF;

//     leds[pingPongPos] = color;
//     pingPongPos += pingPongDir;
//     if (pingPongPos >= NUM_LEDS - 1 || pingPongPos <= 0)
//     {
//         pingPongDir = -pingPongDir;
//     }
// }

// void updateGradientLeds()
// {
//     CRGB color;
//     color.r = (appState.ledColor >> 16) & 0xFF;
//     color.g = (appState.ledColor >> 8) & 0xFF;
//     color.b = appState.ledColor & 0xFF;

//     fill_rainbow(leds, NUM_LEDS, rainbowHue, 255 / NUM_LEDS);
//     rainbowHue++;
// }

// void setLedMode(int mode)
// {
//     appState.ledMode = constrain(mode, 1, 5);
//     runningDotPos = 0;
//     pingPongPos = 0;
//     pingPongDir = 1;
//     rainbowHue = 0;
// }

// void setLedBrightness(int brightness)
// {
//     appState.ledBrightness = constrain(brightness, 0, 255);
//     FastLED.setBrightness(appState.ledBrightness);
// }

// void setLedColor(uint32_t color)
// {
//     appState.ledColor = color;
// }

// void startVolumeMode(int level)
// {
//     appState.volumeModeActive = true;
//     appState.savedLedMode = appState.ledMode;
//     appState.volumeLevel = constrain(level, 0, 100);
// }

// void stopVolumeMode()
// {
//     appState.volumeModeActive = false;
//     appState.ledMode = appState.savedLedMode;
// }

#include "led_effects.h"
#include "app_state.h"
#include <FastLED.h>

#define LED_PIN 2
#define NUM_LEDS 7

CRGB leds[NUM_LEDS];
unsigned long lastLedUpdate = 0;
uint8_t hueCycle = 0;

// Вспомогательная функция для конвертации HEX цвета из appState в CRGB объект
CRGB getSelectedColor()
{
    CRGB color;
    color.r = (appState.ledColor >> 16) & 0xFF;
    color.g = (appState.ledColor >> 8) & 0xFF;
    color.b = appState.ledColor & 0xFF;
    return color;
}

void initLeds()
{
    FastLED.addLeds<WS2812B, LED_PIN, GRB>(leds, NUM_LEDS);
    FastLED.setBrightness(appState.ledBrightness);
    FastLED.clear();
    FastLED.show();
}

// 1. Статический цвет
static void updateStaticLeds()
{
    fill_solid(leds, NUM_LEDS, getSelectedColor());
}

// 2. Дыхание (плавное изменение яркости)
static void updateBreathingLeds()
{
    uint8_t brightness = beatsin8(15, 40, 255); // 15 "вдохов" в минуту
    CRGB col = getSelectedColor();
    fill_solid(leds, NUM_LEDS, col);
    fadeLightBy(leds, NUM_LEDS, 255 - brightness);
}

// 3. Комета (Бегущий огонек с хвостом)
static void updateCometEffect()
{
    fadeToBlackBy(leds, NUM_LEDS, 60);           // Частично гасим диоды для создания хвоста
    uint8_t pos = beatsin8(25, 0, NUM_LEDS - 1); // Движение по синусоиде
    leds[pos] |= getSelectedColor();             // Накладываем цвет головы
}

// 4. Радужный Пинг-Понг
static void updateRainbowPong()
{
    fadeToBlackBy(leds, NUM_LEDS, 45);
    static float pos = 0;
    static float speed = 0.25;

    pos += speed;
    if (pos >= NUM_LEDS - 1 || pos <= 0)
    {
        speed = -speed;
        hueCycle += 40; // Меняем цвет при ударе
    }
    leds[(int)pos] = CHSV(hueCycle, 255, 255);
}

// 5. Классическая радуга
static void updateFullRainbow()
{
    fill_rainbow(leds, NUM_LEDS, hueCycle++, 30);
}

// 6. Огонь
static void updateFireEffect()
{
    for (int i = 0; i < NUM_LEDS; i++)
    {
        // Случайные оттенки оранжевого и красного
        leds[i] = CHSV(random8(0, 22), 255, random8(130, 255));
    }
}

// 7. Матрица
static void updateMatrixEffect()
{
    fadeToBlackBy(leds, NUM_LEDS, 90);
    if (random8() > 210)
    {
        leds[random8(NUM_LEDS)] = CRGB::Green;
    }
}

// Режим громкости (вызывается извне)
// void updateVolumeLeds()
// {
//     int ledsToLight = map(appState.volumeLevel, 0, 100, 0, NUM_LEDS);
//     for (int i = 0; i < NUM_LEDS; i++)
//     {
//         if (i < ledsToLight)
//         {
//             if (i < 3)
//                 leds[i] = CRGB::Green;
//             else if (i < 5)
//                 leds[i] = CRGB::Yellow;
//             else
//                 leds[i] = CRGB::Red;
//         }
//         else
//         {
//             leds[i] = CRGB::Black;
//         }
//     }
// }

void updateVolumeLeds()
{
    // Сколько диодов зажигать в каждую сторону от центра (0.0 - 3.0)
    float halfFill = map(appState.volumeLevel, 0, 100, 0, 300) / 100.0f; // 0.0 .. 3.0
    int center = 3;                                                      // индекс центрального диода (из 0..6)

    for (int i = 0; i < NUM_LEDS; i++)
    {
        float dist = abs(i - center); // расстояние от центра (0..3)

        if (dist <= halfFill)
        {
            // Диод полностью в зоне заполнения
            // hue: 96 = зелёный (центр) → 0 = красный (края)
            uint8_t hue = (uint8_t)(96 - (dist / 3.0f) * 96);

            // Яркость: центр ярче, края чуть темнее
            uint8_t brightness = (uint8_t)(255 - (dist / 3.0f) * 80);

            leds[i] = CHSV(hue, 255, brightness);
        }
        else if (dist < halfFill + 1.0f)
        {
            // Частично заполненный диод на границе — плавное угасание
            float fade = halfFill + 1.0f - dist; // 0.0 .. 1.0
            uint8_t hue = (uint8_t)(96 - (dist / 3.0f) * 96);
            uint8_t brightness = (uint8_t)(fade * (255 - (dist / 3.0f) * 80));

            leds[i] = CHSV(hue, 255, brightness);
        }
        else
        {
            // За зоной — гасим совсем, но оставляем еле видимый отблеск
            leds[i] = CHSV(0, 0, 8); // почти чёрный, чуть теплее чем ноль
        }
    }
}

void updateLeds()
{
    unsigned long now = millis();
    if (now - lastLedUpdate < 30)
        return; // ~33 FPS
    lastLedUpdate = now;

    if (appState.volumeModeActive)
    {
        updateVolumeLeds();
    }
    else
    {
        switch (appState.ledMode)
        {
        case LED_MODE_STATIC:
            updateStaticLeds();
            break;
        case LED_MODE_BREATHING:
            updateBreathingLeds();
            break;
        case LED_MODE_COMET:
            updateCometEffect();
            break;
        case LED_MODE_RAINBOW_PONG:
            updateRainbowPong();
            break;
        case LED_MODE_RAINBOW:
            updateFullRainbow();
            break;
        case LED_MODE_FIRE:
            updateFireEffect();
            break;
        case LED_MODE_MATRIX:
            updateMatrixEffect();
            break;
        default:
            fill_solid(leds, NUM_LEDS, CRGB::Black);
            break;
        }
    }
    FastLED.show();
}

void setLedMode(int mode)
{
    appState.ledMode = constrain(mode, 1, 7);
    FastLED.clear(true); // Мгновенно очистить ленту при смене режима
}

void setLedBrightness(int brightness)
{
    appState.ledBrightness = constrain(brightness, 0, 255);
    FastLED.setBrightness(appState.ledBrightness);
}

void setLedColor(uint32_t color)
{
    appState.ledColor = color;
}

void startVolumeMode(int level)
{
    appState.volumeModeActive = true;
    appState.lastLedMode = appState.ledMode;
    appState.volumeLevel = level;
}

void stopVolumeMode()
{
    appState.volumeModeActive = false;
    appState.ledMode = appState.lastLedMode;
}