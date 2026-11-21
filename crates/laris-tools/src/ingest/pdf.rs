//! The text layer of a PDF, read without any PDF library (SR-H13).
//!
//! This reads what a text PDF holds: the objects of the file (found by scanning, so a damaged or hand-made cross
//! reference table does not matter, and objects inside object streams are read too), the page tree, the content
//! stream of each page (stored, or compressed with `FlateDecode`) and the text operators in it (`Tj`, `TJ`, `'`, `"`,
//! `Td`, `TD`, `T*`, `Tm`). A character code becomes text through the font's `ToUnicode` map when it has one, and as
//! Windows-1252 for a simple font without one.
//!
//! It does not guess. A PDF it cannot read says so: encrypted files, filters other than `FlateDecode`, composite
//! fonts without a `ToUnicode` map, and files that hold pictures of pages (scans) each give their own error. A scan
//! has no text layer; `super::ocr` reads it with external OCR programs.

use super::inflate::zlib;
use regex::bytes::Regex;
use std::collections::BTreeMap;
use std::sync::LazyLock;

/// Why a PDF gave no text.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum PdfError {
    /// The bytes do not begin like a PDF.
    #[error("this is not a PDF file")]
    NotPdf,
    /// The file is encrypted.
    #[error("this PDF is encrypted; LARIS does not read encrypted PDFs")]
    Encrypted,
    /// The pages are pictures: nothing to read without OCR.
    #[error(
        "this PDF has no text layer (it looks like a scan); reading scans needs OCR (pdftoppm and tesseract, \
         see vault.ocr)"
    )]
    NoTextLayer,
    /// A feature this reader does not handle.
    #[error("this PDF uses something LARIS cannot read yet: {0}")]
    Unsupported(String),
    /// The file is damaged.
    #[error("this PDF is damaged: {0}")]
    Damaged(String),
}

/// Limits of one extraction.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PdfLimits {
    /// Most bytes one decompressed stream may have.
    pub max_stream_bytes: usize,
    /// Most pages read.
    pub max_pages: usize,
}

/// The text of a PDF, page by page.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PdfText {
    /// One text per page, in order; a page with no text is an empty string.
    pub pages: Vec<String>,
}

impl PdfText {
    /// The pages joined by a blank line.
    pub fn text(&self) -> String {
        self.pages
            .iter()
            .filter(|p| !p.is_empty())
            .cloned()
            .collect::<Vec<_>>()
            .join("\n\n")
    }
}

#[derive(Debug, Clone, PartialEq)]
enum Obj {
    Null,
    Bool(bool),
    Int(i64),
    Real(f64),
    Name(String),
    Str(Vec<u8>),
    Array(Vec<Obj>),
    Dict(BTreeMap<String, Obj>),
    Stream(BTreeMap<String, Obj>, Vec<u8>),
    Ref(u32),
}

impl Obj {
    fn dict(&self) -> Option<&BTreeMap<String, Obj>> {
        match self {
            Obj::Dict(d) | Obj::Stream(d, _) => Some(d),
            _ => None,
        }
    }

    fn name(&self) -> Option<&str> {
        match self {
            Obj::Name(n) => Some(n),
            _ => None,
        }
    }

    fn num(&self) -> Option<f64> {
        match self {
            Obj::Int(i) => Some(*i as f64),
            Obj::Real(r) => Some(*r),
            _ => None,
        }
    }
}

fn is_space(b: u8) -> bool {
    matches!(b, 0 | 9 | 10 | 12 | 13 | 32)
}

fn is_delim(b: u8) -> bool {
    matches!(
        b,
        b'(' | b')' | b'<' | b'>' | b'[' | b']' | b'{' | b'}' | b'/' | b'%'
    )
}

/// A reader of PDF syntax over a byte slice.
struct Lex<'a> {
    data: &'a [u8],
    pos: usize,
}

impl<'a> Lex<'a> {
    fn skip(&mut self) {
        while let Some(&b) = self.data.get(self.pos) {
            if is_space(b) {
                self.pos += 1;
            } else if b == b'%' {
                while self
                    .data
                    .get(self.pos)
                    .is_some_and(|c| !matches!(c, 10 | 13))
                {
                    self.pos += 1;
                }
            } else {
                break;
            }
        }
    }

