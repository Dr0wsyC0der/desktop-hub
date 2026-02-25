#include "bus_schedule.h"
#include "app_state.h"
#include "helpers.h"
#include <ArduinoJson.h>
#include <LittleFS.h>
#include <ui.h>

#define BUS_SCHEDULE_FILE "/bus_schedule.json"

void initBusSchedule()
{
    loadBusScheduleFromFlash();
}

void updateBusScheduleDisplay()
{
    if (!busScheduleData.hasData)
        return;

    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
        return;

    checkScheduleDateChange();

    bool useTomorrow = shouldUseTomorrowSchedule(&timeinfo);
    std::vector<BusSchedule> *schedule = useTomorrow ? &busScheduleData.tomorrow : &busScheduleData.today;

    lv_obj_t *busLabels[] = {ui_bus1, ui_bus2, ui_bus3, ui_bus4};

    struct BusTimeLabels
    {
        lv_obj_t *h1, *d1, *m1, *h2, *d2, *m2, *h3, *d3, *m3, *h4, *d4, *m4;
    };

    BusTimeLabels busLabelsArray[4] = {
        {ui_b1hours1, ui_b1dots1, ui_b1minutes1, ui_b1hours2, ui_b1dots2, ui_b1minutes2,
         ui_b1hours3, ui_b1dots3, ui_b1minutes3, ui_b1hours4, ui_b1dots4, ui_b1minutes4},
        {ui_b2hours1, ui_b2dots1, ui_b2minutes1, ui_b2hours2, ui_b2dots2, ui_b2minutes2,
         ui_b2hours3, ui_b2dots3, ui_b2minutes3, ui_b2hours4, ui_b2dots4, ui_b2minutes4},
        {ui_b3hours1, ui_b3dots1, ui_b3minutes1, ui_b3hours2, ui_b3dots2, ui_b3minutes2,
         ui_b3hours3, ui_b3dots3, ui_b3minutes3, ui_b3hours4, ui_b3dots4, ui_b3minutes4},
        {ui_b4hours1, ui_b4dots1, ui_b4minutes1, ui_b4hours2, ui_b4dots2, ui_b4minutes2,
         ui_b4hours3, ui_b4dots3, ui_b4minutes3, ui_b4hours4, ui_b4dots4, ui_b4minutes4}};

    for (int i = 0; i < 4 && i < schedule->size(); i++)
    {
        BusSchedule &bus = (*schedule)[i];

        if (busLabels[i])
        {
            lv_label_set_text(busLabels[i], bus.name.c_str());
        }

        std::vector<BusTime> nextTimes = findNextBusTimes(bus.times, timeinfo.tm_hour, timeinfo.tm_min);

        BusTimeLabels &labels = busLabelsArray[i];
        lv_obj_t *timeLabelSets[4][3] = {
            {labels.h1, labels.d1, labels.m1},
            {labels.h2, labels.d2, labels.m2},
            {labels.h3, labels.d3, labels.m3},
            {labels.h4, labels.d4, labels.m4}};

        for (int j = 0; j < 4 && j < nextTimes.size(); j++)
        {
            BusTime &bt = nextTimes[j];
            char hoursBuf[3], minutesBuf[3];
            snprintf(hoursBuf, sizeof(hoursBuf), "%02d", bt.hours);
            snprintf(minutesBuf, sizeof(minutesBuf), "%02d", bt.minutes);

            if (timeLabelSets[j][0])
                lv_label_set_text(timeLabelSets[j][0], hoursBuf);
            if (timeLabelSets[j][1])
                lv_label_set_text(timeLabelSets[j][1], ":");
            if (timeLabelSets[j][2])
                lv_label_set_text(timeLabelSets[j][2], minutesBuf);
        }
    }
}

void checkScheduleDateChange()
{
    struct tm timeinfo;
    if (!getLocalTime(&timeinfo))
        return;

    if (busScheduleData.lastDay != timeinfo.tm_mday)
    {
        busScheduleData.lastDay = timeinfo.tm_mday;
    }
}

void loadBusScheduleFromFlash()
{
    if (!LittleFS.exists(BUS_SCHEDULE_FILE))
    {
        Serial.println("[Bus] No cached schedule found");
        return;
    }

    File file = LittleFS.open(BUS_SCHEDULE_FILE, "r");
    if (!file)
    {
        Serial.println("[Bus] Failed to open schedule file");
        return;
    }

    String content = file.readString();
    file.close();

    DynamicJsonDocument doc(4096);
    DeserializationError error = deserializeJson(doc, content);

    if (error)
    {
        Serial.println("[Bus] JSON parse error");
        return;
    }

    if (doc.containsKey("date"))
    {
        busScheduleData.scheduleDate = doc["date"].as<String>();
    }

    busScheduleData.today.clear();
    busScheduleData.tomorrow.clear();

    if (doc.containsKey("today"))
    {
        JsonArray todayArray = doc["today"];
        for (JsonObject bus : todayArray)
        {
            BusSchedule busSchedule;
            busSchedule.name = bus["name"] | "";
            busSchedule.url = bus["url"] | "";
            busSchedule.stopName = bus["stop_name"] | "";

            JsonArray timesArray = bus["times"];
            for (String time : timesArray)
            {
                busSchedule.times.push_back(time);
            }
            busScheduleData.today.push_back(busSchedule);
        }
    }

    if (doc.containsKey("tomorrow"))
    {
        JsonArray tomorrowArray = doc["tomorrow"];
        for (JsonObject bus : tomorrowArray)
        {
            BusSchedule busSchedule;
            busSchedule.name = bus["name"] | "";
            busSchedule.url = bus["url"] | "";
            busSchedule.stopName = bus["stop_name"] | "";

            JsonArray timesArray = bus["times"];
            for (String time : timesArray)
            {
                busSchedule.times.push_back(time);
            }
            busScheduleData.tomorrow.push_back(busSchedule);
        }
    }

    busScheduleData.hasData = true;
    Serial.println("[Bus] Schedule loaded from flash");
}

void saveBusScheduleToFlash()
{
    DynamicJsonDocument doc(4096);
    doc["date"] = busScheduleData.scheduleDate;
    JsonArray todayArray = doc["today"].to<JsonArray>();
    JsonArray tomorrowArray = doc["tomorrow"].to<JsonArray>();

    for (const auto &bus : busScheduleData.today)
    {
        JsonObject busObj = todayArray.add<JsonObject>();
        busObj["name"] = bus.name;
        busObj["url"] = bus.url;
        busObj["stop_name"] = bus.stopName;

        JsonArray timesArray = busObj["times"].to<JsonArray>();
        for (const auto &time : bus.times)
        {
            timesArray.add(time);
        }
    }

    for (const auto &bus : busScheduleData.tomorrow)
    {
        JsonObject busObj = tomorrowArray.add<JsonObject>();
        busObj["name"] = bus.name;
        busObj["url"] = bus.url;
        busObj["stop_name"] = bus.stopName;

        JsonArray timesArray = busObj["times"].to<JsonArray>();
        for (const auto &time : bus.times)
        {
            timesArray.add(time);
        }
    }

    File file = LittleFS.open(BUS_SCHEDULE_FILE, "w");
    if (file)
    {
        serializeJson(doc, file);
        file.close();
        Serial.println("[Bus] Schedule saved to flash");
    }
}
