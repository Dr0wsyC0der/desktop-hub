#ifndef HELPERS_H
#define HELPERS_H

#include <Arduino.h>
#include <time.h>
#include <vector>
#include <algorithm>
#include <lvgl.h>

// Helper functions for bus schedule time parsing and comparison
struct BusTime
{
    int hours;
    int minutes;

    BusTime() : hours(0), minutes(0) {}
    BusTime(int h, int m) : hours(h), minutes(m) {}

    bool operator<(const BusTime &other) const
    {
        if (hours != other.hours)
            return hours < other.hours;
        return minutes < other.minutes;
    }

    int toMinutes() const
    {
        return hours * 60 + minutes;
    }

    static BusTime fromString(String timeStr)
    {
        BusTime bt;
        int colonPos = timeStr.indexOf(':');
        if (colonPos > 0)
        {
            bt.hours = timeStr.substring(0, colonPos).toInt();
            bt.minutes = timeStr.substring(colonPos + 1).toInt();
        }
        return bt;
    }

    String toString() const
    {
        char buf[6];
        snprintf(buf, sizeof(buf), "%02d:%02d", hours, minutes);
        return String(buf);
    }
};

// Find next bus times relative to current time
inline std::vector<BusTime> findNextBusTimes(const std::vector<String> &times, int currentHour, int currentMinute)
{
    std::vector<BusTime> busTimes;
    BusTime currentTime(currentHour, currentMinute);

    // Parse all times
    for (const String &timeStr : times)
    {
        BusTime bt = BusTime::fromString(timeStr);
        busTimes.push_back(bt);
    }

    // Sort times
    std::sort(busTimes.begin(), busTimes.end());

    // Find next 4 times
    std::vector<BusTime> nextTimes;
    bool foundToday = false;

    // First, find times today
    for (const BusTime &bt : busTimes)
    {
        if (bt.toMinutes() >= currentTime.toMinutes())
        {
            nextTimes.push_back(bt);
            foundToday = true;
            if (nextTimes.size() >= 4)
                break;
        }
    }

    // If not enough times today, add from tomorrow (next day)
    if (nextTimes.size() < 4)
    {
        for (const BusTime &bt : busTimes)
        {
            if (nextTimes.size() >= 4)
                break;
            nextTimes.push_back(bt);
        }
    }

    return nextTimes;
}

// Convert hex color string to lv_color_t
inline lv_color_t hexToColor(String hex)
{
    if (hex.startsWith("#"))
    {
        hex = hex.substring(1);
    }
    long color = strtol(hex.c_str(), NULL, 16);
    return lv_color_hex(color);
}

// Format date string (max 8 chars: "2.2.2026")
inline String formatDate(struct tm *timeinfo)
{
    char buf[10];
    snprintf(buf, sizeof(buf), "%d.%d.%d",
             timeinfo->tm_mday,
             timeinfo->tm_mon + 1,
             timeinfo->tm_year + 1900);
    return String(buf);
}

// Format day name (max 4 chars)
inline String formatDay(struct tm *timeinfo)
{
    const char *days[] = {"Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"};
    return String(days[timeinfo->tm_wday]);
}

// Check if we should switch to tomorrow's schedule
inline bool shouldUseTomorrowSchedule(struct tm *timeinfo)
{
    // Use tomorrow's schedule if:
    // 1. It's after 23:00 (late evening)
    // 2. Or if it's very early morning (before 6:00) - might be next day's schedule
    return timeinfo->tm_hour >= 23 || timeinfo->tm_hour < 6;
}

inline void setupTimeFromOffset(long offsetSeconds)
{
    Serial.printf("[TIME] Setting timezone offset: %ld\n", offsetSeconds);

    configTime(offsetSeconds, 0, "pool.ntp.org", "time.google.com");

    struct tm timeinfo;
    for (int i = 0; i < 10; i++)
    {
        if (getLocalTime(&timeinfo))
        {
            Serial.printf("[TIME] Synced: %02d:%02d:%02d\n",
                          timeinfo.tm_hour,
                          timeinfo.tm_min,
                          timeinfo.tm_sec);
            appState.timeValid = true;
            return;
        }
        delay(300);
    }

    Serial.println("[TIME] Failed to sync");
}

#endif