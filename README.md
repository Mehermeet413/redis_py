# Redis Server Implementation in Python

[![progress-banner](https://backend.codecrafters.io/progress/redis/6e2b7c88-c877-4fe5-9d8b-0156f1a1b945)](https://app.codecrafters.io/users/codecrafters-bot?r=2qF)

A fully functional Redis server implementation in Python, built as part of the ["Build Your Own Redis" Challenge](https://codecrafters.io/challenges/redis) by CodeCrafters. This implementation supports core Redis functionality including basic commands, replication, persistence, and the Redis Serialization Protocol (RESP).

## 🚀 Features

### Core Redis Commands
- **PING** - Health check command
- **ECHO** - Echo back messages
- **SET/GET** - Key-value storage with optional expiration
- **CONFIG GET** - Retrieve server configuration
- **KEYS** - List keys matching patterns
- **INFO REPLICATION** - Get replication status
- **WAIT** - Wait for replica acknowledgments

### Advanced Features
- **Master-Replica Replication** - Full replication support with proper handshaking
- **Command Propagation** - Write commands automatically propagated to replicas
- **Replication Offset Tracking** - Precise byte-level offset tracking for consistency
- **RDB File Support** - Basic RDB file loading capability
- **Key Expiration** - TTL support with automatic cleanup
- **RESP Protocol** - Full Redis Serialization Protocol implementation
- **Multi-command Parsing** - Handle multiple commands in a single request
- **Concurrent Connections** - Multi-threaded connection handling

### Replication Features
- **REPLCONF** command handling for replica configuration
- **PSYNC** for replica synchronization with empty RDB transfer
- **REPLCONF GETACK** for replica offset acknowledgment
- **Automatic command propagation** to all connected replicas
- **Replica offset synchronization** for data consistency

## 📁 Project Structure

```
app/
├── main.py              # Main server implementation
├── args_parser.py       # Command-line argument parsing
├── commands.py          # Command handling logic
├── config.py            # Configuration management
├── resp_protocol.py     # RESP protocol implementation
├── test_expiry.py       # Key expiration tests
└── test_replconf_getack.py  # Replication tests
```

## 🛠️ Installation & Setup

### Prerequisites
- Python 3.8+ (recommended: Python 3.13)
- Basic understanding of Redis and networking concepts

### Quick Start

1. **Clone the repository:**
   ```bash
   git clone https://github.com/Mehermeet413/redis_py.git
   cd redis_py
   ```

2. **Run as Master (default):**
   ```bash
   ./your_program.sh
   # or directly:
   python app/main.py --port 6379
   ```

3. **Run as Replica:**
   ```bash
   python app/main.py --port 6380 --replicaof "localhost 6379"
   ```

### Configuration Options

```bash
python app/main.py [OPTIONS]

Options:
  --port PORT              Port to listen on (default: 6379)
  --dir DIR               Directory for RDB files (default: /tmp/redis-files)
  --dbfilename FILENAME   RDB filename (default: dump.rdb)
  --replicaof "HOST PORT" Configure as replica of specified master
```

## 💡 Usage Examples

### Basic Commands
```bash
# Connect with redis-cli or telnet
redis-cli -p 6379

# Basic operations
PING                    # Returns: PONG
SET mykey "Hello"       # Returns: OK
GET mykey              # Returns: "Hello"
SET temp "value" PX 5000  # Set with 5-second expiration
KEYS *                 # List all keys
```

### Replication Setup
```bash
# Terminal 1 - Start master
python app/main.py --port 6379

# Terminal 2 - Start replica
python app/main.py --port 6380 --replicaof "localhost 6379"

# Commands on master are automatically propagated to replica
```

### Configuration
```bash
CONFIG GET dir         # Get RDB directory
CONFIG GET dbfilename  # Get RDB filename
INFO replication       # Get replication status
```

## 🏗️ Architecture

### Core Components

1. **RESP Parser** (`parse_resp`, `parse_multiple_resp_commands`)
   - Handles Redis Serialization Protocol parsing
   - Supports multiple commands in single buffer
   - Returns both parsed commands and raw bytes for offset tracking

2. **Command Handler** (`handle_connection`)
   - Multi-threaded connection handling
   - Command dispatching and response generation
   - Error handling and connection management

3. **Storage Engine**
   - In-memory key-value store with expiration support
   - Automatic cleanup of expired keys
   - Thread-safe operations

4. **Replication System**
   - Master-replica handshake protocol
   - Command propagation with offset tracking
   - REPLCONF GETACK handling for synchronization

### Replication Flow

1. **Replica Handshake:**
   ```
   Replica → Master: PING
   Master → Replica: PONG
   Replica → Master: REPLCONF listening-port <port>
   Master → Replica: OK
   Replica → Master: REPLCONF capa psync2
   Master → Replica: OK
   Replica → Master: PSYNC ? -1
   Master → Replica: FULLRESYNC <replid> <offset>
   Master → Replica: <RDB file>
   ```

2. **Command Propagation:**
   ```
   Client → Master: SET key value
   Master → Client: OK
   Master → Replica: SET key value (propagated)
   ```

3. **Offset Synchronization:**
   ```
   Master → Replica: REPLCONF GETACK *
   Replica → Master: REPLCONF ACK <offset>
   ```

## 🧪 Testing

The project includes comprehensive tests for various features:

```bash
# Run expiration tests
python app/test_expiry.py

# Run replication tests  
python app/test_replconf_getack.py

# Test with CodeCrafters platform
git push origin master
```

## 📝 Implementation Details

### Key Features Implemented

- **Precise Offset Tracking**: Tracks exact bytes processed for replication consistency
- **Multi-command Buffer Handling**: Efficiently processes multiple commands in single network read
- **Threaded Architecture**: Each connection runs in its own thread for concurrency
- **Automatic Propagation**: Write commands automatically sent to all connected replicas
- **Robust Error Handling**: Graceful handling of malformed commands and network issues
- **Memory Management**: Automatic cleanup of expired keys and closed connections

### Protocol Compliance
- Full RESP (Redis Serialization Protocol) support
- Proper error responses for malformed commands
- Bulk string, simple string, and array encoding/decoding
- Null bulk string handling for missing keys

## 🚧 Limitations & Future Enhancements

### Current Limitations
- In-memory storage only (no persistence to disk beyond RDB loading)
- Basic RDB support (loading only, no saving)
- Limited pattern matching in KEYS command
- WAIT command returns hardcoded 0 (basic implementation)

### Potential Enhancements
- [ ] RDB file generation and saving
- [ ] AOF (Append Only File) persistence
- [ ] More Redis commands (DEL, INCR, etc.)
- [ ] Pattern matching in KEYS
- [ ] Pub/Sub functionality
- [ ] Redis Cluster support
- [ ] Memory optimization
- [ ] Advanced data types (Lists, Sets, Hashes)

## 📚 Learning Outcomes

This project demonstrates:
- **Network Programming**: TCP socket handling and multi-threading
- **Protocol Implementation**: RESP protocol parsing and generation
- **Distributed Systems**: Master-replica replication patterns
- **Data Structures**: In-memory storage with expiration
- **Concurrency**: Thread-safe operations and connection management
- **Testing**: Unit testing and integration testing strategies

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues, feature requests, or pull requests.

## 📄 License

This project is part of the CodeCrafters Redis challenge. Feel free to use this code for learning purposes.

## 🙏 Acknowledgments

- [CodeCrafters](https://codecrafters.io) for the excellent Redis challenge
- Redis Labs for the original Redis implementation and documentation
- The Redis community for protocol specifications and best practices

---

**Note**: This is an educational implementation built for learning purposes. For production use, consider using the official Redis server.
