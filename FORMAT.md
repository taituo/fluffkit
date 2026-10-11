# Furby Connect DLC format

This document collects what is known about the Furby Connect DLC format. Most of it was first worked out by **Context Information Security** ([ctxis/Furby](https://github.com/ctxis/Furby), 2017) and **Jeija** ([bluefluff](https://github.com/Jeija/bluefluff)). fluffkit adds a few observations and checks everything it relies on against real files.

Every claim carries one of these labels:

| label | meaning |
|---|---|
| **[verified]** | checked by fluffkit with data: a round trip, a byte comparison or a decode |
| **[ctxis]** | documented or implemented by Context IS / Jeija and not re-checked here |
| **[observed]** | a consistent pattern in `tu003410.dlc`, not yet tested on a Furby |
| **[hypothesis]** | a best guess that needs a real-Furby experiment |

The reference file is `tu003410.dlc` (1,129,942 bytes, SHA-256 `efe11a82…c8e203`). All numbers are little-endian.

## Overview

- No checksum and no encryption. Furby does not verify DLC checksums (bluefluff), and none of the sections contain a hash-like field **[verified]**.
- No compression apart from the A1800 audio codec.

```
0x000  header (0x288 bytes)
0x288  sections, in header-entry order: PAL SPR CEL XLS AMF APL LPS SEQ MTR
```

| section | bytes in tu003410 | contents |
|---|---|---|
| PAL | 768 | colour palettes for the eyes (RGB555) |
| SPR | 5,460 | eye animation playlists and composited frames |
| CEL | 242,688 | eye images |
| XLS | 40,690 | action table: maps action codes to sequences |
| AMF | 832,024 | audio tracks (A1800) |
| APL | 834 | audio playlists |
| LPS | 5,214 | beak (lip) movement |
| SEQ | 1,128 | sequences: link a playlist, beak pattern, eye animations and motor animation |
| MTR | 488 | motor animations |

## Header (0x288 bytes) [verified]

```
0x00  "FURBY" in UTF-16LE, zero padded to 32 bytes
0x20  78 56 34 12 02 00 08 00
0x28  16 entries x 38 bytes
```

A used entry has this layout:

```
+0   "DLC_0000." in UTF-16LE         18 bytes
+18  section name, UTF-16LE           6 bytes ("PAL", "AMF", ...)
+24  00 00
+26  u32  counter      starts at 0x0040CFB5 and grows by 0x1A for each used entry (meaning unknown) [observed]
+30  u32  section length in bytes
+34  u32  0
```

An unused entry is 38 zero bytes.

- Entry slots are fixed: `[-, PAL, SPR, CEL, XLS, -, -, -, -, AMF, APL, LPS, SEQ, MTR, -, -]` **[ctxis]**. The names FIR, FIT, CMR and INT appear in firmware files.
- Section data follows the header in entry order, and the section lengths sum to the file size **[verified]**.

## AMF: audio [verified]

```
u32 count
u32 offset[count]        bytes from section start
track[count]:
  u32 len                frame bytes + 2
  u16 16000              bitrate (all stock tracks)
  frames                 A1800, 40 bytes per 20 ms at 16 kbps
```

- Stock tracks run from 0.22 s to 20.9 s. There are 146 tracks in tu003410.
- A1800 is a G.722.1-like subband codec: 320-sample frames at 16 kHz and 14 subbands of 20 coefficients.
- A file written by the GeneralPlus DLL adds a 48-byte header (`00 FF 00 FF "GENERALPLUS SP" …`) before the `u32 len`. That header does not go into the DLC.
- See [`a1800/Codec.md`](a1800/Codec.md) and [`a1800/NOTICE`](a1800/NOTICE).

Shrinking every track to 128 bytes of frames worked on a real Furby in the Context IS demo **[ctxis]**, and fluffkit does the same.

## APL: audio playlists [verified]

```
u16 count
u16 count + 0x546
u32 4
u32 offset[count]        in 16-bit words from section start
playlist: u16 words, terminated by 0xF000
  < 0x1000   AMF track index
  0x1nnn     pause between tracks [ctxis]
  0xF000     end
```

fluffkit rewrites a playlist as `[track, 0xF000]`.

## SEQ: sequences

```
u16 count
u32 6
u32 offset[count]        in 16-bit words
sequence: u16 words, terminated by 0x0000
```

| word | meaning | label |
|---|---|---|
| first: 0x2000 / 0x3000 | type (meaning unknown) | [ctxis] |
| 0x4546 + n | APL playlist n | [verified] (consistent across all 60 sequences) |
| 0xE0nn | LPS beak pattern nn | [observed] (47 sequences) |
| 0xC4nn | MTR motor animation nn | [observed] (0xC400–0xC40C, 13 sequences, 13 MTR entries) |
| 0x8nnn / 0xAnnn | eye animation; 0xA = pick from a pool | [ctxis] |
| 0x1nnn | delay between eye animations | [ctxis] |

## XLS: action table

The table is a tree of action codes: input, index, sub-index, specific. Each leaf is a 10-byte entry, and its first u16 selects a sequence **[ctxis]**.

- Values of 0x1000 and above refer to the DLC's own SEQ entries (value − 0x1000). Lower values refer to sequences in the firmware **[observed]**: every input-75 entry is 0x10nn, and every other input points below 0x1000.
- Input 75 is the DLC's own content and is triggered over BLE with action `75/x/y/z` **[ctxis]**. tu003410 has 62 input-75 codes and 60 distinct playlists, which give fluffkit its 60 slots.

## LPS: beak movement

```
u16 count
u32 3
u32 offset[count]        (offset + 3) in 16-bit words
u32 0xFFFFFFFF
pattern: u16 words, terminated by 0xFFFF
  0x8nnn  beak open,   n = duration?
  0x0nnn  beak closed, n = duration?
```

The structure is **[ctxis]/[verified]** by round trip. **[hypothesis]:** the durations are not in milliseconds. The sum of n against the audio length gives 1.59, 0.98 and 1.54 for three tracks. The unit, and whether the beak follows the audio or its own clock, needs a Furby and a camera.

## MTR: motor animations

```
u16 count
u32 3
u32 offset[count]
animation: u16 words, terminated by 0xF000
```

The structure is **[ctxis]/[verified]** by round trip. The meaning of the words is a **[hypothesis]**:

| word | guess |
|---|---|
| `0x10nn` / `0x14nn` | drive the motor one way / the other way for nn time units (they alternate in "wiggle" animations) |
| `0x2Cpp` + next word | move to cam position pp, then hold |
| `0x0Cnn` | stop or hold for nn |
| `0x18nn`, `0x1Cnn`, `0x28nn`, `0x04nn` | unknown |
| `0xF000` | end |

Furby Connect has one motor on a cam: ears, eyelids and body tilt are all one position. The beak is a separate electromagnet.

## PAL, CEL, SPR: eyes

**PAL** [verified]

- 64 colours × u16 per palette (128 bytes; 6 palettes in tu003410).
- Each colour is RGB555 (`0RRRRRGGGGGBBBBB`); bit 15 set means transparent.

**CEL** [verified]

- 64×64-pixel images, 3072 bytes each (79 in tu003410).
- Each pixel is a 6-bit palette index, packed 4 pixels per 3 bytes, MSB first: `aaaaaabb bbbbcccc ccdddddd`.
- `eyes.py` decodes all 79 cels exactly as the Context IS library does, and re-encodes them byte-for-byte.

**SPR** [verified]

The structure round-trips and agrees with the Context IS parser:

```
16 x { u16 framecount | u32 frame-list offset (words) | u32 layer | u32 0x40 }
frames: 9 x u16 = (cel, palette ref) x 4 quarters + 0xFFFF
frame lists: u32 word offset of each frame
```

- The quarters are TL, TR, BL, BR of one 128×128 eye **[verified]**: stock frames render correctly.
- Palette refs are not palette indices. Rendering the stock chilli and flame animations with palette 4 for ref 5362 and palette 5 for ref 6386 gives the correct images **[verified]**. Ref 4338 is used for the base layer.
- Playlists 8/9 (base layer), 10/11 (chilli layer) and 12/13 (flame layer) hold 38 frames each, and together they form the DLC's own eye animation. Playlists 12 and 13 are the right and left eye **[ctxis demo]**.

**Showing the animation** [ctxis demo]: a sequence eye word `0x8401` plays the DLC's own eye animation. Stock sequences only use `0x80nn` and `0xA0nn`, which refer to firmware eye animations **[observed]**. fluffkit's `eyes.py` follows the demo that ran on a real Furby:

- cel 1 = white, and playlists 8–11 show only it;
- the custom frames go into 13 (left, palette 4, ref 5362) and 12 (right, palette 5, ref 6386);
- marked sequences become `[type, playlist, motor/lips…, 0x8401, 0]`.

## Firmware audio (.AMF on the NAND)

- The firmware's audio megafiles use **exactly the DLC AMF layout**: `u32 count | u32 offset[count] | clips`, with `offset[0] = 4·(count+1)` **[verified]**. This covers `Personalities/*/*.AMF`, `Downloads/TOY.AMF` and `AudioMegafiles/*.bin`.
- Every clip is a normal A1800 track at 16 kbps **[verified]**. All 2112 A1800 clips of `Base.AMF` decode without error, and their spectrum is speech-like (median spectral flatness 0.05, against 0.09 for the DLC's speech and 0.99 for noise). Random data makes the decoder fail immediately.
- Sizes:

  | file | A1800 clips | audio |
  |---|---|---|
  | Base.AMF | 2112 | 63.7 min |
  | the other six personalities | 1350–1637 each | about 46–53 min each |
  | TOY.AMF | 107 | 7.2 min |

- The last 4 entries of each personality AMF start with `SP62ALP` and are some other GeneralPlus format (songs?). That format is **not decoded**.

## DLC storage on the NAND [verified from a NAND dump]

A public NAND file dump ([Furby-ReConnect/Furby](https://github.com/Furby-ReConnect/Furby), `Furby-Files/Furby-NAND/Slots/`) shows how uploaded DLCs are stored:

- **14 slot files.** `T2000k_1..2` are 2 MB, `A1000k_1..6` are 1 MB and `A500k_1..6` are 0.5 MB. Each holds the uploaded DLC **byte-for-byte** (FURBY header, sections) followed by padding. Deleted slots keep stale data.
- **`Slots.STB`.** 14 entries × 98 bytes: `u32 index`, `u16 size class` (0x20/0x10/0x08 = 2M/1M/0.5M), the UTF-16 path `A:\Slots\…SLT`, the UTF-16 DLC name, then `u32 size` and status words. In the dump only one slot is registered: `A1000k_6` → `TU010160.DLC`, 912,608 bytes, status words `02 00 00 00 00 00 02 00 01 00`.
- **Activation copies the DLC's audio to a fixed file.** `Downloads/TOY.AMF` is byte-identical to the AMF section of the registered DLC. Because there is a single `TOY.AMF`, **only one DLC's audio can be active at a time**.

## Upload over BLE [ctxis]

1. `0x50 0x00 <size u24 BE> <slot> <name 12 B> 00 00` on the GeneralPlus characteristic. Furby replies `24 02` when it is ready to receive.
2. Send the file in 20-byte writes to the file characteristic `dab90758…`. PyFluff and bluefluff pace them at one write every 5 ms, about 4 kB/s.
3. Furby replies `24 05` when the file is complete.
4. Load with `0x60 <slot>`, then activate with `0x61`. `0x74 <slot>` deletes a slot.

The debug screen shows one number per slot: 0 empty, 1 receiving or failed, 2 uploaded, 3 active.

## Open questions (help wanted)

- [ ] Does playback work with fluffkit's encoder on real hardware? (expected yes)
- [ ] Does a sequence stop when its audio ends, or follow the LPS/MTR clock?
- [ ] LPS and MTR time units
- [ ] MTR opcodes and cam position mapping (plan: test packs + video)
- [ ] The header counter field and the SEQ type word
- [ ] Maximum upload rate before Furby drops packets
- [x] One active DLC at a time: activation copies its AMF to `Downloads/TOY.AMF` (see DLC storage)
- [ ] Eye frame timing (38-frame playlist duration) and whether more than one custom animation per pack is possible
