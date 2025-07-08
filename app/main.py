import socket  # noqa: F401
import threading


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
            else:
                connection.sendall(b"-ERR unknown command\r\n")

    finally:
        connection.close()


def main():
    server_socket = socket.create_server(("localhost", 6379), reuse_port=True)
    print("Listening on port 6379...")
    while True:
        connection, _ = server_socket.accept()
        thread = threading.Thread(target=handle_connection, args=(connection,))
        thread.start()


if __name__ == "__main__":
    main()
