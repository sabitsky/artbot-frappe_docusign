"""
Shared helpers used by both envelope.py and webhook.py.
"""
import frappe


def update_deal_stage(deal_name: str, stage_name: str) -> None:
    """
    Update the CRM Deal status (pipeline stage).

    Frappe CRM v2 uses the field 'status' (Link → CRM Deal Status).
    The stage_name must match the name of an existing CRM Deal Status record.
    """
    frappe.db.set_value("CRM Deal", deal_name, "status", stage_name)
