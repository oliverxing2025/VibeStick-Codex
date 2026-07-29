#include <stdbool.h>
#include <ctype.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "vibe_audio.h"
#include "vibe_board.h"
#include "vibe_stick_config.h"
#include "button_gpio.h"
#include "cJSON.h"
#include "driver/gpio.h"
#include "driver/ledc.h"
#include "driver/spi_master.h"
#include "esp_check.h"
#include "esp_event.h"
#include "esp_heap_caps.h"
#include "esp_http_client.h"
#include "esp_lcd_panel_io.h"
#include "esp_lcd_panel_ops.h"
#include "esp_lcd_panel_st7789.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_ota_ops.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "vibe_stick_ui_assets.h"
#include "iot_button.h"
#include "lvgl.h"
#include "nvs_flash.h"

#define LCD_HOST SPI2_HOST
#define LCD_H_RES 135
#define LCD_V_RES 240
#define LCD_X_GAP 52
#define LCD_Y_GAP 40
#define LCD_PIXEL_CLOCK_HZ (20 * 1000 * 1000)
#define LCD_BACKLIGHT_PWM_HZ 5000
#define LCD_BACKLIGHT_PWM_MAX 255
#define LCD_BACKLIGHT_DEFAULT 150
#define LVGL_DRAW_BUF_LINES 24
#define LVGL_TICK_PERIOD_MS 10
#define BATTERY_FILL_MAX_WIDTH 20
#define ACTIVITY_COLUMNS 57
#define ACTIVITY_ROWS 3
#define ACTIVITY_SEGMENT_COLUMNS 28
#define ACTIVITY_WEEK_START_COLUMN 29
#define ACTIVITY_FRAME_MS 36
#define ORIENTATION_SAMPLE_MS 230
#define ORIENTATION_STABLE_SAMPLES 3

#define PIN_BUTTON_FRONT 11
#define PIN_BUTTON_SIDE 12
#define PIN_LCD_MOSI 39
#define PIN_LCD_SCK 40
#define PIN_LCD_DC 45
#define PIN_LCD_CS 41
#define PIN_LCD_RST 21
#define PIN_LCD_BL 38

static const char *TAG = "vibe_stick";

typedef enum {
    VIBE_STICK_EVENT_POLL_STATE,
    VIBE_STICK_EVENT_SHORT_PRESS,
    VIBE_STICK_EVENT_DOUBLE_CLICK,
    VIBE_STICK_EVENT_SIDE_SHORT,
    VIBE_STICK_EVENT_SIDE_DOUBLE,
    VIBE_STICK_EVENT_SIDE_LONG,
    VIBE_STICK_EVENT_SIDE_TRIPLE,
    VIBE_STICK_EVENT_LONG_START,
    VIBE_STICK_EVENT_LONG_STOP,
} agent_event_type_t;

typedef struct {
    agent_event_type_t type;
} agent_event_t;

typedef enum {
    PROVIDER_CODEX = 0,
    PROVIDER_COUNT,
} agent_provider_t;

typedef struct {
    agent_provider_t id;
    const char *key;
    const char *display_name;
    const lv_image_dsc_t *icon;
    lv_color_t accent_color;
} agent_provider_config_t;

typedef struct {
    char time[9];
    char date[8];
    char weekday[12];
    bool wifi;
    bool ble;
    int battery;
    bool battery_charging;
    bool usb_powered;
    char codex_status[24];
    char project[40];
    int quota_5h;
    int quota_7d;
    int quota_7d_reset_days;
    bool quota_5h_valid;
    bool quota_7d_valid;
    bool quota_7d_reset_days_valid;
    char quota_updated_at[8];
    bool quota_stale;
    char funds_balance[20];
    char today_spend[20];
    int today_tokens;
    bool today_tokens_valid;
    int today_used_percent;
    bool today_used_percent_valid;
    int running_tasks;
    int waiting_tasks;
    int finished_tasks;
    char alert_event_id[56];
    char alert_type[24];
    char alert_message[80];
} agent_state_t;

typedef struct {
    char status[24];
    char project[40];
    int quota_5h;
    int quota_7d;
    int quota_7d_reset_days;
    bool quota_5h_valid;
    bool quota_7d_valid;
    bool quota_7d_reset_days_valid;
    char quota_updated_at[8];
    bool quota_stale;
    char funds_balance[20];
    char today_spend[20];
    int today_tokens;
    bool today_tokens_valid;
    int today_used_percent;
    bool today_used_percent_valid;
    int running_tasks;
    int waiting_tasks;
    int finished_tasks;
} provider_display_state_t;

typedef struct {
    char *data;
    int capacity;
    int used;
} http_response_capture_t;

static QueueHandle_t s_event_queue;
static SemaphoreHandle_t s_lvgl_lock;
static bool s_wifi_connected;
static bool s_recording_overlay_visible;
static bool s_long_press_active;
static bool s_side_long_press_active;
static bool s_landscape_active;
static bool s_landscape_reverse;
static bool s_orientation_enabled = true;
static char s_last_alert_event_id[56];
static char s_last_alert_type[24];
static bool s_alert_sound_baseline_ready;
static bool s_wait_sound_baseline_ready;
static int s_last_waiting_tasks;
static char s_recording_session_id[40];

static lv_display_t *s_display;
static esp_lcd_panel_handle_t s_panel;
static lv_obj_t *s_wifi_label;
static lv_obj_t *s_time_label;
static lv_obj_t *s_battery_label;
static lv_obj_t *s_battery_icon;
static lv_obj_t *s_battery_fill;
static lv_obj_t *s_battery_cap;
static lv_obj_t *s_battery_bolt;
static lv_obj_t *s_provider_icon;
static lv_obj_t *s_provider_label;
static lv_obj_t *s_status_dot;
static lv_obj_t *s_status_label;
static lv_obj_t *s_funds_value_label;
static lv_obj_t *s_today_value_label;
static lv_obj_t *s_token_value_label;
static lv_obj_t *s_recording_overlay;
static lv_obj_t *s_recording_wave_group;
static lv_obj_t *s_recording_wave_bars[5];
static lv_obj_t *s_recording_title;
static lv_obj_t *s_recording_hint;
static lv_obj_t *s_seconds_label;
static lv_obj_t *s_days_left_label;
static lv_obj_t *s_percent_left_label;
static lv_obj_t *s_date_group;
static lv_obj_t *s_date_label;
static lv_obj_t *s_date_separator;
static lv_obj_t *s_weekday_label;
static lv_obj_t *s_activity_divider;
static lv_obj_t *s_activity_5h_percent_label;
static lv_obj_t *s_activity_7d_percent_label;
static lv_obj_t *s_run_count_label;
static lv_obj_t *s_ask_count_label;
static lv_obj_t *s_new_count_label;
static lv_obj_t *s_activity_cells[ACTIVITY_ROWS][ACTIVITY_COLUMNS];
static lv_timer_t *s_activity_timer;
static int s_activity_5h_active_columns = -1;
static int s_activity_7d_active_columns = -1;

static agent_state_t s_state = {
    .time = "--:--",
    .date = "--- --",
    .weekday = "-------",
    .wifi = false,
    .ble = false,
    .battery = 0,
    .battery_charging = false,
    .usb_powered = false,
    .codex_status = "OFFLINE",
    .project = "vibestick",
    .quota_5h = 0,
    .quota_7d = 0,
    .quota_7d_reset_days = 0,
    .quota_5h_valid = false,
    .quota_7d_valid = false,
    .quota_7d_reset_days_valid = false,
    .quota_updated_at = "",
    .quota_stale = false,
    .funds_balance = "",
    .today_spend = "",
    .today_tokens = 0,
    .today_tokens_valid = false,
    .today_used_percent = 0,
    .today_used_percent_valid = false,
    .running_tasks = 0,
    .waiting_tasks = 0,
    .finished_tasks = 0,
    .alert_event_id = "",
    .alert_type = "NONE",
    .alert_message = "",
};

static provider_display_state_t s_provider_states[PROVIDER_COUNT] = {
    [PROVIDER_CODEX] = {
        .status = "OFFLINE",
        .project = "vibestick",
        .quota_5h = 0,
        .quota_7d = 0,
        .quota_7d_reset_days = 0,
        .quota_5h_valid = false,
        .quota_7d_valid = false,
        .quota_7d_reset_days_valid = false,
        .quota_updated_at = "",
        .quota_stale = false,
        .funds_balance = "",
        .today_spend = "",
        .today_tokens = 0,
        .today_tokens_valid = false,
        .today_used_percent = 0,
        .today_used_percent_valid = false,
        .running_tasks = 0,
        .waiting_tasks = 0,
        .finished_tasks = 0,
    },
};

extern const lv_font_t vibe_stick_cn_16;
#define FONT_CN (&vibe_stick_cn_16)

static const agent_provider_config_t s_provider_configs[] = {
    {
        .id = PROVIDER_CODEX,
        .key = "codex",
        .display_name = "Codex",
        .icon = &vibe_stick_provider_codex_icon_40,
        .accent_color = LV_COLOR_MAKE(0x4d, 0x82, 0xff),
    },
};

static agent_provider_t s_current_provider = PROVIDER_CODEX;

static const lv_point_precise_t s_battery_bolt_points[] = {
    {3, 0},
    {1, 3},
    {3, 3},
    {2, 7},
    {6, 2},
    {4, 2},
};

static void render_state(void);
static void create_portrait_ui(lv_obj_t *screen);

static void queue_event(agent_event_type_t type)
{
    if (!s_event_queue) {
        return;
    }
    agent_event_t event = {.type = type};
    (void)xQueueSend(s_event_queue, &event, 0);
}

static const agent_provider_config_t *provider_config(agent_provider_t provider)
{
    for (size_t i = 0; i < sizeof(s_provider_configs) / sizeof(s_provider_configs[0]); ++i) {
        if (s_provider_configs[i].id == provider) {
            return &s_provider_configs[i];
        }
    }
    return &s_provider_configs[0];
}

static const agent_provider_config_t *current_provider_config(void)
{
    return provider_config(s_current_provider);
}

static provider_display_state_t *provider_display_state(agent_provider_t provider)
{
    if ((int)provider >= 0 && provider < PROVIDER_COUNT) {
        return &s_provider_states[provider];
    }
    return &s_provider_states[PROVIDER_CODEX];
}

static provider_display_state_t *current_provider_display_state(void)
{
    return provider_display_state(s_current_provider);
}

static bool provider_from_key(const char *key, agent_provider_t *provider)
{
    if (!key || key[0] == '\0') {
        return false;
    }
    for (size_t i = 0; i < sizeof(s_provider_configs) / sizeof(s_provider_configs[0]); ++i) {
        if (strcmp(s_provider_configs[i].key, key) == 0) {
            if (provider) {
                *provider = s_provider_configs[i].id;
            }
            return true;
        }
    }
    return false;
}

static bool set_current_provider_from_key(const char *key)
{
    agent_provider_t provider = PROVIDER_CODEX;
    if (provider_from_key(key, &provider)) {
        s_current_provider = provider;
        return true;
    }
    return false;
}

static void lvgl_lock(void)
{
    if (s_lvgl_lock) {
        xSemaphoreTake(s_lvgl_lock, portMAX_DELAY);
    }
}

static void lvgl_unlock(void)
{
    if (s_lvgl_lock) {
        xSemaphoreGive(s_lvgl_lock);
    }
}

static void lvgl_tick_cb(void *arg)
{
    (void)arg;
    lv_tick_inc(LVGL_TICK_PERIOD_MS);
}

static void lvgl_task(void *arg)
{
    (void)arg;
    while (true) {
        lvgl_lock();
        uint32_t wait_ms = lv_timer_handler();
        lvgl_unlock();
        if (wait_ms < 5) {
            wait_ms = 5;
        }
        if (wait_ms > 250) {
            wait_ms = 250;
        }
        vTaskDelay(pdMS_TO_TICKS(wait_ms));
    }
}

