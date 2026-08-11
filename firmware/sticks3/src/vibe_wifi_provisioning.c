#include "vibe_wifi_provisioning.h"

#include <ctype.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "esp_check.h"
#include "esp_event.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_netif.h"
#include "esp_random.h"
#include "esp_system.h"
#include "esp_wifi.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "nvs.h"

#define WIFI_NVS_NAMESPACE "vibewifi"
#define WIFI_NVS_SSID_KEY "ssid"
#define WIFI_NVS_PASSWORD_KEY "pass"
#define WIFI_NVS_BRIDGE_TOKEN_KEY "bridge_token"
#define WIFI_NVS_PREVIOUS_SSID_KEY "prev_ssid"
#define WIFI_NVS_PREVIOUS_PASSWORD_KEY "prev_pass"
#define WIFI_NVS_SETUP_REQUEST_KEY "setup"
#define WIFI_SETUP_MAX_APS 12
#define WIFI_SETUP_HTML_CAPACITY 7168

static const char *TAG = "vibe_wifi";
static httpd_handle_t s_http_server;

static void generate_ap_password(char *password, size_t capacity)
{
    if (capacity < 9) {
        if (capacity > 0) {
            password[0] = '\0';
        }
        return;
    }
    for (size_t index = 0; index < 8; ++index) {
        password[index] = (char)('0' + (esp_random() % 10));
    }
    password[8] = '\0';
}

static bool bridge_token_is_valid(const char *token)
{
    size_t length = strnlen(token, VIBE_BRIDGE_TOKEN_MAX_LEN + 1);
    if (length < 16 || length > VIBE_BRIDGE_TOKEN_MAX_LEN) {
        return false;
    }
    for (size_t index = 0; index < length; ++index) {
        if (!isalnum((unsigned char)token[index]) && token[index] != '-' &&
            token[index] != '_' && token[index] != '.') {
            return false;
        }
    }
    return true;
}

static esp_err_t init_network_stack(void)
{
    esp_err_t err = esp_netif_init();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    err = esp_event_loop_create_default();
    if (err != ESP_OK && err != ESP_ERR_INVALID_STATE) {
        return err;
    }
    wifi_init_config_t config = WIFI_INIT_CONFIG_DEFAULT();
    err = esp_wifi_init(&config);
    if (err == ESP_ERR_WIFI_INIT_STATE) {
        return ESP_OK;
    }
    return err;
}

bool vibe_wifi_credentials_load(vibe_wifi_credentials_t *credentials)
{
    if (credentials == NULL) {
        return false;
    }
    memset(credentials, 0, sizeof(*credentials));
    nvs_handle_t handle;
    if (nvs_open(WIFI_NVS_NAMESPACE, NVS_READONLY, &handle) != ESP_OK) {
        return false;
    }
    size_t ssid_length = sizeof(credentials->ssid);
    size_t password_length = sizeof(credentials->password);
    esp_err_t ssid_status = nvs_get_str(handle, WIFI_NVS_SSID_KEY,
                                        credentials->ssid, &ssid_length);
    esp_err_t password_status = nvs_get_str(handle, WIFI_NVS_PASSWORD_KEY,
                                            credentials->password,
                                            &password_length);
    size_t bridge_token_length = sizeof(credentials->bridge_token);
    esp_err_t bridge_token_status = nvs_get_str(
        handle, WIFI_NVS_BRIDGE_TOKEN_KEY, credentials->bridge_token,
        &bridge_token_length);
    nvs_close(handle);
    if (ssid_status != ESP_OK || password_status != ESP_OK ||
        credentials->ssid[0] == '\0') {
        memset(credentials, 0, sizeof(*credentials));
        return false;
    }
    if (bridge_token_status != ESP_OK) {
        credentials->bridge_token[0] = '\0';
    }
    return true;
}

