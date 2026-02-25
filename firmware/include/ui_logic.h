#ifndef UI_LOGIC_H
#define UI_LOGIC_H

#include <Arduino.h>
#include "app_state.h"

extern volatile bool buttonInterruptFlag;
void switchScreen(ScreenID screen, bool reverse = false);
void handleButtonPress();
void updateTimeDisplay();
void updateScreen1();
void updateScreen3();
void updateScreen4();
void updateScreen6();
void handleScreen2Timeout();
void handleScreen7Timeout();
void startAnimation();
void stopAnimation();

#endif
