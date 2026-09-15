#!/bin/bash
# Corre WhisperX sobre un video de prueba en el server remoto, midiendo pico de VRAM en paralelo.
# Uso (desde el server, dentro de ~/clipfactory): bash run_with_vram_monitor.sh
set -e
cd ~/clipfactory
rm -f vram.log
touch vram.log
( while true; do nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits >> ~/clipfactory/vram.log; sleep 1; done ) &
MONITOR_PID=$!
.venv/bin/whisperx videos/VideoConGuionYouTube.mp4 --model medium --language es --compute_type int8 --batch_size 1 --device cuda --output_dir output2 --output_format json > run2.log 2>&1
STATUS=$?
kill "$MONITOR_PID" 2>/dev/null || true
echo "whisperx exit status: $STATUS"
echo "--- peak VRAM used (MiB) ---"
sort -n vram.log | tail -1
echo "--- baseline (first sample) ---"
head -1 vram.log
echo "--- sample count ---"
wc -l < vram.log
