# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from datetime import datetime, timedelta, date
from frappe.model.document import Document
from frappe.utils import (
	add_days,
	cint,
	cstr,
	format_date,
	get_datetime,
	get_link_to_form,
	getdate,
	nowdate,
)

from hrms.hr.doctype.shift_assignment.shift_assignment import has_overlapping_timings
from hrms.hr.utils import get_holiday_dates_for_employee, validate_active_employee


class DuplicateAttendanceError(frappe.ValidationError):
	pass


class OverlappingShiftAttendanceError(frappe.ValidationError):
	pass

class SingleLeavePerMonth(frappe.ValidationError):
	pass

class SingleWOPeWeek(frappe.ValidationError):
	pass


class Attendance(Document):
	def validate(self):
		from erpnext.controllers.status_updater import validate_status

		validate_status(self.status, ["P", "A", "L", "WO", "GH"])
		self.validate_attendance_date()
		self.validate_duplicate_record()
		# self.validate_overlapping_shift_attendance()
		self.validate_employee_status()
		# self.check_leave_record()
		self.check_leave_record_for_current_month()
		self.check_wo_record_for_current_week()

	def on_cancel(self):
		self.unlink_attendance_from_checkins()

	def has_override(self):
		current_roles = frappe.get_roles(frappe.session.user)
		submitted_by = self.submitted_by

		return 'HR Manager' in current_roles or submitted_by in ['hardik@picoxpress.com', 'prathap.n@picoxpress.com']

	def validate_attendance_date(self):
		date_of_joining = frappe.db.get_value("Employee", self.employee, "date_of_joining")
		current_attendance_date = getdate(self.attendance_date)
		min_valid_date = getdate(nowdate()) - timedelta(days=3)

		skip_min_validation_check = self.has_override()

		# leaves can be marked for future dates
		if (
			self.status != "L"
			and not self.leave_application
			and getdate(self.attendance_date) > getdate(nowdate())
		):
			frappe.throw(
				_("Attendance can not be marked for future dates: {0}").format(
					frappe.bold(format_date(self.attendance_date)),
				)
			)
		elif current_attendance_date < min_valid_date and not skip_min_validation_check:
			frappe.throw(
				_("Attendance date {0} can not be less than {1}, which is 3 days from today, please reach out to HR").format(
					frappe.bold(format_date(self.attendance_date)),
					frappe.bold(format_date(min_valid_date)),
				)
			)
		elif date_of_joining and getdate(self.attendance_date) < getdate(date_of_joining):
			frappe.throw(
				_("Attendance date {0} can not be less than employee {1}'s joining date: {2}").format(
					frappe.bold(format_date(self.attendance_date)),
					frappe.bold(self.employee),
					frappe.bold(format_date(date_of_joining)),
				)
			)

	def validate_duplicate_record(self):
		duplicate = self.get_duplicate_attendance_record()

		if duplicate:
			frappe.throw(
				_("Attendance for employee {0} is already marked for the date {1}: {2}").format(
					frappe.bold(self.employee),
					frappe.bold(format_date(self.attendance_date)),
					get_link_to_form("Attendance", duplicate),
				),
				title=_("Duplicate Attendance"),
				exc=DuplicateAttendanceError,
			)

	def get_duplicate_attendance_record(self) -> str | None:
		Attendance = frappe.qb.DocType("Attendance")
		query = (
			frappe.qb.from_(Attendance)
			.select(Attendance.name)
			.where(
				(Attendance.employee == self.employee)
				& (Attendance.docstatus < 2)
				& (Attendance.attendance_date == self.attendance_date)
				& (Attendance.name != self.name)
			)
		)

		if self.shift:
			query = query.where(
				((Attendance.shift.isnull()) | (Attendance.shift == ""))
				| (
					((Attendance.shift.isnotnull()) | (Attendance.shift != "")) & (Attendance.shift == self.shift)
				)
			)

		duplicate = query.run(pluck=True)

		return duplicate[0] if duplicate else None

	def check_leave_record_for_current_month(self):
		target_date = datetime(2024, 2, 15).date()
		input_date = datetime.strptime(self.attendance_date, '%Y-%m-%d').date() if not isinstance(self.attendance_date, date) else self.attendance_date
		if self.status == 'L' and input_date > target_date:
			Attendance = frappe.qb.DocType("Attendance")
			month_first_day, month_last_day = self.get_first_and_last_day_of_month(self.attendance_date)
			query = (
				frappe.qb.from_(Attendance)
				.select(Attendance.name)
				.where(
					(Attendance.employee == self.employee)
					& (Attendance.docstatus < 2)
					& (Attendance.attendance_date >= month_first_day)
					& (Attendance.attendance_date <= month_last_day)
					& (Attendance.name != self.name)
					& (Attendance.status == 'L')
				)
			)

			duplicate = query.run(pluck=True)
			if duplicate and not self.has_override():
				frappe.throw(
					_("Attendance for employee {0} is already marked for Leave this Month").format(
						frappe.bold(self.employee)
					),
					title=_("Only Single Leave Per Month"),
					exc=SingleLeavePerMonth,
				)

	def check_wo_record_for_current_week(self):
		target_date = datetime(2024, 2, 15).date()
		input_date = datetime.strptime(self.attendance_date, '%Y-%m-%d').date() if not isinstance(self.attendance_date, date) else self.attendance_date
		if self.status == 'WO' and input_date > target_date:
			Attendance = frappe.qb.DocType("Attendance")
			week_first_day, week_last_day = self.get_first_and_last_day_of_week(self.attendance_date)
			query = (
				frappe.qb.from_(Attendance)
				.select(Attendance.name)
				.where(
					(Attendance.employee == self.employee)
					& (Attendance.docstatus < 2)
					& (Attendance.attendance_date >= week_first_day)
					& (Attendance.attendance_date <= week_last_day)
					& (Attendance.name != self.name)
					& (Attendance.status == 'WO')
				)
			)

			duplicate = query.run(pluck=True)
			if duplicate and not self.has_override():
				frappe.throw(
					_("Attendance for employee {0} is already marked for WO this Week").format(
						frappe.bold(self.employee)
					),
					title=_("Only Single Week Off Per Week"),
					exc=SingleWOPeWeek,
				)

	def get_first_and_last_day_of_month(self, date_str):
		# Parse the input date string
		input_date = datetime.strptime(date_str, '%Y-%m-%d') if not isinstance(date_str, date) else date_str

		# Get the year and month
		year = input_date.year
		month = input_date.month

		# Get the first day of the month
		first_day = datetime(year, month, 1).strftime('%m-%d-%Y')

		# Get the last day of the month
		last_day = datetime(year, month + 1, 1) - timedelta(days=1)
		last_day = last_day.strftime('%m-%d-%Y')

		return first_day, last_day

	def get_first_and_last_day_of_week(self, date_str):
		# Parse the input date string
		input_date = datetime.strptime(date_str, '%Y-%m-%d') if not isinstance(date_str, date) else date_str

		# Calculate the start of the week (Sunday)
		start_of_week = input_date - timedelta(days=input_date.weekday())

		# Calculate the end of the week (Saturday)
		end_of_week = start_of_week + timedelta(days=6)

		# Format the dates in mm-dd-yyyy format
		start_of_week_str = start_of_week.strftime('%m-%d-%Y')
		end_of_week_str = end_of_week.strftime('%m-%d-%Y')

		return start_of_week_str, end_of_week_str

	def validate_overlapping_shift_attendance(self):
		attendance = self.get_overlapping_shift_attendance()

		if attendance:
			frappe.throw(
				_("Attendance for employee {0} is already marked for an overlapping shift {1}: {2}").format(
					frappe.bold(self.employee),
					frappe.bold(attendance.shift),
					get_link_to_form("Attendance", attendance.name),
				),
				title=_("Overlapping Shift Attendance"),
				exc=OverlappingShiftAttendanceError,
			)


	def get_overlapping_shift_attendance(self) -> dict:
		if not self.shift:
			return {}

		Attendance = frappe.qb.DocType("Attendance")
		same_date_attendance = (
			frappe.qb.from_(Attendance)
			.select(Attendance.name, Attendance.shift)
			.where(
				(Attendance.employee == self.employee)
				& (Attendance.docstatus < 2)
				& (Attendance.attendance_date == self.attendance_date)
				& (Attendance.shift != self.shift)
				& (Attendance.name != self.name)
			)
		).run(as_dict=True)

		if same_date_attendance and has_overlapping_timings(self.shift, same_date_attendance[0].shift):
			return same_date_attendance[0]
		return {}

	def validate_employee_status(self):
		input_date = datetime.strptime(self.attendance_date, '%Y-%m-%d') if not isinstance(self.attendance_date, date) else self.attendance_date
		termination_date = frappe.db.get_value("Employee", self.employee, "relieving_date")
		print(type(input_date))
		print(type(termination_date))
		if (frappe.db.get_value("Employee", self.employee, "status") != "Active"
				and termination_date < input_date.date()
		):
			frappe.throw(_("Cannot mark attendance for an Inactive employee {0}").format(self.employee))

	def check_leave_record(self):
		leave_record = frappe.db.sql(
			"""
			select leave_type, half_day, half_day_date
			from `tabLeave Application`
			where employee = %s
				and %s between from_date and to_date
				and status = 'Approved'
				and docstatus = 1
		""",
			(self.employee, self.attendance_date),
			as_dict=True,
		)
		if leave_record:
			for d in leave_record:
				self.leave_type = d.leave_type
				if d.half_day_date == getdate(self.attendance_date):
					self.status = "Half Day"
					frappe.msgprint(
						_("Employee {0} on Half day on {1}").format(self.employee, format_date(self.attendance_date))
					)
				else:
					self.status = "L"
					frappe.msgprint(
						_("Employee {0} is on Leave on {1}").format(self.employee, format_date(self.attendance_date))
					)

		if self.status in ("L", "Half Day"):
			if not leave_record:
				frappe.msgprint(
					_("No leave record found for employee {0} on {1}").format(
						self.employee, format_date(self.attendance_date)
					),
					alert=1,
				)
		elif self.leave_type:
			self.leave_type = None
			self.leave_application = None

	def validate_employee(self):
		emp = frappe.db.sql(
			"select name from `tabEmployee` where name = %s and status = 'Active'", self.employee
		)
		if not emp:
			frappe.throw(_("Employee {0} is not active or does not exist").format(self.employee))

	def unlink_attendance_from_checkins(self):
		EmployeeCheckin = frappe.qb.DocType("Employee Checkin")
		linked_logs = (
			frappe.qb.from_(EmployeeCheckin)
			.select(EmployeeCheckin.name)
			.where(EmployeeCheckin.attendance == self.name)
			.for_update()
			.run(as_dict=True)
		)

		if linked_logs:
			(
				frappe.qb.update(EmployeeCheckin)
				.set("attendance", "")
				.where(EmployeeCheckin.attendance == self.name)
			).run()

			frappe.msgprint(
				msg=_("Unlinked Attendance record from Employee Checkins: {}").format(
					", ".join(get_link_to_form("Employee Checkin", log.name) for log in linked_logs)
				),
				title=_("Unlinked logs"),
				indicator="blue",
				is_minimizable=True,
				wide=True,
			)


