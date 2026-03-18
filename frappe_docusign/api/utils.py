"""
Shared helpers used by both envelope.py and webhook.py.
"""
import frappe


def update_deal_stage(deal_name: str, stage_name: str) -> None:
    """
    Update the CRM Deal pipeline stage.

    Checks actual fieldnames at runtime because different versions of Frappe CRM
    may use 'pipeline_stage' or 'stage'. If neither is found, logs a warning.
    """
    meta = frappe.get_meta("CRM Deal")
    available = {f.fieldname for f in meta.fields}

    if "pipeline_stage" in available:
        frappe.db.set_value("CRM Deal", deal_name, "pipeline_stage", stage_name)
    elif "stage" in available:
        frappe.db.set_value("CRM Deal", deal_name, "stage", stage_name)
    else:
        frappe.log_error(
            f"Cannot update CRM Deal '{deal_name}' stage to '{stage_name}': "
            "neither 'pipeline_stage' nor 'stage' field exists on CRM Deal. "
            "Update frappe_docusign to use the correct field name from the diagnostic endpoint.",
            "frappe_docusign: Stage Update Warning",
        )
