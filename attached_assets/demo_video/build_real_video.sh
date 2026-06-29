#!/usr/bin/env bash
# Build the demo video from REAL app screenshots (Ken Burns motion) + existing
# narration segments + music bed.
set -euo pipefail
cd "$(dirname "$0")"

PAD=0.5
FPS=30

# segment -> source image
seg_img() {
  case "$1" in
    01) echo slide_01.png ;;     # branded intro title card
    02) echo shot_login.jpg ;;   # Google sign-in gate
    03) echo shot_chart.jpg ;;   # chart + probabilities
    04) echo shot_strategy.jpg ;;# AI strategy builder
    05) echo shot_backtest.jpg ;;# backtest / allocation engine
    06a) echo shot_diag.jpg ;;   # diagnostics (system check)
    06b) echo shot_qc.jpg ;;     # diagnostics (OpenAI+GPTZero QC)
    07) echo shot_diag.jpg ;;    # persistence (zoom into Neon row)
  esac
}

# Build normalized 1920x1080 base frames
mkbase() {
  local in="$1" out="$2"
  if [[ "$in" == slide_* ]]; then
    ffmpeg -y -loglevel error -i "$in" -vf "scale=1920:1080" "$out"
  else
    # strip the editor top bar, scale to width, white-pad to 1080
    ffmpeg -y -loglevel error -i "$in" \
      -vf "crop=1280:664:0:56,scale=1920:-2,pad=1920:1080:0:(1080-ih)/2:color=white" "$out"
  fi
}

# Ken Burns clip from a base frame
clip() {
  local base="$1" hold="$2" out="$3" mode="$4" fade="$5"
  local frames; frames=$(python3 -c "print(int(round($hold*$FPS)))")
  local zexpr xexpr yexpr
  case "$mode" in
    in)   zexpr="min(zoom+0.00035,1.10)"; xexpr="iw/2-(iw/zoom/2)"; yexpr="ih/2-(ih/zoom/2)" ;;
    panr) zexpr="min(zoom+0.00030,1.09)"; xexpr="(iw-iw/zoom)*on/$frames"; yexpr="ih/2-(ih/zoom/2)" ;;
    top)  zexpr="min(zoom+0.00090,1.34)"; xexpr="iw/2-(iw/zoom/2)"; yexpr="ih*0.34-(ih/zoom/2)" ;;
  esac
  local vf="scale=2304:1296,zoompan=z='${zexpr}':d=${frames}:x='${xexpr}':y='${yexpr}':s=1920x1080:fps=${FPS},format=yuv420p"
  if [[ "$fade" == "fadein" ]]; then
    vf="${vf},fade=t=in:st=0:d=0.6"
  elif [[ "$fade" == "fadeout" ]]; then
    vf="${vf},fade=t=out:st=$(python3 -c "print(max(0,${hold}-0.8))"):d=0.8"
  fi
  ffmpeg -y -loglevel error -loop 1 -i "$base" -t "$hold" -vf "$vf" \
    -r $FPS -c:v libx264 -preset ultrafast -pix_fmt yuv420p "clip_${out}.mp4"
}

rm -f clip_*.mp4 pad_*.mp3 base_*.png video_list.txt audio_list.txt
: > video_list.txt
: > audio_list.txt

# durations
declare -A D
for i in 01 02 03 04 05 06 07; do
  D[$i]=$(ffprobe -v error -show_entries format=duration -of csv=p=0 seg_$i.mp3)
done

# padded narration audio (in segment order)
for i in 01 02 03 04 05 06 07; do
  ffmpeg -y -loglevel error -i seg_$i.mp3 -af "apad=pad_dur=${PAD}" pad_$i.mp3
  echo "file 'pad_$i.mp3'" >> audio_list.txt
done

# visual clips (note seg 06 is split into two real shots: diag + qc)
build_clip() { # segkey holdvar mode fade
  local key="$1" hold="$2" mode="$3" fade="$4"
  local img; img=$(seg_img "$key")
  mkbase "$img" "base_${key}.png"
  clip "base_${key}.png" "$hold" "$key" "$mode" "$fade"
  echo "file 'clip_${key}.mp4'" >> video_list.txt
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

build_clip 01 "$h01" in   fadein
build_clip 02 "$h02" in   none
build_clip 03 "$h03" panr none
build_clip 04 "$h04" in   none
build_clip 05 "$h05" panr none
build_clip 06a "$h06a" in none
build_clip 06b "$h06b" in none
build_clip 07 "$h07" top  fadeout

ffmpeg -y -loglevel error -f concat -safe 0 -i video_list.txt -c copy video_only.mp4
ffmpeg -y -loglevel error -f concat -safe 0 -i audio_list.txt -c copy narration.mp3

TOTAL=$(ffprobe -v error -show_entries format=duration -of csv=p=0 video_only.mp4)
echo "total video duration: $TOTAL"

ffmpeg -y -loglevel error -i video_only.mp4 -i narration.mp3 -i music_bed.mp3 \
  -filter_complex "[2:a]volume=0.09,afade=t=out:st=$(python3 -c "print(${TOTAL}-2)"):d=2[bed];[1:a][bed]amix=inputs=2:duration=first:dropout_transition=0[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest \
  SOXL_Analysis_Platform_Demo.mp4

echo "DONE -> SOXL_Analysis_Platform_Demo.mp4"
ffprobe -v error -show_entries format=duration -of csv=p=0 SOXL_Analysis_Platform_Demo.mp4
