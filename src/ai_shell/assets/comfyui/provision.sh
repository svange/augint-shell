#!/bin/bash
# ComfyUI provisioning script for augint-shell.
#
# Runs on first container boot via ai-dock/comfyui's PROVISIONING_SCRIPT hook.
# Downloads:
#   - SDXL base 1.0 (always; open weights)
#   - FLUX.1-dev UNet + VAE + CLIP-L + T5-XXL (only when HF_TOKEN is set
#     AND the HF Hub license has been accepted on the account)
#
# Idempotent: skips any file that already exists on the volume.

set -euo pipefail

MODELS_DIR="${MODELS_DIR:-/opt/ComfyUI/models}"
mkdir -p "${MODELS_DIR}"/{checkpoints,unet,vae,clip,loras}

_download() {
    local url="$1"
    local dest="$2"
    local auth="${3:-}"

    if [[ -s "${dest}" ]]; then
        echo "[provision] skip (exists): ${dest}"
        return 0
    fi
    echo "[provision] downloading -> ${dest}"
    if [[ -n "${auth}" ]]; then
        curl -fL --retry 3 --retry-delay 5 -H "Authorization: Bearer ${auth}" \
            -o "${dest}.partial" "${url}"
    else
        curl -fL --retry 3 --retry-delay 5 -o "${dest}.partial" "${url}"
    fi
    mv "${dest}.partial" "${dest}"
}

echo "[provision] augint-shell ComfyUI setup starting"

# SDXL base 1.0 - open weights, always installed.
_download \
    "https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0/resolve/main/sd_xl_base_1.0.safetensors" \
    "${MODELS_DIR}/checkpoints/sd_xl_base_1.0.safetensors"

# FLUX.1-dev - gated, requires HF_TOKEN plus accepted license on the account.
HF_TOKEN_VALUE="${HF_TOKEN:-${HUGGING_FACE_HUB_TOKEN:-}}"
if [[ -n "${HF_TOKEN_VALUE}" ]]; then
    echo "[provision] HF token detected - fetching FLUX.1-dev assets"

    _download \
        "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/flux1-dev.safetensors" \
        "${MODELS_DIR}/unet/flux1-dev.safetensors" \
        "${HF_TOKEN_VALUE}"

    _download \
        "https://huggingface.co/black-forest-labs/FLUX.1-dev/resolve/main/ae.safetensors" \
        "${MODELS_DIR}/vae/ae.safetensors" \
        "${HF_TOKEN_VALUE}"

    _download \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        "${MODELS_DIR}/clip/clip_l.safetensors"

    _download \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
        "${MODELS_DIR}/clip/t5xxl_fp16.safetensors"
else
    echo "[provision] HF_TOKEN not set - skipping FLUX.1-dev (SDXL only)"
fi

echo "[provision] augint-shell ComfyUI setup complete"