    fn word(&mut self) -> &'a [u8] {
        let start = self.pos;
        while self
            .data
            .get(self.pos)
            .is_some_and(|&b| !is_space(b) && !is_delim(b))
        {
            self.pos += 1;
        }
        &self.data[start..self.pos]
    }

    fn string(&mut self) -> Vec<u8> {
        // after the opening parenthesis
        let mut depth = 1;
        let mut out = Vec::new();
        while let Some(&b) = self.data.get(self.pos) {
            self.pos += 1;
            match b {
                b'(' => {
                    depth += 1;
                    out.push(b);
                }
                b')' => {
                    depth -= 1;
                    if depth == 0 {
                        break;
                    }
                    out.push(b);
                }
                b'\\' => {
                    let Some(&e) = self.data.get(self.pos) else {
                        break;
                    };
                    self.pos += 1;
                    match e {
                        b'n' => out.push(b'\n'),
                        b'r' => out.push(b'\r'),
                        b't' => out.push(b'\t'),
                        b'b' => out.push(8),
                        b'f' => out.push(12),
                        b'0'..=b'7' => {
                            let mut v = u32::from(e - b'0');
                            for _ in 0..2 {
                                match self.data.get(self.pos) {
                                    Some(&d @ b'0'..=b'7') => {
                                        v = v * 8 + u32::from(d - b'0');
                                        self.pos += 1;
                                    }
                                    _ => break,
                                }
                            }
                            out.push((v & 0xff) as u8);
                        }
                        b'\r' => {
                            if self.data.get(self.pos) == Some(&b'\n') {
                                self.pos += 1;
                            }
                        }
                        b'\n' => {}
                        other => out.push(other),
                    }
                }
                _ => out.push(b),
            }
        }
        out
    }

    fn hex(&mut self) -> Vec<u8> {
        // after `<`
        let mut digits = Vec::new();
        while let Some(&b) = self.data.get(self.pos) {
            self.pos += 1;
            if b == b'>' {
                break;
            }
            if let Some(d) = (b as char).to_digit(16) {
                digits.push(d as u8);
            }
        }
        if digits.len() % 2 == 1 {
            digits.push(0);
        }
        digits.chunks(2).map(|p| p[0] << 4 | p[1]).collect()
    }

    /// One object. Numbers followed by `G R` become references.
    fn object(&mut self, depth: usize) -> Option<Obj> {
        if depth > 40 {
            return None;
        }
        self.skip();
        let b = *self.data.get(self.pos)?;
        match b {
            b'/' => {
                self.pos += 1;
                let w = self.word();
                Some(Obj::Name(unescape_name(w)))
            }
            b'(' => {
                self.pos += 1;
                Some(Obj::Str(self.string()))
            }
            b'<' if self.data.get(self.pos + 1) == Some(&b'<') => {
                self.pos += 2;
                let mut dict = BTreeMap::new();
                loop {
                    self.skip();
                    if self.data.get(self.pos) == Some(&b'>') {
                        self.pos += if self.data.get(self.pos + 1) == Some(&b'>') {
                            2
                        } else {
                            1
                        };
                        break;
                    }
                    let Some(Obj::Name(key)) = self.object(depth + 1) else {
                        return None;
                    };
                    let value = self.object(depth + 1)?;
                    dict.insert(key, value);
                }
                Some(Obj::Dict(dict))
            }
            b'<' => {
                self.pos += 1;
                Some(Obj::Str(self.hex()))
            }
            b'[' => {
                self.pos += 1;
                let mut items = Vec::new();
                loop {
                    self.skip();
                    match self.data.get(self.pos)? {
                        b']' => {
                            self.pos += 1;
                            break;
                        }
                        _ => items.push(self.object(depth + 1)?),
                    }
                }
                Some(Obj::Array(items))
            }
            b')' | b'>' | b']' | b'{' | b'}' => None,
            _ => {
                let w = self.word();
                if w.is_empty() {
                    return None;
                }
                match w {
                    b"true" => Some(Obj::Bool(true)),
                    b"false" => Some(Obj::Bool(false)),
                    b"null" => Some(Obj::Null),
                    _ => {
                        let text = std::str::from_utf8(w).ok()?;
                        if let Ok(n) = text.parse::<i64>() {
                            // `N G R`?
                            let save = self.pos;
                            if n >= 0 {
                                self.skip();
                                let g = self.word();
                                if !g.is_empty() && g.iter().all(u8::is_ascii_digit) {
                                    self.skip();
                                    if self.data.get(self.pos) == Some(&b'R')
                                        && self
                                            .data
                                            .get(self.pos + 1)
                                            .is_none_or(|&c| is_space(c) || is_delim(c))
                                    {
                                        self.pos += 1;
                                        return Some(Obj::Ref(n as u32));
                                    }
                                }
                            }
                            self.pos = save;
                            Some(Obj::Int(n))
                        } else {
                            text.parse::<f64>().ok().map(Obj::Real)
                        }
                    }
                }
            }
        }
    }
}