@frappe.whitelist()
def get_events(start, end, filters=None):
	events = []

	employee = frappe.db.get_value("Employee", {"user_id": frappe.session.user})

	if not employee:
		return events

	from frappe.desk.reportview import get_filters_cond

	conditions = get_filters_cond("Attendance", filters, [])
	add_attendance(events, start, end, conditions=conditions)
	return events


def add_attendance(events, start, end, conditions=None):
	query = """select name, attendance_date, status
		from `tabAttendance` where
		attendance_date between %(from_date)s and %(to_date)s
		and docstatus < 2"""
	if conditions:
		query += conditions

	for d in frappe.db.sql(query, {"from_date": start, "to_date": end}, as_dict=True):
		e = {
			"name": d.name,
			"doctype": "Attendance",
			"start": d.attendance_date,
			"end": d.attendance_date,
			"title": cstr(d.status),
			"docstatus": d.docstatus,
		}
		if e not in events:
			events.append(e)


def mark_attendance(
	employee,
	attendance_date,
	status,
	shift=None,
	leave_type=None,
	late_entry=False,
	early_exit=False,
):
	savepoint = "attendance_creation"

	try:
		frappe.db.savepoint(savepoint)
		attendance = frappe.new_doc("Attendance")
		attendance.update(
			{
				"doctype": "Attendance",
				"employee": employee,
				"attendance_date": attendance_date,
				"status": status,
				"shift": shift,
				"leave_type": leave_type,
				"late_entry": late_entry,
				"early_exit": early_exit,
			}
		)
		attendance.insert()
		attendance.submit()
	except (DuplicateAttendanceError, OverlappingShiftAttendanceError):
		frappe.db.rollback(save_point=savepoint)
		return

	return attendance.name


