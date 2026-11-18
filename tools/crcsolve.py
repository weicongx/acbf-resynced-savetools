"""Test whether a stored 32-bit value is a CRC (any poly from a list, reflected or not)
with an UNKNOWN init and xorout, over candidate byte ranges, using several genuine saves.

T = crc_reg(init=I, data) ^ O   is affine in (I, O):
T ^ crc_reg(0, data) = Z_n(I) ^ O, where Z_n = operator for n zero bytes.
Stack equations from 3+ saves and solve over GF(2); consistency => match.
Also tests Adler-32 with unknown initial (a, b).
"""
import sys, os, glob, struct, zlib
M = 0xffffffff
POLYS = {'crc32': 0x04C11DB7, 'crc32c': 0x1EDC6F41, 'crc32k': 0x741B8CD7, 'crc32q': 0x814141AB,
         'crc32xfer': 0x000000AF, 'crc32d': 0xA833982B}


def rev32(x): return int(f'{x:032b}'[::-1], 2)


def table(poly, refl):
    t = []
    for i in range(256):
        if refl:
            c = i
            for _ in range(8): c = (c >> 1) ^ (rev32(poly) if c & 1 else 0)
        else:
            c = i << 24
            for _ in range(8): c = ((c << 1) ^ poly) & M if c & 0x80000000 else (c << 1) & M
        t.append(c)
    return t


def crc_reg(t, refl, data, c=0):
    if refl:
        for x in data: c = t[(c ^ x) & 0xff] ^ (c >> 8)
    else:
        for x in data: c = t[((c >> 24) ^ x) & 0xff] ^ ((c << 8) & M)
    return c


def mat_apply(m, v):
    r = 0; k = 0
    while v:
        if v & 1: r ^= m[k]
        v >>= 1; k += 1
    return r


def mat_mul(a, b):  # a after b
    return [mat_apply(a, col) for col in b]


def zero_op(t, refl, n):
    step = [crc_reg(t, refl, b'\0', 1 << k) for k in range(32)]
    res = [1 << k for k in range(32)]; p = step
    while n:
        if n & 1: res = mat_mul(p, res)
        p = mat_mul(p, p); n >>= 1
    return res


def solve(rows):
    """rows: list of (int mask over 64 unknowns, rhs bit). returns True if consistent"""
    piv = {}
    for mask, rhs in rows:
        while mask:
            h = mask.bit_length() - 1
            if h in piv:
                pm, pr = piv[h]; mask ^= pm; rhs ^= pr
            else:
                piv[h] = (mask, rhs); break
        else:
            if rhs: return False
    return True


_cache = {}
def check_crc(t, refl, items):
    rows = []
    for data, T in items:
        key = (id(t), refl, id(data))
        if key not in _cache:
            _cache[key] = (crc_reg(t, refl, data), zero_op(t, refl, len(data)))
        c0, Z = _cache[key]; y = T ^ c0
        for bit in range(32):
            mask = 0
            for k in range(32):
                if (Z[k] >> bit) & 1: mask |= 1 << k
            mask |= 1 << (32 + bit)
            rows.append((mask, (y >> bit) & 1))
    return solve(rows)


def check_adler(items):
    sols = set()
    for i, (data, T) in enumerate(items):
        a = (sum(data)) % 65521
        b = 0; s = 0
        for x in data: s = (s + x) % 65521; b = (b + s) % 65521
        n = len(data); Ta, Tb = T & 0xffff, T >> 16
        a0 = (Ta - a) % 65521
        b0 = (Tb - b - n * a0) % 65521
        sols.add((a0, b0))
    return len(sols) == 1


def main():
    W = sys.argv[1]; names = sys.argv[2:]
    saves = []
    for nm in names:
        d = open(f'{W}/{nm}/decrypted.bin', 'rb').read()
        raw = open(glob.glob(f'{os.path.dirname(W)}/save_backup/*{nm}]*')[0], 'rb').read()
        saves.append((d, raw))
    targets = {
        'trailer_dec_le': lambda d, r: struct.unpack('<I', d[-4:])[0],
        'trailer_dec_be': lambda d, r: struct.unpack('>I', d[-4:])[0],
        'trailer_raw_le': lambda d, r: struct.unpack('<I', r[-4:])[0],
        'trailer_raw_be': lambda d, r: struct.unpack('>I', r[-4:])[0],
        'X_le': lambda d, r: struct.unpack_from('<I', d, 0x38)[0],
        'X_be': lambda d, r: struct.unpack_from('>I', d, 0x38)[0],
    }
    ranges = {}
    for a in (0, 0x28, 0x2c, 0x38, 0x3c, 0x40, 0x4c):
        ranges[f'dec[{a:#x}:-4]'] = lambda d, r, a=a: d[a:-4]
        ranges[f'raw[{a:#x}:-4]'] = lambda d, r, a=a: r[a:-4]
        ranges[f'decXz[{a:#x}:-4]'] = lambda d, r, a=a: (d[:0x38] + b'\0' * 4 + d[0x3c:])[a:-4]
        ranges[f'dec[{a:#x}:]Tz'] = lambda d, r, a=a: (d[:-4] + b'\0' * 4)[a:]
        ranges[f'raw[{a:#x}:]Tz'] = lambda d, r, a=a: (r[:-4] + b'\0' * 4)[a:]
    tabs = {(pn, refl): table(p, refl) for pn, p in POLYS.items() for refl in (True, False)}
    for rn, rf in ranges.items():
        bufs = [rf(d, r) for d, r in saves]
        for tn, tf in targets.items():
            Ts = [tf(d, r) for d, r in saves]
            items = list(zip(bufs, Ts))
            if check_adler(items): print('ADLER-MATCH', rn, tn)
            for (pn, refl), t in tabs.items():
                if check_crc(t, refl, items):
                    print('CRC-MATCH', rn, tn, pn, 'refl' if refl else 'norm', flush=True)
        print('done', rn, flush=True); _cache.clear()


if __name__ == '__main__':
    main()
