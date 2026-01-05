import frappe
from frappe import _
from google_auth_oauthlib.flow import Flow

# Request full Drive scope to support:
# - Reading files (current feature)
# - Renaming files (future feature)
# - Uploading files (future feature)
# - Creating files (future feature)
SCOPES = ['https://www.googleapis.com/auth/drive']
REDIRECT_PATH = '/api/method/integration_hub.features.smart_links.oauth.callback'


def get_flow():
    """Create OAuth flow object."""
    # Try to use Integration_Hub credentials first
    try:
        from integration_hub.utils import get_google_credentials, is_google_workspace_enabled
        if is_google_workspace_enabled():
            credentials = get_google_credentials()
            client_id = credentials["client_id"]
            client_secret = credentials["client_secret"]
        else:
            raise ImportError("Google_Workspace not enabled")
    except (ImportError, Exception):
        # Fall back to Smart Links Settings
        settings = frappe.get_single("Smart Links Settings")
        if not settings.client_id or not settings.client_secret:
            frappe.throw(_("Please configure Google Workspace Settings or Smart Links Settings with Client ID and Client Secret"))
        client_id = settings.client_id
        client_secret = settings.get_password("client_secret")

    # Get base URL and convert .local domains to localhost for OAuth
    # Google OAuth doesn't accept .local domains
    base_url = frappe.utils.get_url()

    # Convert any .local domain to localhost
    # Example: http://site1.local:8000 -> http://localhost:8000
    if '.local' in base_url:
        import re
        # Replace domain.local:port with localhost:port
        base_url = re.sub(r'://[^:/]+\.local', '://localhost', base_url)

    redirect_uri = base_url + REDIRECT_PATH

    client_config = {
        "web": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": [redirect_uri]
        }
    }

    flow = Flow.from_client_config(
        client_config,
        scopes=SCOPES,
        redirect_uri=redirect_uri
    )

    return flow


@frappe.whitelist()
def get_authorization_url():
    """Generate OAuth authorization URL."""
    import json

    flow = get_flow()

    # Generate state token for security (CSRF protection)
    # Include the user and original site URL in the state so we can:
    # 1. Identify the user in the callback (session may be Guest due to domain mismatch)
    # 2. Redirect back to the correct site after authorization
    state_data = {
        "token": frappe.generate_hash(length=32),
        "user": frappe.session.user,
        "site_url": frappe.utils.get_url()  # Original site URL (e.g., http://site1.local:8000)
    }
    state = frappe.safe_encode(json.dumps(state_data))

    # Store the state token for verification
    frappe.cache().set_value(
        f"smart_links_oauth_state_{frappe.session.user}",
        state_data["token"],
        expires_in_sec=600  # 10 minutes
    )

    authorization_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='false',  # Only request the scopes we need
        state=state,
        prompt='consent'  # Force consent to get refresh token
    )

    return authorization_url