@frappe.whitelist()
def mark_bulk_attendance(data):
	import json

	if isinstance(data, str):
		data = json.loads(data)
	data = frappe._dict(data)
	if not data.unmarked_days:
		frappe.throw(_("Please select a date."))
		return

	for date in data.unmarked_days:
		doc_dict = {
			"doctype": "Attendance",
			"employee": data.employee,
			"attendance_date": get_datetime(date),
			"status": data.status,
		}
		attendance = frappe.get_doc(doc_dict).insert()
		attendance.submit()


@frappe.whitelist()
def get_unmarked_days(employee, from_date, to_date, exclude_holidays=0):
	joining_date, relieving_date = frappe.get_cached_value(
		"Employee", employee, ["date_of_joining", "relieving_date"]
	)

	from_date = max(getdate(from_date), joining_date or getdate(from_date))
	to_date = min(getdate(to_date), relieving_date or getdate(to_date))

	records = frappe.get_all(
		"Attendance",
		fields=["attendance_date", "employee"],
		filters=[
			["attendance_date", ">=", from_date],
			["attendance_date", "<=", to_date],
			["employee", "=", employee],
			["docstatus", "!=", 2],
		],
	)

	marked_days = [getdate(record.attendance_date) for record in records]

	if cint(exclude_holidays):
		holiday_dates = get_holiday_dates_for_employee(employee, from_date, to_date)
		holidays = [getdate(record) for record in holiday_dates]
		marked_days.extend(holidays)

	unmarked_days = []

	while from_date <= to_date:
		if from_date not in marked_days:
			unmarked_days.append(from_date)

		from_date = add_days(from_date, 1)

	return unmarked_days

