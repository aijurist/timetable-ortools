"""Extract scheduling artifacts from an Exovance dump + its jan9-converted db.

Produces (in --outdir, default cwd):
  rooms_new.csv             - all rooms, jan9-style columns
  pop.csv                   - POP/special staff availability (constrained + unconstrained POPs)
  core_lab_mapping.csv      - course -> core lab descriptions (exovance, old-jan9 backfill, manual)
  computer_lab_mapping.csv  - course -> computer lab room/block preference
  consecutive_labs.csv      - offered courses with P>=4 (need 2+ lab blocks/week)
  day_order_report.txt      - per-dept observed working-day pattern from the published scenario

Usage:
  python extract_timetable_artifacts.py --source exovance_xxx.sqlite --converted exovance_converted_jan9_xxx.sqlite [--jan9 jan9.sqlite] [--outdir .]

Run convert_exovance_to_jan9.py first to produce the converted db (it builds
_conversion_id_map, which this script needs to resolve room UUIDs).
"""
import argparse
import collections
import csv
import json
import os
import sqlite3

# Exovance availability_blacklist codes MON-A..SAT-F = the 6 daily session
# blocks (same spans as Lab-1..6 in timetableMaster_session), NOT theory T-slots.
SESS = {'A': ('08:00', '09:40'), 'B': ('10:00', '11:40'), 'C': ('11:50', '13:20'),
        'D': ('13:20', '15:00'), 'E': ('15:00', '16:40'), 'F': ('17:00', '18:40')}
LETTERS = 'ABCDEF'
DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT']
ABBR = {'MON': 'Mon', 'TUE': 'Tue', 'WED': 'Wed', 'THU': 'Thu', 'FRI': 'Fri', 'SAT': 'Sat'}

# Mappings confirmed by the user but absent from every database.
MANUAL_CORE_LAB_OVERRIDES = {
    'EE23B21': ['TANCAM'],
}


def jload(raw, default):
    if raw is None:
        return default
    raw = str(raw).strip()
    if raw in ('', '[]', '{}', 'null', '0', '1'):  # *_soft columns are boolean flags
        return default
    try:
        v = json.loads(raw)
    except (ValueError, TypeError):
        return default
    return v if isinstance(v, type(default)) else default


def write_csv(path, header, rows):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)
    print(f'{os.path.basename(path)}: {len(rows)} rows')


def load_rooms(dst):
    rooms_by_id, rooms_by_num = {}, {}
    for rid, rn, bl, ds, rt in dst.execute(
            "SELECT id, room_number, block, description, room_type FROM rooms_room"):
        info = dict(room_number=rn, block=bl, description=ds or rn, room_type=rt)
        rooms_by_id[rid] = info
        rooms_by_num[rn] = info
    roommap = {uuid: int(old_id) for ent, uuid, old_id, ok, note in
               dst.execute("SELECT * FROM _conversion_id_map WHERE entity='room'")}
    return rooms_by_id, rooms_by_num, roommap


def extract_rooms(dst, outdir):
    cols = ['id', 'room_number', 'block', 'description', 'is_lab', 'room_type',
            'room_min_cap', 'room_max_cap', 'has_projector', 'has_ac', 'tech_level',
            'maintained_by_id_id', 'green_board', 'isLcsAvailable', 'smart_board']
    rows = dst.execute('SELECT %s FROM rooms_room ORDER BY id' %
                       ','.join('"%s"' % c for c in cols)).fetchall()
    write_csv(os.path.join(outdir, 'rooms_new.csv'), cols, rows)


