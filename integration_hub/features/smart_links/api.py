import frappe
from frappe import _


def get_smart_links_settings():
    """Get Smart Links Settings with caching to avoid repeated DB queries."""
    return frappe.cache.get_value(
        "smart_links_settings",
        lambda: frappe.get_single("Smart Links Settings")
    )


def _validate_doctype_enabled(doctype: str) -> None:
    """Check if doctype is enabled for Smart Links integration."""
    settings = get_smart_links_settings()
    if not settings.enabled:
        frappe.throw(_("Smart Links integration is not enabled"))

    enabled_doctypes = [d.document_type for d in settings.enabled_doctypes]
    if doctype not in enabled_doctypes:
        frappe.throw(_("Smart Links are not enabled for {0}").format(doctype))


def _validate_has_smart_links_field(doctype: str) -> None:
    """Check if doctype has smart_links field."""
    meta = frappe.get_meta(doctype)
    if not meta.has_field('smart_links'):
        frappe.throw(_("{0} does not have Smart Links field configured").format(doctype))


def _validate_docname(docname: str) -> None:
    """Check if docname is valid (not a new unsaved document)."""
    if not docname or docname.startswith('new-') or docname == 'new':
        frappe.throw(_("Please save the document before adding links"))


@frappe.whitelist()
def get_config():
    """Get configuration for frontend."""
    settings = get_smart_links_settings()

    if not settings.enabled:
        return {'enabled': False}

    # Check if CURRENT USER is connected (per-user authorization for Google Drive)
    user_doc = frappe.get_doc("User", frappe.session.user)
    is_connected = False
    try:
        # Try Google_Workspace token first
        token = None
        try:
            from integration_hub.utils import get_user_refresh_token, is_google_workspace_enabled
            if is_google_workspace_enabled():
                token = get_user_refresh_token(frappe.session.user)
        except (ImportError, Exception):
            pass
        
        # Fall back to gdrive_refresh_token
        if not token and hasattr(user_doc, 'gdrive_refresh_token'):
            token = user_doc.get_password('gdrive_refresh_token', raise_exception=False)
            is_connected = bool(token)
    except Exception:
        is_connected = False

    return {
        'enabled': True,
        'is_connected': is_connected,
        'enabled_doctypes': [d.document_type for d in settings.enabled_doctypes]
    }


@frappe.whitelist()
def add_link(doctype: str, docname: str, url: str) -> dict:
    """Add a Google Drive link to a document."""
    # Validate inputs
    _validate_doctype_enabled(doctype)
    _validate_has_smart_links_field(doctype)
    _validate_docname(docname)

    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    from integration_hub.features.smart_links.utils.url_parser import extract_file_id
    file_id = extract_file_id(url)
    if not file_id:
        frappe.throw(_("Invalid Google Drive URL. Please use a valid Google Drive, Docs, Sheets, or Slides link."))

    doc = frappe.get_doc(doctype, docname)

    # Check for duplicates
    if doc.smart_links:
        existing = next((l for l in doc.smart_links if l.file_id == file_id), None)
        if existing:
            frappe.throw(_("This file is already linked"))

    # Get file metadata
    from integration_hub.features.smart_links.google_drive import GoogleDriveService
    service = GoogleDriveService()
    metadata = service.get_file_metadata(file_id)

    # Add link
    doc.append('smart_links', {
        'file_id': metadata['file_id'],
        'file_name': metadata['file_name'],
        'mime_type': metadata['mime_type'],
        'file_type': metadata['file_type'],
        'file_size': metadata['file_size'],
        'web_view_link': metadata['web_view_link'],
        'icon_link': metadata['icon_link'],
        'thumbnail_link': metadata['thumbnail_link'],
        'drive_id': metadata.get('drive_id'),
        'added_by': frappe.session.user,
        'added_on': frappe.utils.now()
    })

    doc.save()

    return metadata


@frappe.whitelist()
def remove_link(doctype: str, docname: str, file_id: str) -> dict:
    """Remove a link from a document."""
    # Validate inputs
    _validate_doctype_enabled(doctype)
    _validate_has_smart_links_field(doctype)

    if not file_id or not isinstance(file_id, str):
        frappe.throw(_("Invalid file ID"))

    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    doc = frappe.get_doc(doctype, docname)

    if not doc.smart_links:
        frappe.throw(_("No links found"))

    original_count = len(doc.smart_links)
    doc.smart_links = [l for l in doc.smart_links if l.file_id != file_id]

    if len(doc.smart_links) == original_count:
        frappe.throw(_("Link not found"))

    doc.save()

    return {"message": "Link removed"}


