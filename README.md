# fluffkit

**Put your own sounds into a Furby Connect: phrases in any language, your own recordings, songs, sound effects. Everything plays from Furby's own speaker, with its beak, eyes and body moving. Runs on Linux and macOS, with no Windows and no proprietary DLL.**

```text
"Hello! Wanna play?"   ─┐
grandma_says_hi.wav     ├─► 16 kHz mono ─► A1800 (.a18) ─► DLC pack ─► Bluetooth ─► fluffkit say 3
[music] birthday.mp3   ─┘   (TTS/ffmpeg)    fixed open       up to 60     ~1.5 min     instant,
                                            encoder          items        once         any time
```

It started as "make my kids' Furby speak Finnish" and grew into a general custom-content toolkit.

> [!WARNING]
> **Untested on real hardware: the author is still waiting for his Furby to arrive.** 🐣
> Every step has been checked against data (see [Verification](#verification)), but nobody has heard fluffkit audio come out of a real Furby yet. If you try it, please [open an issue](../../issues) and tell us what happened, whether it worked or not.

---

## Contents

- [Quick start](#quick-start)
- [Pack files](#pack-files)
- [Eyes](#eyes)
- [Commands](#commands)
- [Install](#install)
- [How it works](#how-it-works)
- [The A1800 encoder fix](#the-a1800-encoder-fix)
- [Verification](#verification)
- [DLC format reference](FORMAT.md)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [Roadmap](#roadmap)
- [Credits](#credits)
- [License](#license)

## Quick start

```bash
git clone https://github.com/taituo/fluffkit && cd fluffkit
(cd a1800 && cargo build --release)                 # the audio codec
git clone https://github.com/martinwoodward/PyFluff ../PyFluff
python3 -m venv .venv && .venv/bin/pip install -e ../PyFluff

export OPENAI_API_KEY=sk-...                        # or use --engine piper / espeak
.venv/bin/python fluffkit.py pack examples/english.txt -o pack.dlc --pitch 3
.venv/bin/python fluffkit.py check pack.dlc --export listen/   # listen before uploading
.venv/bin/python fluffkit.py upload pack.dlc                   # wake Furby first, ~1.5-2 min
.venv/bin/python fluffkit.py say 1                             # 🎉
```

## Pack files

A pack file is plain text with one item per line. Each item gets its own slot (1–60), and slot N plays with `fluffkit say N`.

```text
# lines starting with # are comments
Hi! I'm your Furby. Wanna play?          ← text: spoken with TTS, in whatever language it's written in
Hei! Leikitäänkö?                        ← Finnish works the same way
~/recordings/grandma_says_hi.wav         ← your own recording (.wav .mp3 .flac .ogg .m4a)
[music] ~/music/birthday_song.mp3        ← [music] / [sfx]: keep dynamics, no pitch shift
~/packs/old/doorbell.a18                 ← already-encoded A18 file
```

Speech is high-passed and normalised for Furby's tiny speaker. `--pitch 3` raises the voice three semitones without changing the tempo, which sounds a lot more Furby-like. TTS results are cached, so you can edit a pack and rebuild it without paying for the same phrases twice.

`pack` writes `pack.dlc` and a `pack.json` map from item number to action code, text and duration. `say` uses the map.

## Eyes

<p align="center"><img src="docs/eyes-thinking.gif" alt="thinking eyes"> <img src="docs/eyes-hearts.gif" alt="heart eyes"> <img src="docs/eyes-blink.gif" alt="blinking eyes"></p>

You can also give Furby's LCD eyes a custom animation from PNG, GIF, WebP or **SVG** frames: your own drawings, generated art, or SVG that an LLM writes ("make Furby surprised eyes").

```bash
python3 examples/eyes/make_examples.py                    # generates thinking / blink / hearts SVG frames
fluffkit.py eyes examples/eyes/thinking/*.svg -o eyes.gif  # preview in Furby's colours
fluffkit.py pack examples/english.txt -o pack.dlc --eyes examples/eyes/thinking/*.svg
```

Lines tagged `[eyes]` in the pack file show the animation while they play:

```text
[eyes] Hmm, let me think about that...
```

- Each eye is 128×128 pixels with 64 colours. fluffkit fits the image, quantises it to Furby's 16-bit palette and splits it into four 64×64 cels. Identical tiles are stored only once.
- The right eye is a mirror of the left by default. Use `--eyes-right` for separate frames, or `--no-mirror` to show the same frames on both eyes.
- Up to 8 distinct frames per eye by default (`--eye-frames`), spread over Furby's 38-frame eye playlist. Packs with custom eyes are *smaller*, because Hasbro's chilli graphics are dropped.
- A pack holds one custom animation, using the same mechanism as the 2017 Context IS demo. Their custom eyes ran on a real Furby.
- SVG is rasterised with `resvg`, `rsvg-convert` or ffmpeg's librsvg, whichever is installed.

## Furby's own voice

Furby's firmware stores its whole voice library in `.AMF` files on its NAND (`Personalities/<name>/<name>.AMF`, `Downloads/TOY.AMF`, `AudioMegafiles/*.bin`). They use the same layout as a DLC's audio section, and the clips are ordinary A1800 audio, so fluffkit decodes them:

```bash
fluffkit.py amf Base.AMF                      # 2112 A1800 clips, 63.7 min of audio
fluffkit.py amf Base.AMF -o clips/ --wav      # decode them all to WAV
```

Use the extracted `.a18` clips in your own packs, for example to mix Furby's real giggles into new phrases. The firmware files are Hasbro's, so dump them from your own Furby. None are included here.

## Home automation (ESPHome / MQTT)

An ESP32 can act as Furby's permanent Bluetooth companion, so Home Assistant plays your pack without a computer. Furby itself stays untouched.

```bash
fluffkit.py esphome pack.json --mac AA:BB:CC:DD:EE:FF -o furby.yaml
esphome run furby.yaml          # needs wifi_ssid / wifi_password in secrets.yaml
```

The generated config gives you:

- **One Home Assistant button per pack item**, named by its text (*"Say 3: Hyvää yötä"*).
- **Actions:**
  - `say` (`item: 3`) plays a pack item.
  - `action` (`inp idx sub spec`) runs any Furby action, including the firmware's own reactions.
  - `antenna` (`r g b`) sets the antenna colour.
  - `send_hex` sends raw GeneralPlus bytes.
- **Sensors:**
  - `Connected`
  - `Event` (`sequence_playing`, `sequence_ended`, `sleep_mask_on`, …)
  - `Sensor data` (the raw `0x21` status; switch it on with *Sensor stream on*)
- **A *Hold in app mode* switch** sends the 3-second keepalive, so Furby stays quiet and waits for commands. Switch it off to let Furby be Furby.

Packs are still uploaded from a computer (`fluffkit.py upload`), which is rare. Regenerate the config after each new pack. CI validates the generated config and compiles it with ESPHome for an ESP32-S3 on every change. It has not been run on hardware yet.

Two alternatives:
- `fluffkit.py say -` reads item numbers on stdin and keeps the Bluetooth connection open, for scripts on a computer.
- [CrazyRobMiles/FurbyESP32](https://github.com/CrazyRobMiles/FurbyESP32) (`MQTTFurby`) is an Arduino MQTT bridge. Publish `13 00 4B 00 y z` to `furbyIn` to play item `75/0/y/z`.

## Commands

| command | what it does |
|---|---|
| `pack FILE -o pack.dlc` | build a pack (`--engine`, `--voice`, `--instructions`, `--pitch`, `--gain`, `--music`, `--eyes`) |
| `check pack.dlc [--export DIR]` | verify the pack and decode every item back to WAV (plus `eyes.gif` if the pack has eyes) |
| `eyes FRAMES... -o eyes.gif` | preview an eye animation exactly as it will be packed |
| `amf FILE.AMF [-o DIR] [--wav]` | list or extract Furby's own firmware voice clips |
| `esphome pack.json --mac MAC` | ESPHome config: an ESP32 bridge with a Home Assistant button per item |
| `upload pack.dlc [--slot 2] [--address MAC]` | delete the slot, upload, load and activate |
| `say N` / `say "text"` | play item N, or the first item whose text matches |
| `say 3 7 "night"` | chain several items in one connection |
| `say -` | keep the connection open and read items from stdin, one per line (`a \| b` chains); use this for instant playback from scripts, home automation or an LLM |
| `encode IN -o OUT.a18 [--gp-header]` | any audio file to Furby A18 (`--gp-header` writes the A1800.DLL-style file header) |
| `decode IN.a18 -o OUT.wav` | A18 to WAV (DLL-made files work too) |
| `tts "text" -o out.wav` | just the text-to-speech step |
| `slots` | list the 60 slots (action codes `75/0/x/y`) |

**TTS engines:**
- `openai` (default) uses `gpt-4o-mini-tts`. Change the model with `FLUFFKIT_TTS_MODEL` and the voice with `--voice` or `FLUFFKIT_TTS_VOICE`. `--instructions` sets the speaking style.
- `piper` runs locally: `--voice path/to/voice.onnx`.
- `espeak` needs no network or key, but sounds robotic: `FLUFFKIT_ESPEAK_VOICE=fi`.

## Install

You need Python 3.11+, `ffmpeg`, Rust (only to build the codec) and Bluetooth LE. [PyFluff](https://github.com/martinwoodward/PyFluff), which brings in `bleak`, is needed for `upload` and `say`.

The codec builds with `cd a1800 && cargo build --release`. A prebuilt binary also works: put it in `./bin/a1800_codec` or point the `A1800_CODEC` environment variable at it. Tagged versions (`v*`) build Linux x86-64 and macOS arm64 binaries into [Releases](../../releases) via CI.

Any Linux or macOS machine with Bluetooth LE works.

## How it works

Furby Connect cannot stream audio. It plays sounds that are stored in its flash memory, and new sounds arrive as **DLC files**. Hasbro's Furby Connect World app used to download them from Amazon S3 and push them to the toy over Bluetooth, in exactly the same way as `fluffkit upload`. The app then triggered the reactions with action `75/x/y/z` while kids watched videos.

fluffkit reuses that mechanism:

1. **Audio:** each item is turned into 16 kHz mono and encoded with GeneralPlus **A1800** at 16 kbps (40-byte frames, 20 ms each), the format of every stock Furby track.
2. **Pack:** `dlcpack.py` takes the stock English DLC `tu003410.dlc`. It shrinks its 146 original tracks to 128-byte stubs, the same trick Context IS used in 2017. Each of the 60 input-75 playlists then points to one of your items. The other sections (eye graphics, motor and lip sequences) are left untouched, so every item still comes with its original eye animation, beak and body movement.
3. **Upload:** PyFluff announces the file with `0x50`, streams it in 20-byte BLE packets, then loads (`0x60`) and activates (`0x61`) it.
4. **Play:** one 6-byte action command (`13 00 4B 00 y z`) starts an item at once. A one-shot `say N` first opens a Bluetooth connection, which takes a few seconds. `say -` keeps the connection open, so playback starts within milliseconds.

The base DLC is downloaded on first use from [ctxis/Furby](https://github.com/ctxis/Furby) and checked against a SHA-256 hash. **No Hasbro files are included in this repository.**

## The A1800 encoder fix

Until 2026 the only A1800 encoder was GeneralPlus's Windows `A1800.DLL`, which people ran through 32-bit Python 2.7, a Windows VM, Wine or a Windows CI runner. Then [John-K/a1800_codec](https://github.com/John-K/a1800_codec) reverse-engineered the DLL into clean-room Rust. Its decoder is correct, but its encoder quantised the subbands with the wrong scale exponent: one recomputed from the gains, instead of the one the analysis filter actually applied. The output came out ~1.4× too loud and much noisier.

`a1800/` fixes that and also picks the rate-control parameter from actual Huffman bit counts, the way the DLL does. The test below compares three encodings of the same source file, all decoded with the same decoder:

| encoder | correlation | SNR | RMS ratio |
|---|---|---|---|
| GeneralPlus `A1800.DLL` | 0.961 | 11.1 dB | 0.97 |
| upstream a1800_codec | 0.865 | 6.0 dB | 1.37 |
| **fluffkit `a1800/`** | **0.961** | **11.1 dB** | **0.97** |

The fixed encoder's gain indices and frame parameters are identical to the DLL's in ~95% of frames. Details are in [`a1800/NOTICE`](a1800/NOTICE), and the patch is in [`a1800/encoder-fix.diff`](a1800/encoder-fix.diff).

## Verification

What has been checked without a Furby:

- **Decoder:** it handles all 146 tracks of `tu003410.dlc` and the DLL-encoded reference files from [furbhax](https://github.com/swarley7/furbhax). On the DLL-encoded file it reaches correlation 0.961 with the source, at zero lag.
- **Encoder:** its output matches the DLL (table above).
  - Frame timing matches the DLL.
  - Track headers use Furby's own layout: `u32 length = frame bytes + 2`, then `u16 16000`, then the frames.
- **End to end:** a speech test phrase reaches correlation 0.987 and SNR 16 dB.
- **DLC writer:**
  - A stock DLC round-trips byte-for-byte.
  - Built packs are byte-identical to packs built with the Context IS Python library.
  - Only the AMF (audio) and APL (playlist) sections change.
  - The header offsets add up to the file size.
- **Codec unit tests:** all 52 pass.
- **Not verified:** playback on a real Furby. Help wanted!

Run the checks yourself with `python3 -m unittest discover -s tests -v`. The BLE tests drive the real PyFluff code against a simulated Furby (`tests/fakeble`), checking the upload bytes, the command order and the action packets. CI runs them on every push, including the real-DLC tests. The full format write-up is in [FORMAT.md](FORMAT.md), where every claim is labelled verified, observed or hypothesis.

## Troubleshooting

- **Watch the slot status.** Open Furby's debug screen (`pyfluff debug`, repeat until the slot page shows). Each slot shows `0` empty, `1` upload in progress or failed, `2` uploaded, `3` active.
- **Nothing plays after upload:** restart Furby and try again. Furby seems to need a reboot between two updates.
- **Upload stalls:** keep Furby awake and close to the computer, and try another slot with `--slot 1`. The slots are about 2 MB, 1 MB and 0.5 MB.
- **Furby acts weird:** a FurBLE reset clears the DLC storage. Hold Furby upside down, hold the tongue and pull the tail for about 10 seconds.

## FAQ

**Can Furby say what an LLM answers, live?**
Not through its own speaker. Each new sound needs an upload of about a minute and a half. The practical setup is a pack of fixed phrases (greetings, routines, home-automation announcements) plus an external speaker for free-form replies, while silent actions move Furby's beak and eyes in time (on the roadmap).

**Why only 60 items?**
That is how many independent input-75 playlists the base DLC has. A pack can be any size the slot fits, and long items are fine, but the upload time grows with the size.

**Why is the upload slow?**
PyFluff and bluefluff send 20 bytes every 5 ms, which works out to 4 kB/s. That pacing was never measured against Furby's real limit, so faster may work. Experiments are welcome.

**Which Furby?**
Furby Connect (2016, Bluetooth, LCD eyes). Not the 2012/Boom models (which use audio-chirp control) and not the 2023 Furby.

## Roadmap

- [ ] Confirm playback on a real Furby (waiting for the delivery 🚚)
- [ ] Faster uploads: tune the BLE pacing and slim the base DLC
- [x] Custom eye animations (PNG/GIF/SVG)
- [ ] Silent "talk" and gesture actions to accompany an external speaker
- [ ] Decode the MTR motor format and write new dances
- [ ] 3D preview of motor and eye sequences
- [ ] Lip sync (LPS) generated from your own audio
- [x] Encoder fix reported upstream: [John-K/a1800_codec#2](https://github.com/John-K/a1800_codec/issues/2) (PR when wanted)

## Credits

fluffkit stands on years of other people's reverse engineering:

- [Context Information Security / ctxis/Furby](https://github.com/ctxis/Furby): the DLC format and the original custom-audio demo (2017)
- [Jeija/bluefluff](https://github.com/Jeija/bluefluff) (Florian Euchner): the BLE protocol and DLC flashing
- [John-K/a1800_codec](https://github.com/John-K/a1800_codec): the clean-room A1800 codec (Apache-2.0), base of `a1800/`
- [mmaker/furpy3](https://github.com/mmaker/furpy3) and [benbalter/Furby](https://github.com/benbalter/Furby): Python 3 DLC tooling and NAND exploration
- [swarley7/furbhax](https://github.com/swarley7/furbhax) (l0ss & swarley): hardware dumps and DLL-encoded reference audio
- [martinwoodward/PyFluff](https://github.com/martinwoodward/PyFluff): Python BLE control

## License

- Everything except `a1800/` is under the [MIT License](LICENSE).
- `a1800/` is under the Apache-2.0 license. It is a modified copy of John-K/a1800_codec, and the changes are listed in [`a1800/NOTICE`](a1800/NOTICE).

Furby and Furby Connect are trademarks of Hasbro. fluffkit is an independent interoperability project and is not affiliated with or endorsed by Hasbro. Use it with your own toy, at your own risk.
