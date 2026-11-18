"""Complete every treasure map in an unpacked save: grant the chest rewards, mark each
chest as dug, and move every map to the "finished" state.

usage: treasure_mod.py <unpacked_in> <treasure.json> <unpacked_out> [--dry] [--like=ITEM:TEMPLATE ...]

treasure.json comes from treasure_db.py. Only the per-map reward bundles are granted
(generic barrel-loot bundles shared between dig spots are skipped).

What a real dig changes (from before/after saves), and what this script does:
  sec17  looted set (prop 72b4497b, sorted by u64 handle) gets the chest handle with
         an index into list 5073cb67, which gets a 189-byte loot record (the same for
         every treasure chest) -> same here.
  sec10  player inventory (ship parts go to the ship's own list ba66ca99 / 1d67d592):
           5cab0626 = items owned now, 9e3b0a59 = items ever acquired (record per item),
           0dc15c5d / 51ffa18a = quantity entries for those two lists (by instance id).
         A map that is owned now has a record in both lists; a finished map only in the
         "ever" list. Digging turns the owned map record into the reward record and
         adds the reward to the "ever" list; reales go to the reales quantity entries.
  sec23  counter 0e9fade4 (next to 5b6a6f41 = 0x2335c72bd7b) counts dug treasures.
"""
import sys, os, json, glob, shutil, struct, random, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import anvil

REALES = 0x212f76c6dee
LOOTED, LOOT_LIST = 0x72b4497b, 0x5073cb67
F_HANDLE, F_LOOTIDX = 0xbb46d388, 0x2529715f
P_OWNED, P_EVER, P_QOWNED, P_QEVER = 0x5cab0626, 0x9e3b0a59, 0x0dc15c5d, 0x51ffa18a
P_SHIP, P_QSHIP = 0xba66ca99, 0x1d67d592    # the ship's own item list + its quantity entries
F_DEF, F_ID, F_QOBJ, F_QTY, F_ORDER, F_FLAG = 0x7b17de42, 0x893a928f, 0x6252fdff, 0x66857460, 0x2727649d, 0x53ae02a5
STAT_ID, STAT_VAL, TREASURE_STAT = 0x5b6a6f41, 0x0e9fade4, 0x2335c72bd7b

rng = random.SystemRandom()


def kid(n, prop):
    for c in n.children:
        if c.kind == 'prop' and c.prop == prop:
            return c


def val(d, p):
    return d[p.start + 17:p.end]


def u(b):
    return int.from_bytes(b, 'little')


def setval(buf, base, prop_node, raw):
    """write raw into prop_node's value; buf is a copy of the bytes starting at `base`"""
    o = prop_node.start + 17 - base
    assert len(raw) == prop_node.end - prop_node.start - 17
    buf[o:o + len(raw)] = raw


def sec_path(d, n):
    return glob.glob(os.path.join(d, f'sec{n:02d}_*.bin'))[0]


# ---------------------------------------------------------------- sec17
def looted_set(d):
    r = anvil.parse_section(d)
    s, l = anvil.find_props(r, LOOTED)[0], anvil.find_props(r, LOOT_LIST)[0]
    return s, l


def mark_dug(d, chests):
    s, l = looted_set(d)
    have = {u(val(d, kid(e, F_HANDLE))): e for e in s.children}
    # template: the loot record of an already dug treasure chest
    tpl_elem = next(e for h, e in have.items() if h in chests['dug'])
    tpl_rec = bytes(d[l.children[u(val(d, kid(tpl_elem, F_LOOTIDX)))].start:
                      l.children[u(val(d, kid(tpl_elem, F_LOOTIDX)))].end])
    tpl_el = bytes(d[tpl_elem.start:tpl_elem.end])
    added = 0
    for h in sorted(chests['todo']):
        s, l = looted_set(d)
        hs = [u(val(d, kid(e, F_HANDLE))) for e in s.children]
        if h in hs:
            continue
        idx = len(l.children)
        anvil.splice(d, l, l.end, tpl_rec, 1)              # list comes after the set
        s, l = looted_set(d)
        el = bytearray(tpl_el)
        # patch handle / index by their offsets inside the template element
        rel_h = kid(tpl_elem, F_HANDLE).start + 17 - tpl_elem.start
        rel_i = kid(tpl_elem, F_LOOTIDX).start + 17 - tpl_elem.start
        el[rel_h:rel_h + 8] = struct.pack('<Q', h)
        el[rel_i:rel_i + 4] = struct.pack('<I', idx)
        pos = next((e.start for e in s.children if u(val(d, kid(e, F_HANDLE))) > h), s.end)
        anvil.splice(d, s, pos, bytes(el), 1)
        added += 1
    return added


