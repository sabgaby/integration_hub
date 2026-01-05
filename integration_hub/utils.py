# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
Utility functions for Google Workspace integration.
Provides centralized credential management for all Google integrations.
"""

import frappe
from frappe import _


def get_google_credentials():
	"""Get Google OAuth credentials from Google_Workspace Settings or fall back to Google Settings.
	
	Returns:
		dict: Dictionary with 'client_id' and 'client_secret'
		
	Raises:
		frappe.ValidationError: If no credentials are configured
	"""
	# Try Google_Workspace Settings first
	if frappe.db.exists("Google Workspace Settings"):
		workspace_settings = frappe.get_single("Google Workspace Settings")
		if workspace_settings.enabled and workspace_settings.client_id and workspace_settings.client_secret:
			return {
				"client_id": workspace_settings.client_id,
				"client_secret": workspace_settings.get_password("client_secret")
			}
	
	# Fall back to Google Settings
	if frappe.db.exists("Google Settings"):
		google_settings = frappe.get_single("Google Settings")
		if google_settings.enable and google_settings.client_id and google_settings.client_secret:
			return {
				"client_id": google_settings.client_id,
				"client_secret": google_settings.get_password("client_secret")
			}
	
	frappe.throw(_("Google OAuth credentials not configured. Please configure Google Workspace Settings or Google Settings."))


def get_google_settings():
	"""Get Google settings object, preferring Google_Workspace Settings.
	
	Returns:
		Document: Google_Workspace Settings or Google Settings document
	"""
	# Try Google_Workspace Settings first
	if frappe.db.exists("Google Workspace Settings"):
		workspace_settings = frappe.get_single("Google Workspace Settings")
		if workspace_settings.enabled:
			return workspace_settings
	
	# Fall back to Google Settings
	if frappe.db.exists("Google Settings"):
		return frappe.get_single("Google Settings")
	
	frappe.throw(_("Google settings not configured. Please configure Google Workspace Settings or Google Settings."))


def is_google_workspace_enabled():
	"""Check if Google_Workspace is enabled and configured.
	
	Returns:
		bool: True if Google_Workspace Settings is enabled and configured
	"""
	if not frappe.db.exists("Google Workspace Settings"):
		return False
	
	try:
		settings = frappe.get_single("Google Workspace Settings")
		return bool(
			settings.enabled 
			and settings.client_id 
			and settings.get_password("client_secret")
		)
	except Exception:
		return False


def get_user_refresh_token(user, service='calendar'):
	"""Get per-user refresh token from User doctype.
	
	Args:
		user: Username
		service: Service name ('calendar', 'drive', etc.) - currently all use google_workspace_refresh_token
		
	Returns:
		str: Refresh token or None if not found
	"""
	try:
		user_doc = frappe.get_doc("User", user)
		if hasattr(user_doc, 'google_workspace_refresh_token'):
			# Use raise_exception=False to return None instead of throwing error if token doesn't exist
			return user_doc.get_password('google_workspace_refresh_token', raise_exception=False)
	except Exception:
		pass
	
	return None


def has_user_refresh_token(user):
	"""Check if user has a Google_Workspace refresh token.
	
	Args:
		user: Username
		
	Returns:
		bool: True if user has refresh token
	"""
	token = get_user_refresh_token(user)
	return bool(token)
