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
