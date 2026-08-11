#pragma once

#include <stdbool.h>
#include <stddef.h>

#include "esp_err.h"

#define VIBE_WIFI_SSID_MAX_LEN 32
#define VIBE_WIFI_PASSWORD_MAX_LEN 64
#define VIBE_BRIDGE_TOKEN_MAX_LEN 64

typedef struct {
    char ssid[VIBE_WIFI_SSID_MAX_LEN + 1];
    char password[VIBE_WIFI_PASSWORD_MAX_LEN + 1];
    char bridge_token[VIBE_BRIDGE_TOKEN_MAX_LEN + 1];
} vibe_wifi_credentials_t;

typedef void (*vibe_wifi_setup_display_cb_t)(const char *ap_ssid,
                                              const char *ap_password);

bool vibe_wifi_credentials_load(vibe_wifi_credentials_t *credentials);
esp_err_t vibe_wifi_credentials_save(const vibe_wifi_credentials_t *credentials);
esp_err_t vibe_wifi_credentials_restore_previous(void);
void vibe_wifi_credentials_confirm(void);
esp_err_t vibe_wifi_request_setup_on_next_boot(void);
bool vibe_wifi_consume_setup_request(void);
esp_err_t vibe_wifi_start_station(const vibe_wifi_credentials_t *credentials);
esp_err_t vibe_wifi_start_provisioning(vibe_wifi_setup_display_cb_t display_cb);
