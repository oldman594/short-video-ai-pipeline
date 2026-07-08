#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APT_DIR="$ROOT_DIR/.local/apt"
WHISPER_DIR="$ROOT_DIR/.local/whispercpp"
MODEL_DIR="$ROOT_DIR/.local/models"

mkdir -p "$APT_DIR" "$WHISPER_DIR" "$MODEL_DIR"

cd "$APT_DIR"
apt-get download whisper.cpp libwhisper1 libggml0

for deb in "$APT_DIR"/*.deb; do
  dpkg-deb -x "$deb" "$WHISPER_DIR"
done

MODEL="$MODEL_DIR/ggml-tiny.bin"
if [[ ! -f "$MODEL" ]]; then
  curl -L --fail -o "$MODEL" https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-tiny.bin
fi

echo "Local whisper.cpp files are prepared under $ROOT_DIR/.local"
echo "If your distro package hardcodes the ggml backend path, system installation with apt is still preferred:"
echo "  sudo apt-get install whisper.cpp"
