#include "ota_manager.h"
#include "app_state.h"
#include <HTTPClient.h>
#include <Update.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>

namespace
{
    enum class OtaState : uint8_t
    {
        IDLE,
        START_HTTP,
        STREAMING,
        FINALIZE,
        RETRY_WAIT,
        RESTART_WAIT
    };

    static const unsigned long OTA_CONNECT_TIMEOUT_MS = 8000;
    static const unsigned long OTA_STREAM_TIMEOUT_MS = 10000;
    static const unsigned long OTA_RESTART_DELAY_MS = 800;
    static const unsigned long OTA_BACKOFF_BASE_MS = 2000;
    static const unsigned long OTA_BACKOFF_MAX_MS = 60000;
    static const uint8_t OTA_MAX_RETRIES = 5;
    static const size_t OTA_CHUNK_SIZE = 1024;

    static OtaState otaState = OtaState::IDLE;
    static HTTPClient http;
    static WiFiClient httpClient;
    static WiFiClientSecure httpsClient;
    static String otaUrl;
    static String otaMd5;
    static size_t expectedLength = 0;
    static size_t writtenLength = 0;
    static uint8_t retryCount = 0;
    static unsigned long nextActionAt = 0;
    static unsigned long lastDataAt = 0;
    static int lastProgress = -1;
    static bool httpStarted = false;
    static OtaEventCallback eventCallback = nullptr;
    static uint8_t chunkBuffer[OTA_CHUNK_SIZE];

    void emitEvent(int progress, const char *stage, const String &message)
    {
        Serial.printf("[OTA] %s: %s (%d%%)\n", stage, message.c_str(), progress);
        if (eventCallback)
        {
            eventCallback(progress, stage, message.c_str());
        }
    }

    void stopHttp()
    {
        if (httpStarted)
        {
            http.end();
            httpStarted = false;
        }
    }

    void abortUpdateIfRunning()
    {
        if (Update.isRunning())
        {
            Update.abort();
        }
    }

    void resetInternalState()
    {
        stopHttp();
        abortUpdateIfRunning();
        expectedLength = 0;
        writtenLength = 0;
        lastProgress = -1;
    }

    void scheduleRetry(const String &reason)
    {
        resetInternalState();

        if (retryCount >= OTA_MAX_RETRIES)
        {
            emitEvent(lastProgress < 0 ? 0 : lastProgress, "error", "max retries reached: " + reason);
            otaState = OtaState::IDLE;
            return;
        }

        unsigned long backoff = OTA_BACKOFF_BASE_MS << retryCount;
        if (backoff > OTA_BACKOFF_MAX_MS)
        {
            backoff = OTA_BACKOFF_MAX_MS;
        }

        retryCount++;
        nextActionAt = millis() + backoff;
        otaState = OtaState::RETRY_WAIT;
        emitEvent(lastProgress < 0 ? 0 : lastProgress, "retry", "retry in " + String(backoff) + " ms: " + reason);
    }
}

void initOtaManager()
{
    otaState = OtaState::IDLE;
    eventCallback = nullptr;
}

void setOtaEventCallback(OtaEventCallback callback)
{
    eventCallback = callback;
}

bool requestOtaUpdate(const String &url, const String &md5)
{
    if (!(url.startsWith("http://") || url.startsWith("https://")))
    {
        emitEvent(0, "error", "invalid URL scheme");
        return false;
    }

    if (otaState != OtaState::IDLE)
    {
        emitEvent(lastProgress < 0 ? 0 : lastProgress, "error", "OTA already in progress");
        return false;
    }

    otaUrl = url;
    otaMd5 = md5;
    retryCount = 0;
    expectedLength = 0;
    writtenLength = 0;
    lastProgress = -1;
    nextActionAt = millis();
    otaState = OtaState::START_HTTP;

    emitEvent(0, "start", "OTA scheduled");
    return true;
}

bool isOtaInProgress()
{
    return otaState != OtaState::IDLE;
}

