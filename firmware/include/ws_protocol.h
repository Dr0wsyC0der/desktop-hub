#ifndef WS_PROTOCOL_H
#define WS_PROTOCOL_H

#include <Arduino.h>
#include <ArduinoJson.h>

void processWebSocketMessage(const String &message);
void processJSONCommand(JsonDocument &doc);
void handleVolumeCommand(int volume);
void handleBusScheduleCommand(JsonObject doc);
void handlePcLoadCommand(JsonDocument &doc);
void handleSetColorCommand(JsonDocument &doc);
void handleSettingsCommand(JsonDocument &doc);
void handleLedStateCommand(JsonDocument &doc);
void handleOtaCommand(JsonDocument &doc);
void handleGifCommand(JsonDocument &doc);
void applySavedUiColors();

#endif