static bool notify_lvgl_flush_ready(esp_lcd_panel_io_handle_t panel_io,
                                    esp_lcd_panel_io_event_data_t *edata,
                                    void *user_ctx)
{
    (void)panel_io;
    (void)edata;
    lv_display_flush_ready((lv_display_t *)user_ctx);
    return false;
}

static void lvgl_flush_cb(lv_display_t *display, const lv_area_t *area, uint8_t *px_map)
{
    esp_lcd_panel_handle_t panel = lv_display_get_user_data(display);
    int32_t width = area->x2 - area->x1 + 1;
    int32_t height = area->y2 - area->y1 + 1;
    lv_draw_sw_rgb565_swap(px_map, width * height);
    esp_lcd_panel_draw_bitmap(panel, area->x1, area->y1, area->x2 + 1, area->y2 + 1, px_map);
}

static void set_backlight(uint8_t brightness)
{
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, brightness);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
}

static void init_backlight(void)
{
    ledc_timer_config_t timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .timer_num = LEDC_TIMER_0,
        .duty_resolution = LEDC_TIMER_8_BIT,
        .freq_hz = LCD_BACKLIGHT_PWM_HZ,
        .clk_cfg = LEDC_AUTO_CLK,
    };
    ESP_ERROR_CHECK(ledc_timer_config(&timer));
    ledc_channel_config_t channel = {
        .gpio_num = PIN_LCD_BL,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
    };
    ESP_ERROR_CHECK(ledc_channel_config(&channel));
    set_backlight(LCD_BACKLIGHT_DEFAULT);
}

static esp_err_t init_display(void)
{
    init_backlight();

    spi_bus_config_t buscfg = {
        .sclk_io_num = PIN_LCD_SCK,
        .mosi_io_num = PIN_LCD_MOSI,
        .miso_io_num = -1,
        .quadwp_io_num = -1,
        .quadhd_io_num = -1,
        .max_transfer_sz = LCD_H_RES * LVGL_DRAW_BUF_LINES * sizeof(lv_color_t),
    };
    ESP_RETURN_ON_ERROR(spi_bus_initialize(LCD_HOST, &buscfg, SPI_DMA_CH_AUTO), TAG, "spi bus");

    esp_lcd_panel_io_handle_t io_handle = NULL;
    esp_lcd_panel_io_spi_config_t io_config = {
        .dc_gpio_num = PIN_LCD_DC,
        .cs_gpio_num = PIN_LCD_CS,
        .pclk_hz = LCD_PIXEL_CLOCK_HZ,
        .lcd_cmd_bits = 8,
        .lcd_param_bits = 8,
        .spi_mode = 0,
        .trans_queue_depth = 10,
        .on_color_trans_done = notify_lvgl_flush_ready,
        .user_ctx = NULL,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_io_spi((esp_lcd_spi_bus_handle_t)LCD_HOST, &io_config, &io_handle),
                        TAG, "panel io");

    esp_lcd_panel_dev_config_t panel_config = {
        .reset_gpio_num = PIN_LCD_RST,
        .rgb_ele_order = LCD_RGB_ELEMENT_ORDER_RGB,
        .bits_per_pixel = 16,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_new_panel_st7789(io_handle, &panel_config, &s_panel), TAG, "panel");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_reset(s_panel), TAG, "panel reset");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_init(s_panel), TAG, "panel init");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_invert_color(s_panel, true), TAG, "panel invert");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_set_gap(s_panel, LCD_X_GAP, LCD_Y_GAP), TAG, "panel gap");
    ESP_RETURN_ON_ERROR(esp_lcd_panel_disp_on_off(s_panel, true), TAG, "panel on");

    lv_init();
    s_display = lv_display_create(LCD_H_RES, LCD_V_RES);
    lv_display_set_user_data(s_display, s_panel);
    lv_display_set_flush_cb(s_display, lvgl_flush_cb);

    size_t buffer_size = LCD_H_RES * LVGL_DRAW_BUF_LINES * sizeof(lv_color_t);
    void *buf = heap_caps_malloc(buffer_size, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
    ESP_RETURN_ON_FALSE(buf != NULL, ESP_ERR_NO_MEM, TAG, "lvgl buffer");
    lv_display_set_buffers(s_display, buf, NULL, buffer_size, LV_DISPLAY_RENDER_MODE_PARTIAL);
    esp_lcd_panel_io_callbacks_t callbacks = {
        .on_color_trans_done = notify_lvgl_flush_ready,
    };
    ESP_RETURN_ON_ERROR(esp_lcd_panel_io_register_event_callbacks(io_handle, &callbacks, s_display),
                        TAG, "panel cb");

    const esp_timer_create_args_t tick_args = {
        .callback = lvgl_tick_cb,
        .name = "lvgl_tick",
    };
    esp_timer_handle_t tick_timer = NULL;
    ESP_RETURN_ON_ERROR(esp_timer_create(&tick_args, &tick_timer), TAG, "tick timer");
    ESP_RETURN_ON_ERROR(esp_timer_start_periodic(tick_timer, LVGL_TICK_PERIOD_MS * 1000), TAG, "tick start");

    xTaskCreate(lvgl_task, "lvgl", 4096, NULL, 3, NULL);
    return ESP_OK;
}

static lv_obj_t *make_label(lv_obj_t *parent, const char *text, const lv_font_t *font,
                            lv_color_t color, int32_t width, lv_text_align_t align)
{
    lv_obj_t *label = lv_label_create(parent);
    lv_label_set_text(label, text);
    lv_obj_set_style_text_font(label, font, 0);
    lv_obj_set_style_text_color(label, color, 0);
    lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
    lv_obj_set_width(label, width);
    lv_obj_set_style_text_align(label, align, 0);
    return label;
}

static lv_obj_t *make_plain_obj(lv_obj_t *parent, int32_t w, int32_t h,
                                lv_color_t color, lv_opa_t opa, int32_t radius)
{
    lv_obj_t *obj = lv_obj_create(parent);
    lv_obj_remove_style_all(obj);
    lv_obj_set_size(obj, w, h);
    lv_obj_set_style_bg_color(obj, color, 0);
    lv_obj_set_style_bg_opa(obj, opa, 0);
    lv_obj_set_style_radius(obj, radius, 0);
    return obj;
}

static void create_provider_icon(lv_obj_t *parent)
{
    s_provider_icon = lv_image_create(parent);
    lv_image_set_src(s_provider_icon, current_provider_config()->icon);
    lv_obj_align(s_provider_icon, LV_ALIGN_TOP_LEFT, 10, 37);
}

static const char *status_text_for(const char *status)
{
    if (strcmp(status, "RUNNING") == 0) {
        return "RUNNING";
    }
    if (strcmp(status, "DONE") == 0) {
        return "DONE";
    }
    if (strcmp(status, "APPROVAL") == 0) {
        return "WAITING";
    }
    if (strcmp(status, "ERROR") == 0) {
        return "ERROR";
    }
    if (strcmp(status, "OFFLINE") == 0) {
        return "OFFLINE";
    }
    if (strcmp(status, "IDLE") == 0 || strcmp(status, "UNKNOWN") == 0) {
        return "IDLE";
    }
    return "IDLE";
}

static void set_battery_ui(int battery_value, bool charging, bool usb_powered)
{
    if (battery_value < 0) {
        battery_value = 0;
    } else if (battery_value > 100) {
        battery_value = 100;
    }

    char battery[8];
    if (battery_value > 0) {
        snprintf(battery, sizeof(battery), "%d%%", battery_value);
    } else {
        snprintf(battery, sizeof(battery), "--%%");
    }
    lv_label_set_text(s_battery_label, battery);

    int fill_width = battery_value > 0 ? (battery_value * 20) / 100 : 0;
    if (fill_width < 1 && battery_value > 0) {
        fill_width = 1;
    }

    const bool external_power = charging || usb_powered;
    const lv_color_t normal_color = lv_color_hex(0xf3f4f6);
    const lv_color_t charging_color = lv_color_hex(0x32d583);

    lv_obj_set_style_border_color(s_battery_icon, normal_color, 0);
    lv_obj_set_style_bg_color(s_battery_fill, external_power ? charging_color : normal_color, 0);
    lv_obj_set_style_bg_color(s_battery_cap, normal_color, 0);
    lv_obj_set_width(s_battery_fill, fill_width);

    if (s_battery_bolt) {
        if (external_power) {
            lv_obj_clear_flag(s_battery_bolt, LV_OBJ_FLAG_HIDDEN);
        } else {
            lv_obj_add_flag(s_battery_bolt, LV_OBJ_FLAG_HIDDEN);
        }
    }
}

static void wave_bar_height_cb(void *obj, int32_t height)
{
    lv_obj_set_height((lv_obj_t *)obj, height);
}

static void stop_recording_wave(void)
{
    static const int heights[5] = {14, 22, 32, 22, 14};
    for (int i = 0; i < 5; ++i) {
        if (s_recording_wave_bars[i]) {
            lv_anim_delete(s_recording_wave_bars[i], NULL);
            lv_obj_set_height(s_recording_wave_bars[i], heights[i]);
        }
    }
}

static void start_recording_wave(void)
{
    static const int min_heights[5] = {10, 14, 18, 14, 10};
    static const int max_heights[5] = {24, 34, 48, 34, 24};
    stop_recording_wave();
    for (int i = 0; i < 5; ++i) {
        if (!s_recording_wave_bars[i]) {
            continue;
        }
        lv_anim_t anim;
        lv_anim_init(&anim);
        lv_anim_set_var(&anim, s_recording_wave_bars[i]);
        lv_anim_set_values(&anim, min_heights[i], max_heights[i]);
        lv_anim_set_duration(&anim, 460);
        lv_anim_set_playback_duration(&anim, 460);
        lv_anim_set_delay(&anim, i * 70);
        lv_anim_set_repeat_count(&anim, LV_ANIM_REPEAT_INFINITE);
        lv_anim_set_exec_cb(&anim, wave_bar_height_cb);
        lv_anim_start(&anim);
    }
}

static lv_obj_t *make_fullscreen_overlay(lv_obj_t *parent)
{
    lv_obj_t *overlay = lv_obj_create(parent);
    lv_obj_set_size(overlay,
                    lv_display_get_horizontal_resolution(s_display),
                    lv_display_get_vertical_resolution(s_display));
    lv_obj_align(overlay, LV_ALIGN_CENTER, 0, 0);
    lv_obj_set_style_radius(overlay, 0, 0);
    lv_obj_set_style_bg_color(overlay, lv_color_hex(0x050608), 0);
    lv_obj_set_style_bg_opa(overlay, LV_OPA_COVER, 0);
    lv_obj_set_style_border_width(overlay, 0, 0);
    lv_obj_set_style_pad_all(overlay, 0, 0);
    return overlay;
}

