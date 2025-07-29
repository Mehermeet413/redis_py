import socket  # noqa: F401
import threading
import time
import sys
import os
import struct
import argparse

# Configuration storage
config = {
    "dir": "/tmp/redis-files",  # Default value
    "dbfilename": "dump.rdb"     # Default value
}

# Replication configuration
replication_config = {
    "role": "master",  # Default role is master
    "master_host": None,
    "master_port": None,
    "master_replid": "8371b4fb1155b71f4a04d3e1bc3e18c4a990aeeb",  # 40-character replication ID
    "master_repl_offset": 0  # Replication offset starts at 0
}

# In-memory storage for key-value pairs
# Format: {key: {"value": value, "expiry": timestamp_in_seconds}}
redis_store = {}

# List to track replica connections for command propagation
replica_connections = []


def parse_arguments():
    """Parse command line arguments for the Redis server."""
    parser = argparse.ArgumentParser(description="Redis Server")
    parser.add_argument("--dir", type=str, help="Directory for RDB files")
    parser.add_argument("--dbfilename", type=str, help="RDB filename")
    parser.add_argument("--port", type=int, default=6379, help="Port to listen on")
    parser.add_argument("--replicaof", type=str, help="Master host and port (e.g., 'localhost 6379')")
    
    return parser.parse_args()


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


def parse_multiple_resp_commands(data: bytes):
    """
    Parses multiple RESP commands from a single buffer.
    Returns a list of commands and any remaining incomplete data.
    """
    commands = []
    remaining_data = data
    
    while remaining_data:
        if not remaining_data.startswith(b"*"):
            break
            
        # Find the end of this command
        lines = remaining_data.split(b"\r\n")
        if len(lines) < 2:
            break  # Incomplete command
            
        try:
            num_elements = int(lines[0][1:])
        except (ValueError, IndexError):
            break
            
        # Calculate how many lines this command needs
        lines_needed = 1 + (num_elements * 2)  # 1 for array header + 2 per element (length + data)
        
        if len(lines) < lines_needed:
            break  # Incomplete command
            
        # Extract this command's data
        command_lines = lines[:lines_needed]
        command_data = b"\r\n".join(command_lines) + b"\r\n"
        
        # Parse this single command
        command = parse_resp(command_data)
        if command:
            commands.append(command)
            
        # Remove processed command from remaining data
        remaining_data = b"\r\n".join(lines[lines_needed:])
        if remaining_data == b"":
            remaining_data = b""
            break
            
    return commands, remaining_data


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


def handle_ping():
    return b"+PONG\r\n"


def handle_echo(message):
    return encode_bulk_string(message)


def handle_set(command, silent=False):
    """
    Handles SET command. If silent=True, doesn't return response (for propagated commands).
    """
    response = None
    if len(command) == 3:
        # SET key value
        key = command[1]
        value = command[2]
        redis_store[key] = value
        if not silent:
            response = b"+OK\r\n"
    elif len(command) == 5 and command[3].upper() == "PX":
        # SET key value PX milliseconds
        key = command[1]
        value = command[2]
        expiry_ms = int(command[4])
        expiry_time = time.time() + (expiry_ms / 1000.0)
        redis_store[key] = {"value": value, "expiry": expiry_time}
        if not silent:
            response = b"+OK\r\n"
    else:
        if not silent:
            return b"-ERR wrong number of arguments for 'set' command\r\n"
        return None
    
    # Propagate write commands to replicas if we're acting as master
    if not silent and response is not None and replication_config["role"] == "master":
        propagate_command_to_replicas(command)
    
    return response


def process_propagated_command(command, master_socket=None):
    """
    Processes a command propagated from master.
    Most commands are processed silently (no response), but REPLCONF GETACK
    requires a response back to the master.
    """
    if not command:
        return
        
    command_name = command[0].upper()
    
    if command_name == "SET":
        handle_set(command, silent=True)
        print(f"Processed propagated command: {command}")
    elif command_name == "REPLCONF" and len(command) >= 3 and command[1].upper() == "GETACK":
        # Handle REPLCONF GETACK * command
        print(f"Received REPLCONF GETACK command: {command}")
        if master_socket:
            # Respond with REPLCONF ACK 0 (hardcoded offset for now)
            # Format: *3\r\n$8\r\nREPLCONF\r\n$3\r\nACK\r\n$1\r\n0\r\n
            ack_response = b"*3\r\n$8\r\nREPLCONF\r\n$3\r\nACK\r\n$1\r\n0\r\n"
            master_socket.send(ack_response)
            print("Sent REPLCONF ACK 0 response to master")
    # Add other write commands as needed (DEL, etc.)
    else:
        print(f"Ignoring unsupported propagated command: {command}")


