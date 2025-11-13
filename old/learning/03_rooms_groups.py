"""03 — Rooms and department-preferred rooms

Shows how to represent rooms with pandas and pick preferred rooms for a
department (simple heuristic similar to `CombinedScheduler._get_preferred_rooms_for_department`).
"""
import pandas as pd


def sample_rooms_df():
    return pd.DataFrame([
        {'id': 'A101', 'is_lab': 0, 'room_type': 'Theory', 'block': 'A Block', 'floor': 1},
        {'id': 'A102', 'is_lab': 1, 'room_type': 'Laboratory', 'block': 'A Block', 'floor': 1},
        {'id': 'B201', 'is_lab': 0, 'room_type': 'Theory', 'block': 'B Block', 'floor': 2},
    ])


def get_preferred_rooms(df, department):
    # simple priority: A Block first, non-TIFAC
    pref_block = 'A Block' if 'Computer' in department else 'B Block'
    candidates = df[df['block'] == pref_block]
    return candidates['id'].tolist()


def main():
    print('03_rooms_groups: demo')
    df = sample_rooms_df()
    print(df)
    print('Preferred for Computer Science:', get_preferred_rooms(df, 'Computer Science & Engineering'))

if __name__ == '__main__':
    main()
