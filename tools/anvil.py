"""Parser / editor for the serialized object tree inside a decompressed save section.

Grammar (little endian), worked out from before/after saves:

  object   = hdr[14] u32 class, u32 lenA, u32 lenB, property*, u32 trailer
             lenB = bytes of the properties, lenA = 4 + lenB + 4
  property = u32 size, u32 prop_hash, u32 type_info, u16 flags, u8 type, u8 sub, u8 0x0b, value
             size counts everything after the size field
  value    = object                       when type == 0x13 (embedded object) or 0x16 (owned pointer)
           = u8 1, u32 count, element*    when type & 0x7f == 0x1d (array); elements are objects when sub == 0x0b
           = raw bytes otherwise (length implied by size)

Objects inside sub-0x0a arrays carry one extra header byte (15 instead of 14).
A section is one top-level object. Editing = splice bytes, then fix every size field
that encloses the splice point (property sizes, lenA/lenB of objects) and array counts.
"""
import struct

HDR = 14


class Node:
    __slots__ = ('hdr', 'kind', 'start', 'end', 'cls', 'prop', 'type', 'sub', 'children', 'parent', 'count_off', 'size_off')

    def __init__(self, kind, start, end, parent):
        self.kind, self.start, self.end, self.parent = kind, start, end, parent
        self.children = []
        self.cls = self.prop = self.type = self.sub = None
        self.count_off = self.size_off = None
        self.hdr = HDR

    def __repr__(self):
        h = lambda v: f'{v:08x}' if v is not None else '-'
        return f'<{self.kind} {self.start:#x}-{self.end:#x} cls={h(self.cls)} prop={h(self.prop)} type={self.type}>'


def u32(d, p):
    return struct.unpack_from('<I', d, p)[0]


def parse_object(d, p, parent=None, hdr=HDR):
    """object at p (pointing at its header: 14 bytes, 15 inside sub-0x0a arrays)."""
    n = Node('obj', p, None, parent)
    n.hdr = hdr
    n.cls = u32(d, p + hdr)
    lenA, lenB = u32(d, p + hdr + 4), u32(d, p + hdr + 8)
    if lenA < lenB + 8 or p + hdr + 8 + lenA > len(d):
        raise ValueError(f'bad object lens at {p:#x}: {lenA:#x} {lenB:#x}')
    q = p + hdr + 12
    stop = q + lenB
    while q < stop:
        c = parse_property(d, q, n)
        n.children.append(c)
        q = c.end
    if q != stop:
        raise ValueError(f'object at {p:#x} overran: {q:#x} != {stop:#x}')
    # lenA = 4 (lenB field) + lenB + extra block (usually just a 4-byte trailer)
    n.end = p + hdr + 8 + lenA
    return n


def parse_property(d, p, parent):
    size = u32(d, p)
    n = Node('prop', p, p + 4 + size, parent)
    n.prop, n.cls = u32(d, p + 4), u32(d, p + 8)
    n.type, n.sub = d[p + 14], d[p + 15]
    v = p + 17
    t = n.type & 0x7f
    if t in (0x13, 0x16) and size > 13:
        n.children.append(parse_object(d, v, n))
    elif t == 0x1d and n.sub in (0x0a, 0x0b) and size > 13:
        # arrays of objects; some sub-0x0a arrays hold other element kinds -> keep opaque
        n.count_off = v + 1
        cnt = u32(d, v + 1)
        q = v + 5
        for _ in range(cnt):
            e = parse_object(d, q, n, HDR + (n.sub == 0x0a))
            n.children.append(e)
            q = e.end
        if q != n.end:
            raise ValueError(f'array at {p:#x} size mismatch {q:#x} != {n.end:#x}')
    elif t == 0x1d:
        n.count_off = v + 1
    return n


def parse_section(d):
    return parse_object(d, 0)


def walk(n):
    yield n
    for c in n.children:
        yield from walk(c)


def find_props(root, prop_hash):
    return [n for n in walk(root) if n.kind == 'prop' and n.prop == prop_hash]


def splice(d: bytearray, node: Node, at: int, data: bytes, count_delta=0):
    """Insert `data` at offset `at` inside `node` (an array prop or object) and fix all
    enclosing sizes. count_delta adjusts the array count of `node` if it is an array."""
    return replace(d, node, at, at, data, count_delta)


def replace(d: bytearray, node: Node, a: int, b: int, data: bytes, count_delta=0):
    """Replace d[a:b] (inside `node`) with `data` and fix all enclosing sizes.
    Node offsets are stale afterwards: re-parse before the next edit."""
    delta = len(data) - (b - a)
    d[a:b] = data
    n = node
    if count_delta and n.count_off is not None:
        struct.pack_into('<I', d, n.count_off, u32(d, n.count_off) + count_delta)
    while n is not None:
        if n.kind == 'prop':
            struct.pack_into('<I', d, n.start, u32(d, n.start) + delta)
        else:
            o = n.start + n.hdr
            struct.pack_into('<II', d, o + 4, u32(d, o + 4) + delta, u32(d, o + 8) + delta)
        n = n.parent
    return d


if __name__ == '__main__':
    import sys, glob
    for f in sys.argv[1:]:
        for s in sorted(glob.glob(f)):
            d = open(s, 'rb').read()
            try:
                r = parse_section(d)
                ok = r.end == len(d)
                print(f'{s}: {"OK" if ok else "END MISMATCH"} end={r.end:#x} len={len(d):#x} nodes={sum(1 for _ in walk(r))}')
            except Exception as e:
                print(f'{s}: FAIL {e}')
