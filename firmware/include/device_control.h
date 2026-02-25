#ifndef DEVICE_CONTROL_H
#define DEVICE_CONTROL_H

#include <Arduino.h>

void initDeviceControl();
void setScreenBrightness(int brightness);
void playSound(int frequency, int duration);
void saveSettings();
void loadSettings();
void updateConnectionStatus();
void updateAutoBrightness();
void updateSleepMode();

#endif
