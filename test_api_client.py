import json
import socket
import time

def test_api():
    """
    A simple Python test client to verify the Headless API (Virtual Bridge).
    This fulfills the 'Testability' requirement of Phase 4.
    """
    host = "127.0.0.1"
    port = 8080
    
    print(f"Attempting to connect to {host}:{port}...")
    try:
        with socket.create_connection((host, port), timeout=10) as client_socket:
            print("Connected to FPMS API Server!")
            
            # Step 1: Send a CENTER button press to enter the Main Menu from the Home Page
            print("Sending 'CENTER' payload to enter Main Menu...")
            client_socket.sendall(json.dumps({"action": "CENTER"}).encode('utf-8') + b'\n')

            # Wait for the menu state response
            response = client_socket.recv(4096).decode('utf-8').strip()
            print(f"Received menu state: {response.split(chr(10))[0]}")
            
            time.sleep(0.5)

            # Step 2: Send a DOWN button press to test menu navigation
            print("\nSending 'DOWN' payload to navigate menu...")
            client_socket.sendall(json.dumps({"action": "DOWN"}).encode('utf-8') + b'\n')

            # Wait for the updated state response
            response = client_socket.recv(4096).decode('utf-8').strip()
            if '\n' in response:
                response = response.split('\n')[-1] # Grab the latest state update if multiple queued
            print(f"Received updated menu state: {response}")
            
            # Verify it's valid JSON
            state = json.loads(response)
            assert isinstance(state, dict), "State should be a JSON dictionary"
            print("Test passed! Received valid JSON state back.")
            
    except Exception as e:
        print(f"Connection or test failed: {e}")

if __name__ == "__main__":
    test_api()