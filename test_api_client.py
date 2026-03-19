import asyncio
import json
import websockets

async def test_api():
    """
    A simple Python test client to verify the Headless API (Virtual Bridge).
    This fulfills the 'Testability' requirement of Phase 4.
    """
    uri = "ws://127.0.0.1:8080"
    
    print(f"Attempting to connect to {uri}...")
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to FPMS API Server!")
            
            # Depending on how the server is implemented, it might send the current state on connect
            # initial_state = await websocket.recv()
            # print(f"Initial State: {initial_state}")

            # Send a button press action
            payload = json.dumps({"action": "DOWN"})
            print(f"Sending payload: {payload}")
            await websocket.send(payload)

            # Wait for the updated state response
            response = await websocket.recv()
            print(f"Received updated state: {response}")
            
            # Verify it's valid JSON
            state = json.loads(response)
            assert isinstance(state, dict), "State should be a JSON dictionary"
            print("Test passed! Received valid JSON state back.")
            
    except Exception as e:
        print(f"Connection or test failed: {e}")

if __name__ == "__main__":
    asyncio.run(test_api())