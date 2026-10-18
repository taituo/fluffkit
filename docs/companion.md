# Furby as a gesture machine, with a companion device

Status: design note written after the first real-hardware session (2026-10-18). The rules in
[What a real Furby taught us](#what-a-real-furby-taught-us) are observed facts; the rest is the plan.

## The idea

Keep the Furby closed and original. Its DLC becomes a **gesture library**: silent beak, body and eye
animations in fixed slots. Everything audible comes from a **companion device** next to it (a laptop
with a Bluetooth speaker, an old Android phone, a Raspberry Pi Zero 2 W or an ESP32-S3 with a speaker
and microphone). The brain (an LLM agent, e.g. Claude over MCP) can live anywhere.

```
brain (LLM / agent)          tools: speak(text) · sfx(prompt) · sing(prompt) · gesture(name) · listen()
        │
companion (panel.py today)   audio out → speaker beside Furby, mic in, sound bank cache
        │ BLE: 13 00 <action>  (one write, instant)
Furby (stock firmware)       DLC slot = silent gestures: beak 1–10 s, body moves, dances, eyes
```

Why: Furby's own speaker only plays audio that was uploaded beforehand (about 2 min over BLE) and
activated. Nothing is known that streams audio to it. A gesture, on the other hand, is one BLE write
and starts at once.

## Gesture library DLC (template)

One pack, one name (= one slot), fixed layout so the companion knows every code:

| slots | what | how it is built |
|---|---|---|
| beak 1–10 s | beak moves, no sound | base sequences with an LPS beak pattern and no motor, silent audio of N s |
| body moves | ears, eyes, tilt; no sound | base sequences with an MTR motor animation, 0.3 s of silence |
| dances | longer motor animations | motor sequences from TU010160 (recovered stock DLC), audio shrunk or silent |
| eyes | custom eye animations | `fluffkit pack --eyes`, eye word 0x8401 in the sequence |
| a few phrases | offline fallback when no companion is around | normal pack lines |

`out/suomi_nokka.txt` was the first such pack: 8 Finnish phrases + beak 1–10 s + 3 silent body moves.

## Templated sounds

The companion generates and caches sounds; replaying a cached one costs nothing and is instant.

| kind | source (tested) | gesture while it plays |
|---|---|---|
| speech | ElevenLabs TTS (`eleven_multilingual_v2`, about 1.1 s) | beak item ≥ speech length |
| sound effect | ElevenLabs `/v1/sound-generation` (about 1.8 s for 2–3 s) | one random body move |
| song | ElevenLabs `/v1/music` (about 4 s for 10 s) | body move and beak in turns every 4 s |

## Background DLC updates

New gestures or eyes are a new DLC build plus a 2-minute upload. That can run in the background:

1. The current pack keeps working from slot A.
2. The companion says something like "Hetkinen, lataan uusia kuvia!" from its own speaker.
3. Upload the new pack under the other name (slot B), following the rules below.
4. Activate slot B. Actions switch at once; Furby's own audio switches after a power cycle, which a
   companion can do itself with a MOSFET on a USB "dummy battery" (see PyFluff `models/`).

## What a real Furby taught us

- **The slot is chosen by the announced file name**, not by the slot byte of `0x50`. The same name
  replaces the same slot (13 for packs under 0.5 MB); a new name goes to another slot (12 for the next).
  There are 14 slots: 2 × 2 MB, 6 × 1 MB, 6 × 0.5 MB.
- **Activate the slot Furby actually used.** Scan `73 <slot>` for the name and size, then `60 <slot>`,
  `61`. Activating the `--slot` argument activates an empty slot: every 75/x action then answers
  `INPUT_OUT_OF_RANGE`.
- **Never upload onto an active or half-written slot.** Furby crashes about 40 s into the transfer
  (striped eye, reboot, sometimes a long "dead" period). Deactivate `62 <slot>`, delete `74 <slot>`,
  check with `73 <slot>` that it reads empty, then upload. With that, 5 ms pacing (about 3 kB/s) is fine.
- `73` replies for the last slot can arrive several seconds late. Wait ≥ 6 s before deciding.
- Switching with `60`/`61` changes the action table and motion at once, but the **audio** of the newly
  activated pack is only used after a power cycle (activation copies the AMF to `TOY.AMF`, see
  [FORMAT.md](../FORMAT.md)). A fresh upload + activation plays its own audio immediately.
- `10 00 0a xx` (the "lipsync" in furby-connect-ai) makes Furby play its own input-10 speech. Use silent
  beak items instead.
- `20 06` every 3 s keeps the link alive and Furby awake.
- `13 00 75 …` replies: `20:0c` SEQUENCE_PLAYING, `20:0e` SEQUENCE_ENDED, `20:0f` INPUT_OUT_OF_RANGE.

## Phone companion (working, 2026-10-18)

`phone/` turns any Android phone with Chrome into the companion. Tested on a reset Poco F1 (Chrome 83).

```
phone mic ──► ElevenLabs Scribe (scribe_v2, language fin) ──► text
                                                                │ POST /chat-stream (via adb reverse)
computer: phone/serve.py ──► opencode acp (phone/furby-agent: Muse Spark, Finnish storyteller, no tools)
                                                                │ streamed answer, sentence by sentence
phone speaker ◄── ElevenLabs flash TTS (fi)  +  BLE to Furby: silent beak item for each sentence,
                                                 body gestures for [liike] / [nauru], sound for [efekti: …]
```

- Chrome allows Web Bluetooth and the microphone only on https or localhost. `adb reverse tcp:8766 tcp:8766`
  (over USB, or over Wi-Fi after `adb tcpip 5555`) makes the phone's localhost reach `phone/serve.py`.
- Hands-free listening starts above an adjustable level and ends after 0.7 s of quiet; it is muted while
  the phone itself speaks. Push-to-talk works too.
- Measured per turn: Scribe ~0.6 s, first answer piece ~1.5–2.3 s, flash TTS ~0.2–0.3 s per sentence.
  A "thinking" gesture and one of 10 prepared Finnish fillers ("Hetkinen…") play the moment speech ends.
- Pin languages: without `language_code` Scribe heard children as Igbo or Chinese and the TTS read short
  Finnish lines with a foreign accent. `tag_audio_events=false` stops `[clicking]` from becoming a turn.
- The ElevenLabs subscription allows 6 concurrent requests; the page queues calls at 4.
- Old Chrome (83): no `writeValueWithoutResponse`, no `replaceChildren`; the page falls back for both.

Run:

```bash
ELEVENLABS_API_KEY=… python3 phone/serve.py
```
```bash
adb reverse tcp:8766 tcp:8766
```

then open http://localhost:8766 in the phone's Chrome, tap "Yhdistä Furbyyn" and pick Furby.

## Companion hardware: inside the battery box

A child carries the Furby around, so the companion has to travel with it. The battery compartment
(4 × AA in a row) can take a 3D-printed box in the shape of PyFluff's `models/furby-dummy-battery.stl`
that holds the companion and feeds Furby 5 V (Furby draws under 1 A):

| part | why |
|---|---|
| Seeed XIAO ESP32-S3 Sense | BLE to Furby + Wi-Fi to the brain, microphone on board, 21 × 18 mm |
| MAX98357A I2S amplifier + 28–40 mm speaker | Furby's voice |
| 1-cell LiPo (1000–2000 mAh) + 5 V / 2 A boost | powers Furby and the companion |

For a first try with no soldering, an M5Stack Atom Echo (ESP32, speaker, microphone in one 24 mm
cube) shows whether the whole chain works while carried. Neither has been tried with a Furby yet.

## Next steps

- [x] Move the upload rules into `fluffkit upload` (name → slot scan → activate, clear before upload).
- [ ] `fluffkit gestures`: build the gesture-library pack from a template.
- [ ] MCP server on top of `panel.py` so an agent can call speak / sfx / sing / gesture / listen.
- [ ] Companion on an old Android phone (Web Bluetooth in Chrome) or ESP32-S3 / Pi Zero 2 W.
- [ ] Furby sensor events (tickle, antenna, tail) as triggers for the brain.
