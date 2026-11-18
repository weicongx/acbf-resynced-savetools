"""Rebuild an AC Black Flag Resynced save from an unpacked directory.

usage: pack.py <original.save> <unpacked_dir> <out.save> [--x HEX] [--trailer HEX]

Sections are read from <unpacked_dir>/secNN_*.bin (edit those to mod the save),
recompressed with Kraken (oo2core DLL) in 256 KB chunks with Adler-32(init 0)
checksums, and the file is re-XORed with the key aligned to the file end.
"""
import sys, os, glob, struct, zlib, ctypes, argparse

KEY = bytes.fromhex('93cc22c5e0fa46a3f2bc714aadb8abe1')
MAGIC = bytes.fromhex('33aafb5799fa0410')
CHUNK = 0x40000
T = os.path.dirname(os.path.abspath(__file__))
oo = ctypes.WinDLL(os.path.join(T, 'oo2core_5_win64.dll'))
C = oo.OodleLZ_Compress
C.restype = ctypes.c_ssize_t
C.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_ssize_t, ctypes.c_char_p, ctypes.c_int,
              ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t]
KRAKEN, LEVEL_OPTIMAL1 = 8, 5


def kraken(raw):
    out = ctypes.create_string_buffer(len(raw) + 65536)
    n = C(KRAKEN, raw, len(raw), out, LEVEL_OPTIMAL1, None, None, None, None, 0)
    if n <= 0:
        raise RuntimeError('oodle compress failed')
    return out.raw[:n]


def _crc32c_table():
    t = []
    for i in range(256):
        c = i
        for _ in range(8): c = (c >> 1) ^ (0x82F63B78 if c & 1 else 0)
        t.append(c)
    return t


_T32C = _crc32c_table()


def crc32c_reg(data, c):
    t = _T32C
    for x in data: c = t[(c ^ x) & 0xff] ^ (c >> 8)
    return c


def seal(dec):
    """write header checksum X (crc32) and trailer (crc32c) into a decrypted save buffer.
    Constants solved from genuine saves and verified on all 16 of them."""
    x = zlib.crc32(bytes(dec[0x3c:-4]), 0x0B3C475D ^ 0xFFFFFFFF)  # init 0x0B3C475D, xorout ~0
    dec[0x38:0x3c] = struct.pack('<I', x)
    t = crc32c_reg(bytes(dec[0x28:-4]), 0xF7986AF2) ^ 0x035BD250
    dec[-4:] = struct.pack('<I', t)


def xor(buf):
    ph = (1 - len(buf)) % 16
    for i in range(0x28, len(buf)):
        buf[i] ^= KEY[(i + ph) % 16]


def sections(dec):
    """yield (magic_offset, id8, header7, stored_flag, end) from the decrypted original"""
    pos = dec.find(MAGIC)
    while pos >= 0:
        total = struct.unpack_from('<I', dec, pos - 4)[0]
        p = pos + 15; got = 0; stored = False
        while got < total or total == 0:
            flag = dec[p]; comp = struct.unpack_from('<I', dec, p + 1)[0]
            if flag == 0:
                stored = True; got += comp; p += 5 + comp
            else:
                got += struct.unpack_from('<I', dec, p + 5)[0]; p += 13 + comp
            if total == 0:
                break
        yield pos, dec[pos - 16:pos - 8], dec[pos + 8:pos + 15], stored, p
        pos = dec.find(MAGIC, p)


def encode_chunks(data):
    """Kraken-compress in 256 KB chunks; any chunk the old Oodle doesn't emit as
    Kraken (stream header 8C 06) is stored raw instead, since the game only
    produces Kraken and may only ship that decoder."""
    body = bytearray(); kinds = []
    for o in range(0, len(data), CHUNK):
        rawc = data[o:o + CHUNK]; comp = kraken(rawc)
        if comp[:2] == b'\x8c\x06' and len(comp) < len(rawc):
            body += b'\x01' + struct.pack('<III', len(comp), len(rawc), zlib.adler32(comp, 0)) + comp; kinds.append('K')
        else:
            body += b'\x00' + struct.pack('<I', len(rawc)) + rawc; kinds.append('S')
    return body, kinds


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('orig'); ap.add_argument('unpacked'); ap.add_argument('out')
    ap.add_argument('--pristine', help='unpacked dir of the untouched original; sections identical to it are copied verbatim')
    ap.add_argument('--force', default='', help='comma list of section indexes to re-encode even if unchanged (testing)')
    ap.add_argument('--store', default='', help='comma list of section indexes to store uncompressed (testing)')
    ap.add_argument('--x'); ap.add_argument('--trailer')
    a = ap.parse_args()
    force = {int(i) for i in a.force.split(',') if i}; store = {int(i) for i in a.store.split(',') if i}
    raw = bytearray(open(a.orig, 'rb').read())
    dec = bytearray(raw); ph = (1 - len(dec)) % 16
    for i in range(0x28, len(dec)):
        dec[i] ^= KEY[(i + ph) % 16]
    assert dec[0x28:0x2c] == b'\xac\xdb\xfe\x00', 'bad decrypt'
    files = sorted(glob.glob(os.path.join(a.unpacked, 'sec*.bin')))
    secs = list(sections(dec))
    assert len(files) == len(secs), (len(files), len(secs))
    pristine = sorted(glob.glob(os.path.join(a.pristine, 'sec*.bin'))) if a.pristine else [None] * len(files)
    out = bytearray(dec[:0x3c]); report = []
    for i, ((pos, id8, hdr7, stored, end), f, pf) in enumerate(zip(secs, files, pristine)):
        data = open(f, 'rb').read()
        if pf and i not in force and i not in store and data == open(pf, 'rb').read():
            out += dec[pos - 16:end]; continue  # untouched: original bytes verbatim
        body = bytearray(MAGIC + hdr7)
        if stored or i in store:
            body += b'\x00' + struct.pack('<I', len(data)) + data; kinds = ['S']
        else:
            enc, kinds = encode_chunks(data); body += enc
        report.append(f'sec{i:02d}:{"".join(kinds)}')
        out += id8 + struct.pack('<II', len(body) + 4, len(data)) + body
    out += b'\0\0\0\0'
    seal(out)
    if a.x:
        out[0x38:0x3c] = bytes.fromhex(a.x)
    if a.trailer:
        out[-4:] = bytes.fromhex(a.trailer)
    xor(out)
    open(a.out, 'wb').write(out)
    print('wrote', a.out, len(out), 'bytes; re-encoded:', ' '.join(report) or 'none')


if __name__ == '__main__':
    main()