fn unescape_name(raw: &[u8]) -> String {
    let mut out = Vec::new();
    let mut i = 0;
    while i < raw.len() {
        if raw[i] == b'#'
            && i + 2 < raw.len()
            && let (Some(a), Some(b)) = (
                (raw[i + 1] as char).to_digit(16),
                (raw.get(i + 2).copied().unwrap_or(b'x') as char).to_digit(16),
            )
        {
            out.push((a * 16 + b) as u8);
            i += 3;
        } else {
            out.push(raw[i]);
            i += 1;
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

static OBJ_START: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"(\d{1,10})[ \t\r\n]+(\d{1,5})[ \t\r\n]+obj\b").expect("pattern"));

struct Doc {
    objects: BTreeMap<u32, Obj>,
    trailers: Vec<BTreeMap<String, Obj>>,
    limits: PdfLimits,
}

fn find(hay: &[u8], needle: &[u8], from: usize) -> Option<usize> {
    hay.get(from..)?
        .windows(needle.len())
        .position(|w| w == needle)
        .map(|p| p + from)
}

impl Doc {
    fn scan(data: &[u8], limits: PdfLimits) -> Doc {
        let mut doc = Doc {
            objects: BTreeMap::new(),
            trailers: Vec::new(),
            limits,
        };
        let mut pos = 0;
        while let Some(m) = OBJ_START.captures_at(data, pos) {
            let whole = m.get(0).expect("whole match");
            let number: u32 = std::str::from_utf8(&m[1])
                .ok()
                .and_then(|s| s.parse().ok())
                .unwrap_or(0);
            let mut lex = Lex {
                data,
                pos: whole.end(),
            };
            let mut next = whole.end();
            if let Some(obj) = lex.object(0) {
                let obj = if let Obj::Dict(dict) = obj {
                    lex.skip();
                    if data[lex.pos..].starts_with(b"stream") {
                        let mut start = lex.pos + 6;
                        if data.get(start) == Some(&b'\r') {
                            start += 1;
                        }
                        if data.get(start) == Some(&b'\n') {
                            start += 1;
                        }
                        let declared = match dict.get("Length") {
                            Some(Obj::Int(n)) if *n >= 0 => Some(*n as usize),
                            _ => None,
                        };
                        let end = declared
                            .filter(|n| {
                                data.get(start + n..).is_some_and(|rest| {
                                    let mut i = 0;
                                    while rest.get(i).is_some_and(|&b| is_space(b)) {
                                        i += 1;
                                    }
                                    rest[i..].starts_with(b"endstream")
                                })
                            })
                            .map(|n| start + n)
                            .or_else(|| {
                                find(data, b"endstream", start).map(|mut e| {
                                    while e > start && matches!(data[e - 1], 10 | 13) {
                                        e -= 1;
                                    }
                                    e
                                })
                            })
                            .unwrap_or(data.len());
                        next = end;
                        Obj::Stream(dict, data[start..end.max(start)].to_vec())
                    } else {
                        next = lex.pos;
                        Obj::Dict(dict)
                    }
                } else {
                    next = lex.pos;
                    obj
                };
                doc.objects.insert(number, obj);
            }
            pos = next.max(whole.end());
        }
        let mut at = 0;
        while let Some(t) = find(data, b"trailer", at) {
            let mut lex = Lex { data, pos: t + 7 };
            if let Some(Obj::Dict(d)) = lex.object(0) {
                doc.trailers.push(d);
            }
            at = t + 7;
        }
        // cross reference streams carry the trailer keys
        let xrefs: Vec<BTreeMap<String, Obj>> = doc
            .objects
            .values()
            .filter_map(|o| o.dict())
            .filter(|d| d.get("Type").and_then(Obj::name) == Some("XRef"))
            .cloned()
            .collect();
        doc.trailers.extend(xrefs);
        doc.expand_object_streams();
        doc
    }

    fn expand_object_streams(&mut self) {
        let streams: Vec<(u32, BTreeMap<String, Obj>, Vec<u8>)> = self
            .objects
            .iter()
            .filter_map(|(n, o)| match o {
                Obj::Stream(d, raw) if d.get("Type").and_then(Obj::name) == Some("ObjStm") => {
                    Some((*n, d.clone(), raw.clone()))
                }
                _ => None,
            })
            .collect();
        for (_, dict, raw) in streams {
            let Ok(data) = self.decode(&dict, &raw) else {
                continue;
            };
            let count = dict.get("N").and_then(Obj::num).unwrap_or(0.0) as usize;
            let first = dict.get("First").and_then(Obj::num).unwrap_or(0.0) as usize;
            let mut head = Lex {
                data: &data,
                pos: 0,
            };
            let mut pairs = Vec::new();
            for _ in 0..count {
                head.skip();
                let (Ok(n), Ok(o)) = (String::from_utf8_lossy(head.word()).parse::<u32>(), {
                    head.skip();
                    String::from_utf8_lossy(head.word()).parse::<usize>()
                }) else {
                    break;
                };
                pairs.push((n, o));
            }
            for (n, offset) in pairs {
                let mut lex = Lex {
                    data: &data,
                    pos: first + offset,
                };
                if let Some(obj) = lex.object(0) {
                    self.objects.entry(n).or_insert(obj);
                }
            }
        }
    }

    fn resolve<'a>(&'a self, obj: &'a Obj) -> &'a Obj {
        let mut current = obj;
        for _ in 0..16 {
            match current {
                Obj::Ref(n) => match self.objects.get(n) {
                    Some(next) => current = next,
                    None => return &Obj::Null,
                },
                _ => return current,
            }
        }
        &Obj::Null
    }

    fn get<'a>(&'a self, dict: &'a BTreeMap<String, Obj>, key: &str) -> &'a Obj {
        dict.get(key).map_or(&Obj::Null, |o| self.resolve(o))
    }

    /// The decoded bytes of a stream.
    fn decode(&self, dict: &BTreeMap<String, Obj>, raw: &[u8]) -> Result<Vec<u8>, PdfError> {
        let filters: Vec<String> = match self.get(dict, "Filter") {
            Obj::Name(n) => vec![n.clone()],
            Obj::Array(items) => items
                .iter()
                .filter_map(|i| self.resolve(i).name().map(str::to_owned))
                .collect(),
            _ => Vec::new(),
        };
        let mut data = raw.to_vec();
        for filter in filters {
            match filter.as_str() {
                "FlateDecode" | "Fl" => {
                    data = zlib(&data, self.limits.max_stream_bytes)
                        .map_err(|e| PdfError::Damaged(e.to_string()))?;
                    if let Obj::Dict(params) = self.get(dict, "DecodeParms")
                        && params.get("Predictor").and_then(Obj::num).unwrap_or(1.0) > 1.0
                    {
                        return Err(PdfError::Unsupported(
                            "a predictor in a content stream".into(),
                        ));
                    }
                }
                other => {
                    return Err(PdfError::Unsupported(format!("the stream filter {other}")));
                }
            }
        }
        Ok(data)
    }

    fn stream_bytes(&self, obj: &Obj) -> Result<Vec<u8>, PdfError> {
        match self.resolve(obj) {
            Obj::Stream(dict, raw) => self.decode(dict, raw),
            _ => Ok(Vec::new()),
        }
    }

    fn pages(&self) -> Vec<&BTreeMap<String, Obj>> {
        let root = self
            .trailers
            .iter()
            .find_map(|t| t.get("Root"))
            .map(|r| self.resolve(r))
            .and_then(Obj::dict);
        let mut out = Vec::new();
        if let Some(root) = root {
            let mut seen = Vec::new();
            self.walk(self.get(root, "Pages"), &mut out, &mut seen, 0);
        }
        if out.is_empty() {
            out = self
                .objects
                .values()
                .filter_map(Obj::dict)
                .filter(|d| d.get("Type").and_then(Obj::name) == Some("Page"))
                .collect();
        }
        out
    }

    fn walk<'a>(
        &'a self,
        node: &'a Obj,
        out: &mut Vec<&'a BTreeMap<String, Obj>>,
        seen: &mut Vec<*const Obj>,
        depth: usize,
    ) {
        let Some(dict) = node.dict() else { return };
        if depth > 30 || seen.contains(&(node as *const Obj)) {
            return;
        }
        seen.push(node as *const Obj);
        match dict.get("Type").and_then(Obj::name) {
            Some("Pages") => {
                if let Obj::Array(kids) = self.get(dict, "Kids") {
                    for kid in kids {
                        self.walk(self.resolve(kid), out, seen, depth + 1);
                    }
                }
            }
            _ => out.push(dict),
        }
    }

    /// An inheritable page attribute.
    fn inherited<'a>(&'a self, page: &'a BTreeMap<String, Obj>, key: &str) -> &'a Obj {
        let mut current = page;
        for _ in 0..30 {
            if let Some(v) = current.get(key) {
                return self.resolve(v);
            }
            match self.get(current, "Parent").dict() {
                Some(parent) => current = parent,
                None => break,
            }
        }
        &Obj::Null
    }
}

