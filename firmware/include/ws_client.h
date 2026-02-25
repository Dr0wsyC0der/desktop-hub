#ifndef WS_CLIENT_H
#define WS_CLIENT_H

#include <Arduino.h>

void initWebSocketClient();
void updateWebSocketClient();
void sendWebSocketMessage(const String &message);
bool isWebSocketConnected();
void reconnectWebSocket();
void forceWebSocketReconnect();

#endif
