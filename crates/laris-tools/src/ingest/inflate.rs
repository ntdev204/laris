//! DEFLATE and zlib decoding (RFC 1950 and 1951), for the compressed streams of PDF files.
//!
//! A port of the method of zlib's `puff.c`: canonical Huffman codes decoded bit by bit from counts and symbol lists.
//! It is small and slow on purpose; the output is bounded by the caller, so a hostile stream cannot grow without
//! limit.

/// A stream that cannot be decoded.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum InflateError {
    /// The data ends in the middle of a block.
    #[error("the compressed data ends too soon")]
    Truncated,
    /// The data is not valid DEFLATE.
    #[error("the compressed data is damaged")]
    Invalid,
    /// The output would pass the limit.
    #[error("the decompressed data is larger than the limit")]
    TooLarge,
}

const MAX_BITS: usize = 15;
const LENGTH_BASE: [u16; 29] = [
    3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 17, 19, 23, 27, 31, 35, 43, 51, 59, 67, 83, 99, 115, 131,
    163, 195, 227, 258,
];
const LENGTH_EXTRA: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 2, 2, 2, 2, 3, 3, 3, 3, 4, 4, 4, 4, 5, 5, 5, 5, 0,
];
const DIST_BASE: [u16; 30] = [
    1, 2, 3, 4, 5, 7, 9, 13, 17, 25, 33, 49, 65, 97, 129, 193, 257, 385, 513, 769, 1025, 1537,
    2049, 3073, 4097, 6145, 8193, 12289, 16385, 24577,
];
const DIST_EXTRA: [u8; 30] = [
    0, 0, 0, 0, 1, 1, 2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 7, 8, 8, 9, 9, 10, 10, 11, 11, 12, 12, 13,
    13,
];
const ORDER: [usize; 19] = [
    16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15,
];

struct Bits<'a> {
    data: &'a [u8],
    at: usize,
    hold: u32,
    count: u32,
}

impl<'a> Bits<'a> {
    fn need(&mut self, n: u32) -> Result<u32, InflateError> {
        while self.count < n {
            let byte = *self.data.get(self.at).ok_or(InflateError::Truncated)?;
            self.at += 1;
            self.hold |= u32::from(byte) << self.count;
            self.count += 8;
        }
        let value = self.hold & ((1u32 << n) - 1);
        self.hold >>= n;
        self.count -= n;
        Ok(value)
    }
}

struct Huffman {
    count: [u16; MAX_BITS + 1],
    symbol: Vec<u16>,
}

impl Huffman {
    fn new(lengths: &[u8]) -> Result<Self, InflateError> {
        let mut count = [0u16; MAX_BITS + 1];
        for &l in lengths {
            count[usize::from(l)] += 1;
        }
        let mut left: i32 = 1;
        for &c in &count[1..=MAX_BITS] {
            left <<= 1;
            left -= i32::from(c);
            if left < 0 {
                return Err(InflateError::Invalid);
            }
        }
        let mut offs = [0u16; MAX_BITS + 2];
        for len in 1..=MAX_BITS {
            offs[len + 1] = offs[len] + count[len];
        }
        let mut symbol = vec![0u16; lengths.len()];
        for (sym, &l) in lengths.iter().enumerate() {
            if l != 0 {
                symbol[usize::from(offs[usize::from(l)])] = sym as u16;
                offs[usize::from(l)] += 1;
            }
        }
        Ok(Self { count, symbol })
    }

    fn decode(&self, bits: &mut Bits<'_>) -> Result<u16, InflateError> {
        let (mut code, mut first, mut index) = (0i32, 0i32, 0i32);
        for len in 1..=MAX_BITS {
            code |= bits.need(1)? as i32;
            let count = i32::from(self.count[len]);
            if code - count < first {
                return Ok(self.symbol[(index + (code - first)) as usize]);
            }
            index += count;
            first += count;
            first <<= 1;
            code <<= 1;
        }
        Err(InflateError::Invalid)
    }
}

fn codes(
    bits: &mut Bits<'_>,
    out: &mut Vec<u8>,
    limit: usize,
    lit: &Huffman,
    dist: &Huffman,
) -> Result<(), InflateError> {
    loop {
        let sym = usize::from(lit.decode(bits)?);
        match sym {
            0..=255 => {
                if out.len() >= limit {
                    return Err(InflateError::TooLarge);
                }
                out.push(sym as u8);
            }
            256 => return Ok(()),
            257..=285 => {
                let i = sym - 257;
                let len =
                    usize::from(LENGTH_BASE[i]) + bits.need(u32::from(LENGTH_EXTRA[i]))? as usize;
                let d = usize::from(dist.decode(bits)?);
                if d >= 30 {
                    return Err(InflateError::Invalid);
                }
                let back =
                    usize::from(DIST_BASE[d]) + bits.need(u32::from(DIST_EXTRA[d]))? as usize;
                if back > out.len() {
                    return Err(InflateError::Invalid);
                }
                if out.len() + len > limit {
                    return Err(InflateError::TooLarge);
                }
                for _ in 0..len {
                    let byte = out[out.len() - back];
                    out.push(byte);
                }
            }
            _ => return Err(InflateError::Invalid),
        }
    }
}

