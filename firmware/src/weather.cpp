#include "weather.h"
#include "app_state.h"
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <ui.h>
#include "helpers.h"

void initWeather()
{
}

void updateWeather()
{
    Serial.printf("Free heap: %d\n", ESP.getFreeHeap());
    if (appState.openWeatherAPIKey.length() == 0)
        return;

    if (!appState.wifiConnected)
        return;
    if (appState.weatherLat == 0.0 && appState.weatherLon == 0.0)
        return;

    HTTPClient http;
    http.setTimeout(5000);
    if (appState.weatherLat == 0.0 && appState.weatherLon == 0.0)
        return;

    String url = "http://api.openweathermap.org/data/2.5/weather?lat=" +
                 String(appState.weatherLat, 6) +
                 "&lon=" +
                 String(appState.weatherLon, 6) +
                 "&appid=" +
                 appState.openWeatherAPIKey +
                 "&units=metric";

    http.begin(url);
    int httpCode = http.GET();

    if (httpCode == HTTP_CODE_OK)
    {
        String payload = http.getString();
        DynamicJsonDocument doc(768);
        deserializeJson(doc, payload);

        weatherData.city = doc["name"] | "";
        weatherData.region = doc["sys"]["country"] | "";
        weatherData.temperature = doc["main"]["temp"] | 0.0;
        weatherData.feelsLike = doc["main"]["feels_like"] | 0.0;
        weatherData.humidity = doc["main"]["humidity"] | 0;

        String mainCondition = doc["weather"][0]["main"] | "";
        String description = doc["weather"][0]["description"] | "";
        int weatherId = doc["weather"][0]["id"] | 0;

        if (!appState.timeValid)
        {
            long timezoneOffset = doc["timezone"] | 0;
            setupTimeFromOffset(timezoneOffset);
        }

        if (mainCondition == "Clear")
        {
            weatherData.condition = "sunny";
        }
        else if (mainCondition == "Clouds")
        {
            if (weatherId >= 801 && weatherId <= 802)
            {
                weatherData.condition = "partly clowdy";
            }
            else
            {
                weatherData.condition = "clowdy";
            }
        }
        else if (mainCondition == "Rain")
        {
            if (description.indexOf("snow") >= 0 || weatherId >= 600)
            {
                weatherData.condition = "snow and rain";
            }
            else
            {
                weatherData.condition = "rainy";
            }
        }
        else if (mainCondition == "Snow")
        {
            weatherData.condition = "snowy";
        }
        else if (mainCondition == "Thunderstorm")
        {
            weatherData.condition = "storm";
        }
        else
        {
            weatherData.condition = "clowdy";
        }

        weatherData.localIP = WiFi.localIP().toString();
        weatherData.lastUpdate = millis();

        Serial.println("[Weather] Updated: " + weatherData.city + ", " + String(weatherData.temperature) + "C");
    }
    else
    {
        Serial.println("[Weather] HTTP error: " + String(httpCode));
    }
    http.end();
}

void updateWeatherDisplay()
{
    if (ui_city)
    {
        lv_label_set_text(ui_city, weatherData.city.c_str());
    }
    if (ui_region)
    {
        lv_label_set_text(ui_region, weatherData.region.c_str());
    }
    if (ui_templabel)
    {
        char buf[20];
        snprintf(buf, sizeof(buf), "%.0f°C", weatherData.temperature);
        lv_label_set_text(ui_templabel, buf);
    }
    if (ui_tempbar)
    {
        lv_bar_set_value(ui_tempbar, (int)weatherData.temperature, LV_ANIM_ON);
    }
    if (ui_hmlabel)
    {
        char buf[20];
        snprintf(buf, sizeof(buf), "%d%%", weatherData.humidity);
        lv_label_set_text(ui_hmlabel, buf);
    }
    if (ui_hmbar)
    {
        lv_bar_set_value(ui_hmbar, weatherData.humidity, LV_ANIM_ON);
    }

    lv_obj_t *weatherImg = nullptr;
    if (weatherData.condition == "sunny")
        weatherImg = ui_sunny;
    else if (weatherData.condition == "snowy")
        weatherImg = ui_snowy;
    else if (weatherData.condition == "rainy")
        weatherImg = ui_rainy;
    else if (weatherData.condition == "clowdy")
        weatherImg = ui_clowdy;
    else if (weatherData.condition == "storm")
        weatherImg = ui_storm;
    else if (weatherData.condition == "partly clowdy")
        weatherImg = ui_partly_clowdly;
    else if (weatherData.condition == "snow and rain")
        weatherImg = ui_snow_and_rain;

    if (weatherImg && ui_weather_img)
    {
        lv_obj_add_flag(ui_sunny, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_snowy, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_rainy, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_clowdy, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_storm, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_partly_clowdly, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(ui_snow_and_rain, LV_OBJ_FLAG_HIDDEN);
        lv_obj_clear_flag(weatherImg, LV_OBJ_FLAG_HIDDEN);
    }

    if (ui_simb_weather)
    {
        lv_label_set_text(ui_simb_weather, weatherData.condition.c_str());
    }
}
