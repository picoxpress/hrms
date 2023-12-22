import frappe


def execute():
	ss = frappe.qb.DocType("Salary Structure").as_("ss")
	sd = frappe.qb.DocType("Salary Detail").as_("sd")

	(
		frappe.qb.update(sd)
		.set("docstatus", 1)
		.from_(ss)
		.where(
			(ss.docstatus == 1) &
			(sd.parenttype == "Salary Structure") &
			(ss.name == sd.parent)
		)
	).run()