esp_err_t vibe_wifi_credentials_save(const vibe_wifi_credentials_t *credentials)
{
    if (credentials == NULL || credentials->ssid[0] == '\0' ||
        strnlen(credentials->ssid, sizeof(credentials->ssid)) >
            VIBE_WIFI_SSID_MAX_LEN ||
        strnlen(credentials->password, sizeof(credentials->password)) >
            VIBE_WIFI_PASSWORD_MAX_LEN ||
        strnlen(credentials->bridge_token, sizeof(credentials->bridge_token)) >
            VIBE_BRIDGE_TOKEN_MAX_LEN ||
        (credentials->bridge_token[0] != '\0' &&
         !bridge_token_is_valid(credentials->bridge_token))) {
        return ESP_ERR_INVALID_ARG;
    }
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle),
                        TAG, "open Wi-Fi NVS");
    vibe_wifi_credentials_t active = {0};
    size_t active_ssid_length = sizeof(active.ssid);
    size_t active_password_length = sizeof(active.password);
    esp_err_t active_ssid_status = nvs_get_str(
        handle, WIFI_NVS_SSID_KEY, active.ssid, &active_ssid_length);
    esp_err_t active_password_status = nvs_get_str(
        handle, WIFI_NVS_PASSWORD_KEY, active.password, &active_password_length);
    esp_err_t err = ESP_OK;
    if (active_ssid_status == ESP_OK && active_password_status == ESP_OK &&
        active.ssid[0] != '\0' &&
        (strcmp(active.ssid, credentials->ssid) != 0 ||
         strcmp(active.password, credentials->password) != 0)) {
        err = nvs_set_str(handle, WIFI_NVS_PREVIOUS_SSID_KEY, active.ssid);
        if (err == ESP_OK) {
            err = nvs_set_str(handle, WIFI_NVS_PREVIOUS_PASSWORD_KEY,
                              active.password);
        }
    } else {
        (void)nvs_erase_key(handle, WIFI_NVS_PREVIOUS_SSID_KEY);
        (void)nvs_erase_key(handle, WIFI_NVS_PREVIOUS_PASSWORD_KEY);
    }
    memset(active.password, 0, sizeof(active.password));
    if (err == ESP_OK) {
        err = nvs_set_str(handle, WIFI_NVS_SSID_KEY, credentials->ssid);
    }
    if (err == ESP_OK) {
        err = nvs_set_str(handle, WIFI_NVS_PASSWORD_KEY, credentials->password);
    }
    if (err == ESP_OK && credentials->bridge_token[0] != '\0') {
        err = nvs_set_str(handle, WIFI_NVS_BRIDGE_TOKEN_KEY,
                          credentials->bridge_token);
    }
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err;
}

esp_err_t vibe_wifi_credentials_restore_previous(void)
{
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle),
                        TAG, "open Wi-Fi NVS for recovery");
    vibe_wifi_credentials_t previous = {0};
    size_t ssid_length = sizeof(previous.ssid);
    size_t password_length = sizeof(previous.password);
    esp_err_t err = nvs_get_str(handle, WIFI_NVS_PREVIOUS_SSID_KEY,
                                previous.ssid, &ssid_length);
    if (err == ESP_OK) {
        err = nvs_get_str(handle, WIFI_NVS_PREVIOUS_PASSWORD_KEY,
                          previous.password, &password_length);
    }
    if (err == ESP_OK && previous.ssid[0] != '\0') {
        err = nvs_set_str(handle, WIFI_NVS_SSID_KEY, previous.ssid);
    }
    if (err == ESP_OK && previous.ssid[0] != '\0') {
        err = nvs_set_str(handle, WIFI_NVS_PASSWORD_KEY, previous.password);
    }
    if (err == ESP_OK) {
        (void)nvs_erase_key(handle, WIFI_NVS_PREVIOUS_SSID_KEY);
        (void)nvs_erase_key(handle, WIFI_NVS_PREVIOUS_PASSWORD_KEY);
        err = nvs_commit(handle);
    }
    memset(previous.password, 0, sizeof(previous.password));
    nvs_close(handle);
    return err;
}