static lv_obj_t *make_metric_card(lv_obj_t *screen, int32_t y, const char *title,
                                  lv_color_t value_color, lv_obj_t **value_label)
{
    lv_obj_t *card = make_plain_obj(screen, LCD_H_RES - 16, 40,
                                    lv_color_hex(0x101216), LV_OPA_COVER, 7);
    lv_obj_set_style_border_width(card, 1, 0);
    lv_obj_set_style_border_color(card, lv_color_hex(0x30343c), 0);
    lv_obj_align(card, LV_ALIGN_TOP_MID, 0, y);

    lv_obj_t *title_label = make_label(card, title, &lv_font_montserrat_12,
                                       lv_color_hex(0xa5aab3), 58, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(title_label, LV_ALIGN_LEFT_MID, 8, 0);
    *value_label = make_label(card, "--", &lv_font_montserrat_16,
                              value_color, 54, LV_TEXT_ALIGN_RIGHT);
    lv_obj_align(*value_label, LV_ALIGN_RIGHT_MID, -7, 0);
    return card;
}

static lv_color_t scale_activity_color(uint32_t color, float brightness)
{
    uint32_t red = (uint32_t)(((color >> 16) & 0xff) * brightness + 0.5f);
    uint32_t green = (uint32_t)(((color >> 8) & 0xff) * brightness + 0.5f);
    uint32_t blue = (uint32_t)((color & 0xff) * brightness + 0.5f);
    return lv_color_make((uint8_t)red, (uint8_t)green, (uint8_t)blue);
}

static int quota_segment_columns(int remaining, bool valid)
{
    if (!valid) {
        return 0;
    }
    if (remaining < 0) {
        remaining = 0;
    } else if (remaining > 100) {
        remaining = 100;
    }
    return (remaining * ACTIVITY_SEGMENT_COLUMNS + 99) / 100;
}

static float activity_particle_breath(int row, int col, int64_t elapsed_us)
{
    uint32_t seed =
        (uint32_t)(row + 1) * 0x9e3779b9u ^
        (uint32_t)(col + 1) * 0x85ebca6bu;
    seed ^= seed >> 16;
    seed *= 0x7feb352du;
    seed ^= seed >> 15;

    const uint32_t cycle_step =
        (uint32_t)(elapsed_us / 3125LL) & 0x3ffu;
    const uint32_t phase = (cycle_step + (seed & 0x3ffu)) & 0x3ffu;
    const float triangle =
        phase < 512u ? (float)phase / 511.0f
                     : (float)(1023u - phase) / 511.0f;
    return triangle * triangle * (3.0f - 2.0f * triangle);
}

static void activity_timer_cb(lv_timer_t *timer)
{
    (void)timer;
    if (!s_landscape_active) {
        return;
    }
    static const uint32_t base_colors[ACTIVITY_ROWS] = {
        0xc8ff43, 0x72d9ff, 0xbfaeff,
    };
    static const float minimum_brightness[ACTIVITY_ROWS] = {
        0.72f, 0.74f, 0.74f,
    };
    static const float pulse_amplitude[ACTIVITY_ROWS] = {
        0.28f, 0.26f, 0.26f,
    };
    const int64_t elapsed_us = esp_timer_get_time();
    const provider_display_state_t *display_state =
        current_provider_display_state();
    const int five_hour_active_columns =
        quota_segment_columns(display_state->quota_5h,
                              display_state->quota_5h_valid);
    const int weekly_active_columns =
        quota_segment_columns(display_state->quota_7d,
                              display_state->quota_7d_valid);

    if (five_hour_active_columns != s_activity_5h_active_columns ||
        weekly_active_columns != s_activity_7d_active_columns) {
        for (int row = 0; row < ACTIVITY_ROWS; ++row) {
            for (int col = 0; col < ACTIVITY_COLUMNS; ++col) {
                const bool active_5h =
                    col < five_hour_active_columns;
                const bool active_7d =
                    col >= ACTIVITY_WEEK_START_COLUMN &&
                    col < ACTIVITY_WEEK_START_COLUMN + weekly_active_columns;
                if (!active_5h && !active_7d) {
                    lv_obj_set_style_bg_color(s_activity_cells[row][col],
                                              lv_color_hex(0x30353a), 0);
                    lv_obj_set_style_border_color(s_activity_cells[row][col],
                                                  lv_color_hex(0x262a2e), 0);
                }
            }
        }
        s_activity_5h_active_columns = five_hour_active_columns;
        s_activity_7d_active_columns = weekly_active_columns;
    }

    for (int row = 0; row < ACTIVITY_ROWS; ++row) {
        for (int segment = 0; segment < 2; ++segment) {
            const int start_column =
                segment == 0 ? 0 : ACTIVITY_WEEK_START_COLUMN;
            const int active_columns =
                segment == 0 ? five_hour_active_columns : weekly_active_columns;
            for (int local_col = 0; local_col < active_columns; ++local_col) {
                const int col = start_column + local_col;
                const float breath =
                    activity_particle_breath(row, col, elapsed_us);
                float brightness = minimum_brightness[row] +
                                   breath * pulse_amplitude[row];
                lv_color_t fill =
                    scale_activity_color(base_colors[row], brightness);
                lv_color_t border =
                    scale_activity_color(base_colors[row], brightness * 0.86f);
                lv_obj_set_style_bg_color(s_activity_cells[row][col], fill, 0);
                lv_obj_set_style_border_color(s_activity_cells[row][col],
                                              border, 0);
            }
        }
    }
}

static void create_recording_overlay(lv_obj_t *screen)
{
    s_recording_overlay = make_fullscreen_overlay(screen);
    lv_obj_add_flag(s_recording_overlay, LV_OBJ_FLAG_HIDDEN);
    s_recording_wave_group = lv_obj_create(s_recording_overlay);
    lv_obj_remove_style_all(s_recording_wave_group);
    lv_obj_set_size(s_recording_wave_group, 82, 54);
    lv_obj_set_flex_flow(s_recording_wave_group, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_recording_wave_group, LV_FLEX_ALIGN_CENTER,
                          LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_recording_wave_group, 6, 0);
    lv_obj_align(s_recording_wave_group, LV_ALIGN_CENTER, 0, -20);
    static const int initial_wave_heights[5] = {14, 22, 32, 22, 14};
    for (int i = 0; i < 5; ++i) {
        s_recording_wave_bars[i] = make_plain_obj(s_recording_wave_group, 6,
                                                  initial_wave_heights[i],
                                                  lv_color_hex(0xf4f5f7),
                                                  LV_OPA_COVER, 3);
    }
    s_recording_title = make_label(s_recording_overlay, "LISTENING", &lv_font_montserrat_20,
                                   lv_color_hex(0xf4f5f7), 180, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_recording_title, LV_ALIGN_CENTER, 0, 26);
    s_recording_hint = make_label(s_recording_overlay, "RELEASE TO SEND", &lv_font_montserrat_14,
                                  lv_color_hex(0x8b9098), 180, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_recording_hint, LV_ALIGN_BOTTOM_MID, 0, -7);
}

static void layout_landscape_date_row(const char *date_text,
                                      const char *weekday_text)
{
    const int32_t separator_size = 3;
    const int32_t separator_gap = 8;
    lv_label_set_text(s_date_label, date_text);
    lv_label_set_text(s_weekday_label, weekday_text);
    lv_obj_set_size(s_date_label, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_set_size(s_weekday_label, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
    lv_obj_update_layout(s_date_group);
    int32_t date_width = lv_obj_get_width(s_date_label);
    int32_t weekday_width = lv_obj_get_width(s_weekday_label);
    int32_t content_width =
        date_width + separator_gap + separator_size + separator_gap +
        weekday_width;
    int32_t content_x = (LCD_V_RES - content_width) / 2;
    lv_obj_set_pos(s_date_label, content_x, 4);
    lv_obj_set_pos(s_date_separator,
                   content_x + date_width + separator_gap, 11);
    lv_obj_set_pos(s_weekday_label,
                   content_x + date_width + separator_gap + separator_size +
                       separator_gap,
                   4);
    if (s_activity_divider) {
        const int32_t divider_x =
            lv_obj_get_x(s_date_separator) + separator_size / 2;
        lv_obj_set_x(s_activity_divider, divider_x);
        if (s_activity_5h_percent_label) {
            lv_obj_set_x(s_activity_5h_percent_label,
                         divider_x / 2 - 20);
        }
        if (s_activity_7d_percent_label) {
            lv_obj_set_x(s_activity_7d_percent_label,
                         divider_x + (LCD_V_RES - divider_x) / 2 - 20);
        }
    }
    lv_obj_invalidate(s_date_group);
}

static void format_landscape_date_text(const char *source, char *target,
                                       size_t target_size)
{
    snprintf(target, target_size, "%s", source);
    if (strlen(target) >= 3) {
        target[0] = (char)toupper((unsigned char)target[0]);
        target[1] = (char)tolower((unsigned char)target[1]);
        target[2] = (char)tolower((unsigned char)target[2]);
    }
}

static void format_landscape_weekday_text(const char *source, char *target,
                                          size_t target_size)
{
    if (strlen(source) < 3) {
        snprintf(target, target_size, "---.");
        return;
    }
    snprintf(target, target_size, "%c%c%c.",
             toupper((unsigned char)source[0]),
             tolower((unsigned char)source[1]),
             tolower((unsigned char)source[2]));
}

static void create_landscape_ui(lv_obj_t *screen)
{
    s_activity_divider = NULL;
    s_activity_5h_percent_label = NULL;
    s_activity_7d_percent_label = NULL;
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x161a1e), 0);
    lv_obj_set_style_pad_all(screen, 0, 0);

    s_status_dot = make_plain_obj(screen, 7, 7, lv_color_hex(0xc6f24a),
                                  LV_OPA_COVER, LV_RADIUS_CIRCLE);
    lv_obj_align(s_status_dot, LV_ALIGN_TOP_LEFT, 6, 6);
    s_status_label = make_label(screen, "RUNNING", &lv_font_montserrat_12,
                                lv_color_hex(0xc6f24a), 78, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_status_label, LV_ALIGN_TOP_LEFT, 17, 2);
    lv_obj_t *top_line = make_plain_obj(screen, 45, 1, lv_color_hex(0x56606a),
                                        LV_OPA_COVER, 0);
    lv_obj_align(top_line, LV_ALIGN_TOP_RIGHT, -5, 9);

    s_time_label = make_label(screen, "--:--", &lv_font_montserrat_36,
                              lv_color_hex(0xf2f4f7), 126, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_time_label, LV_ALIGN_TOP_LEFT, 10, 26);
    s_seconds_label = make_label(screen, "--", &lv_font_montserrat_16,
                                 lv_color_hex(0xc9d1d9), 38, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_seconds_label, LV_ALIGN_TOP_LEFT, 134, 23);
    s_days_left_label = make_label(screen, "--D", &lv_font_montserrat_16,
                                   lv_color_hex(0xd8dde3), 38,
                                   LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_days_left_label, LV_ALIGN_TOP_LEFT, 134, 41);
    s_percent_left_label = make_label(screen, "--%", &lv_font_montserrat_16,
                                      lv_color_hex(0xd8dde3), 38,
                                      LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_percent_left_label, LV_ALIGN_TOP_LEFT, 134, 59);

    static const char *counter_names[3] = {"RUN", "WAIT", "FIN"};
    static const uint32_t counter_colors[3] = {0xb8e63a, 0xa88bff, 0x41c7ff};
    static const uint32_t counter_text_colors[3] = {0x243000, 0x241a4d, 0x08293a};
    lv_obj_t **counter_values[3] = {&s_run_count_label, &s_ask_count_label,
                                    &s_new_count_label};
    for (int i = 0; i < 3; ++i) {
        lv_obj_t *tag = make_plain_obj(screen, 36, 16, lv_color_hex(counter_colors[i]),
                                       LV_OPA_COVER, 5);
        lv_obj_align(tag, LV_ALIGN_TOP_LEFT, 176, 23 + i * 20);
        lv_obj_t *name = make_label(tag, counter_names[i], &lv_font_montserrat_10,
                                    lv_color_hex(counter_text_colors[i]), 34,
                                    LV_TEXT_ALIGN_CENTER);
        lv_obj_center(name);
        *counter_values[i] = make_label(screen, "0", &lv_font_montserrat_14,
                                        lv_color_hex(0xf2f4f7), 22, LV_TEXT_ALIGN_RIGHT);
        lv_obj_align(*counter_values[i], LV_ALIGN_TOP_RIGHT, -4, 22 + i * 20);
    }

    s_date_group = make_plain_obj(screen, LCD_V_RES, 34,
                                  lv_color_hex(0x161a1e), LV_OPA_TRANSP, 0);
    lv_obj_set_pos(s_date_group, 0, 74);
    lv_obj_remove_flag(s_date_group, LV_OBJ_FLAG_SCROLLABLE);
    s_date_label = make_label(s_date_group, "--- --", &lv_font_montserrat_14,
                              lv_color_hex(0xc9d1d9), 61, LV_TEXT_ALIGN_LEFT);
    s_date_separator = make_plain_obj(s_date_group, 3, 3,
                                      lv_color_hex(0x8e98a3),
                                      LV_OPA_COVER, LV_RADIUS_CIRCLE);
    s_weekday_label = make_label(s_date_group, "-------",
                                 &lv_font_montserrat_14,
                                 lv_color_hex(0xc9d1d9), 66, LV_TEXT_ALIGN_LEFT);
    lv_obj_t *five_hour_hint =
        make_label(s_date_group, "5H:", &lv_font_montserrat_12,
                   lv_color_hex(0x41c7ff), 28, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(five_hour_hint, LV_ALIGN_BOTTOM_LEFT, 6, 0);
    lv_obj_t *weekly_hint =
        make_label(s_date_group, "1W:", &lv_font_montserrat_12,
                   lv_color_hex(0x41c7ff), 28, LV_TEXT_ALIGN_RIGHT);
    lv_obj_align(weekly_hint, LV_ALIGN_BOTTOM_RIGHT, -6, 0);
    s_activity_5h_percent_label =
        make_label(s_date_group, "--%", &lv_font_montserrat_12,
                   lv_color_hex(0x41c7ff), 40, LV_TEXT_ALIGN_CENTER);
    lv_obj_set_y(s_activity_5h_percent_label, 19);
    s_activity_7d_percent_label =
        make_label(s_date_group, "--%", &lv_font_montserrat_12,
                   lv_color_hex(0x41c7ff), 40, LV_TEXT_ALIGN_CENTER);
    lv_obj_set_y(s_activity_7d_percent_label, 19);
    layout_landscape_date_row("--- --", "-------");

    for (int row = 0; row < ACTIVITY_ROWS; ++row) {
        for (int col = 0; col < ACTIVITY_COLUMNS; ++col) {
            s_activity_cells[row][col] = make_plain_obj(screen, 3, 4,
                                                        lv_color_hex(0x30353a),
                                                        LV_OPA_COVER, 1);
            lv_obj_set_style_border_width(s_activity_cells[row][col], 1, 0);
            lv_obj_set_style_border_opa(s_activity_cells[row][col],
                                        LV_OPA_COVER, 0);
            lv_obj_set_style_border_color(s_activity_cells[row][col],
                                          lv_color_hex(0x262a2e), 0);
            lv_obj_set_pos(s_activity_cells[row][col], 6 + col * 4,
                           110 + row * 6);
        }
    }
    s_activity_divider = make_plain_obj(screen, 1, 42,
                                        lv_color_hex(0x41c7ff),
                                        LV_OPA_COVER, 0);
    lv_obj_set_y(s_activity_divider, 90);
    layout_landscape_date_row("--- --", "-------");
    create_recording_overlay(screen);
    s_activity_timer = lv_timer_create(activity_timer_cb, ACTIVITY_FRAME_MS, NULL);
}

static void switch_display_orientation(bool landscape, bool landscape_reverse)
{
    lvgl_lock();
    if (landscape && s_landscape_active) {
        if (landscape_reverse == s_landscape_reverse) {
            lvgl_unlock();
            return;
        }
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(
            s_panel,
            landscape_reverse ? false : true,
            landscape_reverse ? true : false));
        s_landscape_reverse = landscape_reverse;
        lv_obj_invalidate(lv_display_get_screen_active(s_display));
        lv_refr_now(s_display);
        lvgl_unlock();
        ESP_LOGI(TAG, "display orientation=%s mirror-only",
                 landscape_reverse ? "landscape-left" : "landscape-right");
        return;
    }
    lv_obj_t *old_screen = lv_display_get_screen_active(s_display);
    if (s_activity_timer) {
        lv_timer_delete(s_activity_timer);
        s_activity_timer = NULL;
    }
    if (landscape) {
        ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, true));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(
            s_panel,
            landscape_reverse ? false : true,
            landscape_reverse ? true : false));
        ESP_ERROR_CHECK(esp_lcd_panel_set_gap(s_panel, LCD_Y_GAP, LCD_X_GAP));
        lv_display_set_resolution(s_display, LCD_V_RES, LCD_H_RES);
    } else {
        ESP_ERROR_CHECK(esp_lcd_panel_swap_xy(s_panel, false));
        ESP_ERROR_CHECK(esp_lcd_panel_mirror(s_panel, false, false));
        ESP_ERROR_CHECK(esp_lcd_panel_set_gap(s_panel, LCD_X_GAP, LCD_Y_GAP));
        lv_display_set_resolution(s_display, LCD_H_RES, LCD_V_RES);
    }
    lv_obj_t *new_screen = lv_obj_create(NULL);
    s_landscape_active = landscape;
    s_landscape_reverse = landscape && landscape_reverse;
    if (landscape) {
        create_landscape_ui(new_screen);
    } else {
        create_portrait_ui(new_screen);
    }
    lv_screen_load(new_screen);
    lv_obj_delete(old_screen);
    lvgl_unlock();
    ESP_LOGI(TAG, "display orientation=%s",
             landscape
                 ? (landscape_reverse ? "landscape-left" : "landscape-right")
                 : "portrait");
    render_state();
}