def extract_pop(src, dst, outdir):
    selected = {}
    for uid, name, desig, emp, bl, pref in src.execute(
            """SELECT user_id, name, designation, employment_type,
               availability_blacklist, preferences FROM faculty"""):
        p = {k: v for k, v in jload(pref, {}).items() if v not in (None, [], '')}
        blk = jload(bl, [])
        is_pop = (desig == 'PROFESSOR_OF_PRACTICE') or (emp == 'ADJUNCT')
        if is_pop or p or blk:
            selected[uid] = dict(name=name.strip(), prefs=p, blacklist=blk)

    rows = []
    for uid, info in sorted(selected.items(), key=lambda kv: kv[1]['name']):
        r = dst.execute("SELECT id FROM teacher_teacher WHERE teacher_id_id=?", (uid,)).fetchone()
        if r is None:
            print(f'  !! pop.csv: {info["name"]} not in converted db, skipped')
            continue
        tid = r[0]
        blk, pref_days = info['blacklist'], info['prefs'].get('preferred_days')
        avail_days, windows = [], []
        if pref_days or blk:
            for d in DAYS:
                if pref_days and d not in pref_days:
                    continue
                avail = [L for L in LETTERS if f'{d}-{L}' not in blk]
                if not avail:
                    continue
                avail_days.append(ABBR[d])
                if len(avail) == 6:
                    windows.append(f'{ABBR[d]} 08:00-18:40')
                else:
                    run = [avail[0]]
                    for L in avail[1:]:
                        if LETTERS.index(L) == LETTERS.index(run[-1]) + 1:
                            run.append(L)
                        else:
                            windows.append(f'{ABBR[d]} {SESS[run[0]][0]}-{SESS[run[-1]][1]}')
                            run = [L]
                    windows.append(f'{ABBR[d]} {SESS[run[0]][0]}-{SESS[run[-1]][1]}')
        d3 = (avail_days + [''] * 3)[:3]
        rows.append([tid, d3[0], d3[1], d3[2], ', '.join(windows), ''])
    write_csv(os.path.join(outdir, 'pop.csv'),
              ['Teacher ID', 'Preferred Day 1', 'Preferred Day 2', 'Preferred Day 3',
               'day_time_windows', 'alternative_lab_days'], rows)


def offered_courses(dst):
    return {code.strip(): name.strip() for code, name in dst.execute(
        """SELECT DISTINCT cm.course_id, cm.course_name FROM course_course cc
           JOIN courseMaster_coursemaster cm ON cm.id = cc.course_id_id""")}


def extract_lab_mappings(src, dst, old, outdir):
    rooms_by_id, rooms_by_num, roommap = load_rooms(dst)
    depts = {did: name.replace('Department of ', '')
             for did, name in src.execute("SELECT id, name FROM departments")}
    dept_codes = {did: code.lower() for did, code in src.execute("SELECT id, code FROM departments")}
    course_dept = {code.strip(): did for code, did in
                   src.execute("SELECT code, department_id FROM courses")}
    offered = offered_courses(dst)

    core, comp = {}, {}

    def add_core(code, name, dept, descs, source):
        e = core.setdefault(code, dict(name=name, dept=dept, labs=[], source=source))
        for d in descs:
            if d not in e['labs']:
                e['labs'].append(d)

    def resolve(uuids):
        return [rooms_by_id[roommap[u]] for u in uuids
                if isinstance(u, str) and roommap.get(u) in rooms_by_id]

    def handle(code, name, did, room_infos):
        code, name = code.strip(), name.strip()
        core_rs = [r for r in room_infos if r['room_type'] == 'Core-Lab']
        comp_rs = [r for r in room_infos if r['room_type'] == 'Computer-Lab']
        if core_rs:
            add_core(code, name, depts.get(did, ''), [r['description'] for r in core_rs], 'exovance')
        if comp_rs and code not in comp:
            blocks = []
            for r in comp_rs:
                if r['block'] not in blocks:
                    blocks.append(r['block'])
            if len(comp_rs) == 1:
                room_pref, block_pref = comp_rs[0]['room_number'], comp_rs[0]['block']
            elif len(comp_rs) <= 3:
                room_pref = ';'.join(r['room_number'] for r in comp_rs)
                block_pref = ';'.join(blocks)
            else:
                room_pref, block_pref = '', ';'.join(blocks)
            comp[code] = [dept_codes.get(did, ''), code, room_pref, block_pref]

    for code, name, did, ids in src.execute(
            "SELECT code, name, department_id, lab_preferred_room_ids FROM courses"):
        uuids = jload(ids, [])
        if uuids:
            handle(code, name, did, resolve(uuids))
    for code, name, did, ov in src.execute(
            """SELECT DISTINCT c.code, c.name, c.department_id, ta.override_lab_room_ids
               FROM teaching_assignments ta JOIN courses c ON c.id = ta.course_id
               WHERE TRIM(COALESCE(c.lab_preferred_room_ids,'')) IN ('','[]','null')"""):
        uuids = jload(ov, [])
        if uuids:
            handle(code, name, did, resolve(uuids))

    # backfill core labs from the old jan9 db for offered-but-unmapped courses
    if old is not None:
        q = """SELECT cm.course_id, r.room_number FROM courseMaster_coursemasterroompreference p
               JOIN courseMaster_coursemaster cm ON cm.id = p.course_master_id_id
               JOIN rooms_room r ON r.id = p.room_id_id"""
        for code, rn in old.execute(q):
            code = code.strip()
            if code not in offered or code in core:
                continue
            cur_room = rooms_by_num.get(rn)
            if cur_room and cur_room['room_type'] == 'Core-Lab':
                did = course_dept.get(code)
                add_core(code, offered[code], depts.get(did, ''),
                         [cur_room['description']], 'jan9-backfill')

    for code, room_nums in MANUAL_CORE_LAB_OVERRIDES.items():
        descs = [rooms_by_num[rn]['description'] for rn in room_nums if rn in rooms_by_num]
        if descs and code not in core:
            did = course_dept.get(code)
            add_core(code, offered.get(code, ''), depts.get(did, ''), descs, 'manual')

    core_rows = []
    for code in sorted(core):
        e = core[code]
        labs = (e['labs'][:5] + [''] * 5)[:5]
        core_rows.append([code, e['dept'], len(e['labs'][:5]), *labs, e['name']])
    write_csv(os.path.join(outdir, 'core_lab_mapping.csv'),
              ['course_code', 'department', 'total_labs', 'lab_1', 'lab_2', 'lab_3',
               'lab_4', 'lab_5', 'course_name'], core_rows)
    write_csv(os.path.join(outdir, 'computer_lab_mapping.csv'),
              ['department', 'course_code', 'preferred_lab_room', 'preferred_lab_block'],
              [comp[c] for c in sorted(comp)])

    missing = sorted(c for c, n in offered.items()
                     if c not in core and c not in comp and dst.execute(
                         """SELECT 1 FROM courseMaster_coursemaster
                            WHERE TRIM(course_id)=? AND practical_hours > 0""", (c,)).fetchone())
    print(f'  offered lab courses with NO mapping in any source: {len(missing)}')