void vibe_wifi_credentials_confirm(void)
{
    nvs_handle_t handle;
    if (nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) {
        return;
    }
    esp_err_t ssid_status = nvs_erase_key(handle,
                                          WIFI_NVS_PREVIOUS_SSID_KEY);
    esp_err_t password_status = nvs_erase_key(
        handle, WIFI_NVS_PREVIOUS_PASSWORD_KEY);
    if ((ssid_status == ESP_OK || ssid_status == ESP_ERR_NVS_NOT_FOUND) &&
        (password_status == ESP_OK ||
         password_status == ESP_ERR_NVS_NOT_FOUND)) {
        (void)nvs_commit(handle);
    }
    nvs_close(handle);
}

esp_err_t vibe_wifi_request_setup_on_next_boot(void)
{
    nvs_handle_t handle;
    ESP_RETURN_ON_ERROR(nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle),
                        TAG, "open Wi-Fi NVS for setup request");
    esp_err_t err = nvs_set_u8(handle, WIFI_NVS_SETUP_REQUEST_KEY, 1);
    if (err == ESP_OK) {
        err = nvs_commit(handle);
    }
    nvs_close(handle);
    return err;
}

bool vibe_wifi_consume_setup_request(void)
{
    nvs_handle_t handle;
    if (nvs_open(WIFI_NVS_NAMESPACE, NVS_READWRITE, &handle) != ESP_OK) {
        return false;
    }
    uint8_t requested = 0;
    esp_err_t err = nvs_get_u8(handle, WIFI_NVS_SETUP_REQUEST_KEY, &requested);
    if (err == ESP_OK && requested == 1) {
        (void)nvs_erase_key(handle, WIFI_NVS_SETUP_REQUEST_KEY);
        (void)nvs_commit(handle);
    }
    nvs_close(handle);
    return err == ESP_OK && requested == 1;
}

esp_err_t vibe_wifi_start_station(const vibe_wifi_credentials_t *credentials)
{
    if (credentials == NULL || credentials->ssid[0] == '\0') {
        return ESP_ERR_INVALID_ARG;
    }
    ESP_RETURN_ON_ERROR(init_network_stack(), TAG, "network stack");
    esp_netif_create_default_wifi_sta();
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG,
                        "Wi-Fi RAM storage");
    wifi_config_t config = {0};
    strlcpy((char *)config.sta.ssid, credentials->ssid,
            sizeof(config.sta.ssid));
    strlcpy((char *)config.sta.password, credentials->password,
            sizeof(config.sta.password));
    config.sta.threshold.authmode = WIFI_AUTH_OPEN;
    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_STA), TAG,
                        "station mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_STA, &config), TAG,
                        "station config");
    return esp_wifi_start();
}

static bool append_html(char *html, size_t capacity, const char *text)
{
    size_t used = strlen(html);
    size_t remaining = capacity - used;
    if (remaining <= 1) {
        return false;
    }
    int written = snprintf(html + used, remaining, "%s", text);
    return written >= 0 && (size_t)written < remaining;
}

static void append_escaped(char *html, size_t capacity, const char *text)
{
    for (const unsigned char *cursor = (const unsigned char *)text;
         *cursor != '\0'; ++cursor) {
        const char *escaped = NULL;
        switch (*cursor) {
        case '&': escaped = "&amp;"; break;
        case '<': escaped = "&lt;"; break;
        case '>': escaped = "&gt;"; break;
        case '\"': escaped = "&quot;"; break;
        case '\'': escaped = "&#39;"; break;
        default: break;
        }
        char single[2] = {(char)*cursor, '\0'};
        if (!append_html(html, capacity, escaped != NULL ? escaped : single)) {
            return;
        }
    }
}