const CP1252_HIGH: [char; 32] = [
    '€', '\u{81}', '‚', 'ƒ', '„', '…', '†', '‡', 'ˆ', '‰', 'Š', '‹', 'Œ', '\u{8d}', 'Ž', '\u{8f}',
    '\u{90}', '‘', '’', '“', '”', '•', '–', '—', '˜', '™', 'š', '›', 'œ', '\u{9d}', 'ž', 'Ÿ',
];

fn cp1252(byte: u8) -> char {
    match byte {
        0x80..=0x9f => CP1252_HIGH[usize::from(byte - 0x80)],
        b => char::from(b),
    }
}

/// How a font turns character codes into text.
#[derive(Default, Clone)]
struct Font {
    map: BTreeMap<u32, String>,
    width: usize,
    has_map: bool,
    composite: bool,
}

impl Font {
    fn decode(&self, bytes: &[u8]) -> Option<String> {
        if self.has_map {
            let width = self.width.max(1);
            let mut out = String::new();
            for chunk in bytes.chunks(width) {
                let code = chunk.iter().fold(0u32, |a, &b| a << 8 | u32::from(b));
                if let Some(text) = self.map.get(&code) {
                    out.push_str(text);
                } else if width == 1 && !self.composite {
                    out.push(cp1252(chunk[0]));
                }
            }
            return Some(out);
        }
        if self.composite {
            return None;
        }
        Some(bytes.iter().map(|&b| cp1252(b)).collect())
    }
}

