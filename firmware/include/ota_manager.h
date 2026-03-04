#ifndef OTA_MANAGER_H
#define OTA_MANAGER_H

#include <Arduino.h>

typedef void (*OtaEventCallback)(int progress, const char *stage, const char *message);

void initOtaManager();
void setOtaEventCallback(OtaEventCallback callback);
bool requestOtaUpdate(const String &url, const String &md5 = "");
void updateOtaManager();
bool isOtaInProgress();

#endif