void updateOtaManager()
{
    switch (otaState)
    {
    case OtaState::IDLE:
        return;

    case OtaState::RETRY_WAIT:
        if (millis() >= nextActionAt)
        {
            otaState = OtaState::START_HTTP;
        }
        return;

    case OtaState::START_HTTP:
    {
        if (!appState.wifiConnected)
        {
            scheduleRetry("wifi disconnected");
            return;
        }

        stopHttp();

        http.setReuse(false);
        http.setConnectTimeout(OTA_CONNECT_TIMEOUT_MS);
        http.setTimeout(OTA_CONNECT_TIMEOUT_MS);

        bool beginOk = false;
        if (otaUrl.startsWith("https://"))
        {
            httpsClient.setInsecure();
            beginOk = http.begin(httpsClient, otaUrl);
        }
        else
        {
            beginOk = http.begin(httpClient, otaUrl);
        }

        if (!beginOk)
        {
            scheduleRetry("http.begin failed");
            return;
        }
        httpStarted = true;

        int httpCode = http.GET();
        if (httpCode != HTTP_CODE_OK)
        {
            scheduleRetry("HTTP status " + String(httpCode));
            return;
        }

        int contentLength = http.getSize();
        if (contentLength <= 0)
        {
            scheduleRetry("invalid Content-Length");
            return;
        }

        expectedLength = static_cast<size_t>(contentLength);
        writtenLength = 0;

        if (!Update.begin(expectedLength, U_FLASH))
        {
            String err = Update.errorString();
            resetInternalState();
            otaState = OtaState::IDLE;
            emitEvent(0, "error", "Update.begin failed: " + err);
            return;
        }

        if (otaMd5.length() > 0 && !Update.setMD5(otaMd5.c_str()))
        {
            resetInternalState();
            otaState = OtaState::IDLE;
            emitEvent(0, "error", "invalid md5 format");
            return;
        }

        lastDataAt = millis();
        lastProgress = 0;
        emitEvent(0, "downloading", "download started");
        otaState = OtaState::STREAMING;
        return;
    }

    case OtaState::STREAMING:
    {
        if (!appState.wifiConnected)
        {
            scheduleRetry("wifi lost during OTA");
            return;
        }

        WiFiClient *stream = http.getStreamPtr();
        if (!stream)
        {
            scheduleRetry("invalid stream");
            return;
        }

        int availableBytes = stream->available();
        if (availableBytes > 0)
        {
            size_t toRead = static_cast<size_t>(availableBytes);
            if (toRead > OTA_CHUNK_SIZE)
            {
                toRead = OTA_CHUNK_SIZE;
            }

            int bytesRead = stream->readBytes(reinterpret_cast<char *>(chunkBuffer), toRead);
            if (bytesRead > 0)
            {
                size_t bytesWritten = Update.write(chunkBuffer, static_cast<size_t>(bytesRead));
                if (bytesWritten != static_cast<size_t>(bytesRead))
                {
                    scheduleRetry("Update.write failed: " + String(Update.errorString()));
                    return;
                }

                writtenLength += bytesWritten;
                lastDataAt = millis();

                int progress = static_cast<int>((writtenLength * 100UL) / expectedLength);
                if (progress != lastProgress)
                {
                    lastProgress = progress;
                    emitEvent(progress, "downloading", "progress");
                }
            }
        }
        else
        {
            if (writtenLength >= expectedLength)
            {
                otaState = OtaState::FINALIZE;
                return;
            }

            if (!stream->connected())
            {
                scheduleRetry("connection closed before completion");
                return;
            }

            if (millis() - lastDataAt > OTA_STREAM_TIMEOUT_MS)
            {
                scheduleRetry("stream timeout");
                return;
            }
        }

        return;
    }

    case OtaState::FINALIZE:
    {
        if (writtenLength != expectedLength)
        {
            scheduleRetry("size mismatch");
            return;
        }

        if (!Update.end(true))
        {
            scheduleRetry("Update.end failed: " + String(Update.errorString()));
            return;
        }

        stopHttp();
        emitEvent(100, "success", "update applied, restarting");
        nextActionAt = millis() + OTA_RESTART_DELAY_MS;
        otaState = OtaState::RESTART_WAIT;
        return;
    }

    case OtaState::RESTART_WAIT:
        if (millis() >= nextActionAt)
        {
            ESP.restart();
        }
        return;
    }
}
