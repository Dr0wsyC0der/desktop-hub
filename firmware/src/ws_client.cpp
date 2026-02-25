#include "ws_client.h"
#include "app_state.h"
#include "ws_protocol.h"
#include <WebSocketsClient.h>
#include <LittleFS.h>
#include <FS.h>
#include "ui_logic.h"
#include "device_control.h"

WebSocketsClient webSocket;
unsigned long lastWsReconnectAttempt = 0;
const unsigned long WS_RECONNECT_INTERVAL = 5000;
unsigned long deviceBootTime = 0;

const unsigned long WS_BOOT_PHASE_DURATION = 60000;    // 2 минуты
const unsigned long WS_BOOT_RETRY_INTERVAL = 5000;     // каждые 5 сек
const unsigned long WS_NORMAL_RETRY_INTERVAL = 900000; // 15 минут
bool wsConnecting = false;
unsigned long wsConnectStartTime = 0;
const unsigned long WS_CONNECT_TIMEOUT = 10000; // 10 секунд на попытку
static bool wsBeginCalled = false;              // был ли begin() вызван хоть раз
static bool wsParked = false;                   // "припаркованы" — не крутим loop

void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length)
{
    switch (type)
    {
    case WStype_DISCONNECTED:
        wsConnecting = false;
        wsParked = true;
        appState.pcConnected = false;
        appState.isDataLoading = false;
        updateConnectionStatus();
        Serial.println("[WS] Disconnected");
        break;

    case WStype_CONNECTED:
        wsConnecting = false;
        wsParked = false;
        appState.pcConnected = true;
        appState.isDataLoading = false;
        updateConnectionStatus();
        Serial.println("[WS] Connected");
        break;

    case WStype_TEXT:
    {
        String message((char *)payload);
        Serial.println("[WS] Received: " + message);
        processWebSocketMessage(message);
        break;
    }

    case WStype_BIN:
        if (appState.animReceiving)
        {
            if (animFile)
            {
                animFile.write(payload, length);
                appState.animReceivedBytes += length;

                // Выводим лог прогресса каждые ~15 КБ, чтобы не перегружать консоль
                // Или если это последний пакет
                if (appState.animReceivedBytes % 14600 == 0 || appState.animReceivedBytes >= appState.animTotalSize)
                {
                    Serial.printf("[Anim] Downloading: %u / %u bytes (%u%%)\n",
                                  appState.animReceivedBytes,
                                  appState.animTotalSize,
                                  (appState.animReceivedBytes * 100) / appState.animTotalSize);
                }

                // Даем системе обработать фоновые задачи (WiFi, TCP)
                yield();
            }

            if (appState.animReceivedBytes >= appState.animTotalSize)
            {
                animFile.close();
                appState.animReceiving = false;
                Serial.println("[Anim] Transfer complete! Finalizing...");

                // Проверка: реально ли файл записался
                File check = LittleFS.open("/anim.bin", "r");
                if (check)
                {
                    Serial.printf("[Anim] File saved on FS. Size: %u bytes\n", check.size());
                    check.close();
                }

                startAnimation();
                sendWebSocketMessage("{\"type\":\"gif_ready\",\"status\":\"success\"}");
            }
        }
        break;

    default:
        break;
    }
}

void initWebSocketClient()
{
    deviceBootTime = millis();
    webSocket.onEvent(onWebSocketEvent);
    webSocket.setReconnectInterval(0);         // 🚫 отключаем авто-реконнект
    webSocket.enableHeartbeat(15000, 3000, 2); // можно оставить heartbeat
}

void updateWebSocketClient()
{
    // Если соединение установлено — всегда крутим loop
    if (appState.pcConnected)
    {
        webSocket.loop();
        return;
    }

    // Если идёт активная попытка — крутим loop и следим за таймаутом
    if (wsConnecting)
    {
        webSocket.loop();
        if (millis() - wsConnectStartTime > WS_CONNECT_TIMEOUT)
        {
            Serial.println("[WS] Connect timeout. Parking socket.");
            webSocket.disconnect();
            wsConnecting = false;
            wsParked = true; // останавливаем loop до следующей попытки
        }
        return;
    }

    // Пока "припаркованы" — НЕ вызываем loop, библиотека молчит
    reconnectWebSocket();
}

void reconnectWebSocket()
{
    if (!appState.wifiConnected || appState.pcConnected)
        return;

    unsigned long now = millis();
    bool inBootPhase = (now - deviceBootTime) < WS_BOOT_PHASE_DURATION;
    unsigned long retryInterval = inBootPhase ? WS_BOOT_RETRY_INTERVAL : WS_NORMAL_RETRY_INTERVAL;

    if (now - lastWsReconnectAttempt < retryInterval)
        return;

    lastWsReconnectAttempt = now;

    if (appState.pcIP.length() == 0)
        return;

    Serial.print("[WS] Reconnect attempt (");
    Serial.print(inBootPhase ? "BOOT" : "NORMAL");
    Serial.print(") to ");
    Serial.print(appState.pcIP);
    Serial.print(":");
    Serial.print(appState.wsPort);
    Serial.println(appState.wsPath);

    wsParked = false; // снимаем парковку — начинаем новую попытку

    if (wsBeginCalled)
    {
        webSocket.disconnect();
        delay(50);
    }

    webSocket.begin(appState.pcIP.c_str(), appState.wsPort, appState.wsPath.c_str());
    wsBeginCalled = true;

    wsConnecting = true;
    wsConnectStartTime = now;

    appState.isDataLoading = true;
    updateConnectionStatus();
}

void sendWebSocketMessage(const String &message)
{
    if (appState.pcConnected)
    {
        // WebSocketsClient::sendTXT expects a non-const String&, make a mutable copy
        String tmp = message;
        webSocket.sendTXT(tmp);
    }
}

bool isWebSocketConnected()
{
    return appState.pcConnected;
}

void forceWebSocketReconnect()
{
    if (!appState.wifiConnected || appState.pcConnected)
        return;

    Serial.println("[WS] FORCE reconnect attempt");

    // ВАЖНО: мы не трогаем deviceBootTime
    // Просто сбрасываем интервал ожидания

    lastWsReconnectAttempt = millis(); // чтобы следующий авто retry был через 15 мин

    wsParked = false;

    if (wsBeginCalled)
    {
        webSocket.disconnect();
        delay(50);
    }

    webSocket.begin(appState.pcIP.c_str(),
                    appState.wsPort,
                    appState.wsPath.c_str());

    wsBeginCalled = true;
    wsConnecting = true;
    wsConnectStartTime = millis();

    appState.isDataLoading = true;
    updateConnectionStatus();
}
