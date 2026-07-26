idf_component_register(
    SRCS "main.c" "vibe_board.c" "vibe_audio.c" "../generated/vibe_stick_cn_16.c" "../generated/vibe_stick_ui_assets.c"
         "../third_party/bmi270/bmi2.c" "../third_party/bmi270/bmi270.c"
    INCLUDE_DIRS "../include" "../generated" "../third_party/bmi270"
    REQUIRES esp_wifi esp_http_client esp_event esp_netif nvs_flash json driver esp_timer esp_lcd esp_codec_dev
)