@frappe.whitelist()
def convert_file_to_smart_link(doctype: str, docname: str, url: str, file_doc_name: str = None) -> dict:
    """Convert a File attachment to a Smart Link.

    This is called when a user attaches a Google Drive URL via the standard "Link" option.
    It deletes the File attachment and creates a Smart Link instead.

    Args:
        doctype: The parent document type
        docname: The parent document name
        url: The Google Drive URL
        file_doc_name: Optional - the File document name to delete
    """
    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    # Delete the File attachment if provided
    if file_doc_name:
        try:
            file_doc = frappe.get_doc("File", file_doc_name)
            if file_doc.attached_to_doctype == doctype and file_doc.attached_to_name == docname:
                frappe.delete_doc("File", file_doc_name, ignore_permissions=False)
        except frappe.DoesNotExistError:
            pass
        except Exception as e:
            frappe.log_error(f"Error deleting File {file_doc_name}: {str(e)}", "Smart Links Convert")

    return add_link(doctype, docname, url)


@frappe.whitelist()
def add_link_by_file_id(doctype: str, docname: str, file_id: str) -> dict:
    """Add a Google Drive link by file ID (used by Google Picker).

    Args:
        doctype: The parent document type
        docname: The parent document name
        file_id: Google Drive file ID
    """
    # Validate inputs
    _validate_doctype_enabled(doctype)
    _validate_has_smart_links_field(doctype)
    _validate_docname(docname)

    if not file_id or not isinstance(file_id, str) or len(file_id) < 10:
        frappe.throw(_("Invalid file ID"))

    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    doc = frappe.get_doc(doctype, docname)

    # Check for duplicates
    if doc.smart_links:
        existing = next((l for l in doc.smart_links if l.file_id == file_id), None)
        if existing:
            frappe.throw(_("This file is already linked"))

    # Get file metadata
    from integration_hub.features.smart_links.google_drive import GoogleDriveService
    service = GoogleDriveService()
    metadata = service.get_file_metadata(file_id)

    # Add link
    doc.append('smart_links', {
        'file_id': metadata['file_id'],
        'file_name': metadata['file_name'],
        'mime_type': metadata['mime_type'],
        'file_type': metadata['file_type'],
        'file_size': metadata['file_size'],
        'web_view_link': metadata['web_view_link'],
        'icon_link': metadata['icon_link'],
        'thumbnail_link': metadata['thumbnail_link'],
        'drive_id': metadata.get('drive_id'),
        'added_by': frappe.session.user,
        'added_on': frappe.utils.now()
    })

    doc.save()

    return metadata


@frappe.whitelist()
def get_picker_config() -> dict:
    """Get configuration for Google Picker API.

    Returns client_id, api_key, app_id, and a fresh access token
    for initializing the Google Picker.
    """
    settings = get_smart_links_settings()

    if not settings.enabled:
        frappe.throw(_("Smart Links integration is not enabled"))

    # Try to get client_id from Google_Workspace Settings first
    client_id = None
    api_key = None
    try:
        from integration_hub.utils import get_google_credentials, is_google_workspace_enabled
        if is_google_workspace_enabled():
            credentials = get_google_credentials()
            client_id = credentials["client_id"]
            workspace_settings = frappe.get_single("Google Workspace Settings")
            if hasattr(workspace_settings, 'api_key') and workspace_settings.api_key:
                api_key = workspace_settings.api_key
    except (ImportError, Exception):
        pass
    
    # Fall back to Smart Links Settings
    if not client_id:
        client_id = settings.client_id
    
    if not client_id:
        frappe.throw(_("Client ID not configured. Please configure Google Workspace Settings or Smart Links Settings"))

    # API Key is required for the Picker
    if not api_key:
        api_key = getattr(settings, 'api_key', None)
    
    if not api_key:
        frappe.throw(_("API Key not configured. Please add an API Key in Google Workspace Settings or Smart Links Settings."))

    # Extract App ID from Client ID (project number before the dash)
    app_id = client_id.split('-')[0] if client_id else None
    if not app_id:
        frappe.throw(_("Could not extract App ID from Client ID"))

    # Get a fresh access token for the current user
    from integration_hub.features.smart_links.google_drive import GoogleDriveService
    service = GoogleDriveService()
    access_token = service.get_access_token()

    if not access_token:
        frappe.throw(_("Could not get access token. Please re-authorize Google Drive."))

    return {
        'client_id': client_id,
        'api_key': api_key,
        'app_id': app_id,
        'access_token': access_token,
        'origin': frappe.utils.get_url()
    }