static esp_err_t setup_page_handler(httpd_req_t *request)
{
    wifi_ap_record_t access_points[WIFI_SETUP_MAX_APS] = {0};
    uint16_t access_point_count = WIFI_SETUP_MAX_APS;
    wifi_scan_config_t scan = {
        .show_hidden = false,
    };
    if (esp_wifi_scan_start(&scan, true) != ESP_OK ||
        esp_wifi_scan_get_ap_records(&access_point_count, access_points) != ESP_OK) {
        access_point_count = 0;
    }

    char *html = calloc(1, WIFI_SETUP_HTML_CAPACITY);
    if (html == NULL) {
        return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   "Out of memory");
    }
    append_html(html, WIFI_SETUP_HTML_CAPACITY,
                "<!doctype html><html lang=zh-CN><head><meta charset=utf-8>"
                "<meta name=viewport content='width=device-width,initial-scale=1'>"
                "<title>VibeStick Codex Wi-Fi</title><style>"
                "body{font-family:-apple-system,sans-serif;background:#111827;"
                "color:#f9fafb;margin:0;padding:20px}.card{max-width:520px;"
                "margin:auto;background:#1f2937;padding:22px;border-radius:18px}"
                "h2{margin-top:0}label{display:block;margin-top:16px;color:#d1d5db}"
                "select,input,button{box-sizing:border-box;width:100%;padding:12px;"
                "margin-top:7px;border-radius:10px;border:1px solid #4b5563;"
                "font:inherit}button{background:#2563eb;color:white;border:0;"
                "font-weight:700}.note{font-size:13px;color:#9ca3af;line-height:1.5}"
                "</style></head><body><div class=card><h2>连接新的 Wi-Fi</h2>"
                "<p class=note>请选择与运行 VibeStick Bridge 的电脑相同的 2.4 GHz "
                "网络。保存成功后设备会自动重启。</p><form method=post action=/save>"
                "<label>附近的 Wi-Fi</label>"
                "<select name=ssid><option value=''>请选择附近的 2.4GHz Wi-Fi</option>");
    for (uint16_t index = 0; index < access_point_count; ++index) {
        if (access_points[index].ssid[0] == '\0') {
            continue;
        }
        bool duplicate = false;
        for (uint16_t previous = 0; previous < index; ++previous) {
            if (strcmp((const char *)access_points[previous].ssid,
                       (const char *)access_points[index].ssid) == 0) {
                duplicate = true;
                break;
            }
        }
        if (duplicate) {
            continue;
        }
        append_html(html, WIFI_SETUP_HTML_CAPACITY, "<option value='");
        append_escaped(html, WIFI_SETUP_HTML_CAPACITY,
                       (const char *)access_points[index].ssid);
        append_html(html, WIFI_SETUP_HTML_CAPACITY, "'>");
        append_escaped(html, WIFI_SETUP_HTML_CAPACITY,
                       (const char *)access_points[index].ssid);
        append_html(html, WIFI_SETUP_HTML_CAPACITY, "</option>");
    }
    append_html(html, WIFI_SETUP_HTML_CAPACITY,
                "</select><label>隐藏网络（可选）</label>"
                "<input name=manual_ssid maxlength=32 "
                "placeholder='列表中没有时手动输入'>"
                "<label>Wi-Fi 密码</label>"
                "<input name=password type=password maxlength=64 autocomplete=current-password>"
                "<label>Bridge 配对码</label>"
                "<input name=bridge_token type=password maxlength=64 "
                "autocomplete=off placeholder='从电脑语音设置页复制'>"
                "<p class=note>已配对设备换 Wi-Fi 时可留空以保留原配对码。</p>"
                "<button type=submit>保存并重启</button></form>"
                "<p class=note>密码只保存在设备本地，不会显示在日志中。</p>"
                "</div></body></html>");
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    esp_err_t result = httpd_resp_send(request, html, HTTPD_RESP_USE_STRLEN);
    free(html);
    return result;
}

static int hex_value(char value)
{
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}

