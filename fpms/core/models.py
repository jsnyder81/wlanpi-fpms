from dataclasses import dataclass, field
from typing import List, Dict, Any, Union
from enum import Enum

class ViewType(str, Enum):
    HOME = "home"
    MENU = "menu"
    ACTION = "action"
    PAGE = "page"  # Reserved for when we implement SimpleTable/PagedTable

@dataclass
class MenuItemState:
    name: str
    has_children: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "has_children": self.has_children
        }

@dataclass
class ViewState:
    type: ViewType

@dataclass
class HomeState(ViewState):
    type: ViewType = ViewType.HOME
    title: str = "Home"

    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type.value, "title": self.title}

@dataclass
class MenuState(ViewState):
    type: ViewType = ViewType.MENU
    title: str = ""
    items: List[MenuItemState] = field(default_factory=list)
    selected_index: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "title": self.title,
            "items": [item.to_dict() for item in self.items],
            "selected_index": self.selected_index
        }

@dataclass
class ActionState(ViewState):
    type: ViewType = ViewType.ACTION
    action_name: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {"type": self.type.value, "action_name": self.action_name}