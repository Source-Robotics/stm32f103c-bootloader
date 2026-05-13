"""
boards.py — host board registry.

Extend this list as new hardware variants are added.
"""

from dataclasses import dataclass


@dataclass
class BootloaderBoard:
    board_id: int
    name: str
    description: str = ""


# Known host boards.
# board_id=0 is reserved for freshly-programmed bootloaders.
BOARD_REGISTRY = [
    BootloaderBoard(board_id=0,  name="Unassigned board (default ID 0)",
                  description="Default ID after bootloader flash"),
    BootloaderBoard(board_id=1,  name="host #1"),
    BootloaderBoard(board_id=2,  name="host #2"),
    BootloaderBoard(board_id=3,  name="host #3"),
]


def lookup(board_id: int) -> BootloaderBoard | None:
    for b in BOARD_REGISTRY:
        if b.board_id == board_id:
            return b
    return None