def extract_consecutive_labs(src, dst, outdir):
    offered = offered_courses(dst)
    rows = []
    for code, name, st in src.execute("SELECT code, name, structure FROM courses"):
        code = code.strip()
        if code not in offered:
            continue
        j = jload(st, {})
        P = j.get('P', 0) or 0
        if P >= 4:
            rows.append([code, name.strip(), j.get('L', 0) or 0, j.get('T', 0) or 0, P, P // 2])
    rows.sort()
    write_csv(os.path.join(outdir, 'consecutive_labs.csv'),
              ['course_code', 'course_name', 'L', 'T', 'P', 'lab_blocks_per_week'], rows)


def day_order_report(src, outdir):
    usage = collections.defaultdict(collections.Counter)
    for dept, slot in src.execute(
            """SELECT d.code, ss.slot_code FROM scheduled_sessions ss
               JOIN courses c ON c.id = ss.course_id
               JOIN departments d ON d.id = c.department_id"""):
        usage[dept][slot.split('_')[0].split('-')[0]] += 1
    declared = dict(src.execute("SELECT code, working_days FROM departments"))
    lines = [f'{"dept":7} ' + ' '.join(f'{d:>4}' for d in DAYS) + '  observed | declared working_days']
    for dept in sorted(usage):
        c = usage[dept]
        used = [d for d in DAYS if c[d] > 0]
        pattern = f'{used[0]}-{used[-1]}' if used else '-'
        lines.append(f'{dept:7} ' + ' '.join(f'{c[d]:4}' for d in DAYS) +
                     f'  {pattern} | {declared.get(dept) or "-"}')
    path = os.path.join(outdir, 'day_order_report.txt')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')
    print(f'day_order_report.txt: {len(usage)} departments')


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', required=True, help='exovance live dump sqlite')
    ap.add_argument('--converted', required=True, help='output of convert_exovance_to_jan9.py')
    ap.add_argument('--jan9', default='jan9.sqlite', help='old jan9 db for core-lab backfill ("" to skip)')
    ap.add_argument('--outdir', default='.')
    args = ap.parse_args()

    src = sqlite3.connect(args.source)
    dst = sqlite3.connect(args.converted)
    old = sqlite3.connect(args.jan9) if args.jan9 and os.path.exists(args.jan9) else None
    if old is None:
        print('  (no old jan9 db - core-lab backfill skipped)')
    os.makedirs(args.outdir, exist_ok=True)

    extract_rooms(dst, args.outdir)
    extract_pop(src, dst, args.outdir)
    extract_lab_mappings(src, dst, old, args.outdir)
    extract_consecutive_labs(src, dst, args.outdir)
    day_order_report(src, args.outdir)


if __name__ == '__main__':
    main()
