#include <lvgl.h>
#include <LovyanGFX.hpp>
#include "ui.h"

static const uint16_t screenWidth = 240;
static const uint16_t screenHeight = 240;

static lv_disp_draw_buf_t draw_buf;
static lv_color_t *buf1; // ← Динамическая аллокация
static lv_color_t *buf2;

class LGFX : public lgfx::LGFX_Device
{
public:
    lgfx::Panel_ST7789 _panel_instance;
    lgfx::Bus_SPI _bus_instance;

    LGFX(void)
    {
        {
            auto cfg = _bus_instance.config();
            cfg.spi_host = SPI2_HOST;
            cfg.spi_mode = 0;
            cfg.freq_write = 40000000;
            cfg.freq_read = 16000000;
            cfg.spi_3wire = true;
            cfg.use_lock = true;
            cfg.dma_channel = SPI_DMA_CH_AUTO;
            cfg.pin_sclk = 12;
            cfg.pin_mosi = 11;
            cfg.pin_miso = -1;
            cfg.pin_dc = 6;
            _bus_instance.config(cfg);
            _panel_instance.setBus(&_bus_instance);
        }
        {
            auto cfg = _panel_instance.config();
            cfg.pin_cs = 10;
            cfg.pin_rst = 7;
            cfg.panel_width = 240;
            cfg.panel_height = 240;
            cfg.invert = true;
            cfg.rgb_order = false;
            _panel_instance.config(cfg);
        }
        setPanel(&_panel_instance);
    }
};

LGFX tft;

void my_disp_flush(lv_disp_drv_t *disp, const lv_area_t *area, lv_color_t *color_p)
{
    uint32_t w = (area->x2 - area->x1 + 1);
    uint32_t h = (area->y2 - area->y1 + 1);

    tft.startWrite();
    tft.setAddrWindow(area->x1, area->y1, w, h);
    tft.writePixels((lgfx::rgb565_t *)&color_p->full, w * h);
    tft.endWrite();

    lv_disp_flush_ready(disp);
}

void setup()
{
    Serial.begin(115200);
    delay(3000); // Увеличил задержку
    Serial.println("\n\n=== Starting ===");

    // 1. Дисплей первым
    Serial.println("Init display...");
    tft.init();
    tft.setRotation(0);
    tft.setBrightness(255);
    tft.fillScreen(0xF800); // Красный для теста
    delay(500);
    tft.fillScreen(0x0000); // Чёрный
    Serial.println("Display OK");

    // 2. LVGL
    Serial.println("Init LVGL...");
    lv_init();
    Serial.println("LVGL OK");

    // 3. Выделяем память для буферов
    Serial.println("Allocating buffers...");
    buf1 = (lv_color_t *)heap_caps_malloc(screenWidth * 10 * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    buf2 = (lv_color_t *)heap_caps_malloc(screenWidth * 10 * sizeof(lv_color_t), MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);

    if (!buf1 || !buf2)
    {
        Serial.println("ERROR: Buffer allocation failed!");
        while (1)
            delay(1000);
    }
    Serial.printf("Buffer1: %p, Buffer2: %p\n", buf1, buf2);

    lv_disp_draw_buf_init(&draw_buf, buf1, buf2, screenWidth * 10);
    Serial.println("Buffers OK");

    // 4. Регистрация дисплея
    Serial.println("Register display driver...");
    static lv_disp_drv_t disp_drv;
    lv_disp_drv_init(&disp_drv);
    disp_drv.hor_res = screenWidth;
    disp_drv.ver_res = screenHeight;
    disp_drv.flush_cb = my_disp_flush;
    disp_drv.draw_buf = &draw_buf;
    lv_disp_drv_register(&disp_drv);
    Serial.println("Display driver OK");

    // 5. UI инициализация
    Serial.println("Calling ui_init...");
    Serial.printf("Free heap before UI: %d bytes\n", ESP.getFreeHeap());

    ui_init();

    Serial.printf("Free heap after UI: %d bytes\n", ESP.getFreeHeap());
    Serial.println("UI initialized!");

    Serial.println("=== Setup Done ===");
}

void loop()
{
    lv_timer_handler();
    delay(5);
}