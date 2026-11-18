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

fn main() {
    let a: Vec<String> = env::args().collect();
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
