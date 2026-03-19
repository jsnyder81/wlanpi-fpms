from typing import List, Dict, Any
from .models import ViewType, HomeState, MenuState, MenuItemState, ActionState

class FpmsEngine:
    def __init__(self, menu_structure: List[Dict[str, Any]], home_title: str = "Home"):
        self.menu_structure = menu_structure
        self.home_title = home_title
        
        # State tracking
        self.is_home: bool = True
        self.location: List[int] = [0]
        self.pending_action: str = ""

    def _get_current_menu_level(self) -> List[Dict[str, Any]]:
        """Crawls the menu tree to the current depth based on self.location"""
        current_level = self.menu_structure
        for index in self.location[:-1]:
            action = current_level[index].get("action")
            if isinstance(action, list):
                current_level = action
        return current_level

    def get_state(self) -> Dict[str, Any]:
        """Exports the current logical state as a JSON-friendly dictionary."""
        if self.pending_action:
            return ActionState(action_name=self.pending_action).to_dict()
            
        if self.is_home:
            return HomeState(title=self.home_title).to_dict()

        current_level = self.menu_structure
        title = self.home_title
        
        # Traverse tree to find current title and items
        for i, index in enumerate(self.location):
            if i < len(self.location) - 1:
                title = current_level[index]["name"]
                current_level = current_level[index]["action"]
                
        selected_index = self.location[-1]
        
        # Build the menu items list
        items = []
        for item in current_level:
            has_children = isinstance(item.get("action"), list)
            items.append(MenuItemState(name=item["name"], has_children=has_children))
            
        return MenuState(title=title, items=items, selected_index=selected_index).to_dict()

    def handle_down(self):
        if self.pending_action: return
        
        if self.is_home:
            self.is_home = False
            self.location = [0]
            return
            
        current_level = self._get_current_menu_level()
        self.location[-1] = (self.location[-1] + 1) % len(current_level)

    def handle_up(self):
        if self.pending_action: return
        
        if self.is_home:
            self.is_home = False
            self.location = [0]
            return

        current_level = self._get_current_menu_level()
        self.location[-1] = (self.location[-1] - 1) % len(current_level)

    def handle_left(self):
        if self.pending_action:
            # Back out of an action view to the menu
            self.pending_action = ""
            return
            
        if self.is_home:
            return
            
        if len(self.location) > 1:
            self.location.pop()
        else:
            # Reached root, go back to home screen
            self.is_home = True
            self.location = [0]

    def handle_right(self):
        self.handle_center()

    def handle_center(self):
        if self.pending_action or self.is_home:
            # Center behaves differently depending on context. If home, go to menu.
            if self.is_home:
                self.is_home = False
            return
            
        current_level = self._get_current_menu_level()
        selected_item = current_level[self.location[-1]]
        
        if isinstance(selected_item.get("action"), list):
            self.location.append(0)
        else:
            self.pending_action = selected_item["name"]

    def _get_path_for_names(self, names: List[str]) -> List[int]:
        """Finds the integer location list for a given list of menu item names."""
        current_level = self.menu_structure
        location = []
        for name in names:
            found = False
            for i, item in enumerate(current_level):
                if item["name"] == name:
                    location.append(i)
                    action = item.get("action")
                    if isinstance(action, list):
                        current_level = action
                    found = True
                    break
            if not found:
                return []
        return location

    def handle_key1(self):
        shortcuts = [
            ["Utils", "Reachability"],
            ["Network", "LLDP Neighbour"],
            ["Network", "Eth0 IP Config"]
        ]
        
        current_index = -1
        for i, shortcut in enumerate(shortcuts):
            if self.location == self._get_path_for_names(shortcut):
                current_index = i
                break
                
        next_index = (current_index + 1) % len(shortcuts)
        next_path = self._get_path_for_names(shortcuts[next_index])
        
        if next_path:
            self.is_home = False
            self.pending_action = ""
            self.location = next_path

    def handle_key2(self):
        path1 = self._get_path_for_names(["Mode", "Classic Mode"])
        path2 = self._get_path_for_names(["Modes", "Hotspot"])
        
        target_path = path1 if path1 else path2
        if target_path:
            self.is_home = False
            self.pending_action = ""
            self.location = target_path

    def handle_key3(self):
        reboot_path = self._get_path_for_names(["System", "Reboot"])
        shutdown_path = self._get_path_for_names(["System", "Shutdown"])
        
        target_path = reboot_path
        if self.location == reboot_path:
            target_path = shutdown_path
            
        if target_path:
            self.is_home = False
            self.pending_action = ""
            self.location = target_path
