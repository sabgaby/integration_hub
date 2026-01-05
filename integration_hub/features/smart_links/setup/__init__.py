import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

DEFAULT_DOCTYPES = [
    'Supplier',
    'Customer',
    'Purchase Order',
    'Purchase Invoice',
    'Sales Order',
    'Sales Invoice',
    'Project',
]


def setup_smart_links():
    """Setup Smart Links feature."""
    create_smart_links_field()
    create_user_gdrive_token_field()
    setup_default_settings()


def create_user_gdrive_token_field():
    """Create custom fields on User doctype for storing Google Drive refresh token and status."""
    custom_fields_to_create = {}

    # Add gdrive_refresh_token field
    if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'gdrive_refresh_token'}):
        custom_fields_to_create['User'] = custom_fields_to_create.get('User', []) + [{
            'fieldname': 'gdrive_refresh_token',
            'fieldtype': 'Password',
            'label': 'Google Drive Refresh Token',
            'hidden': 1,
            'insert_after': 'api_key',
            'description': 'Stores per-user Google Drive OAuth refresh token for secure file access'
        }]

    # Add gdrive_authorization_status field
    if not frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': 'gdrive_authorization_status'}):
        custom_fields_to_create['User'] = custom_fields_to_create.get('User', []) + [{
            'fieldname': 'gdrive_authorization_status',
            'fieldtype': 'Data',
            'label': 'Google Drive Authorization Status',
            'read_only': 1,
            'default': 'Not Connected',
            'insert_after': 'gdrive_refresh_token',
            'description': 'Current authorization status for Google Drive for this user'
        }]

    if custom_fields_to_create:
        create_custom_fields(custom_fields_to_create)


def create_smart_links_field():
    """Create smart_links custom field on enabled DocTypes."""
    custom_fields = {}

    for dt in DEFAULT_DOCTYPES:
        if frappe.db.exists('DocType', dt):
            custom_fields[dt] = [
                {
                    'fieldname': 'smart_links',
                    'fieldtype': 'Table',
                    'label': 'Smart Links',
                    'options': 'Smart Link',
                    'hidden': 1,  # Managed via sidebar widget
                    'allow_on_submit': 1,  # Allow adding links to submitted documents
                }
            ]

    if custom_fields:
        create_custom_fields(custom_fields)


def setup_default_settings():
    """Setup default settings."""
    settings = frappe.get_single('Smart Links Settings')

    # Get existing document types to avoid duplicates
    existing_types = {d.document_type for d in settings.enabled_doctypes if d.document_type}

    # Add default DocTypes only if they don't exist
    added = 0
    for dt in DEFAULT_DOCTYPES:
        if frappe.db.exists('DocType', dt) and dt not in existing_types:
            settings.append('enabled_doctypes', {
                'document_type': dt,
                'show_in_sidebar': 1
            })
            added += 1

    # Only save if we added something
    if added > 0:
        settings.save(ignore_permissions=True)
        frappe.db.commit()


def cleanup_smart_links():
    """Clean up Smart Links feature."""
    # Remove custom fields
    for dt in DEFAULT_DOCTYPES:
        field_name = f"{dt}-smart_links"
        if frappe.db.exists('Custom Field', field_name):
            frappe.delete_doc('Custom Field', field_name)

    # Remove User custom fields
    for fieldname in ['gdrive_refresh_token', 'gdrive_authorization_status']:
        if frappe.db.exists('Custom Field', {'dt': 'User', 'fieldname': fieldname}):
            frappe.delete_doc('Custom Field', {'dt': 'User', 'fieldname': fieldname})
