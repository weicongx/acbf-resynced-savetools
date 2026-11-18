"""Solve init/xorout for X (crc32) and trailer (crc32c) and verify on every save."""
import sys, os, glob, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import crcsolve as c

def solve_vals(t, refl, items):
    rows = []
    for data, T in items:
        c0 = c.crc_reg(t, refl, data); Z = c.zero_op(t, refl, len(data)); y = T ^ c0
        for bit in range(32):
            mask = 0
            for k in range(32):
                if (Z[k] >> bit) & 1: mask |= 1 << k
            rows.append((mask | (1 << (32 + bit)), (y >> bit) & 1))
    # gaussian elimination -> one solution (free vars = 0), plus rank
    piv = {}
    for mask, rhs in rows:
        while mask:
            h = mask.bit_length() - 1
            if h in piv: pm, pr = piv[h]; mask ^= pm; rhs ^= pr
            else: piv[h] = (mask, rhs); break
        else:
            assert not rhs, 'inconsistent'
    sol = 0
    for h in sorted(piv):
        mask, rhs = piv[h]; low = mask & ~(1 << h)
        v = rhs ^ (bin(low & sol).count('1') & 1)
        if v: sol |= 1 << h
    return sol & 0xffffffff, sol >> 32, len(piv)

W = sys.argv[1]; S0 = 0x3c
names = sorted(os.path.basename(p) for p in glob.glob(W + '/*Save*'))
data = {n: open(f'{W}/{n}/decrypted.bin', 'rb').read() for n in names}
X_of = lambda d: struct.unpack_from('<I', d, 0x38)[0]
T_of = lambda d: struct.unpack('<I', d[-4:])[0]
x_rng = lambda d: d[S0:-4]
t_rng = lambda d: d[0x28:-4]
t32 = c.table(0x04C11DB7, True); t32c = c.table(0x1EDC6F41, True)
train = ['ManualSave01', 'ManualSave02', 'ManualSave03']
xi, xo, xr = solve_vals(t32, True, [(x_rng(data[n]), X_of(data[n])) for n in train])
ti, to, tr = solve_vals(t32c, True, [(t_rng(data[n]), T_of(data[n])) for n in train])
print(f'X: crc32  over dec[0x3c:-4]  init={xi:08x} xorout={xo:08x} rank={xr}')
print(f'T: crc32c over dec[0x28:-4]  init={ti:08x} xorout={to:08x} rank={tr}')
ok = 0
for n in names:
    d = data[n]
    gx = c.crc_reg(t32, True, x_rng(d), xi) ^ xo
    gt = c.crc_reg(t32c, True, t_rng(d), ti) ^ to
    good = gx == X_of(d) and gt == T_of(d); ok += good
    print(f'{n:13} X {"ok" if gx == X_of(d) else "BAD"}  trailer {"ok" if gt == T_of(d) else "BAD"}')
print(f'{ok}/{len(names)} saves verified')
