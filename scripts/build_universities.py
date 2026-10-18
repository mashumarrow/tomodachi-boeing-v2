import csv
import io
import json
from pathlib import Path


SOURCE = "https://www.mext.go.jp/content/20260825-mxt_chousa01-000011635_6.csv"
ROOT = Path(__file__).resolve().parent.parent
INPUT = ROOT / "db" / "20260825-mxt_chousa01-000011635_6.csv"
OUTPUT = ROOT / "data" / "universities.json"


def main():
    raw = INPUT.read_bytes()
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        content = raw.decode("cp932")
    universities = {}
    for row in csv.reader(io.StringIO(content)):
        if len(row) < 10 or not row[0].startswith("F1") or row[9].strip():
            continue
        prefecture = row[2].partition("(")[2].rstrip(")") or row[2].strip()
        universities[row[0]] = {"id": row[0], "name": row[5].strip(),
                                "prefecture": prefecture, "address": row[6].strip()}
    if len(universities) < 700:
        raise ValueError("Unexpected university dataset; check CSV structure")
    OUTPUT.write_text(json.dumps({"source": SOURCE, "sourceFile": INPUT.name, "asOf": "2026-05-01",
                                 "universities": sorted(universities.values(), key=lambda item: item["name"])},
                                ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {len(universities)} universities")


if __name__ == "__main__":
    main()
