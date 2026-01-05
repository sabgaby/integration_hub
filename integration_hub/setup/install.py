# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def after_install():
	"""Run after app installation."""
	create_user_custom_fields()
	# Setup Smart Links feature
	try:
		from integration_hub.features.smart_links.setup import setup_smart_links
		setup_smart_links()
	except Exception as e:
		# Log error but don't fail installation
		frappe.log_error(f"Error setting up Smart Links: {str(e)}", "Integration Hub Setup")


def create_user_custom_fields():
	"""Create custom fields on User doctype for storing Google Workspace credentials."""
	custom_fields_to_create = {}

	# Add google_workspace_refresh_token field
	if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'google_workspace_refresh_token'}):
		custom_fields_to_create['User'] = custom_fields_to_create.get('User', []) + [{
			'fieldname': 'google_workspace_refresh_token',
			'fieldtype': 'Password',
			'label': 'Google Workspace Refresh Token',
			'hidden': 1,
			'insert_after': 'api_key',
			'description': 'Stores per-user Google Workspace OAuth refresh token'
		}]

	# Add google_workspace_status field
	if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'google_workspace_status'}):
		custom_fields_to_create['User'] = custom_fields_to_create.get('User', []) + [{
			'fieldname': 'google_workspace_status',
			'fieldtype': 'Data',
			'label': 'Google Workspace Status',
			'read_only': 1,
			'default': 'Not Connected',
			'insert_after': 'google_workspace_refresh_token',
			'description': 'Current authorization status for Google Workspace'
		}]

	if custom_fields_to_create:
		create_custom_fields(custom_fields_to_create)
		frappe.db.commit()


def before_uninstall():
	"""Clean up before uninstall."""
	# Remove User custom fields
	for fieldname in ['google_workspace_refresh_token', 'google_workspace_status']:
		cf_name = f"User-{fieldname}"
		if frappe.db.exists('Custom Field', cf_name):
			frappe.delete_doc('Custom Field', cf_name, ignore_permissions=True)
	
	# Clean up Smart Links
	try:
		from integration_hub.features.smart_links.setup import cleanup_smart_links
		cleanup_smart_links()
	except Exception as e:
		frappe.log_error(f"Error cleaning up Smart Links: {str(e)}", "Integration Hub Uninstall")
	
	frappe.db.commit()
