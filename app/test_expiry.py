#!/usr/bin/env python3

import socket
import time

def send_redis_command(command):
    """Send a command to Redis and return the response"""
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    client.connect(("localhost", 6379))
    client.send(command.encode())
    response = client.recv(1024)
    client.close()
    return response.decode()

def test_set_with_expiry():
    print("Testing SET with PX expiry...")
    
    # Test SET with expiry
    set_command = "*5\r\n$3\r\nSET\r\n$3\r\nfoo\r\n$3\r\nbar\r\n$2\r\nPX\r\n$3\r\n100\r\n"
    response = send_redis_command(set_command)
    print(f"SET foo bar PX 100: {response.strip()}")
    
    # Immediately get the value
    get_command = "*2\r\n$3\r\nGET\r\n$3\r\nfoo\r\n"
    response = send_redis_command(get_command)
    print(f"GET foo (immediate): {response.strip()}")
    
    # Wait for expiry and try again
    print("Waiting 0.2 seconds for key to expire...")
    time.sleep(0.2)
    response = send_redis_command(get_command)
    print(f"GET foo (after expiry): {response.strip()}")

if __name__ == "__main__":
    test_set_with_expiry()
