#!/usr/bin/env python3
r"""
Pull the latest Exovance live database from the VPS and save it as SQLite.

Default output:
    D:\data_works_timetable\exovance-YYYY-MM-DD-vN.sqlite

Run from PowerShell:
    python C:\Users\ADMIN\Documents\Codex\2026-06-11\create-a-new-ssh-called-timetable\outputs\pull_exovance_latest_sqlite.py
"""

import argparse
import csv
import hashlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path


DEFAULT_HOST = "89.116.121.23"
DEFAULT_USER = "root"
DEFAULT_KEY = Path.home() / ".ssh" / "timetable"
DEFAULT_OUTPUT_DIR = Path(r"D:\data_works_timetable")
DEFAULT_DB_CONTAINER = "exo_postgres"
DEFAULT_DB_USER = "exovance"
DEFAULT_DB_NAME = "exovance_prod"
NULL_SENTINEL = "__CODEX_PG_NULL_7F4C96F4__"


REMOTE_EXPORT_SCRIPT = r"""set -euo pipefail
DB_CONTAINER="${DB_CONTAINER:-exo_postgres}"
DB_USER="${DB_USER:-exovance}"
DB_NAME="${DB_NAME:-exovance_prod}"
NULL_SENTINEL="__CODEX_PG_NULL_7F4C96F4__"
EXPORT_ID="$(date -u +%Y%m%dT%H%M%SZ)"
EXPORT_DIR="/tmp/exovance_sqlite_export_${EXPORT_ID}"
TAR_PATH="${EXPORT_DIR}.tar.gz"

rm -rf "$EXPORT_DIR"
mkdir -p "$EXPORT_DIR/csv"

psqlq() {
  docker exec "$DB_CONTAINER" psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 "$@"
}

psqlq -qAt -F $'\t' -c "
select n.nspname, c.relname,
       case c.relkind
         when 'r' then 'BASE TABLE'
         when 'p' then 'BASE TABLE'
         when 'v' then 'VIEW'
         when 'm' then 'MATERIALIZED VIEW'
       end
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
where c.relkind in ('r','p','v','m')
  and n.nspname not in ('pg_catalog','information_schema')
order by n.nspname, c.relname;
" > "$EXPORT_DIR/tables.tsv"

psqlq -qAt -F $'\t' -c "
select n.nspname, c.relname, a.attname, a.attnum,
       format_type(a.atttypid, a.atttypmod),
       t.typname,
       case when a.attnotnull then 'NO' else 'YES' end
from pg_class c
join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid
join pg_type t on t.oid = a.atttypid
where c.relkind in ('r','p','v','m')
  and n.nspname not in ('pg_catalog','information_schema')
  and a.attnum > 0
  and not a.attisdropped
order by n.nspname, c.relname, a.attnum;
" > "$EXPORT_DIR/columns.tsv"

psqlq -qAt -F $'\t' -c "
select n.nspname, c.relname, a.attname, k.ord
from pg_index i
join pg_class c on c.oid = i.indrelid
join pg_namespace n on n.oid = c.relnamespace
join unnest(i.indkey) with ordinality as k(attnum, ord) on true
join pg_attribute a on a.attrelid = c.oid and a.attnum = k.attnum
where i.indisprimary
  and n.nspname not in ('pg_catalog','information_schema')
order by n.nspname, c.relname, k.ord;
" > "$EXPORT_DIR/primary_keys.tsv"

{
  printf 'source_host\t%s\n' "$(hostname)"
  printf 'source_database\t%s\n' "$DB_NAME"
  printf 'source_container\t%s\n' "$DB_CONTAINER"
  printf 'export_started_utc\t%s\n' "$EXPORT_ID"
  printf 'database_size_bytes\t%s\n' "$(psqlq -qAt -c "select pg_database_size(current_database());")"
  printf 'postgres_version\t%s\n' "$(psqlq -qAt -c "select version();" | tr '\t' ' ')"
  printf 'null_sentinel\t%s\n' "$NULL_SENTINEL"
} > "$EXPORT_DIR/metadata.tsv"

: > "$EXPORT_DIR/table_files.tsv"
while IFS=$'\t' read -r schema table object_type; do
  [ -n "$schema" ] || continue
  q_schema="${schema//\"/\"\"}"
  q_table="${table//\"/\"\"}"
  ident="\"${q_schema}\".\"${q_table}\""
  safe_file="$(printf '%s__%s' "$schema" "$table" | tr -c 'A-Za-z0-9_.-' '_').csv"
  row_count="$(psqlq -qAt -c "select count(*) from ${ident};")"
  psqlq -q -c "COPY (SELECT * FROM ${ident}) TO STDOUT WITH (FORMAT CSV, HEADER true, FORCE_QUOTE *, NULL '${NULL_SENTINEL}');" > "$EXPORT_DIR/csv/$safe_file"
  printf '%s\t%s\t%s\t%s\t%s\n' "$schema" "$table" "$object_type" "$safe_file" "$row_count" >> "$EXPORT_DIR/table_files.tsv"
done < "$EXPORT_DIR/tables.tsv"

tar -czf "$TAR_PATH" -C "$EXPORT_DIR" .
printf 'EXPORT_ID=%s\n' "$EXPORT_ID"
printf 'TAR_PATH=%s\n' "$TAR_PATH"
printf 'TAR_SHA256=%s\n' "$(sha256sum "$TAR_PATH" | awk '{print $1}')"
"""