static bool url_decode(char *destination, size_t capacity, const char *source)
{
    size_t used = 0;
    while (*source != '\0' && used + 1 < capacity) {
        if (*source == '+' ) {
            destination[used++] = ' ';
            ++source;
        } else if (*source == '%' && source[1] != '\0' && source[2] != '\0') {
            int high = hex_value(source[1]);
            int low = hex_value(source[2]);
            if (high >= 0 && low >= 0) {
                destination[used++] = (char)((high << 4) | low);
                source += 3;
            } else {
                destination[used++] = *source++;
            }
        } else {
            destination[used++] = *source++;
        }
    }
    destination[used] = '\0';
    return *source == '\0';
}

static bool form_value(const char *body, const char *name, char *destination,
                       size_t capacity)
{
    size_t name_length = strlen(name);
    const char *cursor = body;
    while (cursor != NULL && *cursor != '\0') {
        if (strncmp(cursor, name, name_length) == 0 && cursor[name_length] == '=') {
            const char *value = cursor + name_length + 1;
            const char *end = strchr(value, '&');
            size_t encoded_length = end != NULL ? (size_t)(end - value) : strlen(value);
            char encoded[VIBE_WIFI_PASSWORD_MAX_LEN * 3 + 1];
            if (encoded_length >= sizeof(encoded)) {
                return false;
            }
            memcpy(encoded, value, encoded_length);
            encoded[encoded_length] = '\0';
            return url_decode(destination, capacity, encoded);
        }
        cursor = strchr(cursor, '&');
        if (cursor != NULL) ++cursor;
    }
    return false;
}

static void restart_task(void *argument)
{
    (void)argument;
    vTaskDelay(pdMS_TO_TICKS(1200));
    esp_restart();
}

static esp_err_t save_handler(httpd_req_t *request)
{
    if (request->content_len <= 0 || request->content_len > 512) {
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "Invalid request");
    }
    char body[513] = {0};
    size_t total_received = 0;
    while (total_received < (size_t)request->content_len) {
        int received = httpd_req_recv(request, body + total_received,
                                      request->content_len - total_received);
        if (received <= 0) {
            memset(body, 0, sizeof(body));
            return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                       "Could not read request");
        }
        total_received += (size_t)received;
    }
    body[total_received] = '\0';
    vibe_wifi_credentials_t credentials = {0};
    char selected_ssid[VIBE_WIFI_SSID_MAX_LEN + 1] = {0};
    char manual_ssid[VIBE_WIFI_SSID_MAX_LEN + 1] = {0};
    if (!form_value(body, "ssid", selected_ssid,
                    sizeof(selected_ssid)) ||
        !form_value(body, "manual_ssid", manual_ssid,
                    sizeof(manual_ssid)) ||
        !form_value(body, "password", credentials.password,
                    sizeof(credentials.password)) ||
        !form_value(body, "bridge_token", credentials.bridge_token,
                    sizeof(credentials.bridge_token))) {
        memset(&credentials, 0, sizeof(credentials));
        memset(body, 0, sizeof(body));
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "Invalid Wi-Fi settings");
    }
    strlcpy(credentials.ssid,
            manual_ssid[0] != '\0' ? manual_ssid : selected_ssid,
            sizeof(credentials.ssid));
    if (credentials.ssid[0] == '\0') {
        memset(&credentials, 0, sizeof(credentials));
        memset(body, 0, sizeof(body));
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "Wi-Fi name is required");
    }
    if (credentials.bridge_token[0] == '\0') {
        vibe_wifi_credentials_t existing = {0};
        if (vibe_wifi_credentials_load(&existing)) {
            strlcpy(credentials.bridge_token, existing.bridge_token,
                    sizeof(credentials.bridge_token));
        }
        memset(&existing, 0, sizeof(existing));
    }
    if (!bridge_token_is_valid(credentials.bridge_token)) {
        memset(credentials.password, 0, sizeof(credentials.password));
        memset(body, 0, sizeof(body));
        return httpd_resp_send_err(request, HTTPD_400_BAD_REQUEST,
                                   "A valid Bridge pairing token is required");
    }
    esp_err_t err = vibe_wifi_credentials_save(&credentials);
    memset(credentials.password, 0, sizeof(credentials.password));
    memset(credentials.bridge_token, 0, sizeof(credentials.bridge_token));
    memset(body, 0, sizeof(body));
    if (err != ESP_OK) {
        return httpd_resp_send_err(request, HTTPD_500_INTERNAL_SERVER_ERROR,
                                   "Could not save Wi-Fi settings");
    }
    httpd_resp_set_type(request, "text/html; charset=utf-8");
    httpd_resp_set_hdr(request, "Cache-Control", "no-store");
    httpd_resp_sendstr(request,
                       "<!doctype html><meta charset=utf-8><meta name=viewport "
                       "content='width=device-width'><body style='font-family:sans-serif;"
                       "padding:24px'><h2>已保存</h2><p>VibeStick 正在重启并连接新网络。</p>");
    xTaskCreate(restart_task, "wifi_restart", 2048, NULL, 5, NULL);
    return ESP_OK;
}

