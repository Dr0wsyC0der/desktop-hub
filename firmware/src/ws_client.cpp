#include "ws_client.h"
#include "app_state.h"
#include "ws_protocol.h"
#include <WebSocketsClient.h>
#include <WiFiUDP.h>
#include <LittleFS.h>
#include <FS.h>
#include <ArduinoJson.h>
#include <Preferences.h>
#include "ui_logic.h"
#include "device_control.h"

WebSocketsClient webSocket;
WiFiUDP discoveryUdp;

static const uint16_t WS_DISCOVERY_PORT = 45678;
static const unsigned long WS_CONNECT_TIMEOUT = 10000;
static const unsigned long WS_RETRY_COOLDOWN = 3000;

static bool wsConnecting = false;
static unsigned long wsConnectStartTime = 0;
static bool wsBeginCalled = false;
static bool udpListening = false;
static unsigned long wsCooldownUntil = 0;

static void saveDiscoveredPcIp(const String &ip)
{
    if (ip.length() == 0 || appState.pcIP == ip)
    {
        return;
    }

    appState.pcIP = ip;

    Preferences prefs;
    prefs.begin("deskhub", false);
    prefs.putString("pcIP", ip);
    prefs.end();
}

static void setDiscoveryListening(bool enable)
{
    if (enable)
    {
        if (udpListening || !appState.wifiConnected)
        {
            return;
        }

        if (discoveryUdp.begin(WS_DISCOVERY_PORT))
        {
            udpListening = true;
            Serial.printf("[UDP] Listening on %u\n", WS_DISCOVERY_PORT);
        }
        else
        {
            Serial.println("[UDP] Failed to start listener");
        }
        return;
    }

    if (!udpListening)
    {
        return;
    }

    discoveryUdp.stop();
    udpListening = false;
    Serial.println("[UDP] Discovery stopped");
}

static void beginWebSocketConnect(const String &ip)
{
    if (!appState.wifiConnected || ip.length() == 0 || appState.pcConnected)
    {
        return;
    }

    if (millis() < wsCooldownUntil)
    {
        return;
    }

    Serial.printf("[WS] Connecting to ws://%s:%d%s\n",
                  ip.c_str(),
                  appState.wsPort,
                  appState.wsPath.c_str());

    if (wsBeginCalled)
    {
        webSocket.disconnect();
    }

    webSocket.begin(ip.c_str(), appState.wsPort, appState.wsPath.c_str());
    wsBeginCalled = true;
    wsConnecting = true;
    wsConnectStartTime = millis();
    appState.isDataLoading = true;
    updateConnectionStatus();
    setDiscoveryListening(false);
}

static void handleDiscoveryPacket()
{
    if (!udpListening || wsConnecting || appState.pcConnected)
    {
        return;
    }

    int packetSize = discoveryUdp.parsePacket();
    if (packetSize <= 0)
    {
        return;
    }

    char payload[384];
    int read = discoveryUdp.read(payload, sizeof(payload) - 1);
    if (read <= 0)
    {
        return;
    }
    payload[read] = '\0';

    DynamicJsonDocument doc(256);
    DeserializationError err = deserializeJson(doc, payload);
    if (err)
    {
        Serial.printf("[UDP] JSON parse error: %s\n", err.c_str());
        return;
    }

    String type = doc["type"] | "";
    if (!(type.equalsIgnoreCase("ws_discovery") || type.equalsIgnoreCase("ws_discowery")))
    {
        return;
    }

    String ip = doc["ip"] | "";
    IPAddress ipAddr;
    if (!ipAddr.fromString(ip))
    {
        Serial.printf("[UDP] Invalid discovery IP: %s\n", ip.c_str());
        return;
    }

    String discoveredIp = ipAddr.toString();
    saveDiscoveredPcIp(discoveredIp);
    beginWebSocketConnect(discoveredIp);
}