@frappe.whitelist()
def refresh_file_names(doctype: str, docname: str) -> dict:
    """Refresh file names from Google Drive for a document."""
    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    doc = frappe.get_doc(doctype, docname)

    if not doc.smart_links:
        return {"updated": 0, "message": "No links to refresh"}

    from integration_hub.features.smart_links.google_drive import GoogleDriveService
    service = GoogleDriveService()
    updated = 0
    errors = []

    for link in doc.smart_links:
        try:
            metadata = service.get_file_metadata(link.file_id)

            link.file_name = metadata['file_name']
            link.mime_type = metadata['mime_type']
            link.file_type = metadata['file_type']
            link.file_size = metadata['file_size']
            link.web_view_link = metadata['web_view_link']
            link.icon_link = metadata['icon_link']
            link.thumbnail_link = metadata['thumbnail_link']
            link.drive_id = metadata.get('drive_id')

            updated += 1
        except Exception as e:
            frappe.log_error(
                f"Error refreshing file {link.file_id}: {str(e)}",
                "Smart Links Refresh"
            )
            errors.append({
                'file_id': link.file_id,
                'file_name': getattr(link, 'file_name', 'Unknown'),
                'error': str(e)
            })

    if updated > 0 or not errors:
        doc.save()

    return {
        "updated": updated,
        "total": len(doc.smart_links),
        "errors": errors,
        "message": f"Refreshed {updated} of {len(doc.smart_links)} file(s)"
    }


@frappe.whitelist()
def add_links_batch(doctype: str, docname: str, file_ids) -> dict:
    """Add multiple Google Drive links in a single request.

    This is more efficient than multiple add_link_by_file_id calls when
    linking several files from Google Picker.

    Args:
        doctype: The parent document type
        docname: The parent document name
        file_ids: List of Google Drive file IDs to link
    """
    import json

    # Handle file_ids passed as JSON string from frontend
    if isinstance(file_ids, str):
        file_ids = json.loads(file_ids)

    if not file_ids or not isinstance(file_ids, list):
        frappe.throw(_("No file IDs provided"))

    # Validate inputs once
    _validate_doctype_enabled(doctype)
    _validate_has_smart_links_field(doctype)
    _validate_docname(docname)

    if not frappe.has_permission(doctype, "write", docname):
        frappe.throw(_("No permission to modify this document"))

    doc = frappe.get_doc(doctype, docname)

    # Build set of existing file IDs for O(1) duplicate check
    existing_ids = {l.file_id for l in doc.smart_links} if doc.smart_links else set()

    from integration_hub.features.smart_links.google_drive import GoogleDriveService
    service = GoogleDriveService()

    linked = []
    errors = []

    for file_id in file_ids:
        # Validate file_id
        if not file_id or not isinstance(file_id, str) or len(file_id) < 10:
            errors.append({"file_id": file_id, "error": "Invalid file ID"})
            continue

        # Check for duplicates
        if file_id in existing_ids:
            errors.append({"file_id": file_id, "error": "Already linked"})
            continue

        try:
            metadata = service.get_file_metadata(file_id)

            doc.append('smart_links', {
                'file_id': metadata['file_id'],
                'file_name': metadata['file_name'],
                'mime_type': metadata['mime_type'],
                'file_type': metadata['file_type'],
                'file_size': metadata['file_size'],
                'web_view_link': metadata['web_view_link'],
                'icon_link': metadata['icon_link'],
                'thumbnail_link': metadata['thumbnail_link'],
                'drive_id': metadata.get('drive_id'),
                'added_by': frappe.session.user,
                'added_on': frappe.utils.now()
            })

            existing_ids.add(file_id)
            linked.append(metadata)

        except Exception as e:
            frappe.log_error(
                f"Error linking file {file_id}: {str(e)}",
                "Smart Links Batch"
            )
            errors.append({"file_id": file_id, "error": str(e)})

    # Save once after all links added
    if linked:
        doc.save()

    return {
        "linked": linked,
        "errors": errors,
        "message": f"Linked {len(linked)} file(s)" + (f", {len(errors)} failed" if errors else "")
    }