fn utf16_text(bytes: &[u8]) -> String {
    let units: Vec<u16> = bytes
        .chunks(2)
        .map(|c| u16::from_be_bytes([c[0], c.get(1).copied().unwrap_or(0)]))
        .collect();
    String::from_utf16_lossy(&units)
}

fn parse_cmap(data: &[u8]) -> (BTreeMap<u32, String>, usize) {
    let mut map = BTreeMap::new();
    let mut width = 0;
    let mut lex = Lex { data, pos: 0 };
    let mut stack: Vec<Obj> = Vec::new();
    loop {
        lex.skip();
        if lex.pos >= data.len() {
            break;
        }
        let b = data[lex.pos];
        if b == b'<' || b == b'[' || b == b'/' || b == b'(' || b.is_ascii_digit() || b == b'-' {
            match lex.object(0) {
                Some(o) => stack.push(o),
                None => lex.pos += 1,
            }
            continue;
        }
        let word = lex.word().to_vec();
        if word.is_empty() {
            lex.pos += 1;
            continue;
        }
        match word.as_slice() {
            b"endbfchar" | b"endbfrange" => {
                let range = word == b"endbfrange";
                let step = if range { 3 } else { 2 };
                let mut i = 0;
                while i + step <= stack.len() {
                    if let (Obj::Str(src), dest) = (&stack[i], &stack[i + step - 1]) {
                        width = width.max(src.len());
                        let code = src.iter().fold(0u32, |a, &b| a << 8 | u32::from(b));
                        if !range {
                            if let Obj::Str(d) = dest {
                                map.insert(code, utf16_text(d));
                            }
                        } else if let Obj::Str(hi) = &stack[i + 1] {
                            let high = hi.iter().fold(0u32, |a, &b| a << 8 | u32::from(b));
                            if high >= code && high - code < 65_536 {
                                match dest {
                                    Obj::Str(d) => {
                                        let base = utf16_text(d);
                                        let chars: Vec<char> = base.chars().collect();
                                        for offset in 0..=(high - code) {
                                            let mut c = chars.clone();
                                            if let Some(last) = c.last_mut() {
                                                *last = char::from_u32(u32::from(*last) + offset)
                                                    .unwrap_or(*last);
                                            }
                                            map.insert(code + offset, c.iter().collect());
                                        }
                                    }
                                    Obj::Array(list) => {
                                        for (offset, item) in list.iter().enumerate() {
                                            if let Obj::Str(d) = item {
                                                map.insert(code + offset as u32, utf16_text(d));
                                            }
                                        }
                                    }
                                    _ => {}
                                }
                            }
                        }
                    }
                    i += step;
                }
                stack.clear();
            }
            b"begincodespacerange" => stack.clear(),
            b"endcodespacerange" => {
                if let Some(Obj::Str(s)) = stack.first() {
                    width = width.max(s.len());
                }
                stack.clear();
            }
            b"beginbfchar" | b"beginbfrange" => stack.clear(),
            _ => {}
        }
    }
    (map, width)
}