def run(command, *, input_bytes=None, timeout=900):
    result = subprocess.run(
        command,
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    stdout = result.stdout.decode("utf-8", errors="replace")
    stderr = result.stderr.decode("utf-8", errors="replace")
    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(str(part) for part in command)
            + "\nSTDOUT:\n"
            + stdout
            + "\nSTDERR:\n"
            + stderr
        )
    return stdout


def ssh_base(args):
    return [
        "ssh",
        "-i",
        str(args.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
        f"{args.user}@{args.host}",
    ]


def scp_base(args):
    return [
        "scp",
        "-i",
        str(args.key),
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=accept-new",
    ]


def parse_kv(text):
    values = {}
    for line in text.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
    return values


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quote_ident(name):
    return '"' + name.replace('"', '""') + '"'


def sqlite_ident(name):
    return '"' + name.replace('"', '""') + '"'


def read_tsv(path):
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle, delimiter="\t"))


def sqlite_type(pg_udt, pg_type):
    pg_udt = (pg_udt or "").lower()
    pg_type = (pg_type or "").lower()
    if pg_udt in {"int2", "int4", "int8", "serial", "bigserial"}:
        return "INTEGER"
    if pg_udt in {"float4", "float8"}:
        return "REAL"
    if pg_udt in {"numeric", "decimal"} or pg_type.startswith("numeric"):
        return "NUMERIC"
    if pg_udt == "bool":
        return "INTEGER"
    if pg_udt == "bytea":
        return "BLOB"
    return "TEXT"


def convert_value(value, pg_udt):
    if value == NULL_SENTINEL:
        return None
    pg_udt = (pg_udt or "").lower()
    if pg_udt == "bool":
        if value in {"t", "true", "TRUE", "1"}:
            return 1
        if value in {"f", "false", "FALSE", "0"}:
            return 0
    if pg_udt == "bytea" and value.startswith("\\x"):
        try:
            return bytes.fromhex(value[2:])
        except ValueError:
            return value
    return value