esp_err_t vibe_wifi_start_provisioning(vibe_wifi_setup_display_cb_t display_cb)
{
    ESP_RETURN_ON_ERROR(init_network_stack(), TAG, "network stack");
    esp_netif_create_default_wifi_ap();
    esp_netif_create_default_wifi_sta();
    ESP_RETURN_ON_ERROR(esp_wifi_set_storage(WIFI_STORAGE_RAM), TAG,
                        "Wi-Fi RAM storage");

    uint32_t random_value = esp_random();
    char ap_ssid[33];
    char ap_password[16];
    snprintf(ap_ssid, sizeof(ap_ssid), "VibeStick-Codex-%04lX",
             (unsigned long)(random_value & 0xffff));
    generate_ap_password(ap_password, sizeof(ap_password));
    wifi_config_t ap_config = {0};
    strlcpy((char *)ap_config.ap.ssid, ap_ssid, sizeof(ap_config.ap.ssid));
    strlcpy((char *)ap_config.ap.password, ap_password,
            sizeof(ap_config.ap.password));
    ap_config.ap.ssid_len = strlen(ap_ssid);
    ap_config.ap.channel = 1;
    ap_config.ap.max_connection = 2;
    ap_config.ap.authmode = WIFI_AUTH_WPA2_PSK;

    ESP_RETURN_ON_ERROR(esp_wifi_set_mode(WIFI_MODE_APSTA), TAG,
                        "setup AP mode");
    ESP_RETURN_ON_ERROR(esp_wifi_set_config(WIFI_IF_AP, &ap_config), TAG,
                        "setup AP config");
    ESP_RETURN_ON_ERROR(esp_wifi_start(), TAG, "setup AP start");

    httpd_config_t server_config = HTTPD_DEFAULT_CONFIG();
    server_config.max_uri_handlers = 4;
    ESP_RETURN_ON_ERROR(httpd_start(&s_http_server, &server_config), TAG,
                        "setup web server");
    const httpd_uri_t root = {
        .uri = "/", .method = HTTP_GET, .handler = setup_page_handler,
    };
    const httpd_uri_t save = {
        .uri = "/save", .method = HTTP_POST, .handler = save_handler,
    };
    const httpd_uri_t android_probe = {
        .uri = "/generate_204", .method = HTTP_GET,
        .handler = setup_page_handler,
    };
    const httpd_uri_t apple_probe = {
        .uri = "/hotspot-detect.html", .method = HTTP_GET,
        .handler = setup_page_handler,
    };
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_http_server, &root), TAG,
                        "setup page");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_http_server, &save), TAG,
                        "setup save");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_http_server,
                                                   &android_probe), TAG,
                        "Android captive portal probe");
    ESP_RETURN_ON_ERROR(httpd_register_uri_handler(s_http_server,
                                                   &apple_probe), TAG,
                        "Apple captive portal probe");
    if (display_cb != NULL) {
        display_cb(ap_ssid, ap_password);
    }
    ESP_LOGI(TAG, "Wi-Fi setup mode active; open 192.168.4.1");
    return ESP_OK;
}
