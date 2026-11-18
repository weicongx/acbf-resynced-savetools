# AC Black Flag Resynced save tools

Tools to unpack, edit and repack *Assassin's Creed Black Flag Resynced* PC saves.
The goal is a save edit that grants all treasure-map rewards and marks every map as found and completed.
See [FORMAT.md](FORMAT.md) for the reverse-engineered format.

## Status

- Decrypt, decompress, recompress and re-checksum: done. Rebuilt saves load in game.
- Treasure maps: done. `treasure_mod.py` completes the 23 buried-chest maps and the 5 restored maps:
  rewards granted (ship parts go to the ship's inventory), chests marked dug, maps finished, counter updated,
  codex entries marked found and completed.
  Verified in game.
- Not handled: Blackbeard's Treasure (quest-driven) and the Map of Shipwreck (underwater chest; its chest
  and reward were not found in the game data).

## Setup

These files are not in the repo (see `.gitignore`):

- `tools/oo2core_5_win64.dll`: Oodle 2.5, used only for **compressing**. Many games ship this DLL;
  copy it from one you own. It is proprietary, so it is not included here.
- `tools/ooztool.exe`: build it with `cargo build --release` in `ooztool/`, then copy
  `ooztool/target/release/ooztool.exe` to `tools/`.
- `save_backup_2026-11-17/`: backups of the original saves, kept locally.

Python 3 on Windows (uses `ctypes` + the Oodle DLL).

## Usage

```bash
# unpack: writes decrypted.bin, secNN_<offset>.bin (decompressed sections) and index.tsv
tools/ooztool.exe "ACBlackFlag[ManualSave06].save" work/ManualSave06

# compare two unpacked saves section by section
python tools/diff.py work/BeforeSave work/AfterSave

# repack after editing secNN_*.bin files in work/Edited (a copy of work/ManualSave06)
python tools/pack.py "ACBlackFlag[ManualSave06].save" work/Edited out.save --pristine work/ManualSave06
```

### Treasure maps

The map, chest and reward IDs come from the game's own data, so build the table from your install
(the output is derived from game files; keep it out of the repo):

```bash
# 1. find and dump decoded blocks: the reward data block (search for a map item ID, 8 bytes little endian)
#    and the world blocks with the dig spots (text "CIN - Buried Chest")
tools/ooztool.exe scan <file.forge> 8c579e4419020000 work/forge/rewards
tools/ooztool.exe scan <file.forge> 43494e202d20427572696564204368657374 work/forge/world

# 2. join them into a map -> chests -> reward bundles table. Dig spots are spread over several
#    .forge files: scan each and pass every world dump folder; a map with no dig spot found is marked "missing"
#    --defs adds each map's codex entry; pass the definitions block that contains the codex entries
#    (class 854eb936, found the same way by scanning for a map item ID)
python tools/treasure_db.py work/forge/rewards/<block>.bin work/forge/world --defs=work/forge/defs/<block>.bin > work/forge/treasure.json

# 3. apply to an unpacked save, then repack it as above
python tools/treasure_mod.py work/ManualSave06 work/forge/treasure.json work/Edited --dry
python tools/treasure_mod.py work/ManualSave06 work/forge/treasure.json work/Edited
```

`treasure_mod.py` skips maps that are already dug, skips the generic barrel-loot bundles near dig spots,
and sets the save time to now so the new slot is not shown as a twin of the source save.
New item records are cloned from the closest existing item (most shared leading hex digits).
If an item has no good match, name a template with `--like=ITEM:TEMPLATE` (both hex IDs, the template must be
an item already in the save, of the same kind). The robes from the restored maps need `--like=0x21ec09648e6:0x2317c952c68`. The `MAPS` list in `treasure_db.py` selects which maps are included.

`pack.py` copies unchanged sections byte-for-byte, re-encodes only the edited ones and recomputes both checksums.
Packing with no edits reproduces the original file exactly.

Always edit a copy and load it from a spare slot. Never overwrite your only save.

## Files

| Path | Purpose |
|---|---|
| `ooztool/` | Rust unpacker (decrypt + walk sections + Kraken decompress via `oozextract`); `scan` / `forge` decode game `.forge` blocks |
| `tools/pack.py` | Repacker: Kraken compress (Oodle DLL), Adler-32 chunk checksums, CRC-32/CRC-32C seal, XOR |
| `tools/diff.py` | Section-aware diff of two unpacked saves |
| `tools/diff2.py` | Resynchronising byte diff of one section that changed size |
| `tools/anvil.py` | Parser and editor for the object tree inside a section (keeps every size field consistent) |
| `tools/treasure_db.py` | Builds the treasure-map table (maps, chests, reward bundles) from dumped game-data blocks |
| `tools/treasure_mod.py` | Applies the table to a save: rewards, dug chests, finished maps, treasure counter, codex |
| `tools/crcsolve.py` | Detects CRCs with unknown init/xorout across several files (GF(2) solve) |
| `tools/crcparams.py` | Solves and verifies the save's checksum constants |
| `tools/hashes.py` | Reference hash implementations used during the search |
