import math
import pandas as pd

core_df = pd.read_csv('data/og-final.csv')
rooms_df = pd.read_csv('data/block_wise/techlongue.csv')

def norm(val):
    if val is None:
        return ''
    try:
        if math.isnan(val):  # type: ignore[arg-type]
            return ''
    except TypeError:
        pass
    return ''.join(ch for ch in str(val).lower() if ch.isalnum())

lookup = {}
for _, row in rooms_df.iterrows():
    room_id = str(row.get('id'))
    if not room_id:
        continue
    names = [row.get('room_number'), row.get('room_name'), row.get('description')]
    block = row.get('block')
    if row.get('room_number') and block:
        names.append(f"{row.get('room_number')}_{block}")
        names.append(f"{row.get('room_number')} {block}")
    for name in names:
        key = norm(name)
        if key:
            lookup[key] = room_id
    lookup[norm(room_id)] = room_id

row = core_df[core_df['course_code'] == 'BT23523'].iloc[0]
resolved = set()
for column, value in row.items():
    column_lower = str(column).lower()
    if not column_lower.startswith('lab_'):
        continue
    if value is None:
        continue
    if column_lower.endswith('_block'):
        continue
    block = None
    if column_lower.endswith('_room'):
        num_token = column_lower.split('_')[1]
        block = row.get(f'lab_{num_token}_block')
    name = str(value)
    candidates = [norm(name)]
    if block:
        candidates.append(norm(f'{name}_{block}'))
        candidates.append(norm(f'{name} {block}'))
    room_id = None
    for key in candidates:
        if key and key in lookup:
            room_id = lookup[key]
            break
    if room_id:
        resolved.add(room_id)

print('Resolved for BT23523:', resolved)
