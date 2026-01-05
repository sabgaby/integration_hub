# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
Google Calendar API service wrapper.

Provides event creation, updating, and deletion for calendar integration.
"""

import frappe
from frappe import _
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from datetime import datetime, timedelta
import time
from functools import wraps

SCOPES = ['https://www.googleapis.com/auth/calendar']

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


class GoogleCalendarService:
	"""Google Calendar API wrapper with per-user authorization."""

	def __init__(self, user=None, calendar_id='primary'):
		"""Initialize Google Calendar service for a specific user.

		Args:
			user: Username (defaults to current session user)
			calendar_id: Calendar ID to use (default: 'primary' = user's main calendar)
		"""
		self.settings = frappe.get_single("Google Workspace Settings")

		if not self.settings.enabled:
			frappe.throw(_("Google Workspace integration is not enabled"))

		if not self.settings.enable_calendar:
			frappe.throw(_("Google Calendar is not enabled in Google Workspace Settings"))

		self.user = user or frappe.session.user
		self.calendar_id = calendar_id

		user_doc = frappe.get_doc("User", self.user)
		if not hasattr(user_doc, 'google_workspace_refresh_token'):
			frappe.throw(_("Google Workspace not authorized for your account. Please authorize in settings."))

		refresh_token = user_doc.get_password('google_workspace_refresh_token', raise_exception=False)

		if not refresh_token:
			frappe.throw(_("Google Workspace not authorized for your account. Please authorize in settings."))

		self.service = self._build_service(refresh_token)

	def _build_service(self, refresh_token):
		"""Build the Google Calendar API service."""
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
			return build('calendar', 'v3', credentials=credentials)

		except Exception as e:
			frappe.log_error(f"Error building Calendar service: {str(e)}", "Google Workspace Calendar")
			frappe.throw(_("Google Workspace authorization expired. Please re-authorize in settings."))

	@retry_with_backoff()
	def create_event(
		self,
		summary: str,
		start_date: str,
		end_date: str = None,
		description: str = None,
		attendees: list = None,
		all_day: bool = True,
		send_notifications: bool = True,
		transparency: str = "opaque"  # "opaque" = busy, "transparent" = free
	) -> dict:
		"""Create a calendar event.

		Args:
			summary: Event title
			start_date: Start date (YYYY-MM-DD for all-day, or ISO datetime)
			end_date: End date (optional, defaults to start_date + 1 day for all-day)
			description: Event description
			attendees: List of email addresses to invite
			all_day: Whether this is an all-day event
			send_notifications: Whether to send email notifications to attendees
			transparency: "opaque" (busy) or "transparent" (free)

		Returns:
			dict with event details including 'id' and 'htmlLink'
		"""
		event = {
			'summary': summary,
			'transparency': transparency,
		}

		if description:
			event['description'] = description

		# Format dates
		if all_day:
			event['start'] = {'date': start_date}
			if end_date:
				# For all-day events, end date is exclusive, so add 1 day
				end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
				event['end'] = {'date': end_dt.strftime('%Y-%m-%d')}
			else:
				end_dt = datetime.strptime(start_date, '%Y-%m-%d') + timedelta(days=1)
				event['end'] = {'date': end_dt.strftime('%Y-%m-%d')}
		else:
			event['start'] = {'dateTime': start_date, 'timeZone': frappe.get_system_settings('time_zone') or 'UTC'}
			if end_date:
				event['end'] = {'dateTime': end_date, 'timeZone': frappe.get_system_settings('time_zone') or 'UTC'}
			else:
				# Default to 1 hour
				event['end'] = {'dateTime': start_date, 'timeZone': frappe.get_system_settings('time_zone') or 'UTC'}

		# Add attendees
		if attendees:
			event['attendees'] = [{'email': email} for email in attendees]

		try:
			result = self.service.events().insert(
				calendarId=self.calendar_id,
				body=event,
				sendUpdates='all' if send_notifications else 'none'
			).execute()

			return {
				'id': result.get('id'),
				'htmlLink': result.get('htmlLink'),
				'status': result.get('status'),
				'summary': result.get('summary')
			}

		except HttpError as e:
			status = e.resp.status if hasattr(e, 'resp') else None
			frappe.log_error(f"Calendar event creation failed ({status}): {str(e)}", "Google Workspace Calendar")
			frappe.throw(_("Failed to create calendar event: {0}").format(str(e)))

	@retry_with_backoff()
	def update_event(
		self,
		event_id: str,
		summary: str = None,
		start_date: str = None,
		end_date: str = None,
		description: str = None,
		attendees: list = None,
		all_day: bool = True,
		send_notifications: bool = True,
		transparency: str = None
	) -> dict:
		"""Update an existing calendar event.

		Args:
			event_id: Google Calendar event ID
			... (same as create_event)

		Returns:
			dict with updated event details
		"""
		try:
			# Get existing event
			event = self.service.events().get(
				calendarId=self.calendar_id,
				eventId=event_id
			).execute()

			# Update fields if provided
			if summary is not None:
				event['summary'] = summary
			if description is not None:
				event['description'] = description
			if transparency is not None:
				event['transparency'] = transparency

			if start_date is not None:
				if all_day:
					event['start'] = {'date': start_date}
				else:
					event['start'] = {'dateTime': start_date, 'timeZone': frappe.get_system_settings('time_zone') or 'UTC'}

			if end_date is not None:
				if all_day:
					end_dt = datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)
					event['end'] = {'date': end_dt.strftime('%Y-%m-%d')}
				else:
					event['end'] = {'dateTime': end_date, 'timeZone': frappe.get_system_settings('time_zone') or 'UTC'}

			if attendees is not None:
				event['attendees'] = [{'email': email} for email in attendees]

			result = self.service.events().update(
				calendarId=self.calendar_id,
				eventId=event_id,
				body=event,
				sendUpdates='all' if send_notifications else 'none'
			).execute()

			return {
				'id': result.get('id'),
				'htmlLink': result.get('htmlLink'),
				'status': result.get('status'),
				'summary': result.get('summary')
			}

		except HttpError as e:
			status = e.resp.status if hasattr(e, 'resp') else None
			if status == 404:
				frappe.throw(_("Calendar event not found"))
			frappe.log_error(f"Calendar event update failed ({status}): {str(e)}", "Google Workspace Calendar")
			frappe.throw(_("Failed to update calendar event: {0}").format(str(e)))

	@retry_with_backoff()
	def delete_event(self, event_id: str, send_notifications: bool = True) -> bool:
		"""Delete a calendar event.

		Args:
			event_id: Google Calendar event ID
			send_notifications: Whether to send cancellation notifications

		Returns:
			True if deleted successfully
		"""
		try:
			self.service.events().delete(
				calendarId=self.calendar_id,
				eventId=event_id,
				sendUpdates='all' if send_notifications else 'none'
			).execute()
			return True

		except HttpError as e:
			status = e.resp.status if hasattr(e, 'resp') else None
			if status == 404:
				# Already deleted, that's fine
				return True
			if status == 410:
				# Gone, already deleted
				return True
			frappe.log_error(f"Calendar event deletion failed ({status}): {str(e)}", "Google Workspace Calendar")
			frappe.throw(_("Failed to delete calendar event: {0}").format(str(e)))

	@retry_with_backoff()
	def get_event(self, event_id: str) -> dict:
		"""Get a calendar event by ID.

		Args:
			event_id: Google Calendar event ID

		Returns:
			dict with event details
		"""
		try:
			result = self.service.events().get(
				calendarId=self.calendar_id,
				eventId=event_id
			).execute()

			return {
				'id': result.get('id'),
				'htmlLink': result.get('htmlLink'),
				'status': result.get('status'),
				'summary': result.get('summary'),
				'description': result.get('description'),
				'start': result.get('start'),
				'end': result.get('end'),
				'attendees': result.get('attendees', [])
			}

		except HttpError as e:
			status = e.resp.status if hasattr(e, 'resp') else None
			if status == 404:
				return None
			frappe.throw(_("Failed to get calendar event: {0}").format(str(e)))

	@retry_with_backoff()
	def list_calendars(self) -> list:
		"""List all calendars the user has access to.

		Returns:
			List of dicts with calendar info
		"""
		calendars = []
		page_token = None

		while True:
			response = self.service.calendarList().list(
				pageToken=page_token,
				fields='nextPageToken, items(id, summary, primary, accessRole)'
			).execute()

			for cal in response.get('items', []):
				calendars.append({
					'id': cal['id'],
					'name': cal['summary'],
					'primary': cal.get('primary', False),
					'access_role': cal.get('accessRole')
				})

			page_token = response.get('nextPageToken')
			if not page_token:
				break

		return calendars
