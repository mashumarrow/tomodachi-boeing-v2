import csv
import json
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
OUTPUT = ROOT / "data" / "facilities.sqlite3"

FACILITY_FILES = (
    ("01-1_hospital_facility_info_20260601.csv", "hospital"),
    ("02-1_clinic_facility_info_20260601.csv", "clinic"),
)
SPECIALITY_FILES = (
    ("01-2_hospital_speciality_hours_20260601.csv", "hospital"),
    ("02-2_clinic_speciality_hours_20260601.csv", "clinic"),
)


def normalize_url(value):
    value = value.strip()
    if not value:
        return ""
    if value.lower().startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def map_department(name):
    if "皮膚" in name:
        return "dermatology"
    if "眼" in name:
        return "eye"
    if "耳鼻" in name:
        return "ent"
    if "婦人" in name or "産婦人" in name:
        return "gynecology"
    if "内科" in name:
        return "internal"
    return None


def time_range(pairs):
    valid = [(start, end) for start, end in pairs if start and end]
    if not valid:
        return "診療時間は詳細で確認"
    starts = sorted(start for start, _ in valid)
    ends = sorted(end for _, end in valid)
    return f"{starts[0]}-{ends[-1]}"


def rows(file_name):
    with (DB_DIR / file_name).open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        next(reader, None)
        yield from reader


def create_schema(connection):
    connection.executescript(
        """
        PRAGMA journal_mode = WAL;
        PRAGMA synchronous = NORMAL;

        CREATE TABLE facilities (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            name TEXT NOT NULL,
            address TEXT NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            website TEXT NOT NULL,
            open TEXT NOT NULL,
            median_wait INTEGER NOT NULL
        );

        CREATE TABLE facility_departments (
            facility_id TEXT NOT NULL,
            department TEXT NOT NULL,
            PRIMARY KEY (facility_id, department)
        );

        CREATE INDEX facilities_location_idx ON facilities(latitude, longitude);
        CREATE INDEX facilities_type_idx ON facilities(type);
        CREATE INDEX departments_lookup_idx ON facility_departments(department, facility_id);
        """
    )


def insert_medical_facilities(connection):
    statement = """
        INSERT OR REPLACE INTO facilities
        (id, type, name, address, latitude, longitude, website, open, median_wait)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    for file_name, kind in FACILITY_FILES:
        batch = []
        for row in rows(file_name):
            try:
                latitude = float(row[10])
                longitude = float(row[11])
            except (ValueError, IndexError):
                continue
            batch.append((
                f"{kind}:{row[0]}",
                kind,
                row[1],
                row[9],
                latitude,
                longitude,
                normalize_url(row[12]),
                "診療時間は詳細で確認",
                60 if kind == "hospital" else 35,
            ))
            if len(batch) >= 2000:
                connection.executemany(statement, batch)
                batch.clear()
        if batch:
            connection.executemany(statement, batch)
        connection.commit()


def insert_specialities(connection):
    department_statement = """
        INSERT OR IGNORE INTO facility_departments(facility_id, department)
        VALUES (?, ?)
    """
    update_hours_statement = "UPDATE facilities SET open = ? WHERE id = ?"

    for file_name, kind in SPECIALITY_FILES:
        department_batch = []
        hours = {}
        for row in rows(file_name):
            facility_id = f"{kind}:{row[0]}"
            department = map_department(row[2] if len(row) > 2 else "")
            if department:
                department_batch.append((facility_id, department))
            pairs = []
            for index in range(4, 19, 2):
                if len(row) > index + 1 and row[index] and row[index + 1]:
                    pairs.append((row[index], row[index + 1]))
            if pairs:
                hours.setdefault(facility_id, []).extend(pairs)
            if len(department_batch) >= 5000:
                connection.executemany(department_statement, department_batch)
                department_batch.clear()
        if department_batch:
            connection.executemany(department_statement, department_batch)
        connection.executemany(
            update_hours_statement,
            ((time_range(pairs), facility_id) for facility_id, pairs in hours.items()),
        )
        connection.commit()


def insert_pharmacies(connection):
    statement = """
        INSERT OR REPLACE INTO facilities
        (id, type, name, address, latitude, longitude, website, open, median_wait)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    department_statement = """
        INSERT OR IGNORE INTO facility_departments(facility_id, department)
        VALUES (?, 'pharmacy')
    """
    facilities_batch = []
    departments_batch = []
    for row in rows("05_pharmacy_20260601.csv"):
        try:
            latitude = float(row[8])
            longitude = float(row[9])
        except (ValueError, IndexError):
            continue
        facility_id = f"pharmacy:{row[0]}"
        opening_pairs = []
        for index in range(64, len(row) - 1, 2):
            if row[index] and row[index + 1]:
                opening_pairs.append((row[index], row[index + 1]))
        facilities_batch.append((
            facility_id,
            "pharmacy",
            row[1],
            row[7],
            latitude,
            longitude,
            normalize_url(row[10]),
            time_range(opening_pairs),
            15,
        ))
        departments_batch.append((facility_id,))
        if len(facilities_batch) >= 2000:
            connection.executemany(statement, facilities_batch)
            connection.executemany(department_statement, departments_batch)
            facilities_batch.clear()
            departments_batch.clear()
    if facilities_batch:
        connection.executemany(statement, facilities_batch)
        connection.executemany(department_statement, departments_batch)
    connection.commit()


def main():
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    connection = sqlite3.connect(OUTPUT)
    try:
        create_schema(connection)
        insert_medical_facilities(connection)
        insert_specialities(connection)
        insert_pharmacies(connection)
        connection.execute("ANALYZE")
        connection.commit()
        counts = dict(connection.execute(
            "SELECT type, COUNT(*) FROM facilities GROUP BY type"
        ).fetchall())
        print(json.dumps(counts, ensure_ascii=False))
    finally:
        connection.close()


if __name__ == "__main__":
    main()