static void create_portrait_ui(lv_obj_t *screen)
{
    lv_obj_set_style_bg_color(screen, lv_color_hex(0x050608), 0);
    lv_obj_set_style_pad_all(screen, 0, 0);

    s_wifi_label = make_label(screen, "WIFI", &lv_font_montserrat_10,
                              lv_color_hex(0xf3f4f6), 36, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_wifi_label, LV_ALIGN_TOP_LEFT, 7, 8);
    s_time_label = make_label(screen, "--:--", &lv_font_montserrat_10,
                              lv_color_hex(0xf3f4f6), 42, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_time_label, LV_ALIGN_TOP_MID, 0, 8);

    s_battery_label = make_label(screen, "", &lv_font_montserrat_10,
                                 lv_color_hex(0xf3f4f6), 1, LV_TEXT_ALIGN_RIGHT);
    lv_obj_add_flag(s_battery_label, LV_OBJ_FLAG_HIDDEN);
    s_battery_icon = make_plain_obj(screen, 26, 13, lv_color_hex(0x000000), LV_OPA_TRANSP, 3);
    lv_obj_set_style_border_width(s_battery_icon, 1, 0);
    lv_obj_set_style_border_color(s_battery_icon, lv_color_hex(0xf3f4f6), 0);
    lv_obj_align(s_battery_icon, LV_ALIGN_TOP_RIGHT, -8, 7);
    s_battery_fill = make_plain_obj(s_battery_icon, 1, 9, lv_color_hex(0xf3f4f6), LV_OPA_COVER, 2);
    lv_obj_align(s_battery_fill, LV_ALIGN_LEFT_MID, 2, 0);
    s_battery_bolt = lv_line_create(s_battery_icon);
    lv_line_set_points(s_battery_bolt, s_battery_bolt_points,
                       sizeof(s_battery_bolt_points) / sizeof(s_battery_bolt_points[0]));
    lv_obj_set_style_line_width(s_battery_bolt, 1, 0);
    lv_obj_set_style_line_color(s_battery_bolt, lv_color_hex(0xffffff), 0);
    lv_obj_set_style_line_rounded(s_battery_bolt, true, 0);
    lv_obj_align(s_battery_bolt, LV_ALIGN_CENTER, 0, 0);
    lv_obj_add_flag(s_battery_bolt, LV_OBJ_FLAG_HIDDEN);
    s_battery_cap = make_plain_obj(screen, 2, 7, lv_color_hex(0xf3f4f6), LV_OPA_COVER, 1);
    lv_obj_align_to(s_battery_cap, s_battery_icon, LV_ALIGN_OUT_RIGHT_MID, 1, 0);

    create_provider_icon(screen);

    s_status_dot = lv_obj_create(screen);
    lv_obj_remove_style_all(s_status_dot);
    lv_obj_set_size(s_status_dot, 7, 7);
    lv_obj_set_style_radius(s_status_dot, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(s_status_dot, lv_color_hex(0xf3f4f6), 0);
    lv_obj_set_style_bg_opa(s_status_dot, LV_OPA_COVER, 0);

    s_provider_label = make_label(screen, "Codex", &lv_font_montserrat_16,
                                  lv_color_hex(0xf3f4f6), 77, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_provider_label, LV_ALIGN_TOP_LEFT, 55, 37);

    s_status_label = make_label(screen, "IDLE", &lv_font_montserrat_12,
                                lv_color_hex(0xf3f4f6), 66, LV_TEXT_ALIGN_LEFT);
    lv_obj_align(s_status_label, LV_ALIGN_TOP_LEFT, 71, 59);
    lv_obj_align_to(s_status_dot, s_status_label, LV_ALIGN_OUT_LEFT_MID, -4, 0);

    make_metric_card(screen, 91, "FUNDS:", lv_color_hex(0x8edb94), &s_funds_value_label);
    make_metric_card(screen, 137, "TODAY:", lv_color_hex(0x8d94ee), &s_today_value_label);
    make_metric_card(screen, 183, "TOKEN:", lv_color_hex(0xe7d86f), &s_token_value_label);
    lv_obj_set_style_text_font(s_token_value_label, &lv_font_montserrat_14, 0);

    s_recording_overlay = make_fullscreen_overlay(screen);
    lv_obj_add_flag(s_recording_overlay, LV_OBJ_FLAG_HIDDEN);

    s_recording_wave_group = lv_obj_create(s_recording_overlay);
    lv_obj_remove_style_all(s_recording_wave_group);
    lv_obj_set_size(s_recording_wave_group, 82, 58);
    lv_obj_set_flex_flow(s_recording_wave_group, LV_FLEX_FLOW_ROW);
    lv_obj_set_flex_align(s_recording_wave_group, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
    lv_obj_set_style_pad_column(s_recording_wave_group, 6, 0);
    lv_obj_align(s_recording_wave_group, LV_ALIGN_CENTER, 0, -34);
    static const int initial_wave_heights[5] = {14, 22, 32, 22, 14};
    for (int i = 0; i < 5; ++i) {
        s_recording_wave_bars[i] = make_plain_obj(s_recording_wave_group, 6, initial_wave_heights[i],
                                                  lv_color_hex(0xf4f5f7), LV_OPA_COVER, 3);
    }

    s_recording_title = make_label(s_recording_overlay, "LISTENING", &lv_font_montserrat_16,
                                   lv_color_hex(0xf4f5f7), 120, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_recording_title, LV_ALIGN_CENTER, 0, 22);
    s_recording_hint = make_label(s_recording_overlay, "RELEASE TO SEND", &lv_font_montserrat_12,
                                  lv_color_hex(0x8b9098), 120, LV_TEXT_ALIGN_CENTER);
    lv_obj_align(s_recording_hint, LV_ALIGN_BOTTOM_MID, 0, -22);

}

static void create_ui(void)
{
    create_portrait_ui(lv_display_get_screen_active(s_display));
}

static void set_status_color(const agent_provider_config_t *provider, const char *status)
{
    (void)provider;
    lv_color_t color = lv_color_hex(0x9aa0aa);
    if (strcmp(status, "RUNNING") == 0) {
        color = s_landscape_active ? lv_color_hex(0xc6f24a) : lv_color_hex(0xf5c84c);
    } else if (strcmp(status, "DONE") == 0) {
        color = lv_color_hex(0x32d583);
    } else if (strcmp(status, "APPROVAL") == 0) {
        color = lv_color_hex(0xf5c84c);
    } else if (strcmp(status, "IDLE") == 0 || strcmp(status, "UNKNOWN") == 0) {
        color = lv_color_hex(0x9aa0aa);
    } else if (strcmp(status, "ERROR") == 0 || strcmp(status, "OFFLINE") == 0) {
        color = lv_color_hex(0xf04438);
    }
    lv_obj_set_style_bg_color(s_status_dot, color, 0);
}

static void set_percent_label(lv_obj_t *label, int value, bool valid)
{
    if (!valid) {
        lv_label_set_text(label, "--");
        return;
    }
    if (value < 0) {
        value = 0;
    } else if (value > 100) {
        value = 100;
    }
    char text[8];
    snprintf(text, sizeof(text), "%d%%", value);
    lv_label_set_text(label, text);
}

static void set_token_label(lv_obj_t *label, int value, bool valid)
{
    if (!valid) {
        lv_label_set_text(label, "--");
        return;
    }
    char text[16];
    if (value >= 1000000) {
        snprintf(text, sizeof(text), "%.1fM", (double)value / 1000000.0);
    } else if (value >= 1000) {
        snprintf(text, sizeof(text), "%.1fK", (double)value / 1000.0);
    } else {
        snprintf(text, sizeof(text), "%d", value);
    }
    lv_label_set_text(label, text);
}

static void render_state(void)
{
    lvgl_lock();
    const agent_provider_config_t *provider = current_provider_config();
    const provider_display_state_t *display_state = current_provider_display_state();
    const char *status_key = display_state->status;

    if (s_landscape_active) {
        char hour_minute[6] = "--:--";
        char seconds[3] = "--";
        if (strlen(s_state.time) >= 5) {
            memcpy(hour_minute, s_state.time, 5);
            hour_minute[5] = '\0';
        }
        if (strlen(s_state.time) >= 8) {
            memcpy(seconds, s_state.time + 6, 2);
            seconds[2] = '\0';
        }
        lv_label_set_text(s_time_label, hour_minute);
        lv_label_set_text(s_seconds_label, seconds);
        char days_left_text[12] = "--D";
        if (display_state->quota_7d_reset_days_valid) {
            int days_left = display_state->quota_7d_reset_days;
            snprintf(days_left_text, sizeof(days_left_text), "%dD", days_left);
        }
        lv_label_set_text(s_days_left_label, days_left_text);
        char percent_left_text[8] = "--%";
        if (display_state->quota_7d_valid) {
            int percent_left = display_state->quota_7d;
            snprintf(percent_left_text, sizeof(percent_left_text), "%d%%",
                     percent_left);
        }
        lv_label_set_text(s_percent_left_label, percent_left_text);
        char five_hour_percent_text[8] = "--%";
        if (display_state->quota_5h_valid) {
            snprintf(five_hour_percent_text,
                     sizeof(five_hour_percent_text), "%d%%",
                     display_state->quota_5h);
        }
        lv_label_set_text(s_activity_5h_percent_label,
                          five_hour_percent_text);
        char weekly_percent_text[8] = "--%";
        if (display_state->quota_7d_valid) {
            snprintf(weekly_percent_text,
                     sizeof(weekly_percent_text), "%d%%",
                     display_state->quota_7d);
        }
        lv_label_set_text(s_activity_7d_percent_label,
                          weekly_percent_text);
        char landscape_date[8];
        char landscape_weekday[6];
        format_landscape_date_text(
            s_state.date[0] ? s_state.date : "--- --",
            landscape_date, sizeof(landscape_date));
        format_landscape_weekday_text(
            s_state.weekday[0] ? s_state.weekday : "-------",
            landscape_weekday, sizeof(landscape_weekday));
        layout_landscape_date_row(landscape_date, landscape_weekday);

        const char *landscape_status = status_key;
        if (strcmp(status_key, "APPROVAL") == 0) {
            landscape_status = "WAITING";
        } else if (strcmp(status_key, "UNKNOWN") == 0) {
            landscape_status = "IDLE";
        }
        lv_label_set_text(s_status_label, landscape_status);
        set_status_color(provider, status_key);
        lv_color_t status_color = lv_color_hex(0x9aa0aa);
        if (strcmp(status_key, "RUNNING") == 0) {
            status_color = lv_color_hex(0xc6f24a);
        } else if (strcmp(status_key, "DONE") == 0) {
            status_color = lv_color_hex(0x65e58c);
        } else if (strcmp(status_key, "APPROVAL") == 0) {
            status_color = lv_color_hex(0xffcf4b);
        } else if (strcmp(status_key, "ERROR") == 0 ||
                   strcmp(status_key, "OFFLINE") == 0) {
            status_color = lv_color_hex(0xff5a5f);
        }
        lv_obj_set_style_text_color(s_status_label, status_color, 0);

        char running_tasks_text[4];
        int visible_running_tasks = display_state->running_tasks;
        if (visible_running_tasks < 0) {
            visible_running_tasks = 0;
        } else if (visible_running_tasks > 99) {
            visible_running_tasks = 99;
        }
        snprintf(running_tasks_text, sizeof(running_tasks_text), "%d",
                 visible_running_tasks);
        lv_label_set_text(s_run_count_label, running_tasks_text);
        char waiting_tasks_text[4];
        int visible_waiting_tasks = display_state->waiting_tasks;
        if (visible_waiting_tasks < 0) {
            visible_waiting_tasks = 0;
        } else if (visible_waiting_tasks > 99) {
            visible_waiting_tasks = 99;
        }
        snprintf(waiting_tasks_text, sizeof(waiting_tasks_text), "%d",
                 visible_waiting_tasks);
        lv_label_set_text(s_ask_count_label, waiting_tasks_text);
        char count_text[4];
        int visible_finished_tasks = display_state->finished_tasks;
        if (visible_finished_tasks < 0) {
            visible_finished_tasks = 0;
        } else if (visible_finished_tasks > 99) {
            visible_finished_tasks = 99;
        }
        snprintf(count_text, sizeof(count_text), "%d", visible_finished_tasks);
        lv_label_set_text(s_new_count_label, count_text);
        activity_timer_cb(NULL);
        lvgl_unlock();
        return;
    }

    lv_label_set_text(s_wifi_label, s_wifi_connected ? "WIFI" : "OFF");
    lv_label_set_text(s_time_label, s_state.time[0] ? s_state.time : "--:--");
    lv_obj_set_style_text_color(s_wifi_label,
                                s_wifi_connected ? lv_color_hex(0xf3f4f6) : lv_color_hex(0x686e78),
                                0);
    set_battery_ui(s_state.battery, s_state.battery_charging, s_state.usb_powered);
    if (provider->icon) {
        lv_image_set_src(s_provider_icon, provider->icon);
        lv_obj_clear_flag(s_provider_icon, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_provider_icon, LV_OBJ_FLAG_HIDDEN);
    }
    lv_label_set_text(s_provider_label, provider->display_name);
    lv_obj_set_style_text_color(s_provider_label, lv_color_hex(0xf3f4f6), 0);
    lv_label_set_text(s_status_label, status_text_for(display_state->status));
    set_status_color(provider, status_key);
    const bool quota_valid = display_state->quota_7d_valid || display_state->quota_5h_valid;
    const int quota_remaining = display_state->quota_7d_valid
        ? display_state->quota_7d : display_state->quota_5h;
    set_percent_label(s_funds_value_label, quota_remaining, quota_valid);
    set_percent_label(s_today_value_label, display_state->today_used_percent,
                      display_state->today_used_percent_valid);
    set_token_label(s_token_value_label, display_state->today_tokens,
                    display_state->today_tokens_valid);
    lvgl_unlock();
}

static void show_recording_overlay(const char *title, const char *hint, bool visible)
{
    lvgl_lock();
    if (visible) {
        if (title) {
            lv_label_set_text(s_recording_title, title);
        }
        if (hint) {
            lv_label_set_text(s_recording_hint, hint);
            if (hint[0] == '\0') {
                lv_obj_add_flag(s_recording_hint, LV_OBJ_FLAG_HIDDEN);
            } else {
                lv_obj_clear_flag(s_recording_hint, LV_OBJ_FLAG_HIDDEN);
            }
        }
        lv_obj_clear_flag(s_recording_overlay, LV_OBJ_FLAG_HIDDEN);
        start_recording_wave();
    } else {
        stop_recording_wave();
        lv_obj_add_flag(s_recording_overlay, LV_OBJ_FLAG_HIDDEN);
    }
    s_recording_overlay_visible = visible;
    lvgl_unlock();
}

static bool sound_for_alert_type(const char *type, agent_sound_t *sound)
{
    if (strcmp(type, "DONE") == 0 ||
        strcmp(type, "COMPLETED") == 0 ||
        strcmp(type, "SUCCESS") == 0) {
        *sound = VIBE_STICK_SOUND_DONE;
        return true;
    }
    if (strcmp(type, "ERROR") == 0 ||
        strcmp(type, "FAILED") == 0 ||
        strcmp(type, "FAILURE") == 0) {
        *sound = VIBE_STICK_SOUND_ERROR;
        return true;
    }
    if (strcmp(type, "APPROVAL") == 0 ||
        strcmp(type, "WAITING_APPROVAL") == 0 ||
        strcmp(type, "PENDING_APPROVAL") == 0 ||
        strcmp(type, "NEEDS_APPROVAL") == 0) {
        *sound = VIBE_STICK_SOUND_APPROVAL;
        return true;
    }
    return false;
}

static void remember_alert_sound_baseline(void)
{
    strlcpy(s_last_alert_event_id, s_state.alert_event_id, sizeof(s_last_alert_event_id));
    strlcpy(s_last_alert_type, s_state.alert_type, sizeof(s_last_alert_type));
    s_alert_sound_baseline_ready = true;
}

static bool should_play_alert_sound(void)
{
    agent_sound_t ignored;
    const bool target = sound_for_alert_type(s_state.alert_type, &ignored);

    if (!s_alert_sound_baseline_ready) {
        remember_alert_sound_baseline();
        return false;
    }

    if (!target) {
        remember_alert_sound_baseline();
        return false;
    }

    bool should_play = false;
    if (s_state.alert_event_id[0] != '\0') {
        should_play = strcmp(s_last_alert_event_id, s_state.alert_event_id) != 0;
    } else {
        should_play = strcmp(s_last_alert_type, s_state.alert_type) != 0;
    }
    remember_alert_sound_baseline();
    return should_play;
}

static void maybe_handle_alert(void)
{
    agent_sound_t sound;
    if (!sound_for_alert_type(s_state.alert_type, &sound)) {
        (void)should_play_alert_sound();
        return;
    }
    if (!should_play_alert_sound()) {
        return;
    }
    if (s_recording_overlay_visible || vibe_audio_is_recording()) {
        ESP_LOGI(TAG, "skip alert sound while recording overlay is active type=%s",
                 s_state.alert_type);
        return;
    }

    esp_err_t err = vibe_audio_play_sound(sound);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "alert sound skipped type=%s err=%s",
                 s_state.alert_type, esp_err_to_name(err));
    }
    ESP_LOGI(TAG, "alert type=%s project=%s message=%s",
             s_state.alert_type, s_state.project, s_state.alert_message);
}

