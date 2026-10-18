#!/usr/bin/env bash
# Recordings -> upload-ready samples -> ElevenLabs Instant Voice Clone -> test clip.
#
#   cd ~/Documents/projects/fluffkit
#   tools/make_voice.sh <audio file or folder> "<voice name>" --i-have-the-rights
#
# Only for a voice you own or may clone (ElevenLabs terms). Needs the ElevenLabs key in
# ~/11labs.md or ELEVENLABS_API_KEY. Prints the new voice_id and writes voice_test.mp3.
set -euo pipefail

cd "$(dirname "$0")/.."                                   # repo root
INPUT="${1:?usage: tools/make_voice.sh <audio file or folder> \"<voice name>\" --i-have-the-rights}"
NAME="${2:?give a name for the new voice}"
RIGHTS="${3:-}"
[ "$RIGHTS" = "--i-have-the-rights" ] || { echo "add --i-have-the-rights (only for a voice you may clone)" >&2; exit 1; }

PY=.venv/bin/python; [ -x "$PY" ] || PY=python3
export ELEVENLABS_API_KEY="${ELEVENLABS_API_KEY:-$(tr -d '[:space:]' < ~/11labs.md)}"

OUT="out/voice-samples/$(echo "$NAME" | tr ' /' '__')"
rm -rf "$OUT"
echo "1/2 preparing samples -> $OUT"
"$PY" tools/voice_samples.py "$INPUT" -o "$OUT" --total 120

echo "2/2 creating the voice \"$NAME\" on ElevenLabs"
"$PY" tools/eleven_clone.py "$NAME" "$OUT"/*.mp3 --i-have-the-rights --language fi \
  --test "Hei! Mä oon Urho, ja nyt mulla on uusi ääni. Hihii!"

echo "Listen: afplay voice_test.mp3"
echo "Use it: put the voice_id into phone/index.html (const VOICE = \"…\") and reload the page on the phone."
