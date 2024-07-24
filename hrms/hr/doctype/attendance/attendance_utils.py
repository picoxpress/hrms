import frappe
from frappe.utils import (
    getdate,
    nowdate,
)


@frappe.whitelist(allow_guest=True)
def get_marked_attendance_for_employee(**kwargs):
    Attendance = frappe.qb.DocType("Attendance")

    employee_code = kwargs.get("employee_code", "")
    attendance_date = getdate(kwargs.get("attendance_date")) or getdate(nowdate())

    query = (
        frappe.qb.from_(Attendance)
        .select(
            Attendance.name,
            Attendance.status,
            Attendance.employee_name,
        )
        .where(
            (Attendance.employee == employee_code)
            & (Attendance.docstatus < 2)
            & (Attendance.attendance_date == attendance_date)
        )
    )
    record = query.run(as_dict=True)
    return {
        'is_marked': len(record) > 0,
        'details': record[0] if (len(record) > 0) else None
    }