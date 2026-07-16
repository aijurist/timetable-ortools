from src.constraints.cross_system.dept_slot_blocking import DeptSlotBlockingSettings


def test_blocking_rows_are_not_locked_by_default():
    settings = DeptSlotBlockingSettings.from_params(
        {"block_dept_slots_course_codes": ["CD23321"]}
    )

    assert settings.lock_blocking_assignments is False


def test_owned_blocking_rows_can_also_be_locked():
    settings = DeptSlotBlockingSettings.from_params(
        {
            "block_dept_slots_course_codes": ["CD23321"],
            "lock_blocking_assignments": True,
        }
    )

    assert settings.lock_blocking_assignments is True
