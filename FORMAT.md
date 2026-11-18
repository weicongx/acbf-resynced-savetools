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

## Save time

sec00 offset `0x2b` is the save time as a `u32` unix timestamp. Copying a save to another slot without changing it
gives two entries with the same time, and the load menu treats them as one save, so stamp edited copies with a new time.

## Treasure-map state

Found with before/after saves around digging up chests (`tools/diff.py`, `tools/diff2.py`); `tools/anvil.py` parses
the object tree. Property hashes below are `u32` values as they appear in the data.

| Where | What |
|---|---|
| sec10 `5cab0626` | Player items owned now (one record per item instance) |
| sec10 `9e3b0a59` | Player items ever acquired |
| sec10 `0dc15c5d` / `51ffa18a` | Quantity entries for the two lists above, keyed by instance ID |
| sec10 `b1d8f7de` | Player equipped slots |
| sec10 object `3a905dd6` | Ship inventory: `ba66ca99` item records, `1d67d592` quantity entries, `7de2139d` equipped slots |
| sec17 `72b4497b` | Looted set: chest handle (sorted by `u64`) plus an index into list `5073cb67`, which holds a 189-byte loot record |
| sec23 `0e9fade4` | Count of dug treasures (next to `5b6a6f41`) |
| sec42 `88d00b34` | Codex: entries `{8f1a0973 = u64 codex entry, 6fb2825d = states}`. States are `4d36c371` (seen flag `a8132e86`) and timestamped events `282e8f8a {531a26a9 = event, 8e6dea49 = unix time}` |

- A map that is carried has a record in both the "owned" and "ever" lists; a finished map is only in "ever".
  Digging turns the owned map record into the reward record and adds the reward to "ever".
- A treasure map's codex entry gets event `7d430c0e` when the map is picked up and `3f9a97b2` when its chest is dug.
  Entries that were never found are absent. In the game data each codex entry (class `854eb936`) is a small rule
  graph whose "found" rule tests `efdfe312` = the map item; the codex "Maps" list (a run of `01 <u64 entry>`)
  names all 30 treasure entries in display order, and the save keeps them in that order.
- Ship parts (sails, wheels, crew outfits) only show in game when they are in the ship inventory, not the player lists.
- Item records come in three sizes (305, 377 and 434 bytes) depending on the item's category in the game data;
  new records are cloned from an existing item of the same kind.
- Reward bundles in the game data: entries `<u64 trigger> cbf9a762 01 <u32 n> <n bytes> 01 <u64 bundle>`; bundle
  properties are tagged with the 6-byte owner ID and hold a quantity (`b48f2e3b`) and optionally an item (`333747b5`).
  A quantity with no item is reales. Dig spots are world objects named `CIN - Buried Chest` with the required map in
  `efdfe312` and the chest entity in `e34a2064`.