fn fixed() -> Result<(Huffman, Huffman), InflateError> {
    let mut lengths = [0u8; 288];
    for (i, l) in lengths.iter_mut().enumerate() {
        *l = match i {
            0..=143 => 8,
            144..=255 => 9,
            256..=279 => 7,
            _ => 8,
        };
    }
    Ok((Huffman::new(&lengths)?, Huffman::new(&[5u8; 30])?))
}

fn dynamic(bits: &mut Bits<'_>) -> Result<(Huffman, Huffman), InflateError> {
    let nlen = bits.need(5)? as usize + 257;
    let ndist = bits.need(5)? as usize + 1;
    let ncode = bits.need(4)? as usize + 4;
    if nlen > 286 || ndist > 30 {
        return Err(InflateError::Invalid);
    }
    let mut lengths = [0u8; 320];
    for &slot in ORDER.iter().take(ncode) {
        lengths[slot] = bits.need(3)? as u8;
    }
    let code_huffman = Huffman::new(&lengths[..19])?;
    let mut lengths = [0u8; 320];
    let mut index = 0;
    while index < nlen + ndist {
        let sym = code_huffman.decode(bits)?;
        if sym < 16 {
            lengths[index] = sym as u8;
            index += 1;
        } else {
            let (value, repeat) = match sym {
                16 => {
                    if index == 0 {
                        return Err(InflateError::Invalid);
                    }
                    (lengths[index - 1], 3 + bits.need(2)? as usize)
                }
                17 => (0, 3 + bits.need(3)? as usize),
                _ => (0, 11 + bits.need(7)? as usize),
            };
            if index + repeat > nlen + ndist {
                return Err(InflateError::Invalid);
            }
            for _ in 0..repeat {
                lengths[index] = value;
                index += 1;
            }
        }
    }
    if lengths[256] == 0 {
        return Err(InflateError::Invalid);
    }
    Ok((
        Huffman::new(&lengths[..nlen])?,
        Huffman::new(&lengths[nlen..nlen + ndist])?,
    ))
}

/// Decodes a raw DEFLATE stream; the output may not pass `limit` bytes.
pub fn inflate(data: &[u8], limit: usize) -> Result<Vec<u8>, InflateError> {
    let mut bits = Bits {
        data,
        at: 0,
        hold: 0,
        count: 0,
    };
    let mut out = Vec::new();
    loop {
        let last = bits.need(1)?;
        match bits.need(2)? {
            0 => {
                bits.hold = 0;
                bits.count = 0;
                let head = data
                    .get(bits.at..bits.at + 4)
                    .ok_or(InflateError::Truncated)?;
                let len = usize::from(u16::from_le_bytes([head[0], head[1]]));
                let inverse = u16::from_le_bytes([head[2], head[3]]);
                if inverse != !(len as u16) {
                    return Err(InflateError::Invalid);
                }
                bits.at += 4;
                let chunk = data
                    .get(bits.at..bits.at + len)
                    .ok_or(InflateError::Truncated)?;
                if out.len() + len > limit {
                    return Err(InflateError::TooLarge);
                }
                out.extend_from_slice(chunk);
                bits.at += len;
            }
            1 => {
                let (lit, dist) = fixed()?;
                codes(&mut bits, &mut out, limit, &lit, &dist)?;
            }
            2 => {
                let (lit, dist) = dynamic(&mut bits)?;
                codes(&mut bits, &mut out, limit, &lit, &dist)?;
            }
            _ => return Err(InflateError::Invalid),
        }
        if last == 1 {
            return Ok(out);
        }
    }
}

/// Decodes a zlib stream (a two-byte header, DEFLATE data, a checksum that is not checked).
pub fn zlib(data: &[u8], limit: usize) -> Result<Vec<u8>, InflateError> {
    if data.len() < 2
        || data[0] & 0x0f != 8
        || (u16::from(data[0]) << 8 | u16::from(data[1])) % 31 != 0
    {
        return Err(InflateError::Invalid);
    }
    inflate(&data[2..], limit)
}
