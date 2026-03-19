import socket
import threading
import json
import select

class FpmsApiServer:
    def __init__(self, event_queue, host='127.0.0.1', port=8080):
        self.host = host
        self.port = port
        self.event_queue = event_queue
        self.clients = []
        self.running = False
        self.server_socket = None

    def start(self):
        self.running = True
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(5)
        
        self.accept_thread = threading.Thread(target=self._accept_clients, daemon=True)
        self.accept_thread.start()

    def stop(self):
        self.running = False
        if self.server_socket:
            self.server_socket.close()

    def _accept_clients(self):
        while self.running:
            try:
                # Using select to allow clean shutdown
                ready_to_read, _, _ = select.select([self.server_socket], [], [], 1.0)
                if ready_to_read:
                    client_socket, _ = self.server_socket.accept()
                    self.clients.append(client_socket)
                    client_thread = threading.Thread(target=self._handle_client, args=(client_socket,), daemon=True)
                    client_thread.start()
            except Exception:
                pass

    def _handle_client(self, client_socket):
        while self.running:
            try:
                ready_to_read, _, _ = select.select([client_socket], [], [], 1.0)
                if ready_to_read:
                    data = client_socket.recv(1024)
                    if not data:
                        break
                    
                    payload = json.loads(data.decode('utf-8').strip())
                    action = payload.get("action")
                    if action:
                        self.event_queue.put(action.upper())
            except Exception:
                break
        
        if client_socket in self.clients:
            self.clients.remove(client_socket)
        client_socket.close()

    def broadcast_state(self, state_dict):
        if not self.clients:
            return
            
        try:
            # Send state as JSON line
            message = json.dumps(state_dict) + "\n"
            encoded_message = message.encode('utf-8')
            
            for client in list(self.clients):
                try:
                    client.sendall(encoded_message)
                except Exception:
                    self.clients.remove(client)
        except Exception:
            pass