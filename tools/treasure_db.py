"""Build the treasure-map table from decoded game-data blocks.

Inputs are blocks dumped by `ooztool scan` (see README):
  - the item/reward data block (contains the treasure-map item definitions, the
    trigger -> reward-bundle table and the reward bundles),
  - world blocks containing "CIN - Buried Chest" (one dig spot per map).

Links, as found in the data:
  dig spot block:  property efdfe312 = required item (the treasure map), e34a2064 = chest entity,
                   plus references to trigger objects
  reward block:    table entries  <u64 trigger> cbf9a762 01 <u32 n> <n bytes> 01 <u64 bundle>
                   bundle props are tagged with the 6-byte owner id (bundle << 4 | bit 47):
                     b48f2e3b 01 <u32 quantity>, optionally followed by 333747b5 01 <u64 item>
                     (a quantity with no item is reales)
  definitions block (optional, --defs): codex entries, class 854eb936, each a small rule graph
                   whose "discovered" rule tests efdfe312 = the map item. The codex "Maps" list is
                   a run of  01 <u64 entry>  items naming every treasure entry in display order.

usage: treasure_db.py <reward_block.bin> <world_dir> [<world_dir> ...] [--defs=<defs_block.bin>]  > treasure.json
"""
import json, re, struct, sys, glob, os

MAPS = [0x219449e578c, 0x219449e57ca, 0x219449e57ce, 0x219449e57d6, 0x219449e57da, 0x219449e57de,
        0x219449e57e2, 0x219449e57ea, 0x219449e57ee, 0x219449e57f2, 0x219449e57f6, 0x219449e57fa,
        0x219449e57fe, 0x219449e5902, 0x219449e5906, 0x219449e590a, 0x219449e590e, 0x219449e5912,
        0x219449e5916, 0x219449e591a, 0x219449e5ca8, 0x219449e5d5e, 0x22d1abd2264,
        # restored maps
        0x2317c94f5d5, 0x2317c94f820, 0x2317c94f8ac, 0x2317c94f8b3, 0x2317c94f8ba]


def q(d, p):
    return struct.unpack_from('<Q', d, p)[0]


def owner_tag(h):
    b = bytearray(struct.pack('<Q', h << 4)[:6])
    b[5] |= 0x80
    return bytes(b)


def trigger_table(rd):
    t = {}
    for m in re.finditer(re.escape(bytes.fromhex('cbf9a76201')), rd):
        p = m.start()
        key = q(rd, p - 8)
        n = struct.unpack_from('<I', rd, p + 5)[0]
        v = p + 9 + n
        if n < 0x100 and v + 9 <= len(rd) and rd[v] == 1:
            t.setdefault(key, set()).add(q(rd, v + 1))
    return t


def bundle(rd, b):
    tag = owner_tag(b)
    hits = [m.start() for m in re.finditer(re.escape(tag + bytes.fromhex('b48f2e3b01')), rd)]
    out = []
    for k, p in enumerate(hits):
        qty = struct.unpack_from('<I', rd, p + 11)[0]
        stop = hits[k + 1] if k + 1 < len(hits) else p + 0x80
        seg = rd[p:stop]
        i = seg.find(bytes.fromhex('333747b501'))
        item = q(seg, i + 5) if i >= 0 else None
        out.append({'qty': qty, 'item': hex(item) if item else 'reales'})
    return out


CODEX_CLS = bytes.fromhex('36b94e85')


def codex_entries(dd, maps):
    """map item -> (codex entry id, position in the codex Maps list)"""
    owner = {}
    for mp in maps:
        for m in re.finditer(re.escape(bytes.fromhex('efdfe3120000') + struct.pack('<Q', mp)), dd):
            o = dd.rfind(CODEX_CLS, 0, m.start())
            owner.setdefault(mp, q(dd, o - 8))
    # the list: a run of 01 <u64> items containing the entries
    order = []
    if owner:
        first = next(iter(owner.values()))
        for m in re.finditer(re.escape(b'' + struct.pack('<Q', first)), dd):
            p = m.start()
            while p >= 9 and dd[p - 9] == 1:
                p -= 9
            run = []
            while p + 9 <= len(dd) and dd[p] == 1:
                run.append(q(dd, p + 1))
                p += 9
            if set(owner.values()) <= set(run):
                order = run
                break
    return {mp: (e, order.index(e) if e in order else None) for mp, e in owner.items()}


def main():
    opts = [x for x in sys.argv[1:] if x.startswith('--')]
    args = [x for x in sys.argv[1:] if not x.startswith('--')]
    defs = next((x[7:] for x in opts if x.startswith('--defs=')), None)
    rd = open(args[0], 'rb').read()
    table = trigger_table(rd)
    codex = codex_entries(open(defs, 'rb').read(), MAPS) if defs else {}
    spots = {}
    for d in args[1:]:
        for f in sorted(glob.glob(os.path.join(d, '*.bin'))):
            wd = open(f, 'rb').read()
            if b'CIN - Buried Chest' not in wd:
                continue
            maps = {q(wd, m.end()) for m in re.finditer(re.escape(bytes.fromhex('f8fb00000000efdfe3120000')), wd)}
            maps &= set(MAPS)
            chests = {q(wd, m.end() + 2) for m in re.finditer(re.escape(bytes.fromhex('f8fb00000000e34a2064')), wd)}
            refs = {q(wd, i) for i in range(len(wd) - 8) if wd[i - 1] in (0, 1) and q(wd, i) in table}
            for mp in maps:
                s = spots.setdefault(mp, {'chests': set(), 'bundles': set(), 'blocks': set()})
                s['chests'] |= chests
                s['blocks'].add(os.path.basename(d) + '/' + os.path.basename(f))
                for r in refs:
                    s['bundles'] |= table[r]
    out = []
    for mp in MAPS:
        s = spots.get(mp)
        if not s:
            out.append({'map': hex(mp), 'missing': True})
            continue
        out.append({'map': hex(mp), 'chests': sorted(hex(c) for c in s['chests']),
                    'bundles': {hex(b): bundle(rd, b) for b in sorted(s['bundles'])},
                    'blocks': sorted(s['blocks'])})
        if mp in codex:
            out[-1]['codex'] = hex(codex[mp][0])
            out[-1]['codex_pos'] = codex[mp][1]
    json.dump(out, sys.stdout, indent=1)


if __name__ == '__main__':
    main()