@frappe.whitelist(allow_guest=True)
def callback(code=None, state=None, error=None):
    """
    Handle OAuth callback from Google.

    NOTE: allow_guest=True is required because Google redirects to localhost
    but the user's session cookie is for the .local domain.
    Security is maintained via state token verification (CSRF protection).
    """
    import frappe.utils.logger

    if error:
        frappe.log_error(
            f"OAuth callback error: {error}",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("Authorization failed: {0}").format(error))

    if not code:
        frappe.log_error(
            "OAuth callback received without authorization code",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("No authorization code received"))

    if not state:
        frappe.log_error(
            "OAuth callback received without state parameter",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("Missing state parameter. Please try again."))

    # Parse the state to get user info, token, and original site URL
    # State is JSON with {token, user, site_url} encoded
    import json
    try:
        state_data = json.loads(frappe.safe_decode(state))
        state_token = state_data.get("token")
        state_user = state_data.get("user")
        state_site_url = state_data.get("site_url", frappe.utils.get_url())
    except (json.JSONDecodeError, TypeError):
        frappe.log_error(
            f"Invalid state format: {state[:100]}",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("Invalid state parameter format. Please try again."))

    if not state_user or not state_token:
        frappe.log_error(
            "OAuth state missing user or token",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("Invalid state parameter. Please try again."))

    # Verify state token (CSRF protection)
    state_key = f"smart_links_oauth_state_{state_user}"
    cached_state = frappe.cache().get_value(state_key)

    if not cached_state:
        frappe.log_error(
            f"OAuth state not found for user {state_user}",
            "Smart Links OAuth Error"
        )
        frappe.throw(_("State token expired or not found. Please try authorizing again."))

    if state_token != cached_state:
        frappe.log_error(
            f"OAuth state mismatch for user {state_user}",
            "Smart Links OAuth Security"
        )
        frappe.throw(_("Invalid state parameter. Possible CSRF attack. Please try again."))

    # Clear state after use (one-time use)
    frappe.cache().delete_value(state_key)

    # Use the user from state (since session might be Guest due to domain mismatch)
    oauth_user = state_user

    flow = get_flow()

    # Fetch token
    try:
        flow.fetch_token(code=code)
    except Exception as e:
        frappe.throw(_("Authorization failed: {0}").format(str(e)))

    # Get credentials
    try:
        credentials = flow.credentials
    except Exception as e:
        frappe.log_error(
            f"Error getting credentials: {str(e)}",
            "Smart Links OAuth"
        )
        frappe.throw(_("Failed to get credentials. Please try again."))

    if not credentials or not credentials.refresh_token:
        frappe.log_error(
            "OAuth callback: No refresh token received",
            "Smart Links OAuth"
        )
        frappe.throw(_("Failed to get refresh token. Please try authorizing again."))

    # Save refresh token to the user who initiated the OAuth flow
    # (identified from state, not session, due to domain mismatch)
    try:
        # Check if custom field exists - if not, it should have been created during install
        if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'gdrive_refresh_token'}):
            frappe.log_error(
                "Custom field gdrive_refresh_token not found on User doctype. Please run after_install hook.",
                "Smart Links OAuth Error"
            )
            frappe.throw(_("Smart Links integration not properly installed. Please contact your administrator."))

        # Verify the user exists
        if not frappe.db.exists("User", oauth_user):
            frappe.log_error(
                f"User {oauth_user} not found",
                "Smart Links OAuth Error"
            )
            frappe.throw(_("User not found. Please try again."))

        # Use direct assignment + save with ignore_permissions
        user = frappe.get_doc("User", oauth_user)

        # Try to save to google_workspace_refresh_token first (if Integration_Hub is enabled)
        try:
            from integration_hub.utils import is_google_workspace_enabled
            if is_google_workspace_enabled():
                if hasattr(user, 'google_workspace_refresh_token'):
                    user.google_workspace_refresh_token = credentials.refresh_token
                    if hasattr(user, 'google_workspace_status'):
                        user.google_workspace_status = "Connected"
                else:
                    # Fall back to gdrive_refresh_token if google_workspace_refresh_token doesn't exist
                    if hasattr(user, 'gdrive_refresh_token'):
                        user.gdrive_refresh_token = credentials.refresh_token
                        if hasattr(user, 'gdrive_authorization_status'):
                            user.gdrive_authorization_status = "Connected"
            else:
                # Google_Workspace not enabled, use gdrive_refresh_token
                if hasattr(user, 'gdrive_refresh_token'):
                    user.gdrive_refresh_token = credentials.refresh_token
                    if hasattr(user, 'gdrive_authorization_status'):
                        user.gdrive_authorization_status = "Connected"
        except (ImportError, Exception):
            # Fall back to gdrive_refresh_token if Google_Workspace import fails
            if hasattr(user, 'gdrive_refresh_token'):
                user.gdrive_refresh_token = credentials.refresh_token
                if hasattr(user, 'gdrive_authorization_status'):
                    user.gdrive_authorization_status = "Connected"

        # Save with ignore_permissions
        try:
            user.save(ignore_permissions=True)
            frappe.db.commit()
        except frappe.PermissionError as perm_error:
            # If permission error, log it and try db.set_value as fallback
            frappe.log_error(
                f"Permission error saving User (trying fallback): {str(perm_error)}",
                "Smart Links OAuth Error"
            )
            # Fallback: Use db.set_value which completely bypasses permissions
            try:
                from integration_hub.utils import is_google_workspace_enabled
                if is_google_workspace_enabled() and hasattr(user, 'google_workspace_refresh_token'):
                    frappe.db.set_value(
                        "User",
                        oauth_user,
                        "google_workspace_refresh_token",
                        credentials.refresh_token,
                        update_modified=False
                    )
                    if hasattr(user, 'google_workspace_status'):
                        frappe.db.set_value(
                            "User",
                            oauth_user,
                            "google_workspace_status",
                            "Connected",
                            update_modified=False
                        )
                else:
                    if hasattr(user, 'gdrive_refresh_token'):
                        frappe.db.set_value(
                            "User",
                            oauth_user,
                            "gdrive_refresh_token",
                            credentials.refresh_token,
                            update_modified=False
                        )
                        if hasattr(user, 'gdrive_authorization_status'):
                            frappe.db.set_value(
                                "User",
                                oauth_user,
                                "gdrive_authorization_status",
                                "Connected",
                                update_modified=False
                            )
            except (ImportError, Exception):
                if hasattr(user, 'gdrive_refresh_token'):
                    frappe.db.set_value(
                        "User",
                        oauth_user,
                        "gdrive_refresh_token",
                        credentials.refresh_token,
                        update_modified=False
                    )
            frappe.db.commit()
        except Exception as save_error:
            # Log any other error
            frappe.log_error(
                f"Error saving User token: {str(save_error)}\nUser: {oauth_user}",
                "Smart Links OAuth Error"
            )
            raise

        # Verify it was saved
        saved_user = frappe.get_doc("User", oauth_user)
        # Check both token fields
        token_saved = False
        try:
            from integration_hub.utils import get_user_refresh_token, is_google_workspace_enabled
            if is_google_workspace_enabled():
                token_saved = bool(get_user_refresh_token(oauth_user))
        except (ImportError, Exception):
            pass
        
        if not token_saved:
            if hasattr(saved_user, 'gdrive_refresh_token'):
                token_saved = bool(saved_user.get_password('gdrive_refresh_token', raise_exception=False))
        
        if not token_saved:
            frappe.throw(_("Refresh token was not saved. Please try again."))

        frappe.log_error(
            f"Successfully authorized Google Drive for user {oauth_user}",
            "Smart Links OAuth Success"
        )

        # Auto-refresh shared drives for this user after successful authorization
        # Note: This may fail if the user is Guest due to domain mismatch,
        # but the user can manually refresh after redirect
        try:
            from .google_drive import GoogleDriveService
            service = GoogleDriveService(user=oauth_user)
            drives = service.list_shared_drives()

            # Try to update Google_Workspace Settings shared drives first
            try:
                from integration_hub.utils import is_google_workspace_enabled
                if is_google_workspace_enabled():
                    workspace_settings = frappe.get_single("Google Workspace Settings")
                    if hasattr(workspace_settings, 'shared_drives'):
                        existing_ids = {d.drive_id for d in workspace_settings.shared_drives}
                        added = 0
                        for drive in drives:
                            if drive['drive_id'] not in existing_ids:
                                workspace_settings.append('shared_drives', {
                                    'drive_id': drive['drive_id'],
                                    'drive_name': drive['name'],
                                    'enabled': 1
                                })
                                added += 1
                        if added > 0:
                            workspace_settings.save(ignore_permissions=True)
                            frappe.db.commit()
            except (ImportError, Exception):
                pass
            
            # Also update Smart Links Settings shared drives for backward compatibility
            settings = frappe.get_single("Smart Links Settings")
            if hasattr(settings, 'shared_drives'):
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

            frappe.log_error(
                f"Auto-refreshed {len(drives)} Shared Drives for user {oauth_user}",
                "Smart Links OAuth"
            )
        except Exception as e:
            # Don't fail authorization if shared drives refresh fails
            frappe.log_error(
                f"Failed to auto-refresh shared drives: {str(e)}",
                "Smart Links OAuth"
            )

    except Exception as e:
        frappe.log_error(
            f"Error saving refresh token for user {oauth_user}: {str(e)}",
            "Smart Links OAuth"
        )
        frappe.throw(_("Failed to save authorization: {0}").format(str(e)))

    # Redirect back to the original site (not localhost)
    # Use the site URL from state to redirect to the correct domain
    # (user's browser will have cookies for the original domain, e.g., site1.local)
    frappe.local.response["type"] = "redirect"
    frappe.local.response["location"] = f"{state_site_url}/app/smart-links-settings?authorized=1"


