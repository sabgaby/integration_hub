import frappe
from frappe import _


def execute(filters=None):
    columns = get_columns()
    data = get_data(filters)
    return columns, data


def get_columns():
    return [
        {
            "label": _("File Name"),
            "fieldname": "file_name",
            "fieldtype": "Data",
            "width": 250
        },
        {
            "label": _("Type"),
            "fieldname": "file_type",
            "fieldtype": "Data",
            "width": 100
        },
        {
            "label": _("Document Type"),
            "fieldname": "parenttype",
            "fieldtype": "Link",
            "options": "DocType",
            "width": 150
        },
        {
            "label": _("Document"),
            "fieldname": "parent",
            "fieldtype": "Dynamic Link",
            "options": "parenttype",
            "width": 180
        },
        {
            "label": _("Added By"),
            "fieldname": "added_by",
            "fieldtype": "Link",
            "options": "User",
            "width": 150
        },
        {
            "label": _("Added On"),
            "fieldname": "added_on",
            "fieldtype": "Datetime",
            "width": 160
        },
        {
            "label": _("Size"),
            "fieldname": "file_size_formatted",
            "fieldtype": "Data",
            "width": 80
        },
        {
            "label": _("Link"),
            "fieldname": "web_view_link",
            "fieldtype": "Data",
            "width": 80
        },
        {
            "label": _("File ID"),
            "fieldname": "file_id",
            "fieldtype": "Data",
            "width": 120
        }
    ]


def get_data(filters):
    conditions = []
    values = {}

    if filters:
        if filters.get("doctype"):
            conditions.append("sl.parenttype = %(doctype)s")
            values["doctype"] = filters.get("doctype")

        if filters.get("added_by"):
            conditions.append("sl.added_by = %(added_by)s")
            values["added_by"] = filters.get("added_by")

        if filters.get("file_type"):
            conditions.append("sl.file_type = %(file_type)s")
            values["file_type"] = filters.get("file_type")

        if filters.get("from_date"):
            conditions.append("sl.added_on >= %(from_date)s")
            values["from_date"] = filters.get("from_date")

        if filters.get("to_date"):
            conditions.append("sl.added_on <= %(to_date)s")
            values["to_date"] = filters.get("to_date")

    where_clause = " AND ".join(conditions) if conditions else "1=1"

    data = frappe.db.sql(f"""
        SELECT
            sl.file_name,
            sl.file_type,
            sl.parenttype,
            sl.parent,
            sl.added_by,
            sl.added_on,
            sl.file_size,
            sl.web_view_link,
            sl.file_id
        FROM `tabSmart Link` sl
        WHERE {where_clause}
        ORDER BY sl.added_on DESC
    """, values, as_dict=True)

    # Format file sizes and make links clickable
    for row in data:
        row["file_size_formatted"] = format_file_size(row.get("file_size") or 0)
        if row.get("web_view_link"):
            row["web_view_link"] = f'<a href="{row["web_view_link"]}" target="_blank">Open</a>'

    return data


def format_file_size(size_bytes):
    """Format bytes to human readable string."""
    if not size_bytes:
        return "-"

    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024

    return f"{size_bytes:.1f} TB"