def next_output_path(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    date_text = datetime.now().strftime("%Y-%m-%d")
    pattern = re.compile(rf"^exovance-{re.escape(date_text)}-v(\d+)\.sqlite$")
    versions = []
    for path in output_dir.glob(f"exovance-{date_text}-v*.sqlite"):
        match = pattern.match(path.name)
        if match:
            versions.append(int(match.group(1)))
    return output_dir / f"exovance-{date_text}-v{max(versions, default=0) + 1}.sqlite"


def build_sqlite(extract_dir, output_db):
    table_files = []
    for row in read_tsv(extract_dir / "table_files.tsv"):
        if len(row) == 5:
            schema, table, object_type, safe_file, count = row
            table_files.append(
                {
                    "schema": schema,
                    "table": table,
                    "object_type": object_type,
                    "safe_file": safe_file,
                    "source_count": int(count),
                }
            )

    columns = defaultdict(list)
    for row in read_tsv(extract_dir / "columns.tsv"):
        if len(row) == 7:
            schema, table, column, ordinal, data_type, udt_name, nullable = row
            columns[(schema, table)].append(
                {
                    "name": column,
                    "ordinal": int(ordinal),
                    "data_type": data_type,
                    "udt_name": udt_name,
                    "nullable": nullable,
                    "sqlite_type": sqlite_type(udt_name, data_type),
                }
            )

    primary_keys = defaultdict(list)
    for row in read_tsv(extract_dir / "primary_keys.tsv"):
        if len(row) == 4:
            schema, table, column, ordinal = row
            primary_keys[(schema, table)].append((int(ordinal), column))
    for key in list(primary_keys):
        primary_keys[key] = [column for _, column in sorted(primary_keys[key])]

    name_counts = Counter(item["table"] for item in table_files)
    for item in table_files:
        if item["schema"] == "public" and name_counts[item["table"]] == 1:
            item["sqlite_table"] = item["table"]
        else:
            item["sqlite_table"] = f"{item['schema']}__{item['table']}"

    if output_db.exists():
        output_db.unlink()
    temp_db = output_db.with_suffix(".tmp.sqlite")
    if temp_db.exists():
        temp_db.unlink()

    metadata = {}
    for row in read_tsv(extract_dir / "metadata.tsv"):
        if len(row) >= 2:
            metadata[row[0]] = row[1]

    summary = []
    conn = sqlite3.connect(temp_db)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute('CREATE TABLE "_export_metadata" ("key" TEXT PRIMARY KEY, "value" TEXT)')
        conn.executemany(
            'INSERT INTO "_export_metadata" ("key", "value") VALUES (?, ?)',
            sorted(metadata.items()),
        )
        conn.execute(
            'CREATE TABLE "_table_counts" ('
            '"sqlite_table" TEXT PRIMARY KEY, '
            '"source_schema" TEXT, '
            '"source_table" TEXT, '
            '"source_type" TEXT, '
            '"source_rows" INTEGER, '
            '"sqlite_rows" INTEGER)'
        )

        for item in table_files:
            key = (item["schema"], item["table"])
            col_meta = sorted(columns[key], key=lambda col: col["ordinal"])
            column_defs = [
                f"{sqlite_ident(col['name'])} {col['sqlite_type']}" for col in col_meta
            ]
            pk_cols = primary_keys.get(key, [])
            if pk_cols and item["object_type"] == "BASE TABLE":
                column_defs.append(
                    "PRIMARY KEY ("
                    + ", ".join(sqlite_ident(column) for column in pk_cols)
                    + ")"
                )

            table_name = item["sqlite_table"]
            conn.execute(
                f"CREATE TABLE {sqlite_ident(table_name)} ("
                + ", ".join(column_defs)
                + ")"
            )

            csv_path = extract_dir / "csv" / item["safe_file"]
            with csv_path.open("r", encoding="utf-8", newline="") as handle:
                reader = csv.reader(handle)
                header = next(reader, [])
                col_by_name = {col["name"]: col for col in col_meta}
                insert_sql = (
                    f"INSERT INTO {sqlite_ident(table_name)} ("
                    + ", ".join(sqlite_ident(column) for column in header)
                    + ") VALUES ("
                    + ", ".join("?" for _ in header)
                    + ")"
                )
                batch = []
                sqlite_rows = 0
                for row in reader:
                    batch.append(
                        [
                            convert_value(value, col_by_name.get(column, {}).get("udt_name"))
                            for column, value in zip(header, row)
                        ]
                    )
                    if len(batch) >= 1000:
                        conn.executemany(insert_sql, batch)
                        sqlite_rows += len(batch)
                        batch.clear()
                if batch:
                    conn.executemany(insert_sql, batch)
                    sqlite_rows += len(batch)

            conn.execute(
                'INSERT INTO "_table_counts" VALUES (?, ?, ?, ?, ?, ?)',
                (
                    table_name,
                    item["schema"],
                    item["table"],
                    item["object_type"],
                    item["source_count"],
                    sqlite_rows,
                ),
            )
            summary.append((table_name, item["source_count"], sqlite_rows))

        conn.commit()
        conn.execute("VACUUM")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        mismatches = [row for row in summary if row[1] != row[2]]
        if mismatches:
            raise RuntimeError(f"Row count mismatches: {mismatches[:5]}")
    finally:
        conn.close()

    temp_db.replace(output_db)
    return summary


def main():
    parser = argparse.ArgumentParser(description="Pull Exovance live DB from VPS and save only SQLite.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--user", default=DEFAULT_USER)
    parser.add_argument("--key", type=Path, default=DEFAULT_KEY)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output", type=Path, default=None, help="Exact output SQLite path.")
    parser.add_argument("--db-container", default=DEFAULT_DB_CONTAINER)
    parser.add_argument("--db-user", default=DEFAULT_DB_USER)
    parser.add_argument("--db-name", default=DEFAULT_DB_NAME)
    args = parser.parse_args()

    output_db = args.output or next_output_path(args.output_dir)
    output_db.parent.mkdir(parents=True, exist_ok=True)

    remote_script = (
        f"export DB_CONTAINER={args.db_container!r} DB_USER={args.db_user!r} DB_NAME={args.db_name!r};\n"
        + REMOTE_EXPORT_SCRIPT
    )

    print("Creating live export on server...")
    result = run(ssh_base(args) + ["bash", "-s"], input_bytes=remote_script.encode("utf-8"))
    values = parse_kv(result)
    export_id = values["EXPORT_ID"]
    tar_path = values["TAR_PATH"]
    remote_sha = values["TAR_SHA256"]

    with tempfile.TemporaryDirectory(prefix="exovance_pull_") as tmp:
        tmp_dir = Path(tmp)
        local_tar = tmp_dir / f"exovance_live_{export_id}.tar.gz"
        extract_dir = tmp_dir / "extract"
        extract_dir.mkdir()

        print("Copying export archive...")
        run(
            scp_base(args)
            + [f"{args.user}@{args.host}:{tar_path}", str(local_tar)],
            timeout=900,
        )

        local_sha = sha256_file(local_tar)
        if local_sha != remote_sha:
            raise RuntimeError(f"SHA256 mismatch: remote={remote_sha} local={local_sha}")

        with tarfile.open(local_tar, "r:gz") as archive:
            archive.extractall(extract_dir)

        print("Building SQLite locally...")
        summary = build_sqlite(extract_dir, output_db)

    try:
        run(ssh_base(args) + [f"rm -rf /tmp/exovance_sqlite_export_{export_id} /tmp/exovance_sqlite_export_{export_id}.tar.gz"], timeout=60)
    except Exception as exc:
        print(f"Warning: could not clean remote temp files: {exc}", file=sys.stderr)

    print("")
    print(f"SQLite: {output_db}")
    print(f"SHA256: {sha256_file(output_db)}")
    print(f"Tables/views exported: {len(summary)}")
    print(f"Total rows exported: {sum(row[2] for row in summary)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
