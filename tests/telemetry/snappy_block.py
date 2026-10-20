"""Bounded raw Snappy decoder for the local-only protobuf telemetry test sink.

Only used to assert signal markers; decoded payloads are never retained or printed.
Format: https://github.com/google/snappy/blob/main/format_description.txt
"""
def decode(data, maximum=16 * 1024 * 1024):
    pos, size, shift = 0, 0, 0
    while True:
        byte = data[pos]; pos += 1
        size |= (byte & 127) << shift
        if not byte & 128: break
        shift += 7
        if shift > 28: raise ValueError('Invalid Snappy length')
    if size > maximum: raise ValueError('Decoded payload too large')
    out = bytearray()
    while pos < len(data):
        tag = data[pos]; pos += 1
        kind = tag & 3
        if kind == 0:
            length = tag >> 2
            if length < 60: length += 1
            else:
                count = length - 59
                length = int.from_bytes(data[pos:pos+count], 'little') + 1
                pos += count
            if pos + length > len(data): raise ValueError('Truncated literal')
            out.extend(data[pos:pos+length]); pos += length
        else:
            count = {1: 1, 2: 2, 3: 4}[kind]
            if pos + count > len(data): raise ValueError('Truncated copy')
            offset = int.from_bytes(data[pos:pos+count], 'little'); pos += count
            if kind == 1:
                offset |= (tag & 224) << 3
                length = 4 + ((tag >> 2) & 7)
            else: length = 1 + (tag >> 2)
            if not 0 < offset <= len(out): raise ValueError('Invalid copy offset')
            if len(out) + length > size: raise ValueError('Invalid copy length')
            for _ in range(length): out.append(out[-offset])
        if len(out) > size: raise ValueError('Invalid decoded size')
    if len(out) != size: raise ValueError('Invalid decoded size')
    return bytes(out)
