import socket  # noqa: F401
import threading


def handle_connection(connection):
    while True:
        data: bytes = connection.recv(1024)
        if data == b"":
            break
        connection.sendall(b"+PONG\r\n")
    connection.close()


def main():
    # Uncomment this to pass the first stage
    #
    server_socket = socket.create_server(("localhost", 6379), reuse_port=True)
    while True:
        connection, _ = server_socket.accept()  # wait for client
        thread = threading.Thread(target=handle_connection, args=(connection,))
        thread.start()

if __name__ == "__main__":
    main()