static void maybe_handle_waiting_tasks(void)
{
    const int waiting_tasks = current_provider_display_state()->waiting_tasks;
    if (!s_wait_sound_baseline_ready) {
        s_last_waiting_tasks = waiting_tasks;
        s_wait_sound_baseline_ready = true;
        return;
    }

    const bool should_play = waiting_tasks > 0 && waiting_tasks > s_last_waiting_tasks;
    s_last_waiting_tasks = waiting_tasks;
    if (!should_play) {
        return;
    }
    if (s_recording_overlay_visible || vibe_audio_is_recording()) {
        ESP_LOGI(TAG, "skip wait sound while recording overlay is active count=%d",
                 waiting_tasks);
        return;
    }

    esp_err_t err = vibe_audio_play_sound(VIBE_STICK_SOUND_WAIT);
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "wait sound skipped count=%d err=%s",
                 waiting_tasks, esp_err_to_name(err));
        return;
    }
    ESP_LOGI(TAG, "wait sound played count=%d", waiting_tasks);
}

static esp_err_t http_event_handler(esp_http_client_event_t *evt)
{
    if (evt->event_id != HTTP_EVENT_ON_DATA || !evt->user_data || !evt->data || evt->data_len <= 0) {
        return ESP_OK;
    }

    http_response_capture_t *capture = (http_response_capture_t *)evt->user_data;
    if (!capture->data || capture->capacity <= 0 || capture->used >= capture->capacity - 1) {
        return ESP_OK;
    }

    int remaining = capture->capacity - 1 - capture->used;
    int copy_len = evt->data_len < remaining ? evt->data_len : remaining;
    memcpy(capture->data + capture->used, evt->data, copy_len);
    capture->used += copy_len;
    capture->data[capture->used] = '\0';
    return ESP_OK;
}

