# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
OAuth 2.0 authentication for Google Workspace services.

Provides multi-scope authorization for Drive, Calendar, and Gmail.
Stores refresh tokens per-user for secure, offline access.
"""

import frappe
from frappe import _
from google_auth_oauthlib.flow import Flow
import json
import re

REDIRECT_PATH = '/api/method/integration_hub.oauth.callback'


def get_settings():
	"""Get Google Workspace Settings."""
	return frappe.get_single("Google Workspace Settings")


def get_flow(scopes=None):
	"""Create OAuth flow object.

	Args:
		scopes: List of scopes to request. If None, uses all enabled scopes from settings.
	"""
	settings = get_settings()

	if not settings.enabled:
		frappe.throw(_("Google Workspace integration is not enabled"))

	if not settings.client_id or not settings.client_secret:
		frappe.throw(_("Please configure Client ID and Client Secret in Google Workspace Settings"))

	if scopes is None:
		scopes = settings.get_scopes()

	if not scopes:
		frappe.throw(_("No Google services are enabled in Google Workspace Settings"))

	# Get base URL and convert .local domains to localhost for OAuth
	# Google OAuth doesn't accept .local domains
	base_url = frappe.utils.get_url()

	if '.local' in base_url:
		base_url = re.sub(r'://[^:/]+\.local', '://localhost', base_url)

	redirect_uri = base_url + REDIRECT_PATH

	client_config = {
		"web": {
			"client_id": settings.client_id,
			"client_secret": settings.get_password("client_secret"),
			"auth_uri": "https://accounts.google.com/o/oauth2/auth",
			"token_uri": "https://oauth2.googleapis.com/token",
			"redirect_uris": [redirect_uri]
		}
	}

	flow = Flow.from_client_config(
		client_config,
		scopes=scopes,
		redirect_uri=redirect_uri
	)

	return flow


@frappe.whitelist()
def get_authorization_url(redirect_to=None):
	"""Generate OAuth authorization URL.

	Args:
		redirect_to: Optional URL to redirect to after authorization
	"""
	flow = get_flow()

	# Generate state token for security (CSRF protection)
	state_data = {
		"token": frappe.generate_hash(length=32),
		"user": frappe.session.user,
		"site_url": frappe.utils.get_url(),
		"redirect_to": redirect_to or "/app/google-workspace-settings"
	}
	state = frappe.safe_encode(json.dumps(state_data))

	# Store the state token for verification
	frappe.cache().set_value(
		f"integration_hub_oauth_state_{frappe.session.user}",
		state_data["token"],
		expires_in_sec=600  # 10 minutes
	)

	authorization_url, _ = flow.authorization_url(
		access_type='offline',
		include_granted_scopes='false',
		state=state,
		prompt='consent'  # Force consent to get refresh token
	)

	return authorization_url


@frappe.whitelist(allow_guest=True)
def callback(code=None, state=None, error=None):
	"""Handle OAuth callback from Google.

	NOTE: allow_guest=True is required because Google redirects to localhost
	but the user's session cookie is for the .local domain.
	Security is maintained via state token verification (CSRF protection).
	"""
	if error:
		frappe.log_error(f"OAuth callback error: {error}", "Google Workspace OAuth Error")
		frappe.throw(_("Authorization failed: {0}").format(error))

	if not code:
		frappe.log_error("OAuth callback received without authorization code", "Google Workspace OAuth Error")
		frappe.throw(_("No authorization code received"))

	if not state:
		frappe.log_error("OAuth callback received without state parameter", "Google Workspace OAuth Error")
		frappe.throw(_("Missing state parameter. Please try again."))

	# Parse the state
	try:
		state_data = json.loads(frappe.safe_decode(state))
		state_token = state_data.get("token")
		state_user = state_data.get("user")
		state_site_url = state_data.get("site_url", frappe.utils.get_url())
		redirect_to = state_data.get("redirect_to", "/app/google-workspace-settings")
	except (json.JSONDecodeError, TypeError):
		frappe.log_error(f"Invalid state format: {state[:100]}", "Google Workspace OAuth Error")
		frappe.throw(_("Invalid state parameter format. Please try again."))

	if not state_user or not state_token:
		frappe.log_error("OAuth state missing user or token", "Google Workspace OAuth Error")
		frappe.throw(_("Invalid state parameter. Please try again."))

	# Verify state token (CSRF protection)
	# Check both integration_hub state key and relay mailbox state key
	mailbox_id = state_data.get("mailbox_id")
	state_key = None
	cached_state = None

	if mailbox_id:
		# This is a Relay mailbox OAuth flow
		state_key = f"relay_mailbox_oauth_state_{mailbox_id}"
		cached_state = frappe.cache().get_value(state_key)

	if not cached_state:
		# Try the integration_hub state key
		state_key = f"integration_hub_oauth_state_{state_user}"
		cached_state = frappe.cache().get_value(state_key)

	if not cached_state:
		frappe.log_error(f"OAuth state not found for user {state_user}", "Google Workspace OAuth Error")
		frappe.throw(_("State token expired or not found. Please try authorizing again."))

	if state_token != cached_state:
		frappe.log_error(f"OAuth state mismatch for user {state_user}", "Google Workspace OAuth Security")
		frappe.throw(_("Invalid state parameter. Possible CSRF attack. Please try again."))

	# Clear state after use (one-time use)
	frappe.cache().delete_value(state_key)

	oauth_user = state_user
	flow = get_flow()

	# Fetch token
	try:
		flow.fetch_token(code=code)
	except Exception as e:
		frappe.log_error(f"Token fetch failed: {str(e)}", "Google Workspace OAuth Error")
		frappe.throw(_("Authorization failed: {0}").format(str(e)))

	# Get credentials
	credentials = flow.credentials

	if not credentials or not credentials.refresh_token:
		frappe.log_error("OAuth callback: No refresh token received", "Google Workspace OAuth Error")
		frappe.throw(_("Failed to get refresh token. Please try authorizing again."))

	# Save refresh token to user
	try:
		# Verify custom field exists
		if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'google_workspace_refresh_token'}):
			frappe.throw(_("Google Workspace integration not properly installed. Please run setup."))

		if not frappe.db.exists("User", oauth_user):
			frappe.throw(_("User not found. Please try again."))

		user = frappe.get_doc("User", oauth_user)
		user.google_workspace_refresh_token = credentials.refresh_token

		if hasattr(user, 'google_workspace_status'):
			user.google_workspace_status = "Connected"

		try:
			user.save(ignore_permissions=True)
			frappe.db.commit()
		except Exception as save_error:
			# Fallback: Use db.set_value
			frappe.log_error(f"Permission error saving User: {str(save_error)}", "Google Workspace OAuth")
			frappe.db.set_value("User", oauth_user, "google_workspace_refresh_token", credentials.refresh_token, update_modified=False)
			if hasattr(user, 'google_workspace_status'):
				frappe.db.set_value("User", oauth_user, "google_workspace_status", "Connected", update_modified=False)
			frappe.db.commit()

		frappe.log_error(f"Successfully authorized Google Workspace for user {oauth_user}", "Google Workspace OAuth Success")

		# Auto-refresh shared drives if Drive is enabled
		try:
			settings = get_settings()
			if settings.enable_drive:
				from integration_hub.services.drive import GoogleDriveService
				service = GoogleDriveService(user=oauth_user)
				drives = service.list_shared_drives()

				existing_ids = {d.drive_id for d in settings.shared_drives}
				added = 0
				for drive in drives:
					if drive['drive_id'] not in existing_ids:
						settings.append('shared_drives', {
							'drive_id': drive['drive_id'],
							'drive_name': drive['name'],
							'enabled': 1
						})
						added += 1
				if added > 0:
					settings.save(ignore_permissions=True)
					frappe.db.commit()
		except Exception as e:
			frappe.log_error(f"Failed to auto-refresh shared drives: {str(e)}", "Google Workspace OAuth")

	except Exception as e:
		frappe.log_error(f"Error saving refresh token for user {oauth_user}: {str(e)}", "Google Workspace OAuth")
		frappe.throw(_("Failed to save authorization: {0}").format(str(e)))

	# Redirect back to the original site
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = f"{state_site_url}{redirect_to}?authorized=1"


@frappe.whitelist()
def disconnect():
	"""Disconnect Google Workspace authorization for current user."""
	try:
		user = frappe.get_doc("User", frappe.session.user)

		if hasattr(user, 'google_workspace_refresh_token'):
			try:
				existing_token = user.get_password('google_workspace_refresh_token', raise_exception=False)
				if existing_token:
					user.set_password('google_workspace_refresh_token', '')
			except Exception:
				pass

		if hasattr(user, 'google_workspace_status'):
			user.google_workspace_status = "Not Connected"

		user.save(ignore_permissions=True)
		frappe.db.commit()

		frappe.log_error(f"Google Workspace disconnected for user {frappe.session.user}", "Google Workspace OAuth")

		return {
			"message": "Disconnected successfully",
			"status": "Not Connected"
		}
	except Exception as e:
		frappe.log_error(f"Error disconnecting: {str(e)}", "Google Workspace OAuth")
		frappe.throw(_("Failed to disconnect: {0}").format(str(e)))


@frappe.whitelist()
def get_connection_status():
	"""Get current user's Google Workspace connection status."""
	try:
		user = frappe.get_doc("User", frappe.session.user)
		is_connected = False

		if hasattr(user, 'google_workspace_refresh_token'):
			try:
				token = user.get_password('google_workspace_refresh_token', raise_exception=False)
				is_connected = bool(token)
			except Exception:
				pass

		return {
			"is_connected": is_connected,
			"status": user.get('google_workspace_status', 'Not Connected') if hasattr(user, 'google_workspace_status') else 'Not Connected'
		}
	except Exception:
		return {"is_connected": False, "status": "Not Connected"}
