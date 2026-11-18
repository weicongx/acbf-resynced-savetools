"""Compare two unpacked saves section by section.

usage: diff.py <unpackedA> <unpackedB> [--max N]

Sections are matched by their 8-byte id (index.tsv), not by file offset.
For each changed section prints size change and the changed byte ranges
(merged when closer than 8 bytes), with a hex view of both sides.
"""
import sys, os, glob, argparse, difflib


def load(d):
    rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(d, 'index.tsv'))][1:]
    files = sorted(glob.glob(os.path.join(d, 'sec*.bin')))
    return {r[2]: (int(r[0]), open(f, 'rb').read()) for r, f in zip(rows, files)}


def ranges(a, b):
    """changed ranges for equal-length buffers"""
    out = []; i = 0; n = len(a)
    while i < n:
        if a[i] != b[i]:
            j = i
            while j < n and (a[j] != b[j] or any(a[k] != b[k] for k in range(j, min(j + 8, n)))):
                j += 1
            out.append((i, j)); i = j
        else:
            i += 1
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('a'); ap.add_argument('b'); ap.add_argument('--max', type=int, default=12)
    a = ap.parse_args(); A = load(a.a); B = load(a.b)
    for k in A.keys() | B.keys():
        if k not in A or k not in B:
            print('section', k, 'only in', 'A' if k in A else 'B'); continue
    for k, (ia, da) in sorted(A.items(), key=lambda x: x[1][0]):
        if k not in B: continue
        ib, db = B[k]
        if da == db: continue
        print(f'== sec{ia:02d} id={k} size {len(da)} -> {len(db)} ({len(db) - len(da):+d})')
        if len(da) == len(db):
            rs = ranges(da, db)
            print(f'   {len(rs)} changed ranges')
            for s, e in rs[:a.max]:
                lo = max(0, s - 4); hi = min(len(da), e + 4)
                print(f'   {s:#08x}+{e - s:<4} A {da[lo:hi].hex(" ")}')
                print(f'   {"":14} B {db[lo:hi].hex(" ")}')
        else:
            m = min(len(da), len(db))
            p = next((i for i in range(m) if da[i] != db[i]), m)
            s = next((i for i in range(m - p) if da[-1 - i] != db[-1 - i]), m - p)
            ma, mb = da[p:len(da) - s], db[p:len(db) - s]
            print(f'   differs in A[{p:#x}:{len(da) - s:#x}] vs B[{p:#x}:{len(db) - s:#x}] ({len(ma)} vs {len(mb)} bytes)')
            if len(ma) <= 96 and len(mb) <= 96:
                print(f'   A {ma.hex(" ")}'); print(f'   B {mb.hex(" ")}')


if __name__ == '__main__':
    main()