static esp_err_t http_request_timeout(const char *method, const char *path, const char *body,
                                      char *response, int response_len, int timeout_ms)
{
    char url[160];
    snprintf(url, sizeof(url), "http://%s:%d%s", VIBE_STICK_BRIDGE_HOST, VIBE_STICK_BRIDGE_PORT, path);
    http_response_capture_t capture = {
        .data = response,
        .capacity = response_len,
        .used = 0,
    };
    if (response && response_len > 0) {
        response[0] = '\0';
    }
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = timeout_ms,
        .event_handler = http_event_handler,
        .user_data = &capture,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    ESP_RETURN_ON_FALSE(client != NULL, ESP_ERR_NO_MEM, TAG, "http init");
    esp_http_client_set_method(client, strcmp(method, "POST") == 0 ? HTTP_METHOD_POST : HTTP_METHOD_GET);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Name", FIRMWARE_NAME);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Version", FIRMWARE_VERSION);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Transport", TRANSPORT);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Build-Date", __DATE__ " " __TIME__);
    if (strlen(VIBE_STICK_BRIDGE_TOKEN) > 0) {
        esp_http_client_set_header(client, "X-Vibe-Stick-Token", VIBE_STICK_BRIDGE_TOKEN);
    }
    if (body) {
        esp_http_client_set_header(client, "Content-Type", "application/json");
        esp_http_client_set_post_field(client, body, strlen(body));
    }
    esp_err_t err = esp_http_client_perform(client);
    int status_code = esp_http_client_get_status_code(client);
    if (err == ESP_OK && response && response_len > 0 && capture.used == 0) {
        ESP_LOGW(TAG, "http %s %s status=%d empty response", method, path, status_code);
    }
    esp_http_client_cleanup(client);
    return err;
}

static esp_err_t http_request(const char *method, const char *path, const char *body,
                              char *response, int response_len)
{
    return http_request_timeout(method, path, body, response, response_len, 2500);
}

static esp_err_t http_post_binary(const char *path, const uint8_t *body, size_t body_len,
                                  char *response, int response_len)
{
    char url[192];
    snprintf(url, sizeof(url), "http://%s:%d%s", VIBE_STICK_BRIDGE_HOST, VIBE_STICK_BRIDGE_PORT, path);
    http_response_capture_t capture = {
        .data = response,
        .capacity = response_len,
        .used = 0,
    };
    if (response && response_len > 0) {
        response[0] = '\0';
    }
    esp_http_client_config_t config = {
        .url = url,
        .timeout_ms = 20000,
        .event_handler = http_event_handler,
        .user_data = &capture,
    };
    esp_http_client_handle_t client = esp_http_client_init(&config);
    ESP_RETURN_ON_FALSE(client != NULL, ESP_ERR_NO_MEM, TAG, "http init");
    esp_http_client_set_method(client, HTTP_METHOD_POST);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Name", FIRMWARE_NAME);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Version", FIRMWARE_VERSION);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Transport", TRANSPORT);
    esp_http_client_set_header(client, "X-Vibe-Stick-Firmware-Build-Date", __DATE__ " " __TIME__);
    if (strlen(VIBE_STICK_BRIDGE_TOKEN) > 0) {
        esp_http_client_set_header(client, "X-Vibe-Stick-Token", VIBE_STICK_BRIDGE_TOKEN);
    }
    esp_http_client_set_header(client, "Content-Type", "application/octet-stream");
    esp_http_client_set_header(client, "X-Vibe-Stick-Sample-Rate", "16000");
    esp_http_client_set_header(client, "X-Vibe-Stick-Channels", "1");
    esp_http_client_set_header(client, "X-Vibe-Stick-Bits-Per-Sample", "16");
    esp_http_client_set_post_field(client, (const char *)body, body_len);
    esp_err_t err = esp_http_client_perform(client);
    int status_code = esp_http_client_get_status_code(client);
    if (err == ESP_OK && response && response_len > 0 && capture.used == 0) {
        ESP_LOGW(TAG, "http POST %s status=%d empty response", path, status_code);
    }
    esp_http_client_cleanup(client);
    return err;
}

static void copy_json_string(cJSON *root, const char *key, char *target, size_t target_len)
{
    cJSON *item = cJSON_GetObjectItemCaseSensitive(root, key);
    if (cJSON_IsString(item) && item->valuestring) {
        strlcpy(target, item->valuestring, target_len);
    }
}

static bool json_percent_value(cJSON *item, int *value)
{
    if (cJSON_IsNumber(item)) {
        *value = item->valueint;
    } else if (cJSON_IsString(item) && item->valuestring && item->valuestring[0] != '\0') {
        char *end = NULL;
        long parsed = strtol(item->valuestring, &end, 10);
        if (!end || end == item->valuestring) {
            return false;
        }
        while (*end == ' ' || *end == '\t' || *end == '\r' || *end == '\n' || *end == '%') {
            end++;
        }
        if (*end != '\0') {
            return false;
        }
        *value = (int)parsed;
    } else {
        return false;
    }
    if (*value < 0) {
        *value = 0;
    } else if (*value > 100) {
        *value = 100;
    }
    return true;
}

static void parse_provider_fields(cJSON *source, provider_display_state_t *target)
{
    copy_json_string(source, "status", target->status, sizeof(target->status));
    copy_json_string(source, "project", target->project, sizeof(target->project));
    copy_json_string(source, "quota_updated_at", target->quota_updated_at, sizeof(target->quota_updated_at));

    cJSON *quota_5h = cJSON_GetObjectItemCaseSensitive(source, "quota_5h_remaining");
    cJSON *quota_7d = cJSON_GetObjectItemCaseSensitive(source, "quota_7d_remaining");
    cJSON *quota_7d_reset_days =
        cJSON_GetObjectItemCaseSensitive(source, "quota_7d_reset_days");
    cJSON *stale = cJSON_GetObjectItemCaseSensitive(source, "quota_stale");
    cJSON *funds = cJSON_GetObjectItemCaseSensitive(source, "funds_balance");
    cJSON *today = cJSON_GetObjectItemCaseSensitive(source, "today_spend");
    cJSON *tokens = cJSON_GetObjectItemCaseSensitive(source, "today_tokens");
    cJSON *today_used_percent =
        cJSON_GetObjectItemCaseSensitive(source, "today_used_percent");
    cJSON *running_tasks = cJSON_GetObjectItemCaseSensitive(source, "running_tasks");
    cJSON *waiting_tasks = cJSON_GetObjectItemCaseSensitive(source, "waiting_tasks");
    cJSON *finished_tasks = cJSON_GetObjectItemCaseSensitive(source, "finished_tasks");
    int quota_value = 0;
    target->quota_5h_valid = json_percent_value(quota_5h, &quota_value);
    if (target->quota_5h_valid) {
        target->quota_5h = quota_value;
    }
    target->quota_7d_valid = json_percent_value(quota_7d, &quota_value);
    if (target->quota_7d_valid) {
        target->quota_7d = quota_value;
    }
    target->quota_7d_reset_days_valid =
        cJSON_IsNumber(quota_7d_reset_days) &&
        quota_7d_reset_days->valuedouble >= 0;
    if (target->quota_7d_reset_days_valid) {
        target->quota_7d_reset_days = (int)quota_7d_reset_days->valuedouble;
    }
    target->quota_stale = cJSON_IsBool(stale) ? cJSON_IsTrue(stale) : false;
    if (cJSON_IsString(funds) && funds->valuestring) {
        strlcpy(target->funds_balance, funds->valuestring, sizeof(target->funds_balance));
    } else {
        target->funds_balance[0] = '\0';
    }
    if (cJSON_IsString(today) && today->valuestring) {
        strlcpy(target->today_spend, today->valuestring, sizeof(target->today_spend));
    } else {
        target->today_spend[0] = '\0';
    }
    if (cJSON_IsNumber(tokens) && tokens->valuedouble >= 0) {
        target->today_tokens = (int)tokens->valuedouble;
        target->today_tokens_valid = true;
    } else {
        target->today_tokens = 0;
        target->today_tokens_valid = false;
    }
    target->today_used_percent_valid =
        json_percent_value(today_used_percent, &quota_value);
    if (target->today_used_percent_valid) {
        target->today_used_percent = quota_value;
    } else {
        target->today_used_percent = 0;
    }
    if (cJSON_IsNumber(running_tasks) && running_tasks->valuedouble >= 0) {
        target->running_tasks = (int)running_tasks->valuedouble;
    } else {
        target->running_tasks = 0;
    }
    if (cJSON_IsNumber(waiting_tasks) && waiting_tasks->valuedouble >= 0) {
        target->waiting_tasks = (int)waiting_tasks->valuedouble;
    } else {
        target->waiting_tasks = 0;
    }
    if (cJSON_IsNumber(finished_tasks) && finished_tasks->valuedouble >= 0) {
        target->finished_tasks = (int)finished_tasks->valuedouble;
    } else {
        target->finished_tasks = 0;
    }
}

static void parse_provider_json(cJSON *state_root, cJSON *provider)
{
    char provider_key[16] = "";
    copy_json_string(provider, "id", provider_key, sizeof(provider_key));
    if (provider_key[0] == '\0') {
        copy_json_string(state_root, "active_provider", provider_key, sizeof(provider_key));
    }
    agent_provider_t provider_id = s_current_provider;
    if (provider_key[0] != '\0' && provider_from_key(provider_key, &provider_id)) {
        s_current_provider = provider_id;
    }

    provider_display_state_t *display_state = provider_display_state(provider_id);
    parse_provider_fields(provider, display_state);
    ESP_LOGI(TAG, "provider parsed key=%s status=%s q5=%s%d q7=%s%d stale=%d",
             provider_config(provider_id)->key,
             display_state->status,
             display_state->quota_5h_valid ? "" : "invalid:",
             display_state->quota_5h,
             display_state->quota_7d_valid ? "" : "invalid:",
             display_state->quota_7d,
             display_state->quota_stale);
}

static void parse_codex_json(cJSON *codex)
{
    provider_display_state_t *display_state = provider_display_state(PROVIDER_CODEX);
    parse_provider_fields(codex, display_state);
    ESP_LOGI(TAG, "codex parsed status=%s q5=%s%d q7=%s%d stale=%d",
             display_state->status,
             display_state->quota_5h_valid ? "" : "invalid:",
             display_state->quota_5h,
             display_state->quota_7d_valid ? "" : "invalid:",
             display_state->quota_7d,
             display_state->quota_stale);
}

