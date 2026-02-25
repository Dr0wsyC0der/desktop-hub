#include "app_state.h"

AppState appState;
WeatherData weatherData;
BusScheduleData busScheduleData;
PCLoadData pcLoadData;

// Инициализация глобального файла
File animFile;
lv_timer_t *animTimer = nullptr;