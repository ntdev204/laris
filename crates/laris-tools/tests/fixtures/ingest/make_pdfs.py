"""Writes the PDF fixtures of the ingestion tests (T148). Run once; the PDFs are committed.

    python3 make_pdfs.py

The files are built by hand from the PDF syntax so that each one has exactly one feature: a text layer compressed
with FlateDecode, a ToUnicode map, an object stream, a scan (a picture and no text), encryption, a font that cannot be
decoded, a damaged stream. Nothing here uses a PDF library.
"""
import zlib
from pathlib import Path

HERE = Path(__file__).parent


def stream(dict_body: str, data: bytes, compress: bool = True) -> bytes:
    if compress:
        data = zlib.compress(data)
        dict_body += " /Filter /FlateDecode"
    return f"<< {dict_body} /Length {len(data)} >>\nstream\n".encode() + data + b"\nendstream"


def pdf(objects: dict[int, bytes], root: int = 1, trailer_extra: str = "") -> bytes:
    out = b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n"
    for number, body in sorted(objects.items()):
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    out += f"trailer\n<< /Size {max(objects) + 1} /Root {root} 0 R {trailer_extra} >>\n%%EOF\n".encode()
    return out


def simple_font() -> bytes:
    return b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"


# 1. two pages, WinAnsi text, kerning in TJ, line moves, a page whose contents are an array of streams
page1 = (
    b"BT /F1 12 Tf 72 720 Td (Perovskite solar cells reach high efficiency.) Tj\n"
    b"0 -14 Td (Stability under heat remains the main limit.) Tj ET\n"
    b"BT /F1 12 Tf 72 640 Td [(Encapsula) -20 (tion) -400 (with glass helps) ] TJ ET"
)
page2a = b"BT /F1 12 Tf 72 720 Td (Caf\\351 results: 25\\2223 percent) Tj"
page2b = b"0 -40 Td (Second paragraph of page two.) Tj ET"
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R 6 0 R] /Count 2 /Resources << /Font << /F1 5 0 R >> >> >>",
    3: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R >>",
    4: stream("", page1),
    5: simple_font(),
    6: b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents [7 0 R 8 0 R] >>",
    7: stream("", page2a),
    8: stream("", page2b, compress=False),
}
(HERE / "report.pdf").write_bytes(pdf(objs))

# 2. a ToUnicode map: codes 1..6 stand for Vietnamese letters, and a composite font with a two-byte range
cmap = b"""/CIDInit /ProcSet findresource begin 12 dict begin begincmap
1 begincodespacerange <00> <FF> endcodespacerange
3 beginbfchar
<01> <0056>
<02> <1EA1>
<03> <006E>
endbfchar
1 beginbfrange
<04> <06> <0061>
endbfrange
endcmap end end"""
cmap2 = b"""1 begincodespacerange <0000> <FFFF> endcodespacerange
1 beginbfrange
<0010> <0014> <0041>
endbfrange
1 beginbfchar
<0020> <0020>
endbfchar"""
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R /F2 7 0 R >> >> /Contents 4 0 R >>",
    4: stream("", b"BT /F1 12 Tf 72 700 Td <010203> Tj 0 -14 Td <040506> Tj ET\nBT /F2 12 Tf 72 600 Td <0010001100120020001300 14> Tj ET".replace(b"00 14", b"0014")),
    5: b"<< /Type /Font /Subtype /Type1 /BaseFont /Custom /ToUnicode 6 0 R >>",
    6: stream("", cmap),
    7: b"<< /Type /Font /Subtype /Type0 /BaseFont /CID /Encoding /Identity-H /DescendantFonts [] /ToUnicode 8 0 R >>",
    8: stream("", cmap2),
}
(HERE / "tounicode.pdf").write_bytes(pdf(objs))

# 3. objects inside an object stream, the root found through a cross reference stream
inner = {1: b"<< /Type /Catalog /Pages 2 0 R >>", 2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
         3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 6 0 R >> >> /Contents 4 0 R >>"}
head, body = "", b""
for n, b in inner.items():
    head += f"{n} {len(body)} "
    body += b + b" "
objstm = stream(f"/Type /ObjStm /N {len(inner)} /First {len(head)}", head.encode() + body)
objs = {
    4: stream("", b"BT /F1 12 Tf 72 700 Td (Read from an object stream.) Tj ET"),
    5: objstm,
    6: simple_font(),
    7: b"<< /Type /XRef /Size 8 /Root 1 0 R /W [1 2 1] /Length 0 >>\nstream\n\nendstream",
}
data = b"%PDF-1.5\n"
for n, b in sorted(objs.items()):
    data += f"{n} 0 obj\n".encode() + b + b"\nendobj\n"
data += b"%%EOF\n"
(HERE / "objstm.pdf").write_bytes(data)

# 4. a scan: one picture per page and no text
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>",
    4: stream("", b"q 612 0 0 792 0 0 cm /Im0 Do Q"),
    5: stream("/Type /XObject /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8", bytes([0, 255, 255, 0]), compress=False),
}
(HERE / "scan.pdf").write_bytes(pdf(objs))

# 5. encrypted
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
    4: stream("", b"BT (hidden) Tj ET"),
    5: b"<< /Filter /Standard /V 2 /R 3 /O (x) /U (y) /P -4 >>",
}
(HERE / "encrypted.pdf").write_bytes(pdf(objs, trailer_extra="/Encrypt 5 0 R"))

# 6. a composite font with no ToUnicode map: the codes mean nothing without it
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    4: stream("", b"BT /F1 12 Tf 72 700 Td <00240025> Tj ET"),
    5: b"<< /Type /Font /Subtype /Type0 /BaseFont /CID /Encoding /Identity-H /DescendantFonts [] >>",
}
(HERE / "no_map.pdf").write_bytes(pdf(objs))

# 7. a stream that is not valid deflate data, and one with a filter that is not supported
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
    4: b"<< /Filter /FlateDecode /Length 12 >>\nstream\nnot deflated!\nendstream",
}
(HERE / "damaged.pdf").write_bytes(pdf(objs))
objs[4] = b"<< /Filter /LZWDecode /Length 4 >>\nstream\nabcd\nendstream"
(HERE / "lzw.pdf").write_bytes(pdf(objs))
# 8. a long text layer: the stream is big enough for dynamic Huffman blocks and back references
lines = [f"Line {i}: measurement {i * 7 % 13} of sample {chr(65 + i % 26)}{i} is recorded in table {i % 9}." for i in range(300)]
content = b"BT /F1 10 Tf 72 780 Td 12 TL\n" + b"".join(f"({l}) '\n".encode() for l in lines) + b"ET"
objs = {
    1: b"<< /Type /Catalog /Pages 2 0 R >>",
    2: b"<< /Type /Pages /Kids [3 0 R] /Count 1 /Resources << /Font << /F1 5 0 R >> >> >>",
    3: b"<< /Type /Page /Parent 2 0 R /Contents 4 0 R >>",
    4: stream("", content),
    5: simple_font(),
}
(HERE / "long.pdf").write_bytes(pdf(objs))
print("written")