void onWebSocketEvent(WStype_t type, uint8_t *payload, size_t length)
{
    switch (type)
    {
    case WStype_DISCONNECTED:
        wsConnecting = false;
        appState.pcConnected = false;
        appState.isDataLoading = false;
        wsCooldownUntil = millis() + WS_RETRY_COOLDOWN;
        updateConnectionStatus();
        if (payload != nullptr && length > 0)
        {
            String reason;
            reason.reserve(length + 1);
            for (size_t i = 0; i < length; i++)
            {
                reason += static_cast<char>(payload[i]);
            }
            Serial.printf("[WS] Disconnected: %s\n", reason.c_str());
        }
        else
        {
            Serial.println("[WS] Disconnected");
        }
        setDiscoveryListening(appState.wifiConnected);
        break;

    case WStype_CONNECTED:
        wsConnecting = false;
        appState.pcConnected = true;
        appState.isDataLoading = false;
        wsCooldownUntil = 0;
        updateConnectionStatus();
        Serial.println("[WS] Connected");
        setDiscoveryListening(false);
        break;

    case WStype_TEXT:
    {
        String message;
        message.reserve(length + 1);
        for (size_t i = 0; i < length; i++)
        {
            message += static_cast<char>(payload[i]);
        }
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

                if (appState.animReceivedBytes % 14600 == 0 || appState.animReceivedBytes >= appState.animTotalSize)
                {
                    const size_t total = appState.animTotalSize == 0 ? 1 : appState.animTotalSize;
                    Serial.printf("[Anim] Downloading: %u / %u bytes (%u%%)\n",
                                  appState.animReceivedBytes,
                                  appState.animTotalSize,
                                  (appState.animReceivedBytes * 100) / total);
                }

                yield();
            }

            if (appState.animReceivedBytes >= appState.animTotalSize)
            {
                animFile.close();
                appState.animReceiving = false;
                appState.isDataLoading = false;
                updateConnectionStatus();
                Serial.println("[Anim] Transfer complete! Finalizing...");

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

    case WStype_ERROR:
        if (payload != nullptr && length > 0)
        {
            String err;
            err.reserve(length + 1);
            for (size_t i = 0; i < length; i++)
            {
                err += static_cast<char>(payload[i]);
            }
            Serial.printf("[WS] Error: %s\n", err.c_str());
        }
        else
        {
            Serial.println("[WS] Error");
        }
        break;

    default:
        break;
    }
}

void initWebSocketClient()
{
    webSocket.onEvent(onWebSocketEvent);
    webSocket.setReconnectInterval(0);
    webSocket.enableHeartbeat(30000, 10000, 2);
    setDiscoveryListening(appState.wifiConnected);
}

void updateWebSocketClient()
{
    if (!appState.wifiConnected)
    {
        if (udpListening)
        {
            setDiscoveryListening(false);
        }
        return;
    }

    if (appState.pcConnected || wsConnecting)
    {
        webSocket.loop();
    }

    if (wsConnecting && millis() - wsConnectStartTime > WS_CONNECT_TIMEOUT)
    {
        Serial.println("[WS] Connect timeout");
        webSocket.disconnect();
        wsConnecting = false;
        appState.isDataLoading = false;
        wsCooldownUntil = millis() + WS_RETRY_COOLDOWN;
        updateConnectionStatus();
        setDiscoveryListening(true);
    }

    if (!appState.pcConnected && !wsConnecting)
    {
        setDiscoveryListening(true);
        handleDiscoveryPacket();
    }
}

void reconnectWebSocket()
{
    if (!appState.wifiConnected || appState.pcConnected)
    {
        return;
    }

    String ip = appState.pcIP;
    if (ip.length() == 0)
    {
        setDiscoveryListening(true);
        return;
    }

    beginWebSocketConnect(ip);
}

void sendWebSocketMessage(const String &message)
{
    if (appState.pcConnected)
    {
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
    if (!appState.wifiConnected)
    {
        return;
    }

    Serial.println("[WS] Force reconnect");

    if (wsBeginCalled)
    {
        webSocket.disconnect();
    }

    wsConnecting = false;
    appState.pcConnected = false;
    appState.isDataLoading = false;
    wsCooldownUntil = 0;
    updateConnectionStatus();

    if (appState.pcIP.length() > 0)
    {
        beginWebSocketConnect(appState.pcIP);
    }
    else
    {
        setDiscoveryListening(true);
    }
}

void onWiFiConnectionChanged(bool connected)
{
    if (connected)
    {
        wsConnecting = false;
        appState.pcConnected = false;
        appState.isDataLoading = false;
        wsCooldownUntil = 0;
        setDiscoveryListening(true);
        updateConnectionStatus();
        return;
    }

    if (wsBeginCalled)
    {
        webSocket.disconnect();
    }

    wsConnecting = false;
    appState.pcConnected = false;
    appState.isDataLoading = false;
    wsCooldownUntil = 0;
    setDiscoveryListening(false);
    updateConnectionStatus();
}
