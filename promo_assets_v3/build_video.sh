#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PAD=0.20
SPEED=1.12
FPS=30
FINAL="SOXLPRO_TikTok_Promo_v3.mp4"
TEMP="${FINAL%.mp4}.tmp.mp4"

rm -f clip_*.mp4 padded_*.m4a video_list.txt audio_list.txt \
  video_only.mp4 narration.m4a "$TEMP"

for n in 01 02 03 04 05 06; do
  duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "voice_${n}.mp3")
  hold=$(python3 -c "print(float('${duration}') / ${SPEED} + ${PAD})")

  ffmpeg -y -loglevel error -i "voice_${n}.mp3" \
    -af "atempo=${SPEED},apad=pad_dur=${PAD}" -c:a aac -b:a 192k "padded_${n}.m4a"

  ffmpeg -y -loglevel error -loop 1 -i "frame_${n}.jpg" -t "${hold}" \
    -vf "scale=1120:1991,crop=1080:1920:x='20+8*sin(t/2.8)':y='28+7*cos(t/2.5)',fade=t=in:st=0:d=0.18,format=yuv420p" \
    -r ${FPS} -c:v libx264 -preset ultrafast -crf 19 "clip_${n}.mp4"

  printf "file 'clip_%s.mp4'\n" "$n" >> video_list.txt
  printf "file 'padded_%s.m4a'\n" "$n" >> audio_list.txt
done

ffmpeg -y -loglevel error -f concat -safe 0 -i video_list.txt -c copy video_only.mp4
ffmpeg -y -loglevel error -f concat -safe 0 -i audio_list.txt -c copy narration.m4a
ffmpeg -y -loglevel error -i video_only.mp4 -i narration.m4a \
  -map 0:v -map 1:a -c:v copy -c:a copy -shortest -movflags +faststart "$TEMP"
mv "$TEMP" "$FINAL"

ffprobe -v error -show_entries format=duration,size \
  -of default=noprint_wrappers=1 "$FINAL"