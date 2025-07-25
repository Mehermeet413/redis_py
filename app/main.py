import socket  # noqa: F401
import threading
import time
import sys
import argparse
import os
import struct

# In-memory storage for key-value pairs
# Format: {key: {"value": value, "expiry": timestamp_in_seconds}}
redis_store = {}

# Configuration storage
config = {
    "dir": "/tmp/redis-files",  # Default value
    "dbfilename": "dump.rdb"     # Default value
}


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


def is_key_expired(key):
    """
    Check if a key has expired and remove it if so.
    Returns True if the key was expired and removed, False otherwise.
    """
    if key not in redis_store:
        return False
    
    key_data = redis_store[key]
    if isinstance(key_data, dict) and "expiry" in key_data:
        if time.time() > key_data["expiry"]:
            del redis_store[key]
            return True
    return False


def handle_connection(connection):
    try:
        while True:
            data: bytes = connection.recv(1024)
            if not data:
                break

            print(f"Received: {data}")
            command = parse_resp(data)

            if command is None:
                continue

            cmd = command[0].upper()

            if cmd == "PING":
                connection.sendall(b"+PONG\r\n")
            elif cmd == "ECHO" and len(command) == 2:
                message = command[1]
                connection.sendall(encode_bulk_string(message))
            elif cmd == "SET":
                if len(command) == 3:
                    # SET key value
                    key = command[1]
                    value = command[2]
                    redis_store[key] = value
                    connection.sendall(b"+OK\r\n")
                elif len(command) == 5 and command[3].upper() == "PX":
                    # SET key value PX milliseconds
                    key = command[1]
                    value = command[2]
                    expiry_ms = int(command[4])
                    expiry_time = time.time() + (expiry_ms / 1000.0)
                    redis_store[key] = {"value": value, "expiry": expiry_time}
                    connection.sendall(b"+OK\r\n")
                else:
                    connection.sendall(b"-ERR wrong number of arguments for 'set' command\r\n")
            elif cmd == "GET" and len(command) == 2:
                key = command[1]
                # Check if key exists and is not expired
                if key in redis_store and not is_key_expired(key):
                    key_data = redis_store[key]
                    if isinstance(key_data, dict):
                        value = key_data["value"]
                    else:
                        value = key_data  # For backwards compatibility with non-expiring keys
                    connection.sendall(encode_bulk_string(value))
                else:
                    connection.sendall(encode_null_bulk_string())
            elif cmd == "CONFIG" and len(command) == 3 and command[1].upper() == "GET":
                param_name = command[2].lower()
                if param_name in config:
                    response = encode_resp_array([param_name, config[param_name]])
                    connection.sendall(response)
                else:
                    # Return empty array for unknown configuration parameters
                    connection.sendall(b"*0\r\n")
            elif cmd == "KEYS" and len(command) == 2:
                pattern = command[1]
                if pattern == "*":
                    # Return all keys (filter out expired ones)
                    active_keys = []
                    for key in list(redis_store.keys()):
                        if not is_key_expired(key):
                            active_keys.append(key)
                    response = encode_resp_array(active_keys)
                    connection.sendall(response)
                else:
                    # For this stage, only support "*" pattern
                    connection.sendall(b"*0\r\n")
            else:
                connection.sendall(b"-ERR unknown command\r\n")

    finally:
        connection.close()


