import argparse


def parse_arguments():
    """Parse command line arguments for the Redis server."""
    parser = argparse.ArgumentParser(description="Redis Server")
    parser.add_argument("--dir", type=str, help="Directory for RDB files")
    parser.add_argument("--dbfilename", type=str, help="RDB filename")
    parser.add_argument("--port", type=int, default=6379, help="Port to listen on")
    parser.add_argument("--replicaof", type=str, help="Master host and port (e.g., 'localhost 6379')")
    
    return parser.parse_args()