static bool parse_state_json(const char *json)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        return false;
    }
    cJSON *state_root = root;
    cJSON *wrapped_state = cJSON_GetObjectItemCaseSensitive(root, "state");
    if (cJSON_IsObject(wrapped_state)) {
        state_root = wrapped_state;
    }

    copy_json_string(state_root, "time", s_state.time, sizeof(s_state.time));
    copy_json_string(state_root, "date", s_state.date, sizeof(s_state.date));
    copy_json_string(state_root, "weekday", s_state.weekday, sizeof(s_state.weekday));
    cJSON *wifi = cJSON_GetObjectItemCaseSensitive(state_root, "wifi");
    cJSON *ble = cJSON_GetObjectItemCaseSensitive(state_root, "ble");
    s_state.wifi = cJSON_IsBool(wifi) ? cJSON_IsTrue(wifi) : s_state.wifi;
    s_state.ble = cJSON_IsBool(ble) ? cJSON_IsTrue(ble) : s_state.ble;

    cJSON *provider = cJSON_GetObjectItemCaseSensitive(state_root, "provider");
    cJSON *codex = cJSON_GetObjectItemCaseSensitive(state_root, "codex");
    if (cJSON_IsObject(provider)) {
        parse_provider_json(state_root, provider);
    } else {
        char active_provider[16] = "";
        copy_json_string(state_root, "active_provider", active_provider, sizeof(active_provider));
        if (active_provider[0] != '\0') {
            set_current_provider_from_key(active_provider);
        }
    }
    if (cJSON_IsObject(codex)) {
        parse_codex_json(codex);
    }

    cJSON *alert = cJSON_GetObjectItemCaseSensitive(state_root, "alert");
    if (cJSON_IsObject(alert)) {
        copy_json_string(alert, "event_id", s_state.alert_event_id, sizeof(s_state.alert_event_id));
        copy_json_string(alert, "type", s_state.alert_type, sizeof(s_state.alert_type));
        copy_json_string(alert, "message", s_state.alert_message, sizeof(s_state.alert_message));
    }
    cJSON_Delete(root);
    return true;
}

static void poll_state(void)
{
    char response[1536] = {0};
    int battery_level = 0;
    if (vibe_board_battery_level(&battery_level) == ESP_OK) {
        s_state.battery = battery_level;
    }
    bool charging = false;
    bool usb_powered = false;
    bool power_read_ok = false;
    if (vibe_board_battery_charging(&charging) == ESP_OK) {
        s_state.battery_charging = charging;
        power_read_ok = true;
    }
    if (vibe_board_usb_powered(&usb_powered) == ESP_OK) {
        s_state.usb_powered = usb_powered;
        power_read_ok = true;
    }
    static bool last_power_logged = false;
    static bool last_charging = false;
    static bool last_usb_powered = false;
    if (power_read_ok &&
        (!last_power_logged ||
         last_charging != s_state.battery_charging ||
         last_usb_powered != s_state.usb_powered)) {
        ESP_LOGI(TAG, "power status battery=%d charging=%d usb=%d",
                 s_state.battery, s_state.battery_charging, s_state.usb_powered);
        last_power_logged = true;
        last_charging = s_state.battery_charging;
        last_usb_powered = s_state.usb_powered;
    }
    esp_err_t err = http_request("GET", VIBE_STICK_STATE_PATH, NULL, response, sizeof(response));
    if (err != ESP_OK || response[0] == '\0' || !parse_state_json(response)) {
        provider_display_state_t *display_state = current_provider_display_state();
        strlcpy(display_state->status, "OFFLINE", sizeof(display_state->status));
        s_state.wifi = s_wifi_connected;
        render_state();
        return;
    }
    render_state();
    maybe_handle_alert();
    maybe_handle_waiting_tasks();
}

static void post_simple_event(const char *event_name, const char *path)
{
    char body[96];
    snprintf(body, sizeof(body), "{\"event\":\"%s\",\"source\":\"sticks3\"}", event_name);
    char response[512] = {0};
    const char *target_path = path ? path : VIBE_STICK_EVENT_PATH;
    esp_err_t err = http_request("POST", target_path, body, response, sizeof(response));
    if (err == ESP_OK && response[0] != '\0' && parse_state_json(response)) {
        render_state();
    }
}

static bool parse_recording_session_id(const char *json, char *session_id, size_t session_id_len)
{
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        return false;
    }
    cJSON *recording = cJSON_GetObjectItemCaseSensitive(root, "recording");
    cJSON *sid = cJSON_IsObject(recording) ? cJSON_GetObjectItemCaseSensitive(recording, "session_id") : NULL;
    bool ok = false;
    if (cJSON_IsString(sid) && sid->valuestring && sid->valuestring[0] != '\0') {
        strlcpy(session_id, sid->valuestring, session_id_len);
        ok = true;
    }
    cJSON_Delete(root);
    return ok;
}

static bool is_recording_failure_status(const char *status)
{
    return strcmp(status, "transcription_failed") == 0 ||
           strcmp(status, "transcript_rejected") == 0 ||
           strcmp(status, "paste_failed") == 0 ||
           strcmp(status, "audio_failed") == 0 ||
           strcmp(status, "audio_skipped") == 0 ||
           strcmp(status, "start_failed") == 0 ||
           strcmp(status, "stop_failed") == 0;
}

static bool parse_recording_status(const char *json, char *status_text, size_t status_text_len)
{
    if (status_text_len > 0) {
        status_text[0] = '\0';
    }
    cJSON *root = cJSON_Parse(json);
    if (!root) {
        return false;
    }
    cJSON *recording = cJSON_GetObjectItemCaseSensitive(root, "recording");
    cJSON *status = cJSON_IsObject(recording) ?
        cJSON_GetObjectItemCaseSensitive(recording, "status") : NULL;
    bool ok = false;
    if (cJSON_IsString(status) && status->valuestring) {
        strlcpy(status_text, status->valuestring, status_text_len);
        ok = true;
    }
    cJSON_Delete(root);
    return ok;
}

static void generate_recording_session_id(char *session_id, size_t session_id_len)
{
    if (session_id_len < 33) {
        if (session_id_len > 0) {
            session_id[0] = '\0';
        }
        return;
    }
    static const char hex[] = "0123456789abcdef";
    for (int i = 0; i < 32; ++i) {
        uint32_t value = esp_random();
        session_id[i] = hex[value & 0x0f];
    }
    session_id[32] = '\0';
}

static void upload_recording_audio(void)
{
    size_t audio_len = 0;
    const uint8_t *audio = vibe_audio_data(&audio_len);
    if (!audio || audio_len == 0 || s_recording_session_id[0] == '\0') {
        ESP_LOGW(TAG, "skip audio upload audio=%p len=%u session=%s",
                 audio, (unsigned)audio_len, s_recording_session_id);
        return;
    }
    char path[96];
    snprintf(path, sizeof(path), "%s?session_id=%s", VIBE_STICK_RECORDING_AUDIO_PATH, s_recording_session_id);
    char response[768] = {0};
    esp_err_t err = http_post_binary(path, audio, audio_len, response, sizeof(response));
    if (err != ESP_OK) {
        ESP_LOGW(TAG, "audio upload failed: %s", esp_err_to_name(err));
        return;
    }
    if (response[0] != '\0' && parse_state_json(response)) {
        render_state();
    }
}

static void handle_recording_start(void)
{
    generate_recording_session_id(s_recording_session_id, sizeof(s_recording_session_id));
    if (s_recording_session_id[0] == '\0') {
        ESP_LOGW(TAG, "recording start failed: no session id");
        return;
    }

    esp_err_t audio_err = vibe_audio_start();
    if (audio_err != ESP_OK) {
        ESP_LOGW(TAG, "hardware recording start failed: %s", esp_err_to_name(audio_err));
        s_recording_session_id[0] = '\0';
        return;
    }
    show_recording_overlay("LISTENING", "RELEASE TO SEND", true);

    char body[192];
    snprintf(body, sizeof(body),
             "{\"event\":\"button_long_start\",\"source\":\"sticks3\","
             "\"audio_source\":\"sticks3_pcm\",\"session_id\":\"%s\"}",
             s_recording_session_id);
    char response[1024] = {0};
    esp_err_t err = http_request("POST", VIBE_STICK_RECORDING_START_PATH, body, response, sizeof(response));
    if (err == ESP_OK && response[0] != '\0') {
        char response_session_id[40] = {0};
        parse_recording_session_id(response, response_session_id, sizeof(response_session_id));
        if (response_session_id[0] != '\0' &&
            strcmp(response_session_id, s_recording_session_id) != 0) {
            ESP_LOGW(TAG, "bridge returned a different recording session id");
        }
        if (parse_state_json(response)) {
            render_state();
        }
    } else {
        ESP_LOGW(TAG, "recording start bridge request failed: %s", esp_err_to_name(err));
    }

}

static void handle_recording_stop(void)
{
    show_recording_overlay("SENDING", "", true);
    if (s_recording_session_id[0] == '\0') {
        (void)vibe_audio_stop();
        vibe_audio_clear();
        poll_state();
        show_recording_overlay(NULL, NULL, false);
        return;
    }

    esp_err_t audio_err = vibe_audio_stop();
    if (audio_err != ESP_OK) {
        ESP_LOGW(TAG, "hardware recording stop failed: %s", esp_err_to_name(audio_err));
    }

    upload_recording_audio();
    vibe_audio_clear();

    show_recording_overlay("TRANSCRIBING", "", true);
    const char *body =
        "{\"event\":\"button_long_stop\",\"source\":\"sticks3\",\"paste\":true,\"submit\":false}";
    char response[1024] = {0};
    esp_err_t err = http_request_timeout("POST", VIBE_STICK_RECORDING_STOP_PATH, body, response, sizeof(response), 30000);
    bool recording_failed = false;
    char recording_status[32] = {0};
    if (err == ESP_OK && response[0] != '\0') {
        if (parse_recording_status(response, recording_status, sizeof(recording_status))) {
            recording_failed = is_recording_failure_status(recording_status);
            if (recording_failed) {
                ESP_LOGW(TAG, "recording failed status=%s", recording_status);
            }
        }
        if (parse_state_json(response)) {
            render_state();
        }
    }
    if (err != ESP_OK || recording_failed) {
        ESP_LOGW(TAG, "recording stop bridge request failed: %s", esp_err_to_name(err));
        const char *title = (strcmp(recording_status, "audio_skipped") == 0 ||
                             strcmp(recording_status, "transcript_rejected") == 0)
            ? "NO SPEECH" : "FAILED";
        show_recording_overlay(title, "", true);
        vTaskDelay(pdMS_TO_TICKS(900));
    }
    s_recording_session_id[0] = '\0';
    poll_state();
    show_recording_overlay(NULL, NULL, false);
}

static void wifi_event_handler(void *arg, esp_event_base_t event_base,
                               int32_t event_id, void *event_data)
{
    (void)arg;
    (void)event_data;
    if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_START) {
        esp_wifi_connect();
    } else if (event_base == WIFI_EVENT && event_id == WIFI_EVENT_STA_DISCONNECTED) {
        s_wifi_connected = false;
        esp_wifi_connect();
        render_state();
    } else if (event_base == IP_EVENT && event_id == IP_EVENT_STA_GOT_IP) {
        s_wifi_connected = true;
        render_state();
        queue_event(VIBE_STICK_EVENT_POLL_STATE);
    }
}

