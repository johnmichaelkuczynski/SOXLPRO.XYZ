#!/usr/bin/env bash
# Build the demo video from REAL recorded app footage (Playwright screen
# recordings) re-timed to the existing narration segments + music bed.
set -euo pipefail
cd "$(dirname "$0")"

PAD=0.5
FPS=30
F=footage

# Preflight: required inputs must exist.
for need in slide_01.png music_bed.mp3 \
  "$F/login.webm" "$F/chart.webm" "$F/strategy.webm" "$F/backtest.webm" \
  "$F/diag.webm" "$F/qc.webm"; do
  [[ -f "$need" ]] || { echo "ERROR: missing required input: $need" >&2; exit 1; }
done
for i in 01 02 03 04 05 06 07; do
  [[ -f "seg_$i.mp3" ]] || { echo "ERROR: missing narration seg_$i.mp3" >&2; exit 1; }
done

rm -f clip_*.mp4 pad_*.mp3 video_list.txt audio_list.txt video_only.mp4 narration.mp3
: > video_list.txt
: > audio_list.txt

# segment durations
declare -A D
for i in 01 02 03 04 05 06 07; do
  D[$i]=$(ffprobe -v error -show_entries format=duration -of csv=p=0 seg_$i.mp3)
done

# padded narration (segment order)
for i in 01 02 03 04 05 06 07; do
  ffmpeg -y -loglevel error -i seg_$i.mp3 -af "apad=pad_dur=${PAD}" pad_$i.mp3
  echo "file 'pad_$i.mp3'" >> audio_list.txt
done

# Normalize a recorded webm: scale to 1080 tall, white-pad to 1920 wide,
# then re-time (setpts) so the whole clip lasts exactly `target` seconds.
footage_clip() { # src target out [zoom] [start]
  local src="$1" target="$2" out="$3" zoom="${4:-no}" start="${5:-0}"
  local total; total=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$src")
  python3 -c "import sys; sys.exit(0 if $start < $total else 1)" \
    || { echo "ERROR: start=$start exceeds duration of $src ($total s)" >&2; exit 1; }
  local srcdur; srcdur=$(python3 -c "print($total-$start)")
  local factor; factor=$(python3 -c "print($target/$srcdur)")
  local base="scale=-2:1080,pad=1920:1080:(1920-iw)/2:0:color=white,setpts=${factor}*PTS,fps=${FPS}"
  if [[ "$zoom" == "zoom" ]]; then
    local frames; frames=$(python3 -c "print(int(round($target*$FPS)))")
    base="${base},zoompan=z='min(zoom+0.0010,1.32)':d=1:x='iw/2-(iw/zoom/2)':y='ih*0.30-(ih/zoom/2)':s=1920x1080:fps=${FPS}"
  fi
  ffmpeg -y -loglevel error -ss "$start" -i "$src" -an -vf "${base},format=yuv420p" \
    -t "$target" -r $FPS -c:v libx264 -preset veryfast -pix_fmt yuv420p "clip_${out}.mp4"
  echo "file 'clip_${out}.mp4'" >> video_list.txt
}

# Ken Burns clip for the static intro title card.
title_clip() { # img target out
  local img="$1" target="$2" out="$3"
  local frames; frames=$(python3 -c "print(int(round($target*$FPS)))")
  ffmpeg -y -loglevel error -loop 1 -i "$img" -t "$target" \
    -vf "scale=2304:1296,zoompan=z='min(zoom+0.00035,1.10)':d=${frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps=${FPS},format=yuv420p,fade=t=in:st=0:d=0.6" \
    -r $FPS -c:v libx264 -preset veryfast -pix_fmt yuv420p "clip_${out}.mp4"
  echo "file 'clip_${out}.mp4'" >> video_list.txt
}

h01=$(python3 -c "print(${D[01]}+${PAD})")
h02=$(python3 -c "print(${D[02]}+${PAD})")
h03=$(python3 -c "print(${D[03]}+${PAD})")
h04=$(python3 -c "print(${D[04]}+${PAD})")
h05=$(python3 -c "print(${D[05]}+${PAD})")
h06=$(python3 -c "print(${D[06]}+${PAD})")
h06a=$(python3 -c "print(round(($h06)/2,3))")
h06b=$(python3 -c "print(round(($h06)-($h06a),3))")
h07=$(python3 -c "print(${D[07]}+${PAD})")

title_clip   slide_01.png   "$h01" 01
footage_clip "$F/login.webm"    "$h02" 02
footage_clip "$F/chart.webm"    "$h03" 03
footage_clip "$F/strategy.webm" "$h04" 04 no 4.0
footage_clip "$F/backtest.webm" "$h05" 05
footage_clip "$F/diag.webm"     "$h06a" 06a
footage_clip "$F/qc.webm"       "$h06b" 06b
footage_clip "$F/diag.webm"     "$h07" 07 zoom

ffmpeg -y -loglevel error -f concat -safe 0 -i video_list.txt -c copy video_only.mp4
ffmpeg -y -loglevel error -f concat -safe 0 -i audio_list.txt -c copy narration.mp3

TOTAL=$(ffprobe -v error -show_entries format=duration -of csv=p=0 video_only.mp4)
echo "total video duration: $TOTAL"

ffmpeg -y -loglevel error -i video_only.mp4 -i narration.mp3 -i music_bed.mp3 \
  -filter_complex "[2:a]volume=0.09,afade=t=out:st=$(python3 -c "print(${TOTAL}-2)"):d=2[bed];[1:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest \
  .out.tmp.mp4
mv -f .out.tmp.mp4 SOXL_Analysis_Platform_Demo.mp4

echo "DONE -> SOXL_Analysis_Platform_Demo.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 SOXL_Analysis_Platform_Demo.mp4