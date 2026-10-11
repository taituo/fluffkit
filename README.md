# fluffkit

**Put your own sounds into a Furby Connect (2016), played through its own speaker, from Linux or macOS. No Windows, no proprietary DLL.**

Phrases in any language (OpenAI / Piper / espeak-ng TTS), your own recordings, songs, sound effects → GeneralPlus A1800 (`.a18`) → DLC pack → Bluetooth upload → trigger any item instantly over BLE.

It started as "make my kids' Furby speak Finnish" and ended up as a general custom-content toolkit.

> ⚠️ **Untested on real hardware.** The author is still waiting for his Furby to arrive. 🐣
> Everything below has been verified against data (see [What has been verified](#what-has-been-verified)), but nobody has heard it come out of an actual Furby yet. If you try it, please open an issue and tell us what happened.

## Why this exists

Furby Connect plays custom audio only from DLC files encoded with GeneralPlus's A1800 codec. Until now the only working encoder was GeneralPlus's Windows `A1800.DLL` (via 32-bit Python 2.7, a Windows VM, Wine or a Windows CI runner). An open reimplementation, [John-K/a1800_codec](https://github.com/John-K/a1800_codec), appeared in 2026. Its decoder was right, but its encoder had a scaling bug that made output ~1.4× too loud and much noisier.

This repo:

1. **Fixes the open A1800 encoder** (`a1800/`, see [`a1800/NOTICE`](a1800/NOTICE)). With the fix, its output matches the original DLL on the same input:

   | encoder (same input, same decoder) | corr | SNR | RMS ratio |
   |---|---|---|---|
   | GeneralPlus `A1800.DLL` | 0.961 | 11.1 dB | 0.97 |
   | upstream a1800_codec | 0.865 | 6.0 dB | 1.37 |
   | **this fork** | **0.961** | **11.1 dB** | **0.97** |

   Gain indices and frame parameters are identical to the DLL's in ~95% of frames.
2. **Builds custom packs** with a small, self-contained DLC writer (`dlcpack.py`). It puts up to 60 items (phrases, recordings, music) into the input-75 actions of the stock `tu003410.dlc`, the same route Context IS used in 2017 to play custom audio on a real Furby.
3. **Uploads and triggers** them with [PyFluff](https://github.com/martinwoodward/PyFluff) over BLE.

## What has been verified

- The decoder handles all 146 tracks of Hasbro's `tu003410.dlc` and the DLL-encoded files from [furbhax](https://github.com/swarley7/furbhax). On a DLL-encoded file it reaches correlation 0.961 with the source, at zero lag.
- The fixed encoder matches the DLL (table above). Frame timing matches the DLL (the first frame is dropped), and track headers use the same layout as Furby's own tracks: `u32 len = frame bytes + 2`, `u16 16000`, then 40-byte frames.
- The full pipeline on a Finnish test phrase reaches correlation 0.987 and SNR 16 dB.
- `dlcpack.py`:
  - An untouched DLC round-trips byte-for-byte.
  - A built pack is byte-identical to one built with the Context IS Python library.
  - Only the AMF (audio) and APL (playlist) sections change; the other 7 sections are byte-identical to the original.
  - The header offsets add up to the file size.
- The codec's 52 unit tests pass.
- **Not verified:** actual playback on a Furby.

## Install

Requirements: Python 3.11+, `ffmpeg`, Rust (to build the codec), plus `bleak` and PyFluff for BLE.

```bash
git clone https://github.com/<you>/fluffkit && cd fluffkit
(cd a1800 && cargo build --release)              # or grab a binary from Releases into ./bin/
git clone https://github.com/martinwoodward/PyFluff ../PyFluff
python3 -m venv .venv && .venv/bin/pip install -e ../PyFluff
```

**Steam Deck (Desktop mode):** the root filesystem is read-only. Install Rust with `rustup` in your home directory, use a static `ffmpeg` in `~/.local/bin`, or do everything inside `distrobox`.

## Use

```bash
export OPENAI_API_KEY=sk-...
python3 fluffkit.py pack examples/english.txt -o pack.dlc --pitch 3   # one item per line: text or an audio file
python3 fluffkit.py check pack.dlc --export listen/                    # decode back to WAV and listen first
.venv/bin/python fluffkit.py upload pack.dlc                           # ~1.5–2 min over BLE
.venv/bin/python fluffkit.py say 1                                     # or: say "tickles"
```

- A line is either text (spoken with TTS, in whatever language it is written in) or a path to a `.wav/.mp3/.flac/.ogg/.m4a/.a18` file. Prefix `[music]` or `[sfx]` to keep dynamics and skip the pitch shift.
- `--engine openai|piper|espeak`, `--voice`, `--instructions`.
- `--pitch N` raises the voice by N semitones without changing the tempo.
- Examples: [`examples/english.txt`](examples/english.txt), [`examples/finnish.txt`](examples/finnish.txt).
- Other commands: `encode` / `decode` single files, `slots`.
- The base DLC is downloaded on first use from [ctxis/Furby](https://github.com/ctxis/Furby) and checked against a SHA-256 hash. No Hasbro files are included in this repo.

## Limits and ideas

- Each pack holds at most 60 items. Long audio is fine, but the upload time grows with it.
- Uploads run at ~4 kB/s. That figure comes from the 20 B / 5 ms pacing PyFluff and bluefluff use, not from a measured Furby limit, so it may be possible to go faster.
- New sentences need a re-upload. For live LLM replies, play them through an external speaker and trigger silent "talking" actions so Furby moves its beak and eyes in time.
- The mouth (LPS) still follows the original track's pattern.
- Next steps: silent gesture actions, decoding the MTR motor format to write new dances, and a 3D preview.

## Credits

All the hard reverse engineering was done by others:

- [Context Information Security / ctxis/Furby](https://github.com/ctxis/Furby): DLC format and the original custom-audio demo (2017)
- [Jeija/bluefluff](https://github.com/Jeija/bluefluff) (Florian Euchner): BLE protocol and DLC flashing
- [John-K/a1800_codec](https://github.com/John-K/a1800_codec): clean-room A1800 codec (Apache-2.0), the base of `a1800/`
- [mmaker/furpy3](https://github.com/mmaker/furpy3) and [benbalter/Furby](https://github.com/benbalter/Furby): Python 3 DLC tooling and NAND exploration
- [swarley7/furbhax](https://github.com/swarley7/furbhax) (l0ss & swarley): hardware dumps and DLL-encoded reference audio
- [martinwoodward/PyFluff](https://github.com/martinwoodward/PyFluff): Python BLE control

## License

- Everything except `a1800/`: [MIT](LICENSE).
- `a1800/`: Apache-2.0 (a modified copy of John-K/a1800_codec; see `a1800/NOTICE`).

Furby and Furby Connect are trademarks of Hasbro. This project is not affiliated with or endorsed by Hasbro. It is an independent interoperability project for people's own toys.
