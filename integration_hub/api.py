# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
API endpoints for Google Workspace integration.
"""

import frappe
from frappe import _
from .utils import get_google_credentials, is_google_workspace_enabled


@frappe.whitelist()
def get_google_client_credentials():
	"""Get Google OAuth client credentials for frontend use.
	
	Returns:
		dict: Dictionary with 'client_id' and optionally 'api_key'
	"""
	try:
		credentials = get_google_credentials()
		
		result = {
			"client_id": credentials["client_id"]
		}
		
		# Try to get API key from Google_Workspace Settings
		if is_google_workspace_enabled():
			workspace_settings = frappe.get_single("Google Workspace Settings")
			if hasattr(workspace_settings, 'api_key') and workspace_settings.api_key:
				result["api_key"] = workspace_settings.api_key
		else:
			# Fall back to Google Settings
			if frappe.db.exists("Google Settings"):
				google_settings = frappe.get_single("Google Settings")
				if hasattr(google_settings, 'api_key') and google_settings.api_key:
					result["api_key"] = google_settings.api_key
		
		return result
	except Exception as e:
		frappe.log_error(f"Error getting Google client credentials: {str(e)}", "Google Workspace API")
		frappe.throw(_("Failed to get Google client credentials: {0}").format(str(e)))