def handle_get(key):
    # Check if key exists and is not expired
    if key in redis_store and not is_key_expired(key):
        key_data = redis_store[key]
        if isinstance(key_data, dict):
            value = key_data["value"]
        else:
            value = key_data  # For backwards compatibility with non-expiring keys
        return encode_bulk_string(value)
    else:
        return encode_null_bulk_string()


def handle_config_get(param_name):
    param_name = param_name.lower()
    if param_name in config:
        response = encode_resp_array([param_name, config[param_name]])
        return response
    else:
        # Return empty array for unknown configuration parameters
        return b"*0\r\n"


def handle_keys(pattern):
    if pattern == "*":
        # Return all keys (filter out expired ones)
        active_keys = []
        for key in list(redis_store.keys()):
            if not is_key_expired(key):
                active_keys.append(key)
        response = encode_resp_array(active_keys)
        return response
    else:
        # For this stage, only support "*" pattern
        return b"*0\r\n"


def handle_info_replication():
    # Return replication information as a bulk string
    role = replication_config["role"]
    replid = replication_config["master_replid"]
    offset = replication_config["master_repl_offset"]
    
    # Build multi-line response
    info_lines = [
        f"role:{role}",
        f"master_replid:{replid}",
        f"master_repl_offset:{offset}"
    ]
    info_response = "\n".join(info_lines)
    return encode_bulk_string(info_response)


def handle_replconf(command):
    """
    Handles REPLCONF command from replicas during handshake.
    For now, we ignore the arguments and just respond with OK.
    """
    # Log the REPLCONF command for debugging
    if len(command) >= 2:
        subcommand = command[1].lower()
        if subcommand == "listening-port" and len(command) >= 3:
            port = command[2]
            print(f"Replica listening on port {port}")
        elif subcommand == "capa" and len(command) >= 3:
            capability = command[2]
            print(f"Replica capability: {capability}")
        else:
            print(f"REPLCONF subcommand: {' '.join(command[1:])}")
    
    # Always respond with OK for any REPLCONF command
    return b"+OK\r\n"


def propagate_command_to_replicas(command):
    """
    Propagates a write command to all connected replicas.
    Commands are sent as RESP arrays over the replication connection.
    """
    if not replica_connections:
        return  # No replicas to propagate to
    
    # Encode the command as a RESP array
    command_resp = encode_resp_array(command)
    
    # Send to all replicas (remove any closed connections)
    active_replicas = []
    for replica_conn in replica_connections:
        try:
            replica_conn.send(command_resp)
            active_replicas.append(replica_conn)
            print(f"Propagated command {command} to replica")
        except Exception as e:
            print(f"Failed to propagate command to replica: {e}")
            # Connection is broken, don't add it back to active list
    
    # Update the list with only active connections
    replica_connections[:] = active_replicas


def handle_psync(command, connection):
    """
    Handles PSYNC command from replicas during handshake.
    Responds with FULLRESYNC and then sends an empty RDB file.
    After the handshake, adds the connection to the replica list for command propagation.
    """
    # Log the PSYNC command for debugging
    if len(command) >= 3:
        repl_id = command[1]
        offset = command[2]
        print(f"Received PSYNC with repl_id='{repl_id}' offset='{offset}'")
    
    # Since this is the first time replica is connecting (repl_id=? and offset=-1),
    # we respond with FULLRESYNC containing our replication ID and current offset
    master_replid = replication_config["master_replid"]
    master_offset = replication_config["master_repl_offset"]
    
    # Format: +FULLRESYNC <REPL_ID> <OFFSET>\r\n
    fullresync_response = f"+FULLRESYNC {master_replid} {master_offset}\r\n".encode()
    print(f"Responding with FULLRESYNC {master_replid} {master_offset}")
    
    # Send the FULLRESYNC response first
    connection.send(fullresync_response)
    
    # After FULLRESYNC, send an empty RDB file
    # Using the canonical empty RDB file from CodeCrafters documentation
    # This is a minimal valid empty RDB file that should work for any replica
    empty_rdb_hex = "524544495330303131fa0972656469732d76657205372e322e30fa0a72656469732d62697473c040fa056374696d65c26d08bc65fa08757365642d6d656dc2b0c41000fa08616f662d62617365c000fff00fec0ff5aa2"
    
    try:
        # Convert hex to binary
        empty_rdb_binary = bytes.fromhex(empty_rdb_hex)
    except ValueError as e:
        print(f"Error converting hex to binary: {e}")
        # Fall back to a minimal empty RDB file
        # REDIS0011 (header) + 0xFF (EOF) + 8-byte checksum
        empty_rdb_binary = bytes([0x52, 0x45, 0x44, 0x49, 0x53, 0x30, 0x30, 0x31, 0x31, 0xFF, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00])
    
    # Send RDB file in format: $<length>\r\n<binary_contents>
    # Note: This is NOT a standard RESP bulk string (no trailing \r\n)
    rdb_length = len(empty_rdb_binary)
    rdb_header = f"${rdb_length}\r\n".encode()
    
    print(f"Sending empty RDB file ({rdb_length} bytes)")
    connection.send(rdb_header + empty_rdb_binary)
    
    # Add this connection to the replica list for command propagation
    # Only do this if we're acting as a master
    if replication_config["role"] == "master":
        replica_connections.append(connection)
        print(f"Added replica connection for command propagation (total: {len(replica_connections)})")
    
    # Return a special value to indicate this connection should be kept alive for replication
    return "REPLICA_CONNECTION"


