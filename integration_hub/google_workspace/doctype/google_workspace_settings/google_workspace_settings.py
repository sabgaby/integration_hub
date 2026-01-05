# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class GoogleWorkspaceSettings(Document):
	def validate(self):
		if self.enabled:
			if not self.client_id:
				frappe.throw("Client ID is required when enabled")
			if not self.client_secret:
				frappe.throw("Client Secret is required when enabled")

	def get_scopes(self):
		"""Return list of OAuth scopes based on enabled services."""
		scopes = []
		if self.enable_drive:
			scopes.append("https://www.googleapis.com/auth/drive")
		if self.enable_calendar:
			scopes.append("https://www.googleapis.com/auth/calendar")
		if self.enable_gmail:
			scopes.append("https://mail.google.com/")
			# Add Admin Directory API scopes for Google Groups support
			# These are needed for listing groups and syncing members
			scopes.append("https://www.googleapis.com/auth/admin.directory.group.readonly")
			scopes.append("https://www.googleapis.com/auth/admin.directory.group.member.readonly")
		return scopes