# ---------------------------------------------------------------- sec10
class Inv:
    def __init__(self, d):
        self.d = d
        self.parse()

    def parse(self):
        d = self.d
        r = anvil.parse_section(d)
        big = lambda p: max(anvil.find_props(r, p), key=lambda n: n.end - n.start)
        self.owned, self.ever = big(P_OWNED), big(P_EVER)
        self.qowned = next(n for n in anvil.find_props(r, P_QOWNED) if n.start == self.ever.end)
        self.qever = next(n for n in anvil.find_props(r, P_QEVER) if n.start == self.qowned.end)
        sh = anvil.find_props(r, P_SHIP)[0]
        self.ship = sh
        self.qship = next(c for c in sh.parent.children if c.kind == 'prop' and c.prop == P_QSHIP)
        arr = lambda p: p.children[0].children[0]
        self.A = {k: arr(getattr(self, k)) for k in ('owned', 'ever', 'qowned', 'qever', 'ship', 'qship')}

    def recs(self, k):
        """owned/ever/ship -> [(def, id, node)]; qowned/qever/qship -> {id: node}"""
        d = self.d
        if k in ('owned', 'ever', 'ship'):
            return [(u(val(d, kid(e, F_DEF))), u(val(d, kid(e, F_ID))), e) for e in self.A[k].children]
        return {u(val(d, kid(e, F_ID))): e for e in self.A[k].children}

    def ids(self):
        s = set()
        for k in ('owned', 'ever', 'ship'):
            s |= {i for _, i, _ in self.recs(k)}
        return s

    def new_id(self):
        used = self.ids()
        while True:
            i = rng.getrandbits(32)
            if i and i not in used:
                return i

    def append(self, k, data):
        a = self.A[k]
        anvil.splice(self.d, a, a.end, data, 1)
        self.parse()

    def remove(self, k, node):
        anvil.replace(self.d, self.A[k], node.start, node.end, b'', -1)
        self.parse()

    def clone_rec(self, tpl, new_def, new_id):
        d = self.d
        b = bytearray(d[tpl.start:tpl.end])
        setval(b, tpl.start, kid(tpl, F_DEF), struct.pack('<Q', new_def))
        setval(b, tpl.start, kid(tpl, F_ID), struct.pack('<I', new_id))
        return bytes(b)

    def clone_q(self, tpl, new_id, qty, order=None, flag=None):
        d = self.d
        b = bytearray(d[tpl.start:tpl.end])
        setval(b, tpl.start, kid(tpl, F_ID), struct.pack('<I', new_id))
        setval(b, tpl.start, kid(tpl, F_QTY), struct.pack('<I', qty))
        qo = kid(tpl, F_QOBJ).children[0]
        if order is not None:
            setval(b, tpl.start, kid(qo, F_ORDER), struct.pack('<I', order))
        if flag is not None:
            setval(b, tpl.start, kid(qo, F_FLAG), bytes([flag]))
        return bytes(b)

    def next_order(self):
        d = self.d
        return 1 + max(u(val(d, kid(kid(e, F_QOBJ).children[0], F_ORDER))) for e in self.recs('qowned').values())

    def template(self, item, like=None):
        """(record, shared hex digits, list) of the existing item whose def shares the longest
        hex prefix (same family), or of item `like` when given. The ship list wins ties: ship
        parts (sails, wheels, crew outfits...) belong in the ship's inventory, not the player's."""
        if like is not None:
            for k in ('ship', 'ever', 'owned'):
                for df, _, e in self.recs(k):
                    if df == like:
                        return e, 11, k
            raise SystemExit(f'template item {like:#x} not in save')
        best, bl, bk = None, -1, None
        for k in ('ship', 'ever', 'owned'):
            for df, _, e in self.recs(k):
                a, b = f'{df:011x}', f'{item:011x}'
                l = next((i for i in range(11) if a[i] != b[i]), 11)
                if l > bl:
                    best, bl, bk = e, l, k
        return best, bl, bk

    def add_qty(self, k, id_, delta, order=None):
        d = self.d
        e = self.recs(k)[id_]
        q = kid(e, F_QTY)
        struct.pack_into('<I', d, q.start + 17, u(val(d, q)) + delta)
        if order is not None:
            o = kid(kid(e, F_QOBJ).children[0], F_ORDER)
            struct.pack_into('<I', d, o.start + 17, order)


