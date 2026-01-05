# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
Google Drive API service wrapper.

Provides file access, Shared Drives support, and Google Picker integration.
"""

import frappe
from frappe import _
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import time
from functools import wraps

SCOPES = ['https://www.googleapis.com/auth/drive']

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF = 1


def retry_with_backoff(max_retries=MAX_RETRIES, initial_backoff=INITIAL_BACKOFF):
	"""Decorator for retrying Google API calls with exponential backoff."""
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

					if status and 400 <= status < 500 and status != 429:
						raise

					if status in (429, 500, 503) and attempt < max_retries - 1:
						frappe.log_error(
							f"Google API error (attempt {attempt + 1}/{max_retries}): {str(e)}",
							"Google Workspace API Retry"
						)
						time.sleep(backoff)
						backoff *= 2
						continue

					raise

			raise last_exception
		return wrapper
	return decorator


class GoogleDriveService:
	"""Google Drive API wrapper with per-user authorization."""

	def __init__(self, user=None):
		"""Initialize Google Drive service for a specific user."""
		self.settings = frappe.get_single("Google Workspace Settings")

		if not self.settings.enabled:
			frappe.throw(_("Google Workspace integration is not enabled"))

		if not self.settings.enable_drive:
			frappe.throw(_("Google Drive is not enabled in Google Workspace Settings"))

		self.user = user or frappe.session.user

		user_doc = frappe.get_doc("User", self.user)
		if not hasattr(user_doc, 'google_workspace_refresh_token'):
			frappe.throw(_("Google Workspace not authorized for your account. Please authorize in settings."))

		refresh_token = user_doc.get_password('google_workspace_refresh_token', raise_exception=False)

		if not refresh_token:
			frappe.throw(_("Google Workspace not authorized for your account. Please authorize in settings."))

		self.service = self._build_service(refresh_token)

	def _build_service(self, refresh_token):
		"""Build the Google Drive API service."""
		try:
			credentials = Credentials(
				token=None,
				refresh_token=refresh_token,
				token_uri='https://oauth2.googleapis.com/token',
				client_id=self.settings.client_id,
				client_secret=self.settings.get_password('client_secret'),
				scopes=SCOPES
			)

			# Refresh credentials
			from google.auth.transport.requests import Request
			request = Request()
			credentials.refresh(request)

			self._credentials = credentials
			return build('drive', 'v3', credentials=credentials)

		except Exception as e:
			frappe.log_error(f"Error building Drive service: {str(e)}", "Google Workspace Drive")
			frappe.throw(_("Google Workspace authorization expired. Please re-authorize in settings."))

	def get_access_token(self) -> str:
		"""Get the current access token (for Google Picker API)."""
		if hasattr(self, '_credentials') and self._credentials:
			if not self._credentials.valid:
				from google.auth.transport.requests import Request
				self._credentials.refresh(Request())
			return self._credentials.token
		return None

	@retry_with_backoff()
	def get_file_metadata(self, file_id: str) -> dict:
		"""Fetch metadata for a file or folder."""
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
				frappe.throw(_("File not found or not accessible"))
			elif status == 403:
				frappe.throw(_("No permission to access this file"))
			elif status == 401:
				frappe.throw(_("Authentication failed. Please re-authorize Google Workspace."))
			else:
				frappe.throw(_("Google Drive API error: {0}").format(str(e)))

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

	@retry_with_backoff()
	def list_shared_drives(self) -> list:
		"""List all Shared Drives the user has access to."""
		drives = []
		page_token = None

		while True:
			response = self.service.drives().list(
				pageSize=100,
				pageToken=page_token,
				fields='nextPageToken, drives(id, name)'
			).execute()

			for drive in response.get('drives', []):
				drives.append({
					'drive_id': drive['id'],
					'name': drive['name']
				})

			page_token = response.get('nextPageToken')
			if not page_token:
				break

		return drives