fn load_font(doc: &Doc, dict: &BTreeMap<String, Obj>) -> Result<Font, PdfError> {
    let composite = doc.get(dict, "Subtype").name() == Some("Type0");
    let mut font = Font {
        composite,
        width: if composite { 2 } else { 1 },
        ..Font::default()
    };
    if let Some(unicode) = dict.get("ToUnicode") {
        let data = doc.stream_bytes(unicode)?;
        let (map, width) = parse_cmap(&data);
        if !map.is_empty() {
            font.map = map;
            font.has_map = true;
            if width > 0 {
                font.width = width;
            }
        }
    }
    Ok(font)
}

#[derive(Default)]
struct Page {
    text: String,
    decoded_any: bool,
    undecodable: bool,
    shows_text: bool,
}

impl Page {
    fn newline(&mut self) {
        if !self.text.is_empty() && !self.text.ends_with('\n') {
            self.text.push('\n');
        }
    }

    fn space(&mut self) {
        if !self.text.is_empty() && !self.text.ends_with([' ', '\n']) {
            self.text.push(' ');
        }
    }

    fn show(&mut self, font: Option<&Font>, bytes: &[u8]) {
        self.shows_text = true;
        let decoded = match font {
            Some(f) => f.decode(bytes),
            None => Some(bytes.iter().map(|&b| cp1252(b)).collect()),
        };
        match decoded {
            Some(t) => {
                self.decoded_any = true;
                self.text.push_str(&t);
            }
            None => self.undecodable = true,
        }
    }
}

