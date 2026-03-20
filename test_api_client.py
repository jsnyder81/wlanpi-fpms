import json
import socket

def test_api():
    """
    A simple Python test client to verify the Headless API (Virtual Bridge).
    This fulfills the 'Testability' requirement of Phase 4.
    """
    host = "127.0.0.1"
    port = 8080
    
    print(f"Attempting to connect to {host}:{port}...")
    try:
        with socket.create_connection((host, port), timeout=5) as client_socket:
            print("Connected to FPMS API Server!")
            
            # Send a button press action
            payload = json.dumps({"action": "DOWN"})
            print(f"Sending payload: {payload}")
            client_socket.sendall(payload.encode('utf-8') + b'\n')

            # Wait for the updated state response
            response = client_socket.recv(4096).decode('utf-8').strip()
            print(f"Received updated state: {response}")
            
            # Verify it's valid JSON
            state = json.loads(response)
            assert isinstance(state, dict), "State should be a JSON dictionary"
            print("Test passed! Received valid JSON state back.")
            
    except Exception as e:
        print(f"Connection or test failed: {e}")

if __name__ == "__main__":
    test_api()