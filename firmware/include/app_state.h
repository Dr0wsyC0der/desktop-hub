#ifndef APP_STATE_H
#define APP_STATE_H

#include <Arduino.h>
#include <vector>
#include <time.h>
#include <freertos/semphr.h> // <--- ВАЖНО
#include <lvgl.h>
#include <FS.h>       // <--- Нужно для File
#include <LittleFS.h> // <--- Нужно для LittleFS

// Screen navigation
enum ScreenID
{
    SCREEN_1 = 1,
    SCREEN_2 = 2,
    SCREEN_3 = 3,
    SCREEN_4 = 4,
    SCREEN_6 = 6,
    SCREEN_7 = 7
};

struct AppState
{
    // WiFi and connections
    bool wifiConnected = false;
    bool pcConnected = false;
    bool isFirstBoot = true;
    bool isDataLoading = false;

    // Screen management
    ScreenID currentScreen = SCREEN_1;
    ScreenID previousScreen = SCREEN_1;
    unsigned long screen2StartTime = 0;
    bool screen2Active = false;
    // LED state
    int ledMode = 5;
    int ledBrightness = 120;
    uint32_t ledColor = 0xFFFFFF;
    bool volumeModeActive = false;
    int volumeLevel = 0;
    int lastLedMode = 5;
    // Settings
    int screenBrightness = 200;
    bool autoBrightness = false;
    int ldrPin = 6;
    int autoBrightnessMin = 30;  // минимум экрана
    int autoBrightnessMax = 255; // максимум
    int autoLedMin = 10;         // минимум LED при автояркости (0–255)
    int autoLedMax = 255;

    float autoBrightnessGamma = 2.2;     // гамма-коррекция
    float autoBrightnessSmoothing = 0.1; // 0.05–0.2
    int autoBrightnessNightMin = 0;      // ночной минимум (в процентах)
    int buzzerVolume = 60;
    int defaultLedMode = 5;

    // Configuration
    String wifiSSID;
    String wifiPassword;
    String pcIP;
    int wsPort = 8765;
    String wsPath = "/ws";
    String openWeatherAPIKey;
    String openWeatherCity;

    // Time and date
    time_t lastTimeSync = 0;
    bool timeValid = false;

    // GIF / Animation State
    bool animReceiving = false;
    int animFrames = 0;
    int animWidth = 0;
    int animHeight = 0;
    size_t animFrameSize = 0;
    size_t animTotalSize = 0;
    size_t animReceivedBytes = 0;
    int animDelay = 100; // Задержка между кадрами (мс)

    // Song overlay
    bool screen7Active = false;
    unsigned long screen7StartTime = 0;
    ScreenID screen7ReturnScreen = SCREEN_1;
    String currentSongName;
    String currentSongAuthor;

    // Sleep mode
    bool sleepEnabled = false;
    int sleepStartHour = 23;
    int sleepStartMinute = 0;
    int sleepEndHour = 7;
    int sleepEndMinute = 0;
    bool isSleepingNow = false;

    // Weather settings
    float weatherLat = 0.0;
    float weatherLon = 0.0;
    bool useCoordinates = false;
    int weatherTimeoutSec = 600;
};

struct WeatherData
{
    String city;
    String region;
    float temperature = 0;
    float feelsLike = 0;
    float pressureHpa = 0;
    int humidity = 0;
    String condition;
    String localIP;
    unsigned long lastUpdate = 0;
};

struct BusSchedule
{
    String name;
    String url;
    String stopName;
    std::vector<String> times;
};

struct BusScheduleData
{
    std::vector<BusSchedule> today;
    std::vector<BusSchedule> tomorrow;
    bool hasData = false;
    int lastDay = -1;
    unsigned long lastUpdate = 0;
    String scheduleDate;
};

struct PCLoadData
{
    int cpu = 0;
    int gpu = 0;
    int ram = 0;
    bool active = false;
    unsigned long lastUpdate = 0;
};

extern AppState appState;
extern WeatherData weatherData;
extern BusScheduleData busScheduleData;
extern PCLoadData pcLoadData;

// Глобальный мьютекс для защиты LVGL
extern SemaphoreHandle_t uiMutex;

// Добавляем глобальную переменную файла
extern File animFile;
extern lv_timer_t *animTimer;

#endif