fn run_content(content: &[u8], fonts: &BTreeMap<String, Font>, page: &mut Page) {
    let mut lex = Lex {
        data: content,
        pos: 0,
    };
    let mut operands: Vec<Obj> = Vec::new();
    let mut font: Option<&Font> = None;
    let mut size = 12.0_f64;
    let mut last_y: Option<f64> = None;
    loop {
        lex.skip();
        let Some(&b) = content.get(lex.pos) else {
            break;
        };
        let operand_start =
            matches!(b, b'/' | b'(' | b'<' | b'[' | b'-' | b'+' | b'.') || b.is_ascii_digit();
        if operand_start {
            match lex.object(0) {
                Some(o) => operands.push(o),
                None => lex.pos += 1,
            }
            if operands.len() > 64 {
                operands.remove(0);
            }
            continue;
        }
        let op = lex.word().to_vec();
        if op.is_empty() {
            lex.pos += 1;
            continue;
        }
        let nums: Vec<f64> = operands.iter().filter_map(Obj::num).collect();
        match op.as_slice() {
            b"BI" => {
                // an inline image: skip to its end
                if let Some(e) = find(content, b"EI", lex.pos) {
                    lex.pos = e + 2;
                }
            }
            b"Tf" => {
                if let (Some(Obj::Name(n)), Some(s)) = (operands.first(), nums.last()) {
                    font = fonts.get(n);
                    size = if *s == 0.0 { 12.0 } else { s.abs() };
                }
            }
            b"Tj" => {
                if let Some(Obj::Str(s)) = operands.last() {
                    page.show(font, s);
                }
            }
            b"'" => {
                page.newline();
                if let Some(Obj::Str(s)) = operands.last() {
                    page.show(font, s);
                }
            }
            b"\"" => {
                page.newline();
                if let Some(Obj::Str(s)) = operands.last() {
                    page.show(font, s);
                }
            }
            b"TJ" => {
                if let Some(Obj::Array(items)) = operands.last() {
                    for item in items {
                        match item {
                            Obj::Str(s) => page.show(font, s),
                            n => {
                                if n.num().is_some_and(|k| k < -250.0) {
                                    page.space();
                                }
                            }
                        }
                    }
                }
            }
            b"Td" | b"TD" => {
                if let [tx, ty] = nums[..] {
                    if ty.abs() > 0.01 {
                        page.newline();
                        if ty.abs() > size * 1.8 {
                            page.text.push('\n');
                        }
                    } else if tx.abs() > 0.01 {
                        page.space();
                    }
                }
            }
            b"T*" => page.newline(),
            b"Tm" => {
                if nums.len() == 6 {
                    let y = nums[5];
                    if last_y.is_some_and(|l| (l - y).abs() > 0.5) {
                        page.newline();
                    }
                    last_y = Some(y);
                }
            }
            b"ET" => page.newline(),
            _ => {}
        }
        operands.clear();
    }
}

fn clean(text: &str) -> String {
    let mut out = String::new();
    let mut blank = 0;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            blank += 1;
            continue;
        }
        if !out.is_empty() {
            out.push('\n');
            if blank > 0 {
                out.push('\n');
            }
        }
        blank = 0;
        out.push_str(line);
    }
    out
}

/// Reads the text layer of a PDF.
pub fn extract(data: &[u8], limits: &PdfLimits) -> Result<PdfText, PdfError> {
    if !data[..data.len().min(1024)]
        .windows(5)
        .any(|w| w == b"%PDF-")
    {
        return Err(PdfError::NotPdf);
    }
    let doc = Doc::scan(data, *limits);
    if doc.trailers.iter().any(|t| t.contains_key("Encrypt")) {
        return Err(PdfError::Encrypted);
    }
    let pages = doc.pages();
    if pages.is_empty() {
        return Err(PdfError::Damaged("it has no pages".into()));
    }
    let mut texts = Vec::new();
    let mut any_text = false;
    let mut any_undecodable = false;
    for page in pages.into_iter().take(limits.max_pages) {
        let mut fonts: BTreeMap<String, Font> = BTreeMap::new();
        if let Some(resources) = doc.inherited(page, "Resources").dict()
            && let Some(table) = doc.get(resources, "Font").dict()
        {
            for (name, entry) in table {
                if let Some(dict) = doc.resolve(entry).dict() {
                    fonts.insert(name.clone(), load_font(&doc, dict)?);
                }
            }
        }
        let mut content = Vec::new();
        match doc.get(page, "Contents") {
            Obj::Array(parts) => {
                for part in parts {
                    content.extend(doc.stream_bytes(part)?);
                    content.push(b'\n');
                }
            }
            Obj::Stream(d, raw) => content = doc.decode(d, raw)?,
            _ => {}
        }
        let mut out = Page::default();
        run_content(&content, &fonts, &mut out);
        any_undecodable |= out.undecodable;
        let text = clean(&out.text);
        any_text |= !text.is_empty();
        texts.push(text);
    }
    if !any_text {
        return Err(if any_undecodable {
            PdfError::Unsupported("fonts without a text map (no ToUnicode)".into())
        } else {
            PdfError::NoTextLayer
        });
    }
    Ok(PdfText { pages: texts })
}
