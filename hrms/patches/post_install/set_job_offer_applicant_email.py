import frappe


def execute():
	Offer = frappe.qb.DocType("Job Offer")
	Applicant = frappe.qb.DocType("Job Applicant")

	(
		frappe.qb.update(Offer)
		.set("applicant_email", Applicant.email_id)
		.from_(Applicant)
		.where(Offer.applicant_email.isnull() & (Applicant.name == Offer.job_applicant))
	).run()
