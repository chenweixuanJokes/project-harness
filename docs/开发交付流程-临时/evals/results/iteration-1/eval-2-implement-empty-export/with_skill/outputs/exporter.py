import csv
import io

COLUMNS = ("id", "name")


def export_csv(rows, can_export=True):
    if not can_export:
        raise PermissionError("export denied")
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()
