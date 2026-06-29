#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PAD=0.6      # seconds of silence/hold after each narration segment
FPS=30

durs=()
for i in 01 02 03 04 05 06 07; do
  d=$(ffprobe -v error -show_entries format=duration -of csv=p=0 seg_$i.mp3)
  durs+=("$d")
done

rm -f clip_*.mp4 pad_*.mp3
vlist="video_list.txt"; : > "$vlist"
alist="audio_list.txt"; : > "$alist"

idx=0
for i in 01 02 03 04 05 06 07; do
  d=${durs[$idx]}
  hold=$(python3 -c "print(${d}+${PAD})")
  # padded audio (segment + trailing silence)
  ffmpeg -y -loglevel error -i seg_$i.mp3 -af "apad=pad_dur=${PAD}" pad_$i.mp3
  # still-image video clip for the held duration
  ffmpeg -y -loglevel error -loop 1 -i slide_$i.png -t "$hold" \
    -vf "scale=1920:1080,format=yuv420p,fade=t=in:st=0:d=0.4,fade=t=out:st=$(python3 -c "print(${hold}-0.4)"):d=0.4" \
    -r $FPS -c:v libx264 -preset ultrafast clip_$i.mp4
  echo "file 'clip_$i.mp4'" >> "$vlist"
  echo "file 'pad_$i.mp3'" >> "$alist"
  idx=$((idx+1))
done

# concat video and narration
ffmpeg -y -loglevel error -f concat -safe 0 -i "$vlist" -c copy video_only.mp4
ffmpeg -y -loglevel error -f concat -safe 0 -i "$alist" -c copy narration.mp3

TOTAL=$(ffprobe -v error -show_entries format=duration -of csv=p=0 video_only.mp4)
echo "total video duration: $TOTAL"

# mix narration (full) with music bed (low), trim music to total, gentle fade out
ffmpeg -y -loglevel error -i video_only.mp4 -i narration.mp3 -i music_bed.mp3 \
  -filter_complex "[2:a]volume=0.10,afade=t=out:st=$(python3 -c "print(${TOTAL}-2)"):d=2[bed];[1:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest \
  SOXL_Analysis_Platform_Demo.mp4

echo "DONE -> SOXL_Analysis_Platform_Demo.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 SOXL_Analysis_Platform_Demo.mp4
