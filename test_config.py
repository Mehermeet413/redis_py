#!/usr/bin/env python3

import socket

def send_redis_command(command):
    """Send a command to Redis and return the response"""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("localhost", 6379))
    client.send(command.encode())
    response = client.recv(1024)
    client.close()
    return response.decode()

def test_config_get():
    print("Testing CONFIG GET commands...")
    
    # Test CONFIG GET dir
    dir_command = "*3\r\n$6\r\nCONFIG\r\n$3\r\nGET\r\n$3\r\ndir\r\n"
    response = send_redis_command(dir_command)
    print(f"CONFIG GET dir: {repr(response)}")
    
    # Test CONFIG GET dbfilename
    dbfilename_command = "*3\r\n$6\r\nCONFIG\r\n$3\r\nGET\r\n$10\r\ndbfilename\r\n"
    response = send_redis_command(dbfilename_command)
    print(f"CONFIG GET dbfilename: {repr(response)}")

if __name__ == "__main__":
    test_config_get()
