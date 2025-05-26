import pprint

def create_simplified_timetable_structure(raw_data_str):
    """
    Parses the raw timetable string into a simplified Python dictionary structure,
    storing the raw content of each slot.
    """
    timetable = {
        "time_slot_definitions": {},
        "daily_schedules": {}
    }
    lines = raw_data_str.strip().split('\n')

    # Parse T and L time slot definitions (first two lines)
    time_slot_definition_lines = lines[:2]
    day_schedule_lines = lines[2:]

    for line in time_slot_definition_lines:
        try:
            parts = line.split(',', 1)
            slot_type_key = parts[0].strip()
            slots_str_list = [s.strip() for s in parts[1].split(',')]
            timetable["time_slot_definitions"][slot_type_key] = slots_str_list
        except IndexError:
            print(f"Warning: Could not parse time slot definition line: {line}")
            continue

    # Use 'L' time slots for daily schedule timing, as daily schedules have 12 entries.
    daily_slot_times = timetable["time_slot_definitions"].get("L", [])

    # Parse day schedules
    for line in day_schedule_lines:
        try:
            day_part, items_part = line.split(',', 1)
        except ValueError:
            print(f"Warning: Could not split day from schedule items: {line}")
            continue
            
        day_name = day_part.strip().lower()
        
        # Items are separated by commas, then need stripping
        raw_schedule_items_text = [item.strip() for item in items_part.split(',')]
        
        current_day_schedule_entries = []
        for i, item_text_content in enumerate(raw_schedule_items_text):
            slot_entry = {
                "slot_index": i,
                "content": item_text_content  # Store the raw string content
            }
            
            if i < len(daily_slot_times):
                slot_entry["time_interval"] = daily_slot_times[i]
            else:
                # Fallback if 'L' time slots are not available or fewer than actual items
                slot_entry["time_interval"] = f"Time Slot {i+1}" 

            current_day_schedule_entries.append(slot_entry)
        timetable["daily_schedules"][day_name] = current_day_schedule_entries
        
    return timetable

# --- Input Data ---
raw_data = """
T,       8:00 - 8:50,9:00 - 9:50,10:00 - 10:50,11:00 - 11:50,12:00 - 12:50,1:00  - 1:50,2:00 - 2:50,3:00 - 3:50,4:00 - 4:50,5:00 - 5:50,6:00 - 6:50
L,       8:00 - 8:50,8:50 - 9:40, 9:50 - 10:40,10:40 - 11:30,11:50 - 12:40,12:40 - 1:30,1:50 - 2:40,2:40 - 3:30,3:50 - 4:40,4:40 - 5:30,5:30 - 6:20, 6:20 - 7:10
tuesday, a1/L1,       f1/L2,       d1/L3,       b1/a2/L4,       g1/f2/L5,       d2/L6,       b2/a3/L7,   g2/f3/L8,   d3/L9,       b3/L10,       g3/L11,       L12
wed,     b1/L12,       g1/L14,       e1/L15,       c1/b2/L24,     ta1/g2/L17,     e1/L18,       c2/b3/L19,  ta2/g3/L20, e3/L21,       c3/L22,       ta3/L23,       L24
thur,    c1/L25,       a1/L26,       f1/L27,       d1/c2/L28,     tb1/a2/L29,     f2/L30,       d2/c3/L31,  tb2/a3/L32, f3/L33,       d3/L34,       tb3/L35,       L36
fri,     d1/L37,       b1/L38,       g1/L39,       e1/d2/L40,     tc1/b2/L41,     g2/L42,       e2/d3/L43,  tc2/b4/L44, g3/L45,       e3/L46,       tc3/L47,       L46
sat,     e1/L49,       c1/L50,       a1/L51,       f1/e2/L52,     td1/c2/L53,     a2/L54,       f2/e3/L55,  td2/c3/L56, a3/L57,       f3/L58,       td3/L59,       L60
"""

# Parse the data into the simplified structure
simplified_timetable_data = create_simplified_timetable_structure(raw_data)

# Print the resulting dictionary (optional, for verification)
pp = pprint.PrettyPrinter(indent=2)
pp.pprint(simplified_timetable_data)

# Example of how to access parts of the data:
# print("\nL Time Slots:", simplified_timetable_data['time_slot_definitions']['L'])
# print("\nTuesday's Schedule:", simplified_timetable_data['daily_schedules']['tuesday'])
# if 'tuesday' in simplified_timetable_data['daily_schedules'] and simplified_timetable_data['daily_schedules']['tuesday']:
#     print("\nFirst slot on Tuesday:", simplified_timetable_data['daily_schedules']['tuesday'][0])
#     print("Content of first slot on Tuesday:", simplified_timetable_data['daily_schedules']['tuesday'][0]['content'])