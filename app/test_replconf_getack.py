#!/usr/bin/env python3

import socket
import time
import threading
import subprocess
import sys

def test_replconf_getack():
    """
    Test that a replica responds to REPLCONF GETACK commands correctly.
    """
    
    # Start a master server
    print("Starting master server...")
    master_process = subprocess.Popen([
        sys.executable, "main.py", "--port", "6379"
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # Give the master time to start
    time.sleep(1)
    
    try:
        # Start a replica server
        print("Starting replica server...")
        replica_process = subprocess.Popen([
            sys.executable, "main.py", "--port", "6380", "--replicaof", "localhost 6379"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        # Give the replica time to connect and complete handshake
        time.sleep(2)
        
        try:
            # Connect to the master and get the replica connection
            print("Connecting to master to send REPLCONF GETACK...")
            
            # We need to simulate what the master would do
            # Since we can't easily access the replica connection from the master,
            # let's connect directly to the replica and send the handshake + GETACK
            
            replica_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            replica_socket.connect(("localhost", 6380))
            
            # Send PING
            replica_socket.send(b"*1\r\n$4\r\nPING\r\n")
            response = replica_socket.recv(1024)
            print(f"PING response: {response}")
            
            # Send REPLCONF listening-port
            replica_socket.send(b"*3\r\n$8\r\nREPLCONF\r\n$14\r\nlistening-port\r\n$4\r\n6379\r\n")
            response = replica_socket.recv(1024)
            print(f"REPLCONF listening-port response: {response}")
            
            # Send REPLCONF capa
            replica_socket.send(b"*3\r\n$8\r\nREPLCONF\r\n$4\r\ncapa\r\n$6\r\npsync2\r\n")
            response = replica_socket.recv(1024)
            print(f"REPLCONF capa response: {response}")
            
            # Send PSYNC
            replica_socket.send(b"*3\r\n$5\r\nPSYNC\r\n$1\r\n?\r\n$2\r\n-1\r\n")
            response = replica_socket.recv(4096)  # This includes FULLRESYNC + RDB
            print(f"PSYNC response received ({len(response)} bytes)")
            
            # Now send REPLCONF GETACK *
            print("Sending REPLCONF GETACK * command...")
            replica_socket.send(b"*3\r\n$8\r\nREPLCONF\r\n$6\r\nGETACK\r\n$1\r\n*\r\n")
            
            # Receive the ACK response
            response = replica_socket.recv(1024)
            print(f"REPLCONF GETACK response: {response}")
            
            # Expected response: *3\r\n$8\r\nREPLCONF\r\n$3\r\nACK\r\n$1\r\n0\r\n
            expected = b"*3\r\n$8\r\nREPLCONF\r\n$3\r\nACK\r\n$1\r\n0\r\n"
            
            if response == expected:
                print("✓ Test PASSED: Replica responded correctly to REPLCONF GETACK")
                return True
            else:
                print(f"✗ Test FAILED: Expected {expected}, got {response}")
                return False
                
        finally:
            replica_process.terminate()
            replica_process.wait()
            
    finally:
        master_process.terminate()
        master_process.wait()

if __name__ == "__main__":
    success = test_replconf_getack()
    sys.exit(0 if success else 1)