@frappe.whitelist()
def disconnect():
    """Disconnect Google Drive authorization for current user."""
    try:
        user = frappe.get_doc("User", frappe.session.user)

        # Clear refresh token for this user - try Google_Workspace first
        try:
            from integration_hub.utils import is_google_workspace_enabled
            if is_google_workspace_enabled() and hasattr(user, 'google_workspace_refresh_token'):
                existing_token = user.get_password('google_workspace_refresh_token', raise_exception=False)
                if existing_token:
                    user.set_password('google_workspace_refresh_token', '')
                if hasattr(user, 'google_workspace_status'):
                    user.google_workspace_status = "Not Connected"
        except (ImportError, Exception):
            pass
        
        # Also clear old gdrive_refresh_token for backward compatibility
        if hasattr(user, 'gdrive_refresh_token'):
            try:
                existing_token = user.get_password('gdrive_refresh_token')
                if existing_token:
                    user.set_password('gdrive_refresh_token', '')
            except Exception:
                pass
            if hasattr(user, 'gdrive_authorization_status'):
                user.gdrive_authorization_status = "Not Connected"

        user.save(ignore_permissions=True)
        frappe.db.commit()

        frappe.log_error(
            f"Google Drive disconnected for user {frappe.session.user}",
            "Smart Links OAuth"
        )

        return {
            "message": "Disconnected successfully",
            "status": "Not Connected"
        }
    except Exception as e:
        frappe.log_error(
            f"Error disconnecting: {str(e)}",
            "Smart Links OAuth"
        )
        frappe.throw(_("Failed to disconnect: {0}").format(str(e)))
