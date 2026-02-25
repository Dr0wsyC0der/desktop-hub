#ifndef BUS_SCHEDULE_H
#define BUS_SCHEDULE_H

#include <Arduino.h>
#include <time.h>

void initBusSchedule();
void updateBusScheduleDisplay();
void loadBusScheduleFromFlash();
void saveBusScheduleToFlash();
void checkScheduleDateChange();

#endif
