import socket  # noqa: F401
import threading
import time
import sys
import os
import struct

from config import config, replication_config, redis_store
from args_parser import parse_arguments
from resp_protocol import parse_resp, encode_bulk_string, encode_null_bulk_string, encode_resp_array
from commands import handle_connection

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


def connect_to_master():
    """
    Connects to the master server and performs the initial handshake.
    Sends a PING command as the first step of the replication handshake.
    """
    master_host = replication_config["master_host"]
    master_port = replication_config["master_port"]
    
    try:
        # Create connection to master
        master_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        master_socket.connect((master_host, master_port))
        print(f"Connected to master at {master_host}:{master_port}")
        
        # Send PING command in RESP format: *1\r\n$4\r\nPING\r\n
        ping_command = b"*1\r\n$4\r\nPING\r\n"
        master_socket.send(ping_command)
        print("Sent PING command to master")
        
        # Receive response from master
        response = master_socket.recv(1024)
        print(f"Received response from master: {response}")
        
        # Keep the connection open for future replication steps
        # For now, we'll close it, but in later stages this will remain open
        master_socket.close()
        print("Handshake completed successfully")
        
    except Exception as e:
        print(f"Error connecting to master: {e}")
        sys.exit(1)


def main():
    # Parse command-line arguments and update config
    args = parse_arguments()
    config["dir"] = args.dir
    config["dbfilename"] = args.dbfilename
    port = args.port
    
    # Handle replicaof configuration
    if args.replicaof:
        try:
            master_host, master_port = args.replicaof.split()
            replication_config["role"] = "slave"
            replication_config["master_host"] = master_host
            replication_config["master_port"] = int(master_port)
            print(f"Configured as replica of {master_host}:{master_port}")
        except ValueError:
            print("Error: --replicaof format should be 'host port'")
            sys.exit(1)
    else:
        print("Configured as master")
    
    print(f"Configuration: dir={config['dir']}, dbfilename={config['dbfilename']}, port={port}, role={replication_config['role']}")
    
    # Load RDB file if it exists
    rdb_file_path = os.path.join(config["dir"], config["dbfilename"])
    try:
        load_rdb_file(rdb_file_path)
    except Exception as e:
        print(f"Error loading RDB file: {e}")
    
    # If this is a replica, connect to master and perform handshake
    if replication_config["role"] == "slave":
        connect_to_master()
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", port))
    server_socket.listen(5)
    print(f"Listening on port {port}...")
    while True:
        connection, _ = server_socket.accept()
        thread = threading.Thread(target=handle_connection, args=(connection,))
        thread.start()


if __name__ == "__main__":
    main()
