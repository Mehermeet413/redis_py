def parse_resp(data: bytes):
    """
    Parses RESP arrays like: *2\r\n$4\r\nECHO\r\n$3\r\nhey\r\n
    Returns: ["ECHO", "hey"]
    """
    if not data.startswith(b"*"):
        return None

    lines = data.split(b"\r\n")
    num_elements = int(lines[0][1:])

    elements = []
    i = 1
    while len(elements) < num_elements and i < len(lines):
        if lines[i].startswith(b"$"):
            length = int(lines[i][1:])
            value = lines[i + 1]
            elements.append(value.decode())
            i += 2
        else:
            i += 1
    return elements


def encode_bulk_string(value: str):
    return f"${len(value)}\r\n{value}\r\n".encode()


def encode_null_bulk_string():
    return b"$-1\r\n"


def encode_resp_array(elements):
    """
    Encode a RESP array from a list of strings.
    Example: ["dir", "/tmp/redis-files"] -> *2\r\n$3\r\ndir\r\n$16\r\n/tmp/redis-files\r\n
    """
    result = f"*{len(elements)}\r\n".encode()
    for element in elements:
        result += encode_bulk_string(element)
    return result
