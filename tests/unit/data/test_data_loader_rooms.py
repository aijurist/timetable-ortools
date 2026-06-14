"""Room classification tests for scheduler data loading."""

from __future__ import annotations

import pandas as pd

from src.data.data_loader import DataLoader


def test_unmapped_lab_fallback_rooms_are_computer_labs_only() -> None:
	loader = object.__new__(DataLoader)
	rooms_df = pd.DataFrame(
		[
			{"id": "CORE1", "room_type": "Core-Lab", "is_lab": 1},
			{"id": "COMP1", "room_type": "Computer-Lab", "is_lab": 1},
			{"id": "COMP2", "room_type": "Computer Lab", "is_lab": 1},
			{"id": "CLS1", "room_type": "Class-Room", "is_lab": 0},
		]
	)

	rooms = loader._build_room_collections(rooms_df)

	assert rooms.lab_room_ids == ("CORE1", "COMP1", "COMP2")
	assert rooms.theory_room_ids == ("CLS1",)
	assert rooms.laboratory_room_ids == ("COMP1", "COMP2")
