import csv
from decimal import Decimal

from django.http import HttpResponse


def csv_safe(value):
    """Format a cell; neutralise spreadsheet formula injection in text (=, +, -, @)."""
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return f"{value:.2f}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t", "\r") else s


def report_to_csv(report, filename):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
    w = csv.writer(response)
    w.writerow([report.title])
    for section in report.sections:
        w.writerow([])
        if section.title:
            w.writerow([section.title])
        w.writerow(section.headers)
        for row in section.rows:
            w.writerow([csv_safe(c) for c in row])
        if section.total:
            w.writerow([csv_safe(c) for c in section.total])
    return response
