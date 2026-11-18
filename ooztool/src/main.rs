// Unpacks an AC Black Flag Resynced save: XOR-decrypt, walk Anvil compressed sections,
// Kraken-decompress each chunk, write every section to <outdir>/secNN_<offset>.bin
// plus index.tsv describing them.
use std::{env, fs, io::Write, path::Path};

const KEY: [u8; 16] = [
    0x93, 0xcc, 0x22, 0xc5, 0xe0, 0xfa, 0x46, 0xa3, 0xf2, 0xbc, 0x71, 0x4a, 0xad, 0xb8, 0xab, 0xe1,
];
const MAGIC: [u8; 8] = [0x33, 0xaa, 0xfb, 0x57, 0x99, 0xfa, 0x04, 0x10];

fn u32le(d: &[u8], p: usize) -> u32 {
    u32::from_le_bytes([d[p], d[p + 1], d[p + 2], d[p + 3]])
}

fn find(d: &[u8], from: usize) -> Option<usize> {
    if from >= d.len() {
        return None;
    }
    d[from..].windows(8).position(|w| w == MAGIC).map(|i| i + from)
}

// Forge (game data) compressed block: magic, u16 ver, u8 codec, u32 max_chunk, u32 nchunks,
// nchunks x (u32 unc, u32 comp), then per chunk u32 adler + comp bytes (stored when comp == unc).
// usage: ooztool forge <file.forge> <offset_hex_of_magic> <out.bin> [count]
// Decodes `count` consecutive blocks (default 1), appending them to out.bin; prints end offset.
fn forge_block(a: &[String]) {
    use std::io::{Read, Seek, SeekFrom};
    let mut f = fs::File::open(&a[2]).expect("open forge");
    let mut off = u64::from_str_radix(a[3].trim_start_matches("0x"), 16).unwrap();
    let count: usize = a.get(5).map(|s| s.parse().unwrap()).unwrap_or(1);
    let mut out = Vec::new();
    let mut ex = oozextract::Extractor::new();
    for _ in 0..count {
        let mut h = vec![0u8; 19];
        f.seek(SeekFrom::Start(off)).unwrap();
        f.read_exact(&mut h).unwrap();
        if h[..8] != MAGIC {
            eprintln!("no magic at {off:#x}");
            break;
        }
        let n = u32le(&h, 15) as usize;
        let mut t = vec![0u8; n * 8];
        f.read_exact(&mut t).unwrap();
        let mut p = off + 19 + (n * 8) as u64;
        for i in 0..n {
            let unc = u32le(&t, i * 8) as usize;
            let comp = u32le(&t, i * 8 + 4) as usize;
            let mut c = vec![0u8; comp + 4];
            f.seek(SeekFrom::Start(p)).unwrap();
            f.read_exact(&mut c).unwrap();
            if comp == unc {
                out.extend_from_slice(&c[4..]);
            } else {
                let mut o = vec![0u8; unc];
                match ex.read_from_slice(&c[4..], &mut o) {
                    Ok(r) if r == unc => out.extend_from_slice(&o),
                    r => {
                        eprintln!("chunk {i} at {p:#x}: {r:?}");
                        out.extend_from_slice(&o);
                    }
                }
            }
            p += 4 + comp as u64;
        }
        println!("block {off:#x} -> {p:#x}, {n} chunks, out {}", out.len());
        off = p;
    }
    fs::write(&a[4], &out).unwrap();
}

// Decode a forge block whose magic is at `m` inside `buf` (buf must hold the whole block).
// Returns (decoded, end offset) or None if it does not fit / is malformed.
fn decode_block(buf: &[u8], m: usize, ex: &mut oozextract::Extractor) -> Option<(Vec<u8>, usize)> {
    if m + 19 > buf.len() {
        return None;
    }
    let n = u32le(buf, m + 15) as usize;
    if n == 0 || n > 4096 || m + 19 + n * 8 > buf.len() {
        return None;
    }
    let mut p = m + 19 + n * 8;
    let mut out = Vec::new();
    for i in 0..n {
        let unc = u32le(buf, m + 19 + i * 8) as usize;
        let comp = u32le(buf, m + 23 + i * 8) as usize;
        if unc > 0x100000 || p + 4 + comp > buf.len() {
            return None;
        }
        let c = &buf[p + 4..p + 4 + comp];
        if comp == unc {
            out.extend_from_slice(c);
        } else {
            let mut o = vec![0u8; unc];
            match ex.read_from_slice(c, &mut o) {
                Ok(r) if r == unc => out.extend_from_slice(&o),
                _ => return None,
            }
        }
        p += 4 + comp;
    }
    Some((out, p))
}

