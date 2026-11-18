import struct,hashlib,zlib
M32=0xffffffff
def _tbl(poly,refl):
    t=[]
    for i in range(256):
        if refl:
            c=i
            for _ in range(8): c=(c>>1)^(poly if c&1 else 0)
        else:
            c=i<<24
            for _ in range(8): c=((c<<1)^poly)&M32 if c&0x80000000 else (c<<1)&M32
        t.append(c)
    return t
def _rev(x,n=32): return int(f'{x:0{n}b}'[::-1],2)
CRCS={}
for nm,poly in (('crc32',0x04C11DB7),('crc32c',0x1EDC6F41),('crc32k',0x741B8CD7),('crc32q',0x814141AB)):
    for refl in (True,False):
        CRCS[(nm,refl)]=( _tbl(_rev(poly) if refl else poly,refl), refl)
def crc(b,key,init,xo):
    t,refl=CRCS[key]; c=init
    if refl:
        for x in b: c=t[(c^x)&0xff]^(c>>8)
    else:
        for x in b: c=t[((c>>24)^x)&0xff]^((c<<8)&M32)
    return c^xo
def xxh32(b,seed=0):
    P1,P2,P3,P4,P5=2654435761,2246822519,3266489917,668265263,374761393
    rotl=lambda x,r:((x<<r)|(x>>(32-r)))&M32
    n=len(b); i=0
    if n>=16:
        v=[(seed+P1+P2)&M32,(seed+P2)&M32,seed,(seed-P1)&M32]
        while i+16<=n:
            for k in range(4):
                v[k]=rotl((v[k]+struct.unpack_from('<I',b,i)[0]*P2)&M32,13)*P1&M32; i+=4
        h=(rotl(v[0],1)+rotl(v[1],7)+rotl(v[2],12)+rotl(v[3],18))&M32
    else: h=(seed+P5)&M32
    h=(h+n)&M32
    while i+4<=n: h=rotl((h+struct.unpack_from('<I',b,i)[0]*P3)&M32,17)*P4&M32; i+=4
    while i<n: h=rotl((h+b[i]*P5)&M32,11)*P1&M32; i+=1
    h^=h>>15; h=h*P2&M32; h^=h>>13; h=h*P3&M32; h^=h>>16
    return h
def murmur3(b,seed=0):
    c1,c2=0xcc9e2d51,0x1b873593; h=seed; n=len(b); r=n&~3
    rotl=lambda x,r:((x<<r)|(x>>(32-r)))&M32
    for i in range(0,r,4):
        k=struct.unpack_from('<I',b,i)[0]*c1&M32; k=rotl(k,15)*c2&M32
        h^=k; h=rotl(h,13); h=(h*5+0xe6546b64)&M32
    k=0; t=b[r:]
    for j in range(len(t)-1,-1,-1): k=(k<<8)|t[j]
    if t: k=k*c1&M32; k=rotl(k,15)*c2&M32; h^=k
    h^=n; h^=h>>16; h=h*0x85ebca6b&M32; h^=h>>13; h=h*0xc2b2ae35&M32; h^=h>>16
    return h
def fnv1a(b):
    h=0x811c9dc5
    for x in b: h=((h^x)*0x01000193)&M32
    return h
def all_hashes(b):
    out={}
    for key in CRCS:
        for init in (0,M32):
            for xo in (0,M32): out[f'{key[0]}{"r" if key[1] else "n"}_i{init:x}_x{xo:x}']=crc(b,key,init,xo)
    out['xxh32']=xxh32(b); out['murmur3']=murmur3(b); out['fnv1a']=fnv1a(b)
    out['adler']=zlib.adler32(b); out['adler0']=zlib.adler32(b,0)
    for hn in ('md5','sha1','sha256'):
        dg=hashlib.new(hn,b).digest()
        out[hn+'_first']=struct.unpack('<I',dg[:4])[0]; out[hn+'_last']=struct.unpack('<I',dg[-4:])[0]
    out['sum32']=sum(struct.unpack_from(f'<{len(b)//4}I',b))&M32
    return out
