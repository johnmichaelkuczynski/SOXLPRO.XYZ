#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PAD=0.55
FPS=30
rm -f clip_*.mp4 padded_*.m4a video_list.txt audio_list.txt video_only.mp4 narration.m4a SOXLPRO_Probability_Promo.mp4

for n in 01 02 03 04 05 06 07 08; do
  duration=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "voice_${n}.mp3")
  hold=$(python3 -c "print(float('${duration}') + ${PAD})")
  fade_out=$(python3 -c "print(max(0, float('${hold}') - 0.28))")

  ffmpeg -y -loglevel error -i "voice_${n}.mp3" \
    -af "apad=pad_dur=${PAD}" -c:a aac -b:a 192k "padded_${n}.m4a"

  ffmpeg -y -loglevel error -loop 1 -i "frame_${n}.jpg" -t "${hold}" \
    -vf "scale=1344:756,crop=1280:720:x='32+8*sin(t/3)':y='18+6*cos(t/2.7)',fade=t=in:st=0:d=0.28,fade=t=out:st=${fade_out}:d=0.28,format=yuv420p" \
    -r ${FPS} -c:v libx264 -preset ultrafast -crf 20 "clip_${n}.mp4"

  printf "file 'clip_%s.mp4'\n" "$n" >> video_list.txt
  printf "file 'padded_%s.m4a'\n" "$n" >> audio_list.txt
done

ffmpeg -y -loglevel error -f concat -safe 0 -i video_list.txt -c copy video_only.mp4
ffmpeg -y -loglevel error -f concat -safe 0 -i audio_list.txt -c copy narration.m4a
ffmpeg -y -loglevel error -i video_only.mp4 -i narration.m4a \
  -map 0:v -map 1:a -c:v copy -c:a copy -shortest SOXLPRO_Probability_Promo.mp4

ffprobe -v error -show_entries format=duration,size -of default=noprint_wrappers=1 SOXLPRO_Probability_Promo.mp4