// usage: ooztool scan <file.forge> <hexpattern>[,<hexpattern>...] [dumpdir]
// Decodes every compressed block in the forge and reports blocks containing any pattern.
// With dumpdir, writes each matching block as <dumpdir>/<offset>.bin.
fn scan(a: &[String]) {
    use std::io::{Read, Seek, SeekFrom};
    let pats: Vec<Vec<u8>> = a[3]
        .split(',')
        .map(|h| (0..h.len()).step_by(2).map(|i| u8::from_str_radix(&h[i..i + 2], 16).unwrap()).collect())
        .collect();
    let dump = a.get(4).map(|s| Path::new(s).to_path_buf());
    if let Some(d) = &dump {
        fs::create_dir_all(d).unwrap();
    }
    let mut f = fs::File::open(&a[2]).expect("open");
    let len = f.metadata().unwrap().len();
    const WIN: usize = 64 << 20;
    const OVL: usize = 8 << 20;
    let mut ex = oozextract::Extractor::new();
    let mut base: u64 = 0;
    let mut buf = vec![0u8; WIN + OVL];
    let (mut blocks, mut fails) = (0u64, 0u64);
    while base < len {
        let want = ((len - base) as usize).min(WIN + OVL);
        f.seek(SeekFrom::Start(base)).unwrap();
        f.read_exact(&mut buf[..want]).unwrap();
        let b = &buf[..want];
        let mut p = 0usize;
        let mut next_base = base + WIN as u64;
        while let Some(m) = find(b, p) {
            if m >= WIN && base + (want as u64) < len {
                next_base = base + m as u64;
                break;
            }
            match decode_block(b, m, &mut ex) {
                Some((out, end)) => {
                    blocks += 1;
                    for (k, pat) in pats.iter().enumerate() {
                        let mut s = 0;
                        while let Some(i) = out[s..].windows(pat.len()).position(|w| w == &pat[..]) {
                            println!("pat{k} block {:#x} len {} at {:#x}", base + m as u64, out.len(), s + i);
                            s += i + 1;
                            if let Some(d) = &dump {
                                fs::write(d.join(format!("{:x}.bin", base + m as u64)), &out).unwrap();
                            }
                        }
                    }
                    p = end;
                    if end >= WIN && base + (want as u64) < len {
                        next_base = base + end as u64;
                        break;
                    }
                }
                None => {
                    fails += 1;
                    p = m + 8;
                }
            }
        }
        if p < WIN && find(b, p).is_none() {
            next_base = next_base.min(base + WIN as u64);
        }
        base = next_base;
        eprint!("\r{:.1}%  blocks {blocks} fails {fails}   ", base as f64 * 100.0 / len as f64);
    }
    eprintln!();
}

fn main() {
    let a: Vec<String> = env::args().collect();
    if a.len() >= 4 && a[1] == "scan" {
        scan(&a);
        return;
    }
    if a.len() >= 5 && a[1] == "forge" {
        forge_block(&a);
        return;
    }
    if a.len() < 3 {
        eprintln!("usage: ooztool <save> <outdir>");
        std::process::exit(2);
    }
    let mut d = fs::read(&a[1]).expect("read save");
    // key phase varies per file: pick the one that makes offset 0x28 read ACDBFE00
    let want = [0xac, 0xdb, 0xfe, 0x00];
    let phase = (0..16)
        .find(|&ph| (0..4).all(|j| d[0x28 + j] ^ KEY[(0x28 + j + ph) % 16] == want[j]))
        .expect("no XOR phase matches ACDBFE00 header");
    eprintln!("xor phase {phase}");
    for i in 0x28..d.len() {
        d[i] ^= KEY[(i + phase) % 16];
    }
    let out = Path::new(&a[2]);
    fs::create_dir_all(out).unwrap();
    fs::write(out.join("decrypted.bin"), &d).unwrap();
    let mut idx = fs::File::create(out.join("index.tsv")).unwrap();
    writeln!(idx, "sec\tmagic_off\tid8\tsec_size\ttotal\tchunks\tend\tok").unwrap();
    let mut ex = oozextract::Extractor::new();
    let mut pos = find(&d, 0);
    let mut n = 0;
    while let Some(m) = pos {
        let id8 = &d[m - 16..m - 8];
        let sec_size = u32le(&d, m - 8);
        let total = u32le(&d, m - 4) as usize;
        let mut p = m + 15;
        let mut buf: Vec<u8> = Vec::with_capacity(total);
        let mut chunks = 0;
        let mut ok = true;
        loop {
            let flag = d[p];
            let comp = u32le(&d, p + 1) as usize;
            if flag == 0 {
                // stored chunk: [flag][u32 size][data]
                buf.extend_from_slice(&d[p + 5..p + 5 + comp]);
                chunks += 1;
                p += 5 + comp;
                if buf.len() >= total {
                    break;
                }
                continue;
            }
            let unc = u32le(&d, p + 5) as usize;
            let data = &d[p + 13..p + 13 + comp];
            if flag == 1 {
                let mut o = vec![0u8; unc];
                match ex.read_from_slice(data, &mut o) {
                    Ok(r) if r == unc => buf.extend_from_slice(&o),
                    Ok(r) => {
                        eprintln!("sec{n} chunk{chunks}: got {r} want {unc}");
                        ok = false;
                        buf.extend_from_slice(&o[..r.min(unc)]);
                    }
                    Err(e) => {
                        eprintln!("sec{n} chunk{chunks}: {e:?}");
                        ok = false;
                    }
                }
            } else {
                buf.extend_from_slice(data);
            }
            chunks += 1;
            p += 13 + comp;
            if buf.len() >= total || unc == 0 || !ok {
                break;
            }
        }
        let name = format!("sec{n:02}_{m:06x}.bin");
        fs::write(out.join(&name), &buf).unwrap();
        writeln!(
            idx,
            "{n}\t{m:#x}\t{}\t{sec_size}\t{total}\t{chunks}\t{p:#x}\t{ok}",
            id8.iter().map(|b| format!("{b:02x}")).collect::<String>()
        )
        .unwrap();
        n += 1;
        pos = find(&d, p);
    }
    println!("{} sections, file len {:#x}", n, d.len());
}