@frappe.whitelist(allow_guest=True)
def send_unmarked_attendance_summary():
	attendance_date = datetime.now() - timedelta(days=1)
	hr_settings = frappe.get_doc("HR Settings")
	hubs = frappe.get_all(
		"Hub Location",
		fields=["manager_email", "name"]
	)
	print("Hub List", hubs)
	for h in hubs:
		off_role_employees = frappe.get_all(
			"Employee",
			fields=["employee_name", "name"],
			filters=[
				["location", "=", h.name],
				["employment_type", "=", "Off-Roll"],
				["status", "=", "Active"]
			]
		)
		if len(off_role_employees) > 0:
			print("Employees for Hubs", h.name, off_role_employees)
			missed_attendance_employee = []
			for e in off_role_employees:
				attendance_record = frappe.get_all(
					"Attendance",
					fields=["attendance_date", "employee"],
					filters=[
						["attendance_date", "=", attendance_date],
						["employee", "=", e.name],
						["docstatus", "!=", 2],
					],
				)
				if len(attendance_record) == 0:
					missed_attendance_employee.append(
						{
							"name": e.employee_name,
						}
					)
			if len(missed_attendance_employee) > 0 and h.manager_email:
				print("Sending Email for Hub: {} and date: {} and Employees Missing: {}".format(h.name, attendance_date.strftime("%d-%m-%Y"), missed_attendance_employee))
				frappe.sendmail(
					recipients=[h.manager_email],
					subject=_("Missing Attendance for Hub: {} on: {}".format(h.name, attendance_date.strftime("%d-%m-%Y"))),
					template="missing_offrole_attendance_summary",
					args=dict(
						title="Attendance was not marked for the below employees at: {} on {}".format(h.name, attendance_date.strftime("%d-%m-%Y")),
						missing_attendance=missed_attendance_employee
					),
				)
		else:
			print("No Off Role Employees found for hub: {}".format(h.name))