static esp_err_t init_wifi(void)
{
    if (strlen(VIBE_STICK_WIFI_SSID) == 0) {
        ESP_LOGW(TAG, "VIBE_STICK_WIFI_SSID is empty; Wi-Fi disabled");
        return ESP_OK;
    }
    ESP_RETURN_ON_ERROR(esp_netif_init(), TAG, "netif init");
    ESP_RETURN_ON_ERROR(esp_event_loop_create_default(), TAG, "event loop");
    esp_netif_create_default_wifi_sta();
    wifi_init_config_t cfg = WIFI_INIT_CONFIG_DEFAULT();
    ESP_RETURN_ON_ERROR(esp_wifi_init(&cfg), TAG, "wifi init");
    ESP_ERROR_CHECK(esp_event_handler_register(WIFI_EVENT, ESP_EVENT_ANY_ID, &wifi_event_handler, NULL));
    ESP_ERROR_CHECK(esp_event_handler_register(IP_EVENT, IP_EVENT_STA_GOT_IP, &wifi_event_handler, NULL));
    wifi_config_t wifi_config = {0};
    strlcpy((char *)wifi_config.sta.ssid, VIBE_STICK_WIFI_SSID, sizeof(wifi_config.sta.ssid));
    strlcpy((char *)wifi_config.sta.password, VIBE_STICK_WIFI_PASSWORD, sizeof(wifi_config.sta.password));
    wifi_config.sta.threshold.authmode = WIFI_AUTH_WPA2_PSK;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG, "wifi mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &wifi_config), TAG, "wifi config");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "wifi start");
    return ESP_OK;
}

static void button_single_click_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    queue_event(VIBE_STICK_EVENT_SHORT_PRESS);
}

static void button_double_click_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    queue_event(VIBE_STICK_EVENT_DOUBLE_CLICK);
}

static void side_button_single_click_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    queue_event(VIBE_STICK_EVENT_SIDE_SHORT);
}

static void side_button_double_click_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    queue_event(VIBE_STICK_EVENT_SIDE_DOUBLE);
}

static void side_button_triple_click_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    ESP_LOGI(TAG, "side button triple click detected");
    queue_event(VIBE_STICK_EVENT_SIDE_TRIPLE);
}

static void side_button_long_start_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    s_side_long_press_active = true;
}

static void side_button_up_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    if (s_side_long_press_active) {
        s_side_long_press_active = false;
        queue_event(VIBE_STICK_EVENT_SIDE_LONG);
    }
}

static void button_long_start_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    s_long_press_active = true;
    queue_event(VIBE_STICK_EVENT_LONG_START);
}

static void button_up_cb(void *button_handle, void *usr_data)
{
    (void)button_handle;
    (void)usr_data;
    if (s_long_press_active) {
        s_long_press_active = false;
        queue_event(VIBE_STICK_EVENT_LONG_STOP);
    }
}

static esp_err_t init_button(void)
{
    button_handle_t button = NULL;
    button_handle_t side_button = NULL;
    const button_config_t button_config = {0};
    const button_config_t side_button_config = {
        /*
         * The component default is only 180 ms between clicks, which makes a
         * deliberate three-click gesture very easy to split into unrelated
         * single/double clicks. Keep the front button unchanged, but give the
         * side button a human-friendly multi-click window.
         */
        .short_press_time = 380,
        .long_press_time = 500,
    };
    const button_gpio_config_t gpio_config = {
        .gpio_num = PIN_BUTTON_FRONT,
        .active_level = 0,
        .enable_power_save = true,
    };
    ESP_RETURN_ON_ERROR(iot_button_new_gpio_device(&button_config, &gpio_config, &button), TAG, "button");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(button, BUTTON_SINGLE_CLICK, NULL, button_single_click_cb, NULL),
                        TAG, "button single");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(button, BUTTON_DOUBLE_CLICK, NULL, button_double_click_cb, NULL),
                        TAG, "button double");
    button_event_args_t long_press_args = {
        .long_press = {
            .press_time = 450,
        },
    };
    ESP_RETURN_ON_ERROR(iot_button_register_cb(button, BUTTON_LONG_PRESS_START, &long_press_args, button_long_start_cb, NULL),
                        TAG, "button long");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(button, BUTTON_PRESS_UP, NULL, button_up_cb, NULL),
                        TAG, "button up");

    const button_gpio_config_t side_gpio_config = {
        .gpio_num = PIN_BUTTON_SIDE,
        .active_level = 0,
        .enable_power_save = false,
    };
    ESP_RETURN_ON_ERROR(iot_button_new_gpio_device(&side_button_config, &side_gpio_config, &side_button), TAG, "side button");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(side_button, BUTTON_SINGLE_CLICK, NULL,
                                               side_button_single_click_cb, NULL),
                        TAG, "side button single");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(side_button, BUTTON_DOUBLE_CLICK, NULL,
                                               side_button_double_click_cb, NULL),
                        TAG, "side button double");
    button_event_args_t triple_click_args = {
        .multiple_clicks = {
            .clicks = 3,
        },
    };
    ESP_RETURN_ON_ERROR(iot_button_register_cb(
                            side_button, BUTTON_MULTIPLE_CLICK,
                            &triple_click_args,
                            side_button_triple_click_cb, NULL),
                        TAG, "side button triple");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(side_button, BUTTON_LONG_PRESS_START,
                                               &long_press_args, side_button_long_start_cb, NULL),
                        TAG, "side button long");
    ESP_RETURN_ON_ERROR(iot_button_register_cb(side_button, BUTTON_PRESS_UP, NULL,
                                               side_button_up_cb, NULL),
                        TAG, "side button up");
    return ESP_OK;
}

static void orientation_task(void *arg)
{
    (void)arg;
    bool candidate_landscape = false;
    bool candidate_landscape_reverse = false;
    int stable_samples = 0;
    int log_countdown = 0;
    while (true) {
        vTaskDelay(pdMS_TO_TICKS(ORIENTATION_SAMPLE_MS));
        if (!s_orientation_enabled ||
            s_recording_overlay_visible || vibe_audio_is_recording()) {
            stable_samples = 0;
            continue;
        }
        int16_t x = 0;
        int16_t y = 0;
        int16_t z = 0;
        if (vibe_board_accel_read(&x, &y, &z) != ESP_OK) {
            continue;
        }
        int ax = abs((int)x);
        int ay = abs((int)y);
        int az = abs((int)z);
        int in_plane = ax > ay ? ax : ay;
        int cross_plane = ax > ay ? ay : ax;
        if (in_plane < 8000 || in_plane < az + 2500 ||
            in_plane < cross_plane + 3000) {
            stable_samples = 0;
            continue;
        }
        // StickS3's BMI270 Y axis follows the display's long edge:
        // Y-dominant gravity is landscape, X-dominant gravity is portrait.
        // Keep this mapping absolute so the initial device pose cannot reverse it.
        bool wants_landscape = ay > ax;
        // Positive Y is the already validated button-on-right landscape pose.
        // Negative Y is the opposite 90-degree pose and needs a 180-degree LCD
        // mirror so the same landscape UI remains upright.
        bool wants_landscape_reverse = wants_landscape && y < 0;
        if (wants_landscape != candidate_landscape ||
            wants_landscape_reverse != candidate_landscape_reverse) {
            candidate_landscape = wants_landscape;
            candidate_landscape_reverse = wants_landscape_reverse;
            stable_samples = 1;
        } else if (stable_samples < ORIENTATION_STABLE_SAMPLES) {
            stable_samples++;
        }
        if (++log_countdown >= 20) {
            log_countdown = 0;
            ESP_LOGI(TAG, "orientation accel=%d,%d,%d target=%s current=%s",
                     x, y, z,
                     wants_landscape
                         ? (wants_landscape_reverse
                                ? "landscape-left"
                                : "landscape-right")
                         : "portrait",
                     s_landscape_active
                         ? (s_landscape_reverse
                                ? "landscape-left"
                                : "landscape-right")
                         : "portrait");
        }
        if (stable_samples >= ORIENTATION_STABLE_SAMPLES &&
            (wants_landscape != s_landscape_active ||
             (wants_landscape &&
              wants_landscape_reverse != s_landscape_reverse))) {
            stable_samples = 0;
            switch_display_orientation(
                wants_landscape,
                wants_landscape_reverse);
        }
    }
}

static void app_task(void *arg)
{
    (void)arg;
    agent_event_t event;
    int64_t last_poll = 0;
    while (true) {
        int64_t now_ms = esp_timer_get_time() / 1000;
        if (s_wifi_connected && now_ms - last_poll >= VIBE_STICK_STATE_POLL_MS) {
            last_poll = now_ms;
            poll_state();
        }
        if (xQueueReceive(s_event_queue, &event, pdMS_TO_TICKS(100)) != pdTRUE) {
            continue;
        }
        if (event.type == VIBE_STICK_EVENT_SIDE_TRIPLE) {
            const esp_partition_t *running = esp_ota_get_running_partition();
            const esp_partition_t *next = esp_partition_find_first(
                ESP_PARTITION_TYPE_APP,
                ESP_PARTITION_SUBTYPE_APP_OTA_0,
                NULL);
            if (!running || !next || next == running) {
                ESP_LOGE(TAG, "hourglass partition ota_0 unavailable");
                continue;
            }
            esp_err_t err = esp_ota_set_boot_partition(next);
            if (err != ESP_OK) {
                ESP_LOGE(TAG, "app switch failed: %s",
                         esp_err_to_name(err));
                continue;
            }
            ESP_LOGI(TAG, "switch app %s -> %s",
                     running->label, next->label);
            vTaskDelay(pdMS_TO_TICKS(120));
            esp_restart();
        }
        switch (event.type) {
        case VIBE_STICK_EVENT_POLL_STATE:
            poll_state();
            break;
        case VIBE_STICK_EVENT_SHORT_PRESS:
            post_simple_event("front_short", NULL);
            break;
        case VIBE_STICK_EVENT_DOUBLE_CLICK:
            post_simple_event("front_double", VIBE_STICK_QUOTA_REFRESH_PATH);
            poll_state();
            break;
        case VIBE_STICK_EVENT_SIDE_SHORT:
            post_simple_event("side_short", NULL);
            break;
        case VIBE_STICK_EVENT_SIDE_DOUBLE:
            post_simple_event("side_double", NULL);
            break;
        case VIBE_STICK_EVENT_SIDE_LONG:
            post_simple_event("side_long", NULL);
            break;
        case VIBE_STICK_EVENT_SIDE_TRIPLE:
            break;
        case VIBE_STICK_EVENT_LONG_START:
            handle_recording_start();
            break;
        case VIBE_STICK_EVENT_LONG_STOP:
            handle_recording_stop();
            break;
        }
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "boot %s version=%s build=%s %s transport=%s",
             FIRMWARE_NAME, FIRMWARE_VERSION, __DATE__, __TIME__, TRANSPORT);
    esp_err_t nvs = nvs_flash_init();
    if (nvs == ESP_ERR_NVS_NO_FREE_PAGES || nvs == ESP_ERR_NVS_NEW_VERSION_FOUND) {
        ESP_ERROR_CHECK(nvs_flash_erase());
        ESP_ERROR_CHECK(nvs_flash_init());
    } else {
        ESP_ERROR_CHECK(nvs);
    }

    ESP_ERROR_CHECK_WITHOUT_ABORT(vibe_board_init_power());
    esp_err_t imu_status = vibe_board_imu_init();
    if (imu_status != ESP_OK) {
        ESP_LOGW(TAG, "orientation switching disabled: %s", esp_err_to_name(imu_status));
    }
    s_event_queue = xQueueCreate(10, sizeof(agent_event_t));
    s_lvgl_lock = xSemaphoreCreateMutex();
    ESP_ERROR_CHECK(init_display());
    lvgl_lock();
    create_ui();
    lvgl_unlock();
    render_state();
    ESP_ERROR_CHECK(init_button());
    ESP_ERROR_CHECK(vibe_audio_init());
    ESP_ERROR_CHECK(init_wifi());
    xTaskCreate(app_task, "agent_app", 6144, NULL, 4, NULL);
    if (imu_status == ESP_OK) {
        xTaskCreate(orientation_task, "orientation", 4096, NULL, 3, NULL);
    }
}
