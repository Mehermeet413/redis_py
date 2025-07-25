import time
from config import redis_store, replication_config, config
from resp_protocol import encode_bulk_string, encode_null_bulk_string, encode_resp_array


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


def handle_set(command):
    if len(command) == 3:
        # SET key value
        key = command[1]
        value = command[2]
        redis_store[key] = value
        return b"+OK\r\n"
    elif len(command) == 5 and command[3].upper() == "PX":
        # SET key value PX milliseconds
        key = command[1]
        value = command[2]
        expiry_ms = int(command[4])
        expiry_time = time.time() + (expiry_ms / 1000.0)
        redis_store[key] = {"value": value, "expiry": expiry_time}
        return b"+OK\r\n"
    else:
        return b"-ERR wrong number of arguments for 'set' command\r\n"


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
