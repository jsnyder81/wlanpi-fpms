# Headless Core Refactoring Plan

Here is a phased implementation plan to retool the `wlanpi-fpms` project into a headless, state-driven architecture. 

By breaking this down into phases, you can ensure the physical OLED screen continues to work while you slowly replace the underlying plumbing, making the system highly testable at every step.

### Phase 1: Establish the State Machine (The "Core")
Before touching the existing code, build a pure-Python state manager. This core will not know about OLED screens, Pillow images, or GPIO buttons. It will only handle logical data.

*   **Step 1: Define the Data Models:** Create Python `dataclasses` or `TypedDicts` representing the UI states (e.g., `MenuState`, `TableState`, `AlertState`).
*   **Step 2: Build the Core Engine:** Create an `FpmsEngine` class that holds the current state and the menu tree structure.
*   **Step 3: Implement Pure Input Functions:** Add methods to `FpmsEngine` like `handle_up()`, `handle_down()`, `handle_center()`. These functions will calculate the next logical state (e.g., incrementing a selected index or moving to a child menu).
*   **Step 4: State Exporter:** Add a `get_json_state()` method that serializes the current view into a JSON-friendly dictionary.
*   **Testability:** Because this phase has no hardware dependencies, you can easily write `pytest` unit tests. You can instantiate `FpmsEngine`, call `handle_down()` three times, and assert `get_json_state()['selected_index'] == 3`.

### Phase 2: Refactor Renderers to Consume State (The "View")
Currently, classes like `Page` and `PagedTable` handle both the logic (figuring out what to display) and the rendering (drawing the pixels). We need to strip the logic out of them.

*   **Step 1: Create a State Renderer Interface:** Update `Page.draw_page()` to accept the JSON dictionary generated in Phase 1 instead of crawling `g_vars['current_menu_location']`. 
*   **Step 2: Dumb Down the Renderers:** The renderers should now simply loop over the provided state dictionary. If the JSON says `{"title": "Network", "items": ["Eth0", "WLAN0"], "selected": 0}`, the renderer just blindly paints that to the Pillow image buffer.
*   **Step 3: Wire Engine to Renderers:** In your main loop, when a button is pressed, call `engine.handle_down()`, get the new state, and pass it to the renderer. 
*   **Testability:** You can pass static JSON dictionaries into the renderers to visually test edge cases (like extremely long strings or pagination boundaries) without needing to navigate the actual menu.

### Phase 3: Decouple the Hardware Inputs (The "Controller")
Currently, the button interrupts (via `gpiod`) directly execute Python closures tied to `g_vars`. We want to introduce an event queue.

*   **Step 1: Create an Input Queue:** Implement a standard `queue.Queue` (or `asyncio.Queue` if you are moving to async).
*   **Step 2: Refactor Button Handlers:** Update the GPIO interrupt callbacks so all they do is push a string onto the queue (e.g., `queue.put("BTN_DOWN")`).
*   **Step 3: The Main Event Loop:** Create a main loop that consumes items from the queue, passes them to the `FpmsEngine` (Phase 1), gets the resulting state, and sends it to the Renderers (Phase 2).
*   **Testability:** You can push mock strings into the queue and verify that the system processes them correctly, completely independent of the actual hardware buttons.

### Phase 4: Build the Headless API (The "Virtual Bridge")
With the core separated from the hardware, you can now expose the system to the outside world.

*   **Step 1: Run a Background Server:** Spin up a lightweight server (a simple WebSocket server or TCP socket) running in a background thread or async task alongside the main event loop.
*   **Step 2: Broadcast State Changes:** Whenever the `FpmsEngine` generates a new state dictionary, have the server broadcast that JSON to any connected clients (your WebUI).
*   **Step 3: Inject Remote Inputs:** When the server receives a message from a connected client (e.g., `{"action": "BTN_DOWN"}`), push it onto the Input Queue created in Phase 3.
*   **Testability:** You can write a small Python test client that connects to the socket, sends a "BTN_DOWN" payload, and asserts it receives an updated JSON state back.

### Phase 5: Refactor Business Logic & Blocking Tasks
The hardest part of this transition will be the scripts in `cloud_tests.py` and other utilities, which currently block the execution thread while running `subprocess` commands and repeatedly call `display_simple_table()`.

*   **Step 1: Decouple Execution from UI:** Modify these scripts so they run in a separate worker thread or process.
*   **Step 2: Emit Progress Events:** Instead of calling `display_simple_table` directly, have these workers yield or push status updates to the Input Queue (e.g., `{"type": "task_update", "status": "Eth0 Port Up: YES"}`).
*   **Step 3: Update Engine State:** The `FpmsEngine` will catch these updates and transition its internal state to an `ExecutingTaskState`, which the renderers will then paint to the screen or broadcast over WebSockets.
*   **Testability:** You can unit test the parsers in the test scripts by mocking the `subprocess` outputs and verifying the correct task update events are emitted.