def handle_connection(connection):
    is_replica_connection = False
    try:
        while True:
            data = connection.recv(1024)
            if not data:
                break

            # Parse the RESP data
            command = parse_resp(data)
            if not command:
                break

            command_name = command[0].upper()

            if command_name == "PING":
                response = handle_ping()
            elif command_name == "ECHO":
                response = handle_echo(command[1])
            elif command_name == "SET":
                response = handle_set(command)
            elif command_name == "GET":
                response = handle_get(command[1])
            elif command_name == "CONFIG" and len(command) == 3 and command[1].upper() == "GET":
                response = handle_config_get(command[2])
            elif command_name == "KEYS":
                response = handle_keys(command[1])
            elif command_name == "INFO" and len(command) == 2 and command[1].upper() == "REPLICATION":
                response = handle_info_replication()
            elif command_name == "REPLCONF":
                response = handle_replconf(command)
            elif command_name == "PSYNC":
                response = handle_psync(command, connection)
                # Check if this connection became a replica connection
                if response == "REPLICA_CONNECTION":
                    is_replica_connection = True
                    response = None  # Don't send anything back
            else:
                response = b"-ERR unknown command\r\n"

            # Only send response if it's not None and not a replica connection
            if response is not None and not is_replica_connection:
                connection.send(response)
                
            # If this became a replica connection, keep it alive but don't process more commands from it
            # The connection will be used only for sending propagated commands
            if is_replica_connection:
                print("Connection converted to replica connection, keeping alive for command propagation")
                # Keep the connection alive but don't process further commands from the replica
                # The replica won't send more commands anyway, it will just receive propagated commands
                while True:
                    try:
                        # Just keep the connection alive, but ignore any data received
                        # In a real implementation, we might handle REPLCONF GETACK here
                        connection.settimeout(1.0)  # Set a timeout to periodically check
                        data = connection.recv(1024)
                        if not data:
                            break
                    except socket.timeout:
                        # Timeout is expected, just continue to keep connection alive
                        continue
                    except Exception:
                        # Connection lost
                        break
                break
                
    except Exception as e:
        print(f"Error handling connection: {e}")
    finally:
        # Only close the connection if it's not a replica connection
        # Replica connections should stay open for command propagation
        if not is_replica_connection:
            connection.close()
        else:
            print("Replica connection ended, cleaning up")
            # Remove this connection from replica_connections if it's there
            if connection in replica_connections:
                replica_connections.remove(connection)
                print(f"Removed replica connection (remaining: {len(replica_connections)})")
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