def grant(inv, maps, rewards, reales, log, like=None):
    like = like or {}
    d = inv.d
    map_tpl = next((e for df, _, e in inv.recs('ever') if df in maps), None)
    q_tpl_owned = next(e for e in inv.recs('qowned').values() if u(val(d, kid(e, F_QTY))) == 1)
    q_tpl_ever = next(e for e in inv.recs('qever').values() if u(val(d, kid(e, F_QTY))) == 1)
    q_tpl_owned_b = bytes(d[q_tpl_owned.start:q_tpl_owned.end])
    q_tpl_ever_b = bytes(d[q_tpl_ever.start:q_tpl_ever.end])
    map_tpl_b = bytes(d[map_tpl.start:map_tpl.end]) if map_tpl is not None else None

    def qclone(tpl_b, k, new_id, qty, order=None, flag=None):
        # re-locate a node with identical bytes to use as a parse template
        tpl = next(e for e in inv.recs(k).values() if bytes(d[e.start:e.end]) == tpl_b)
        return inv.clone_q(tpl, new_id, qty, order, flag)

    # 1. maps: finished = in "ever" (with quantity entry), not owned
    ever_defs = {df for df, _, _ in inv.recs('ever')}
    for m in maps:
        if m not in ever_defs:
            tpl = next(e for df, _, e in inv.recs('ever') if bytes(d[e.start:e.end]) == map_tpl_b)
            i = inv.new_id()
            inv.append('ever', inv.clone_rec(tpl, m, i))
            inv.append('qever', qclone(q_tpl_ever_b, 'qever', i, 1))
            log.append(f'map {m:#x}: added to collected list')
    for m in maps:
        for df, i, e in inv.recs('owned'):
            if df == m:
                q = inv.recs('qowned').get(i)
                if q is not None:
                    inv.remove('qowned', q)
                e = next(e for df2, i2, e in inv.recs('owned') if i2 == i)
                inv.remove('owned', e)
                log.append(f'map {m:#x}: removed from inventory (finished)')
                break
    # 2. reward items
    owned_defs = {df for k in ('owned', 'ship') for df, _, _ in inv.recs(k)}
    for item in rewards:
        if item in owned_defs:
            log.append(f'item {item:#x}: already owned, skipped')
            continue
        tpl, l, where = inv.template(item, like.get(item))
        size = tpl.end - tpl.start
        tdef = u(val(d, kid(tpl, F_DEF)))
        if where == 'ship':
            # ship parts: one record in the ship list + a quantity entry, nothing in the player lists
            q_tpl = next(iter(inv.recs('qship').values()))
            i1 = inv.new_id()
            inv.append('ship', inv.clone_rec(tpl, item, i1))
            q_tpl = next(iter(inv.recs('qship').values()))
            inv.append('qship', inv.clone_q(q_tpl, i1, 1))
            log.append(f'item {item:#x}: granted to the ship ({size}-byte record, template {tdef:#x}, {l} hex digits shared)')
            continue
        i1, order = inv.new_id(), inv.next_order()
        inv.append('owned', inv.clone_rec(tpl, item, i1))
        inv.append('qowned', qclone(q_tpl_owned_b, 'qowned', i1, 1, order, 0))
        tpl = next(e for df, _, e in inv.recs('ever') + inv.recs('owned') if df == tdef)
        i2 = inv.new_id()
        inv.append('ever', inv.clone_rec(tpl, item, i2))
        inv.append('qever', qclone(q_tpl_ever_b, 'qever', i2, 1))
        log.append(f'item {item:#x}: granted ({size}-byte record, template {tdef:#x}, {l} hex digits shared)')
    # 3. reales: current + lifetime totals
    if reales:
        oid = next(i for df, i, _ in inv.recs('owned') if df == REALES)
        eid = next(i for df, i, _ in inv.recs('ever') if df == REALES)
        before = u(val(d, kid(inv.recs('qowned')[oid], F_QTY)))
        inv.add_qty('qowned', oid, reales, inv.next_order())
        inv.add_qty('qever', eid, reales)
        log.append(f'reales: {before} -> {before + reales}')


