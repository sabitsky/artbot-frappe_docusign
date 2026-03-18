/**
 * frappe_docusign — DocuSign buttons for CRM Deal form
 *
 * Loaded in two contexts:
 *   1. Frappe Desk  — via doctype_js in hooks.py
 *   2. Frappe CRM   — via CRM Form Script record created by after_install / after_migrate
 *
 * Frappe CRM v2: deal status field is 'status' (Link → CRM Deal Status).
 * Button appears when status === SEND_TRIGGER_STATUS and no envelope exists yet.
 *
 * Email candidates : email, contact_email, customer_email
 * Name candidates  : lead_name, contact_name, customer_name
 */

// Stage at which the "Send for Signing" button appears.
// ArtBot pipeline: button shows on "New" — ops fills service_type + preferred_language,
// then sends the contract manually via this button.
var SEND_TRIGGER_STATUS = "New";

frappe.ui.form.on("CRM Deal", {
	refresh(frm) {
		_addDocuSignButtons(frm);
	},
});

function _addDocuSignButtons(frm) {
	var currentStage = frm.doc.status;
	var hasEnvelope = Boolean(frm.doc.docusign_envelope_id);
	var terminalStatuses = ["Completed", "Declined", "Voided"];

	// "Send for Signing" — only on Proposal/Quotation stage and before any envelope is created
	if (currentStage === SEND_TRIGGER_STATUS && !hasEnvelope) {
		frm.add_custom_button(
			__("Send for Signing"),
			function () {
				_showSendDialog(frm);
			},
			__("DocuSign")
		);
	}

	// "Check Status" — when an envelope exists but is not in a terminal state
	if (hasEnvelope && !terminalStatuses.includes(frm.doc.docusign_status)) {
		frm.add_custom_button(
			__("Check Status"),
			function () {
				frappe.call({
					method: "frappe_docusign.api.envelope.check_status",
					args: { deal: frm.doc.name },
					freeze: true,
					freeze_message: __("Checking status with DocuSign…"),
					callback: function () {
						frm.reload_doc();
					},
				});
			},
			__("DocuSign")
		);
	}
}

function _showSendDialog(frm) {
	const emailField = _detectField(frm, ["email", "contact_email", "customer_email"]);
	const nameField = _detectField(frm, ["lead_name", "contact_name", "customer_name"]);

	const dialog = new frappe.ui.Dialog({
		title: __("Send for DocuSign Signing"),
		fields: [
			{
				fieldname: "signer_name",
				fieldtype: "Data",
				label: __("Client Name"),
				default: frm.doc[nameField] || "",
				reqd: 1,
			},
			{
				fieldname: "signer_email",
				fieldtype: "Data",
				label: __("Client Email"),
				options: "Email",
				default: frm.doc[emailField] || "",
				reqd: 1,
			},
			{
				fieldname: "section_docs",
				fieldtype: "Section Break",
				label: __("Documents to Sign"),
			},
			{
				// Table allows attaching multiple files in one send
				fieldname: "documents",
				fieldtype: "Table",
				label: __("Documents"),
				fields: [
					{
						fieldname: "file",
						fieldtype: "Attach",
						label: __("File"),
						in_list_view: 1,
						reqd: 1,
					},
				],
			},
		],
		primary_action_label: __("Send via DocuSign"),
		primary_action: function (values) {
			const files = (values.documents || [])
				.map(function (row) { return row.file; })
				.filter(Boolean);

			if (files.length === 0) {
				frappe.msgprint(__("Please attach at least one document."));
				return;
			}

			frappe.call({
				method: "frappe_docusign.api.envelope.send_envelope",
				args: {
					deal: frm.doc.name,
					documents: files,
					signer_name: values.signer_name,
					signer_email: values.signer_email,
				},
				freeze: true,
				freeze_message: __("Sending to DocuSign…"),
				callback: function () {
					dialog.hide();
					frappe.show_alert({
						message: __("Documents sent for signing via DocuSign!"),
						indicator: "green",
					});
					frm.reload_doc();
				},
			});
			// On error Frappe shows the ValidationError message natively.
		},
	});

	dialog.show();
}

/**
 * Return the first fieldname from candidates that exists on this DocType.
 * Falls back to candidates[0] if none found (safe default).
 */
function _detectField(frm, candidates) {
	const existing = new Set(
		(frm.meta.fields || []).map(function (f) { return f.fieldname; })
	);
	for (var i = 0; i < candidates.length; i++) {
		if (existing.has(candidates[i])) return candidates[i];
	}
	return candidates[0];
}