def load_rdb_file(file_path):
    """
    Loads the RDB file and populates the in-memory database.
    """
    if not os.path.exists(file_path):
        print("RDB file not found, starting with an empty database.")
        return

    print(f"Loading RDB file: {file_path}")
    with open(file_path, "rb") as f:
        # Read and verify the header
        header = f.read(9)
        if not header.startswith(b"REDIS"):
            raise ValueError("Invalid RDB file format.")
        print(f"RDB version: {header.decode()}")

        # Parse the RDB file
        while True:
            byte = f.read(1)
            if not byte:
                break

            byte_val = ord(byte)
            
            if byte_val == 0xFA:  # Metadata section
                # Skip metadata
                key = read_encoded_string(f)
                value = read_encoded_string(f)
                print(f"Metadata: {key} = {value}")
            elif byte_val == 0xFE:  # Database section
                db_index = read_size_encoded(f)
                print(f"Database index: {db_index}")
            elif byte_val == 0xFB:  # Hash table size info
                hash_table_size = read_size_encoded(f)
                expire_hash_table_size = read_size_encoded(f)
                print(f"Hash table sizes: {hash_table_size}, {expire_hash_table_size}")
            elif byte_val == 0xFF:  # End of file
                print("End of RDB file.")
                break
            elif byte_val == 0xFC:  # Expire time in milliseconds
                expire_time_ms = struct.unpack('<Q', f.read(8))[0]
                value_type = ord(f.read(1))
                key = read_encoded_string(f)
                value = read_encoded_string(f)
                expire_time_sec = expire_time_ms / 1000.0
                redis_store[key] = {"value": value, "expiry": expire_time_sec}
                print(f"Loaded key with expiry: {key} = {value} (expires at {expire_time_sec})")
            elif byte_val == 0xFD:  # Expire time in seconds
                expire_time_sec = struct.unpack('<I', f.read(4))[0]
                value_type = ord(f.read(1))
                key = read_encoded_string(f)
                value = read_encoded_string(f)
                redis_store[key] = {"value": value, "expiry": float(expire_time_sec)}
                print(f"Loaded key with expiry: {key} = {value} (expires at {expire_time_sec})")
            elif byte_val == 0x00:  # String value type
                key = read_encoded_string(f)
                value = read_encoded_string(f)
                redis_store[key] = value
                print(f"Loaded key: {key} = {value}")
            else:
                print(f"Unknown byte: 0x{byte_val:02x}")
                break


def read_encoded_string(f):
    """
    Reads an encoded string from the file.
    """
    # First, peek at the length byte to check for special encodings
    pos = f.tell()
    length_byte = ord(f.read(1))
    f.seek(pos)
    
    if (length_byte & 0xC0) == 0xC0:  # Special string encoding
        encoding_type = length_byte & 0x3F
        f.read(1)  # consume the length byte
        if encoding_type == 0:  # 8-bit integer
            value = struct.unpack('B', f.read(1))[0]
            return str(value)
        elif encoding_type == 1:  # 16-bit integer
            value = struct.unpack('<H', f.read(2))[0]
            return str(value)
        elif encoding_type == 2:  # 32-bit integer
            value = struct.unpack('<I', f.read(4))[0]
            return str(value)
        else:
            raise ValueError(f"Unsupported special string encoding: {encoding_type}")
    else:
        # Regular string encoding
        length = read_size_encoded(f)
        return f.read(length).decode()


def read_size_encoded(f):
    """
    Reads a size-encoded integer from the file.
    """
    byte = ord(f.read(1))
    if (byte & 0xC0) == 0x00:  # 6-bit encoding
        return byte & 0x3F
    elif (byte & 0xC0) == 0x40:  # 14-bit encoding
        return ((byte & 0x3F) << 8) | ord(f.read(1))
    elif (byte & 0xC0) == 0x80:  # 32-bit encoding
        return struct.unpack(">I", f.read(4))[0]
    elif (byte & 0xC0) == 0xC0:  # Special string encoding
        encoding_type = byte & 0x3F
        if encoding_type == 0:  # 8-bit integer
            return struct.unpack('B', f.read(1))[0]
        elif encoding_type == 1:  # 16-bit integer
            return struct.unpack('<H', f.read(2))[0]
        elif encoding_type == 2:  # 32-bit integer
            return struct.unpack('<I', f.read(4))[0]
        else:
            raise ValueError(f"Unsupported special encoding: {encoding_type}")
    else:
        raise ValueError(f"Unknown encoding pattern: 0x{byte:02x}")


def parse_arguments():
    """
    Parse command-line arguments for --dir and --dbfilename.
    """
    parser = argparse.ArgumentParser(description="Redis Server")
    parser.add_argument("--dir", default="/tmp/redis-files", help="Directory for RDB file")
    parser.add_argument("--dbfilename", default="dump.rdb", help="RDB filename")
    return parser.parse_args()


def main():
    # Parse command-line arguments and update config
    args = parse_arguments()
    config["dir"] = args.dir
    config["dbfilename"] = args.dbfilename
    
    print(f"Configuration: dir={config['dir']}, dbfilename={config['dbfilename']}")
    
    # Load RDB file if it exists
    rdb_file_path = os.path.join(config["dir"], config["dbfilename"])
    try:
        load_rdb_file(rdb_file_path)
    except Exception as e:
        print(f"Error loading RDB file: {e}")
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", 6379))
    server_socket.listen(5)
    print("Listening on port 6379...")
    while True:
        connection, _ = server_socket.accept()
        thread = threading.Thread(target=handle_connection, args=(connection,))
        thread.start()


if __name__ == "__main__":
    main()
