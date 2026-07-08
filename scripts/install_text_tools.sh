#!/usr/bin/env bash
set -euo pipefail

echo "Installing server-side text extraction tools..."

if command -v apt-get >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y ffmpeg mkvtoolnix tesseract-ocr tesseract-ocr-chi-sim
else
  echo "apt-get was not found. Install ffmpeg, mkvtoolnix, and tesseract with your OS package manager."
fi

echo
echo "Optional Python tools:"
echo "  yt-dlp:         python3 -m pip install --user yt-dlp"
echo "  openai-whisper: use a Python version supported by PyTorch, then install openai-whisper"
echo
echo "After installation, restart the server and open /api/system/text-extraction-tools."
