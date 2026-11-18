# AC Black Flag Resynced save format

Reverse-engineered 2026-11-17 against build `c9817950_d18488575_s256377 (PC)`, save version `TU4 (1.0.6)`.
Everything below was verified by rebuilding saves that the game loads.

## File

Save slots are files named `ACBlackFlag[ManualSaveNN].save` / `ACBlackFlag[AutoSaveNN].save` in the game's save folder
(the exact location depends on how the game is installed and launched).

| Offset | Size | Content |
|---|---|---|
| `0x00` | `0x28` | Plaintext wrapper: `u32 0x24`, then zeros |
| `0x28` | to end | XOR-encrypted payload (below) |

The game's save manifest (`%LOCALAPPDATA%\Ubisoft\Assassin's Creed Black Flag Resynced\save\SaveStorageManifest-*.json`)
records each file as 44 bytes smaller: the 0x28 wrapper plus the 4-byte trailer.

## Encryption

Repeating 16-byte XOR key `93cc22c5e0fa46a3f2bc714aadb8abe1`, applied from `0x28` to the end of the file.
The key is aligned to the **end** of the file:

```
key_index(i) = (i + ((1 - file_length) mod 16)) mod 16
```

## Decrypted payload

| Offset | Content |
|---|---|
| `0x28` | magic `AC DB FE 00` |
| `0x2c` | `u32 0x36`, `u32 4`, `u32 0x2e` (constant) |
| `0x38` | `u32 X`: header checksum |
| `0x3c` | sections, back to back |
| `len-4` | `u32` trailer checksum |

### Checksums (both validated; a wrong value gives "Save file corrupted 0x71000003")

| Field | Algorithm | Range (decrypted) | init | xorout |
|---|---|---|---|---|
| X at `0x38` | CRC-32 (reflected, poly `04C11DB7`) | `[0x3c, len-4)` | `0x0B3C475D` | `0xFFFFFFFF` |
| trailer | CRC-32C (reflected, poly `1EDC6F41`) | `[0x28, len-4)` (includes X, so compute X first) | `0xF7986AF2` | `0x035BD250` |

The constants were recovered by solving `T = crc(init, data) ^ xorout` as an affine system over GF(2) across three genuine saves
(`tools/crcsolve.py`, `tools/crcparams.py`) and verified on all 16 saves.
Copying a save to another slot unchanged is accepted; the slot name is not part of either checksum.

### Section record (52 per save)

```
u8[8]  id               stable across saves
u32    size             4 + bytes from magic to end of section
u32    total            decompressed size
u8[8]  magic            33 AA FB 57 99 FA 04 10
u16    version          3
u8     type             5
u32    max_chunk        0x40000
chunks until `total` bytes are produced:
  compressed: u8 1, u32 comp, u32 uncomp, u32 adler32(comp, init 0), comp bytes (Oodle Kraken, header 8C 06)
  stored:     u8 0, u32 size, size bytes
```

Notes:
- Adler-32 here starts from 0, not the usual 1 (`zlib.adler32(data, 0)`).
- The game's Kraken streams need a modern decoder; Oodle 2.5 (`oo2core_5`) only decodes the smallest ones.
  `ooztool` uses the open-source `oozextract` crate instead.
- Oodle 2.5 can compress Kraken that the game accepts, but for tiny inputs it emits a non-Kraken stream (`8C 02`);
  `pack.py` stores those chunks raw instead.
- Section contents are serialized Anvil objects with hashed IDs and no readable names. Values often appear as
  a small property header ending in `00 0b` followed by the value.

## Section sizes (ManualSave06)

The largest sections (by decompressed size) are sec11 (3.7 MB), sec33 (707 KB), sec00 (627 KB), sec10 (493 KB) and sec09 (211 KB).
sec36 contains the strings `PlayerLevel` and DLC ids.

## Open work

Locating treasure-map state ("collected", "completed") and rewards. Plan: diff before/after saves around picking up a map
and digging up its chest (`tools/diff.py`), then find the full list of map and reward IDs.
