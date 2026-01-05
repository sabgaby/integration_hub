import frappe
from frappe import _
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time
from functools import wraps

# Must match the scope in oauth.py
SCOPES = ['https://www.googleapis.com/auth/drive']

# Retry configuration for Google API calls
MAX_RETRIES = 3
INITIAL_BACKOFF = 1  # seconds


def retry_with_backoff(max_retries=MAX_RETRIES, initial_backoff=INITIAL_BACKOFF):
    """
    Decorator for retrying Google API calls with exponential backoff.

    Handles:
    - Rate limit errors (429)
    - Transient errors (500, 503)
    - Network errors
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            backoff = initial_backoff
            last_exception = None

            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except HttpError as e:
                    last_exception = e
                    status = e.resp.status if hasattr(e, 'resp') else None

                    # Don't retry on client errors (4xx) except rate limits
                    if status and 400 <= status < 500 and status != 429:
                        raise

                    # Retry on rate limits (429) and server errors (5xx)
                    if status in (429, 500, 503) and attempt < max_retries - 1:
                        frappe.log_error(
                            f"Google API error (attempt {attempt + 1}/{max_retries}): {str(e)}",
                            "Smart Links API Retry"
                        )
                        time.sleep(backoff)
                        backoff *= 2
                        continue

                    raise
                except Exception as e:
                    raise

            raise last_exception
        return wrapper
    return decorator


class GoogleDriveService:
    """Google Drive API wrapper.

    Uses per-user authorization - each user must authorize their own Google account.
    This ensures users can only access files they have permission to view.
    """

    def __init__(self, user=None):
        """
        Initialize Google Drive service for a specific user.

        Args:
            user: Username (defaults to current session user)
        """
        # Check if Smart Links is enabled
        self.settings = frappe.get_single("Smart Links Settings")
        if not self.settings.enabled:
            frappe.throw(_("Smart Links integration is not enabled"))

        self.user = user or frappe.session.user

        # Get refresh token from user's account - try Google_Workspace first, then fall back to gdrive_refresh_token
        user_doc = frappe.get_doc("User", self.user)
        refresh_token = None
        
        # Try Google_Workspace token first
        try:
            from integration_hub.utils import get_user_refresh_token, is_google_workspace_enabled
            if is_google_workspace_enabled():
                refresh_token = get_user_refresh_token(self.user)
        except (ImportError, Exception):
            pass
        
        # Fall back to old gdrive_refresh_token
        if not refresh_token:
            if hasattr(user_doc, 'gdrive_refresh_token'):
                refresh_token = user_doc.get_password('gdrive_refresh_token', raise_exception=False)
        
        if not refresh_token:
            frappe.throw(_("Google Drive not authorized for your account. Please authorize in settings."))

        self.service = self._build_service()

    def _build_service(self):
        """
        Build the Google Drive API service using current user's refresh token.

        Raises:
            frappe.ValidationError: If credentials are invalid or missing
        """
        try:
            # Get refresh token - try Google_Workspace first, then fall back to gdrive_refresh_token
            refresh_token = None
            try:
                from integration_hub.utils import get_user_refresh_token, is_google_workspace_enabled
                if is_google_workspace_enabled():
                    refresh_token = get_user_refresh_token(self.user)
            except (ImportError, Exception):
                pass
            
            if not refresh_token:
                user_doc = frappe.get_doc("User", self.user)
                if hasattr(user_doc, 'gdrive_refresh_token'):
                    refresh_token = user_doc.get_password('gdrive_refresh_token', raise_exception=False)
            
            if not refresh_token:
                frappe.throw(_("Google Drive not authorized. Please authorize in settings."))

            # Get credentials from Google_Workspace or Smart Links Settings
            try:
                from integration_hub.utils import get_google_credentials, is_google_workspace_enabled
                if is_google_workspace_enabled():
                    credentials_dict = get_google_credentials()
                    client_id = credentials_dict["client_id"]
                    client_secret = credentials_dict["client_secret"]
                else:
                    raise ImportError("Google_Workspace not enabled")
            except (ImportError, Exception):
                # Fall back to Smart Links Settings
                client_id = self.settings.client_id
                client_secret = self.settings.get_password('client_secret')

            credentials = Credentials(
                token=None,
                refresh_token=refresh_token,
                token_uri='https://oauth2.googleapis.com/token',
                client_id=client_id,
                client_secret=client_secret,
                scopes=SCOPES
            )

            # Refresh credentials
            try:
                from google.auth.transport.requests import Request
                request = Request()
                credentials.refresh(request)
            except Exception as e:
                frappe.log_error(
                    f"Failed to refresh Google credentials: {str(e)}",
                    "Smart Links Auth"
                )
                frappe.throw(_("Google Drive authorization expired. Please re-authorize in settings."))

            # Store credentials for access token retrieval
            self._credentials = credentials
            return build('drive', 'v3', credentials=credentials)
        except Exception as e:
            if isinstance(e, frappe.ValidationError):
                raise
            frappe.log_error(
                f"Error building Google Drive service: {str(e)}",
                "Smart Links Service"
            )
            frappe.throw(_("Error initializing Google Drive service: {0}").format(str(e)))

    def get_access_token(self) -> str:
        """
        Get the current access token for the Google Picker API.

        Returns:
            str: The current access token

        Raises:
            frappe.ValidationError: If token cannot be obtained
        """
        if hasattr(self, '_credentials') and self._credentials:
            if not self._credentials.valid:
                try:
                    from google.auth.transport.requests import Request
                    self._credentials.refresh(Request())
                except Exception as e:
                    frappe.throw(_("Failed to refresh access token: {0}").format(str(e)))

            return self._credentials.token
        return None

    @retry_with_backoff()
    def get_file_metadata(self, file_id: str) -> dict:
        """
        Fetch metadata for a file or folder.
        Works with both My Drive and Shared Drives.

        Args:
            file_id: Google Drive file ID

        Returns:
            dict with file metadata

        Raises:
            frappe.ValidationError: If file not found or no permission
        """
        try:
            file = self.service.files().get(
                fileId=file_id,
                supportsAllDrives=True,
                fields='id, name, mimeType, size, webViewLink, iconLink, thumbnailLink, driveId'
            ).execute()

            return {
                'file_id': file['id'],
                'file_name': file['name'],
                'mime_type': file['mimeType'],
                'file_type': self._get_file_type(file['mimeType']),
                'file_size': int(file.get('size', 0)),
                'web_view_link': file.get('webViewLink', ''),
                'icon_link': file.get('iconLink', ''),
                'thumbnail_link': file.get('thumbnailLink', ''),
                'drive_id': file.get('driveId')
            }

        except HttpError as e:
            status = e.resp.status if hasattr(e, 'resp') else None

            if status == 404:
                frappe.log_error(f"File not found: {file_id}", "Smart Links API")
                frappe.throw(_("File not found or not accessible"))
            elif status == 403:
                frappe.log_error(f"No permission to access file: {file_id}", "Smart Links API")
                frappe.throw(_("No permission to access this file"))
            elif status == 401:
                frappe.log_error(f"Authentication failed for file: {file_id}", "Smart Links API")
                frappe.throw(_("Authentication failed. Please re-authorize Google Drive."))
            else:
                frappe.log_error(f"Google Drive API error ({status}): {str(e)}", "Smart Links API")
                frappe.throw(_("Google Drive API error: {0}").format(str(e)))
        except Exception as e:
            frappe.log_error(f"Unexpected error fetching file metadata: {str(e)}", "Smart Links API")
            frappe.throw(_("Error fetching file metadata: {0}").format(str(e)))

    def _get_file_type(self, mime_type: str) -> str:
        """Convert MIME type to simplified file type."""
        mime_map = {
            'application/vnd.google-apps.folder': 'Folder',
            'application/vnd.google-apps.document': 'Document',
            'application/vnd.google-apps.spreadsheet': 'Spreadsheet',
            'application/vnd.google-apps.presentation': 'Presentation',
            'application/pdf': 'PDF',
        }

        if mime_type in mime_map:
            return mime_map[mime_type]
        if mime_type.startswith('image/'):
            return 'Image'
        return 'File'
