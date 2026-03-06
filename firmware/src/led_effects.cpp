#include "led_effects.h"
#include "app_state.h"
#include <FastLED.h>

#define LED_PIN 2
#define NUM_LEDS 7

CRGB leds[NUM_LEDS];
unsigned long lastLedUpdate = 0;
uint8_t hueCycle = 0;

static CRGB getSelectedColor()
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

static void updateStaticLeds()
{
    fill_solid(leds, NUM_LEDS, getSelectedColor());
}

static void updateBreathingLeds()
{
    uint8_t brightness = beatsin8(15, 40, 255);
    CRGB color = getSelectedColor();
    fill_solid(leds, NUM_LEDS, color);
    fadeLightBy(leds, NUM_LEDS, 255 - brightness);
}

static void updateCometEffect()
{
    fadeToBlackBy(leds, NUM_LEDS, 60);
    uint8_t pos = beatsin8(25, 0, NUM_LEDS - 1);
    leds[pos] |= getSelectedColor();
}

static void updateRainbowPong()
{
    fadeToBlackBy(leds, NUM_LEDS, 45);
    static float pos = 0.0f;
    static float speed = 0.25f;

    pos += speed;
    if (pos >= NUM_LEDS - 1 || pos <= 0)
    {
        speed = -speed;
        hueCycle += 40;
    }

    leds[(int)pos] = CHSV(hueCycle, 255, 255);
}

static void updateFullRainbow()
{
    fill_rainbow(leds, NUM_LEDS, hueCycle++, 30);
}

static void updateConfettiEffect()
{
    static bool spawnPhase = false;
    spawnPhase = !spawnPhase;

    fadeToBlackBy(leds, NUM_LEDS, 32);

    if (spawnPhase)
    {
        uint8_t pos = random8(NUM_LEDS);
        leds[pos] += CHSV(hueCycle + random8(96), 220, 255);

        if (random8() > 235)
        {
            leds[random8(NUM_LEDS)] += CRGB::White;
        }
    }

    hueCycle++;
}

static void updateAuroraEffect()
{
    static uint8_t auroraDrift = 0;

    for (int i = 0; i < NUM_LEDS; i++)
    {
        uint8_t paletteIndex = sin8(auroraDrift + i * 24);
        uint8_t brightness = qadd8(75, scale8(sin8(auroraDrift + i * 27), 170));
        leds[i] = ColorFromPalette(OceanColors_p, paletteIndex, brightness);
    }

    auroraDrift++;
    if ((auroraDrift & 0x01) == 0)
    {
        hueCycle++;
    }
}

static void updatePrismEffect()
{
    static uint8_t prismDrift = 0;

    for (int i = 0; i < NUM_LEDS; i++)
    {
        uint8_t wave = cubicwave8(prismDrift * 2 + i * 26);
        uint8_t hue = hueCycle * 2 + i * 22 + scale8(wave, 72);
        uint8_t brightness = qadd8(65, scale8(wave, 180));
        leds[i] = CHSV(hue, 230, brightness);
    }

    leds[(prismDrift / 10) % NUM_LEDS] += CRGB::White;
    prismDrift++;
    if ((prismDrift & 0x01) == 0)
    {
        hueCycle++;
    }
}

static void updateVolumeLeds()
{
    float halfFill = map(appState.volumeLevel, 0, 100, 0, 300) / 100.0f;
    int center = 3;

    for (int i = 0; i < NUM_LEDS; i++)
    {
        float dist = abs(i - center);

        if (dist <= halfFill)
        {
            uint8_t hue = (uint8_t)(96 - (dist / 3.0f) * 96);
            uint8_t brightness = (uint8_t)(255 - (dist / 3.0f) * 80);
            leds[i] = CHSV(hue, 255, brightness);
        }
        else if (dist < halfFill + 1.0f)
        {
            float fade = halfFill + 1.0f - dist;
            uint8_t hue = (uint8_t)(96 - (dist / 3.0f) * 96);
            uint8_t brightness = (uint8_t)(fade * (255 - (dist / 3.0f) * 80));
            leds[i] = CHSV(hue, 255, brightness);
        }
        else
        {
            leds[i] = CHSV(0, 0, 8);
        }
    }
}

void updateLeds()
{
    unsigned long now = millis();
    if (now - lastLedUpdate < 30)
        return;

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
        case LED_MODE_CONFETTI:
            updateConfettiEffect();
            break;
        case LED_MODE_AURORA:
            updateAuroraEffect();
            break;
        case LED_MODE_PRISM:
            updatePrismEffect();
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
    appState.ledMode = constrain(mode, 1, LED_MODE_PRISM);
    FastLED.clear(true);
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
