#ifndef LED_EFFECTS_H
#define LED_EFFECTS_H

#include <Arduino.h>

void initLeds();
void updateLeds();
void setLedMode(int mode);
void setLedBrightness(int brightness);
void setLedColor(uint32_t color);
void startVolumeMode(int level);
void stopVolumeMode();

enum LedMode
{
    LED_MODE_VOLUME = 0, // Служебный режим (не участвует в переборе кнопкой)
    LED_MODE_STATIC = 1,
    LED_MODE_BREATHING = 2,
    LED_MODE_COMET = 3,
    LED_MODE_RAINBOW_PONG = 4,
    LED_MODE_RAINBOW = 5,
    LED_MODE_FIRE = 6,
    LED_MODE_MATRIX = 7
};

#endif
