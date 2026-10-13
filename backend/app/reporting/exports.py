"""Aggregate report exports. Exports contain metrics, not patient identifiers."""

import csv
import io
from datetime import date
from xml.sax.saxutils import escape

from openpyxl import Workbook
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from app.analytics.service import AnalyticsFilter, category_slice, denial_analytics, payer_analytics, underpayment_analytics


def build_report(db, report_name: str, filters: AnalyticsFilter, demo_mode: bool) -> tuple[str, list[dict]]:
    title = report_name.replace("_", " ").title()
    notice = "Synthetic demo data. " if demo_mode else ""
    if report_name in {"weekly_denial", "daily_remittance", "monthly_payer"}:
        data = denial_analytics(db, filters)
        rows = data["by_payer"] or [{"notice": "No claims in the selected period."}]
        if report_name == "monthly_payer":
            rows = payer_analytics(db, filters)["payers"] or rows
    elif report_name == "underpayment_exception":
        data = underpayment_analytics(db, filters)
        rows = data["items"] or [{"notice": data["notice"], "metric_basis": data["metric_basis"]}]
    elif report_name == "authorization_denial":
        rows = category_slice(db, filters, "authorization")["by_payer"] or [{"notice": "No authorization denials."}]
    elif report_name == "coding_denial":
        rows = category_slice(db, filters, "coding")["by_payer"] or [{"notice": "No coding denials."}]
    elif report_name == "reconciliation":
        from app.models import ReconciliationResult

        results = db.query(ReconciliationResult).all()
        rows = [
            {
                "scope": item.scope,
                "status": item.status,
                "expected_amount": f"{item.expected_amount:.2f}",
                "actual_amount": f"{item.actual_amount:.2f}",
                "difference": f"{item.difference:.2f}",
            }
            for item in results
        ] or [{"notice": "No reconciliation results."}]
    else:
        raise KeyError(report_name)
    for row in rows:
        row["report"] = title
        row["demo_notice"] = notice.strip()
    return title, rows


def to_csv(rows: list[dict]) -> bytes:
    buffer = io.StringIO()
    fields = sorted({key for row in rows for key in row})
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in rows:
        writer.writerow({key: _plain(row.get(key)) for key in fields})
    return buffer.getvalue().encode("utf-8")


def to_xlsx(title: str, rows: list[dict]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Report"
    fields = sorted({key for row in rows for key in row})
    sheet.append(fields)
    for row in rows:
        sheet.append([_plain(row.get(field)) for field in fields])
    sheet["A1"].value = fields[0] if fields else title
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def to_pdf(title: str, rows: list[dict], demo_mode: bool) -> bytes:
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    pdf.setTitle(title)
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, 750, title)
    pdf.setFont("Helvetica", 9)
    y = 730
    if demo_mode:
        pdf.drawString(40, y, "SYNTHETIC DEMO DATA. Not a production remittance report.")
        y -= 16
    for row in rows[:40]:
        line = escape(" | ".join(f"{key}: {_plain(value)}" for key, value in row.items() if key != "trace"))
        pdf.drawString(40, y, line[:140])
        y -= 14
        if y < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 9)
            y = 750
    pdf.save()
    return buffer.getvalue()


def _plain(value) -> str:
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, list):
        return "; ".join(str(item) for item in value)
    return str(value)