def connect_to_master(replica_port):
    """
    Connects to the master server and performs the initial handshake.
    Sends PING, then two REPLCONF commands as part of the replication handshake.
    """
    master_host = replication_config["master_host"]
    master_port = replication_config["master_port"]
    
    try:
        # Create connection to master
        master_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        master_socket.connect((master_host, master_port))
        print(f"Connected to master at {master_host}:{master_port}")
        
        # Step 1: Send PING command in RESP format: *1\r\n$4\r\nPING\r\n
        ping_command = b"*1\r\n$4\r\nPING\r\n"
        master_socket.send(ping_command)
        print("Sent PING command to master")
        
        # Receive response from master
        response = master_socket.recv(1024)
        print(f"Received PING response from master: {response}")
        
        # Step 2: Send REPLCONF listening-port <PORT>
        # Use the actual port this replica is listening on
        port_str = str(replica_port)
        
        # Format: *3\r\n$8\r\nREPLCONF\r\n$14\r\nlistening-port\r\n$<port_len>\r\n<port>\r\n
        replconf_port_command = f"*3\r\n$8\r\nREPLCONF\r\n$14\r\nlistening-port\r\n${len(port_str)}\r\n{port_str}\r\n".encode()
        master_socket.send(replconf_port_command)
        print(f"Sent REPLCONF listening-port {port_str} command to master")
        
        # Receive response from master
        response = master_socket.recv(1024)
        print(f"Received REPLCONF listening-port response from master: {response}")
        
        # Step 3: Send REPLCONF capa psync2
        # Format: *3\r\n$8\r\nREPLCONF\r\n$4\r\ncapa\r\n$6\r\npsync2\r\n
        replconf_capa_command = b"*3\r\n$8\r\nREPLCONF\r\n$4\r\ncapa\r\n$6\r\npsync2\r\n"
        master_socket.send(replconf_capa_command)
        print("Sent REPLCONF capa psync2 command to master")
        
        # Receive response from master
        response = master_socket.recv(1024)
        print(f"Received REPLCONF capa response from master: {response}")
        
        # Step 4: Send PSYNC ? -1
        # Format: *3\r\n$5\r\nPSYNC\r\n$1\r\n?\r\n$2\r\n-1\r\n
        psync_command = b"*3\r\n$5\r\nPSYNC\r\n$1\r\n?\r\n$2\r\n-1\r\n"
        master_socket.send(psync_command)
        print("Sent PSYNC ? -1 command to master")
        
        # Receive response from master
        response = master_socket.recv(1024)
        print(f"Received PSYNC response from master: {response}")
        
        # After PSYNC, we expect to receive an RDB file
        # The RDB file comes as: $<length>\r\n<binary_data>
        # We need to read and consume it before processing commands
        print("Waiting for RDB file...")
        
        # Read the RDB file header: $<length>\r\n
        rdb_header_data = b""
        while b"\r\n" not in rdb_header_data:
            chunk = master_socket.recv(1)
            if not chunk:
                break
            rdb_header_data += chunk
        
        if rdb_header_data.startswith(b"$"):
            # Parse the length
            rdb_length_str = rdb_header_data[1:rdb_header_data.find(b"\r\n")].decode()
            rdb_length = int(rdb_length_str)
            print(f"Expecting RDB file of {rdb_length} bytes")
            
            # Read the RDB file data
            rdb_data = b""
            while len(rdb_data) < rdb_length:
                chunk = master_socket.recv(min(4096, rdb_length - len(rdb_data)))
                if not chunk:
                    break
                rdb_data += chunk
            
            print(f"Received RDB file ({len(rdb_data)} bytes)")
        
        # Now keep the connection open for command propagation
        remaining_data = b""
        while True:
            try:
                # Try to receive data from master
                master_socket.settimeout(1.0)  # Set a timeout to periodically check
                data = master_socket.recv(4096)
                if not data:
                    break

                # Concatenate with any remaining incomplete data
                remaining_data += data

                # Parse and process commands
                commands, remaining_data = parse_multiple_resp_commands(remaining_data)
                for command in commands:
                    process_propagated_command(command, master_socket)

            except socket.timeout:
                # Timeout is expected, just continue to keep connection alive
                continue
            except Exception as e:
                print(f"Error receiving data from master: {e}")
                break
        
        master_socket.close()
        print("Replication stream ended")
        
    except Exception as e:
        print(f"Error connecting to master: {e}")
        sys.exit(1)


def main():
    # Parse command-line arguments and update config
    args = parse_arguments()
    if args.dir is not None:
        config["dir"] = args.dir
    if args.dbfilename is not None:
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
    
    # Start the server to listen for client connections
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind(("localhost", port))
    server_socket.listen(5)
    print(f"Listening on port {port}...")
    
    # If this is a replica, connect to master in a separate thread
    if replication_config["role"] == "slave":
        replication_thread = threading.Thread(target=connect_to_master, args=(port,))
        replication_thread.daemon = True  # Dies when main thread dies
        replication_thread.start()
    
    # Accept client connections
    while True:
        connection, _ = server_socket.accept()
        thread = threading.Thread(target=handle_connection, args=(connection,))
        thread.start()


if __name__ == "__main__":
    main()
