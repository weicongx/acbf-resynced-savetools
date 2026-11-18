"""Resynchronising diff for one section that changed size.

usage: diff2.py <A.bin> <B.bin> [--ctx 24] [--max 40]

Walks both buffers; on a mismatch, finds where they line up again by searching for
the next 32 bytes of one side in a window of the other. Prints changed / inserted /
deleted spans with hex.
"""
import sys, argparse


def hexs(b, n=96):
    s = b[:n].hex(' ')
    return s + (' ...' if len(b) > n else '')


def resync(a, b, i, j, win=1 << 16, k=32):
    best = None
    for step in range(0, win, 1):
        # A advanced by step, B searched / B advanced by step, A searched
        if i + step + k <= len(a):
            pat = a[i + step:i + step + k]
            jj = b.find(pat, j, j + win + k)
            if jj >= 0:
                cand = (step + (jj - j), i + step, jj)
                if best is None or cand[0] < best[0]: best = cand
        if j + step + k <= len(b):
            pat = b[j + step:j + step + k]
            ii = a.find(pat, i, i + win + k)
            if ii >= 0:
                cand = ((ii - i) + step, ii, j + step)
                if best is None or cand[0] < best[0]: best = cand
        if best and best[0] <= step: break
    return best


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('a'); ap.add_argument('b')
    ap.add_argument('--ctx', type=int, default=24); ap.add_argument('--max', type=int, default=40)
    o = ap.parse_args()
    a = open(o.a, 'rb').read(); b = open(o.b, 'rb').read()
    i = j = 0; n = 0
    while i < len(a) and j < len(b) and n < o.max:
        if a[i] == b[j]:
            i += 1; j += 1; continue
        r = resync(a, b, i, j)
        if not r:
            print(f'no resync after A@{i:#x} B@{j:#x}'); break
        _, ni, nj = r
        da, db = a[i:ni], b[j:nj]
        kind = 'insert' if not da else 'delete' if not db else 'change'
        print(f'{kind:6} A[{i:#x}:{ni:#x}] ({len(da)})  B[{j:#x}:{nj:#x}] ({len(db)})')
        print(f'   before: {a[max(0, i - o.ctx):i].hex(" ")}')
        if da: print(f'   A: {hexs(da)}')
        if db: print(f'   B: {hexs(db, 2048 if kind == "insert" else 96)}')
        i, j = ni, nj; n += 1
    if (len(a) - i) != (len(b) - j):
        print(f'tail mismatch: A rest {len(a) - i}, B rest {len(b) - j}')


if __name__ == '__main__':
    main()
