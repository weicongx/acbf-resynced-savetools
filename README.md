# AC Black Flag Resynced save tools

Tools to unpack, edit and repack *Assassin's Creed Black Flag Resynced* PC saves.
The goal is a save edit that grants all treasure-map rewards and marks every map as found and completed.
See [FORMAT.md](FORMAT.md) for the reverse-engineered format.

## Status

- Decrypt, decompress, recompress and re-checksum: done. Rebuilt saves load in game.
- Treasure-map data: not located yet (needs before/after saves).

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

`pack.py` copies unchanged sections byte-for-byte, re-encodes only the edited ones and recomputes both checksums.
Packing with no edits reproduces the original file exactly.

Always edit a copy and load it from a spare slot. Never overwrite your only save.

## Files

| Path | Purpose |
|---|---|
| `ooztool/` | Rust unpacker (decrypt + walk sections + Kraken decompress via `oozextract`) |
| `tools/pack.py` | Repacker: Kraken compress (Oodle DLL), Adler-32 chunk checksums, CRC-32/CRC-32C seal, XOR |
| `tools/diff.py` | Section-aware diff of two unpacked saves |
| `tools/crcsolve.py` | Detects CRCs with unknown init/xorout across several files (GF(2) solve) |
| `tools/crcparams.py` | Solves and verifies the save's checksum constants |
| `tools/hashes.py` | Reference hash implementations used during the search |