# ---------------------------------------------------------------- sec23
def set_treasure_stat(d, n):
    r = anvil.parse_section(d)
    for p in anvil.find_props(r, STAT_VAL):
        sid = kid(p.parent, STAT_ID)
        if sid is not None and u(val(d, sid)) == TREASURE_STAT:
            old = u(val(d, p))
            struct.pack_into('<I', d, p.start + 17, max(old, n))
            return old
    raise SystemExit('treasure counter not found')


def main():
    a = [x for x in sys.argv[1:] if not x.startswith('--')]
    dry = '--dry' in sys.argv
    # --like=ITEM:TEMPLATE  clone ITEM's records from TEMPLATE (an item already in the save)
    like = {int(k, 16): int(v, 16) for x in sys.argv if x.startswith('--like=')
            for k, v in [x[7:].split(':')]}
    src, tj, dst = a
    T = [t for t in json.load(open(tj)) if not t.get('missing')]
    maps = [int(t['map'], 16) for t in T]
    if not dry:
        if os.path.exists(dst):
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
    out = src if dry else dst

    d17 = bytearray(open(sec_path(out, 17), 'rb').read())
    s, _ = looted_set(d17)
    dug_handles = {u(val(d17, kid(e, F_HANDLE))) for e in s.children}
    todo, rewards, reales, dug = [], [], 0, []
    # generic loot bundles (barrels/crates near a dig spot): the 1f3b3... family, or any
    # bundle that shows up at more than one dig spot. The rest are per-map rewards.
    seen = {}
    for t in T:
        for b in t['bundles']:
            seen[b] = seen.get(b, 0) + 1
    generic = {b for b, n in seen.items() if n > 1 or int(b, 16) >> 24 == 0x1f3b3}
    for t in T:
        chests = [int(c, 16) for c in t['chests']]
        if all(c in dug_handles for c in chests):
            dug += chests
            continue
        todo += chests
        for b, entries in t['bundles'].items():
            if b in generic:
                continue
            for e in entries:
                if e['item'] == 'reales':
                    reales += e['qty']
                else:
                    rewards.append(int(e['item'], 16))
    log = [f'{len(maps)} maps, {len(dug)} already dug, {len(todo)} chests to dig, '
           f'{len(rewards)} reward items, {reales} reales']
    log.append(f'sec17: {mark_dug(d17, {"dug": set(dug), "todo": set(todo)})} chests marked dug')

    d10 = bytearray(open(sec_path(out, 10), 'rb').read())
    grant(Inv(d10), maps, rewards, reales, log, like)

    d23 = bytearray(open(sec_path(out, 23), 'rb').read())
    old = set_treasure_stat(d23, len(maps))
    log.append(f'sec23 treasure counter: {old} -> {max(old, len(maps))}')

    for n, d in ((10, d10), (17, d17), (23, d23)):
        r = anvil.parse_section(d)
        assert r.end == len(d), f'sec{n} does not re-parse'
        if not dry:
            open(sec_path(out, n), 'wb').write(d)
    # sec00 0x2b = save time (unix u32). A copy that keeps the source's time shows up in the
    # load menu as a twin of the source save, so stamp it with the current time.
    if not dry:
        d00 = bytearray(open(sec_path(out, 0), 'rb').read())
        struct.pack_into('<I', d00, 0x2b, int(time.time()))
        open(sec_path(out, 0), 'wb').write(d00)
        log.append('sec00 save time set to now')
    print('\n'.join(log))


if __name__ == '__main__':
    main()
