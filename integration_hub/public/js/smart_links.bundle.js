// GDrive Link - Frontend JavaScript
// Use Frappe standard patterns for reliability
// Version: 2024-12-05-v14 (Google Picker API integration)

(function() {
    'use strict';

    // Only proceed if Frappe is available
    if (typeof frappe === 'undefined') {
        console.warn('Smart Links: Frappe not available');
        return;
    }

    // Create namespace
    try {
        frappe.provide('smart_links');
    } catch (e) {
        console.warn('Smart Links: Failed to create namespace', e);
        return;
    }

    // Configuration
    smart_links.config = null;
    smart_links.loaded = false;
    smart_links.registered_doctypes = {};
    smart_links.upload_option_registered = false;
    smart_links.upload_intercepted = false;
    
    // Debug mode - set to true for verbose logging (useful for development)
    smart_links.DEBUG = false;
    
    // Helper function for debug logging
    smart_links.debug = function() {
        if (smart_links.DEBUG && console.log) {
            console.log.apply(console, arguments);
        }
    };

    // Load configuration and register form handlers for enabled doctypes
    smart_links.load_config = function(callback) {
        if (typeof frappe === 'undefined' || !frappe.call) {
            console.warn('Smart Links: frappe.call not available');
            return;
        }

        // Check if user is logged in
        if (!frappe.session || !frappe.session.user || frappe.session.user === 'Guest') {
            smart_links.debug('Smart Links: User not logged in, skipping config load');
            return;
        }

        smart_links.debug('Smart Links: Loading config for user', frappe.session.user);

        frappe.call({
            method: 'integration_hub.features.smart_links.api.get_config',
            async: true,
            callback: function(r) {
                smart_links.debug('Smart Links: API response', r);
                if (r && r.message) {
                    smart_links.config = r.message;
                    smart_links.loaded = true;
                    smart_links.debug('Smart Links: Config loaded successfully', smart_links.config);

                    // Register form handlers for enabled doctypes
                    if (smart_links.config.enabled && smart_links.config.enabled_doctypes) {
                        smart_links.config.enabled_doctypes.forEach(function(doctype) {
                            smart_links.register_doctype_handler(doctype);
                        });
                    }

                    // Intercept file uploads to catch Google Drive links from "Link" option
                    smart_links.intercept_file_upload();

                    // Note: Picker API preload moved to check_current_form() to only preload
                    // when on an enabled doctype's form

                    if (callback) callback();
                } else {
                    console.warn('Smart Links: Empty response from API', r);
                }
            },
            error: function(r) {
                console.error('Smart Links: Failed to load config', r);
            }
        });
    };

    // Register form handler for a specific doctype
    smart_links.register_doctype_handler = function(doctype) {
        // Skip if already registered
        if (smart_links.registered_doctypes[doctype]) {
            return;
        }

        smart_links.debug('Smart Links: Registering handler for', doctype);
        smart_links.registered_doctypes[doctype] = true;

        // Register the form handler
        frappe.ui.form.on(doctype, {
            refresh: function(frm) {
                smart_links.on_form_refresh(frm);
            }
        });
    };

    // Handle form refresh for enabled doctypes
    smart_links.on_form_refresh = function(frm) {
        if (!frm || !frm.doctype) return;

        // Skip new documents
        if (frm.is_new && frm.is_new()) return;
        if (!frm.docname) return;

        // Check if enabled
        if (!smart_links.loaded || !smart_links.config || !smart_links.config.enabled) {
            return;
        }

        // Add integrated chips in the attachments section
        smart_links.add_integrated_chips(frm);
    };

    // Load config on page load
    $(document).ready(function() {
        // Small delay to ensure Frappe is fully initialized
        setTimeout(function() {
            smart_links.load_config(function() {
                // After config loads, check if we're already on an enabled form
                smart_links.check_current_form();
            });
        }, 500);
    });

    // Also check when navigating between pages (SPA navigation)
    $(document).on('page-change', function() {
        if (smart_links.loaded) {
            setTimeout(function() {
                smart_links.check_current_form();
            }, 300);
        }
    });

    // Check if we're on an enabled form and add widget
    smart_links.check_current_form = function() {
        if (!smart_links.loaded || !smart_links.config || !smart_links.config.enabled) {
            return;
        }

        // Check if current route is a form for an enabled doctype
        var route = frappe.get_route();
        if (!route || !route.length) {
            return;
        }

        if (route[0] === 'Form') {
            var doctype = route[1];
            var docname = route[2];

            if (doctype && docname && smart_links.config.enabled_doctypes.includes(doctype)) {
                // Preload Google Picker API only when on an enabled doctype's form
                if (smart_links.config.is_connected) {
                    smart_links.preload_picker_api();
                }

                // We're on an enabled form - use on_form_refresh which handles display mode
                if (cur_frm && cur_frm.doctype === doctype && cur_frm.docname === docname) {
                    smart_links.debug('Smart Links: Refreshing widget on current form', doctype, docname);
                    smart_links.on_form_refresh(cur_frm);
                }
            }
        }
    };
    
    // ============================================================================
    // SETTINGS FORM HANDLER
    // ============================================================================
    frappe.ui.form.on('Smart Links Settings', {
        refresh: function(frm) {
            // Handle return from OAuth
            const urlParams = new URLSearchParams(window.location.search);
            if (urlParams.get('authorized') === '1') {
                frm.reload_doc().then(function() {
                    window.history.replaceState({}, '', window.location.pathname);
                    frappe.show_alert({
                        message: __('Google Drive authorized successfully'),
                        indicator: 'green'
                    });
                });
                return;
            }

            // Add action buttons
            frm.add_custom_button(__('Authorize with Google'), function() {
                smart_links.authorize_google(frm);
            });

            frm.add_custom_button(__('Disconnect'), function() {
                smart_links.disconnect_google(frm);
            });
        }
    });
    
    
    // ============================================================================
    // AUTHORIZE WITH GOOGLE
    // ============================================================================
    smart_links.authorize_google = function(frm) {
        if (!frm || !frm.doc) {
            frappe.msgprint(__('Invalid form'));
            return;
        }
        
        if (!frm.doc.client_id || !frm.doc.client_secret) {
            frappe.msgprint(__('Please enter Client ID and Client Secret first'));
            return;
        }
        
        frappe.call({
            method: 'integration_hub.features.smart_links.oauth.get_authorization_url',
            callback: function(r) {
                if (r && r.message) {
                    window.location.href = r.message;
                } else {
                    frappe.msgprint(__('Failed to get authorization URL'));
                }
            },
            error: function(r) {
                frappe.msgprint(__('Error: {0}', [r.message || 'Unknown error']));
            }
        });
    };
    
    // ============================================================================
    // DISCONNECT GOOGLE
    // ============================================================================
    smart_links.disconnect_google = function(frm) {
        // Check if current user is actually connected (per-user authorization)
        // Using async call to avoid blocking the UI
        frappe.call({
            method: 'integration_hub.features.smart_links.api.get_config',
            callback: function(r) {
                if (!r || !r.message || !r.message.is_connected) {
                    frappe.msgprint(__('Google Drive is not connected for your account.'));
                    return;
                }

                frappe.confirm(__('Disconnect your Google Drive account? This will remove your authorization.'), function() {
                    frappe.call({
                        method: 'integration_hub.features.smart_links.oauth.disconnect',
                        callback: function(r) {
                            if (r && r.message) {
                                frappe.show_alert({
                                    message: __('Disconnected successfully'),
                                    indicator: 'green'
                                });
                                // Reload config to update status
                                smart_links.load_config();
                                // Reload form to update status display
                                if (frm && typeof frm.reload_doc === 'function') {
                                    frm.reload_doc();
                                }
                            }
                        },
                        error: function(r) {
                            frappe.msgprint(__('Error: {0}', [r.message || 'Failed to disconnect']));
                        }
                    });
                });
            }
        });
    };

    // ============================================================================
    // ADD GOOGLE DRIVE BUTTON TO FILE UPLOADER DIALOG
    // ============================================================================
    smart_links.add_gdrive_button_to_uploader = function() {
        if (smart_links.uploader_patched) return;

        // Hook into Frappe's Dialog.show() instead of watching entire document.body
        // This is much more efficient as it only fires when dialogs open
        if (frappe.ui && frappe.ui.Dialog) {
            const OriginalDialogShow = frappe.ui.Dialog.prototype.show;
            frappe.ui.Dialog.prototype.show = function() {
                // Call original show method first
                OriginalDialogShow.apply(this, arguments);

                // Check if this dialog contains a file uploader
                const $wrapper = this.$wrapper;
                if ($wrapper && $wrapper.length) {
                    // Small delay to let dialog content render
                    setTimeout(function() {
                        const uploaderArea = $wrapper.find('.file-upload-area');
                        if (uploaderArea.length) {
                            smart_links.inject_gdrive_button(uploaderArea);
                        }
                    }, 50);
                }
            };
        }

        smart_links.uploader_patched = true;
        smart_links.debug('Smart Links: File uploader dialog hook ready');
    };

    // Inject Google Drive button into the file uploader
    smart_links.inject_gdrive_button = function(uploaderArea) {
        // Check if already injected
        if (uploaderArea.find('.gdrive-upload-btn').length) return;

        // Check if GDrive Link is enabled and user is connected
        if (!smart_links.config || !smart_links.config.enabled || !smart_links.config.is_connected) return;

        // Check if current doctype is enabled
        if (cur_frm && smart_links.config.enabled_doctypes &&
            !smart_links.config.enabled_doctypes.includes(cur_frm.doctype)) return;

        // Find the button container (where My Device, Library, Link, Camera buttons are)
        const buttonContainer = uploaderArea.find('.text-center').last();
        if (!buttonContainer.length) return;

        // Find existing buttons to match their style
        const existingBtn = buttonContainer.find('.btn-file-upload').first();
        if (!existingBtn.length) return;

        // Create Google Drive button matching Frappe's style exactly
        // Using official Google Drive PNG icon
        const $gdriveBtn = jQuery(`
            <button class="btn btn-file-upload gdrive-upload-btn">
                <img src="https://ssl.gstatic.com/docs/doclist/images/drive_2022q3_32dp.png"
                     alt="Google Drive"
                     width="30"
                     height="30"
                     style="border-radius: 50%; background: var(--subtle-fg); padding: 2px;">
                <div class="mt-1">${__('Google Drive')}</div>
            </button>
        `);

        // Add click handler
        $gdriveBtn.on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            // Close the file uploader dialog
            const dialog = jQuery(this).closest('.modal');
            if (dialog.length) {
                dialog.modal('hide');
            }

            // Open Google Picker
            if (cur_frm) {
                smart_links.show_file_browser(cur_frm);
            }
        });

        // Add to button container
        buttonContainer.append($gdriveBtn);
        smart_links.debug('Smart Links: Added Google Drive button to file uploader');
    };

    // ============================================================================
    // INTERCEPT FILE UPLOAD TO CATCH GOOGLE DRIVE LINKS
    // When user uses "Link" in attachment dialog and pastes a GDrive URL,
    // intercept it and create a GDrive Link instead of a regular File attachment
    // ============================================================================
    smart_links.intercept_file_upload = function() {
        if (smart_links.upload_intercepted) return;
        if (!frappe.ui.FileUploader) return;

        smart_links.debug('Smart Links: Setting up file upload interception');

        // Add Google Drive button to file uploader dialog
        smart_links.add_gdrive_button_to_uploader();

        // Store the original FileUploader class
        const OriginalFileUploader = frappe.ui.FileUploader;

        // Create a wrapper class that intercepts uploads
        frappe.ui.FileUploader = class extends OriginalFileUploader {
            constructor(opts) {
                // Wrap the on_success callback to intercept Google Drive URLs
                const originalOnSuccess = opts.on_success;

                opts.on_success = function(file_doc, response) {
                    // Check if this is a web link (file_url) that's a Google Drive URL
                    const fileUrl = file_doc?.file_url || '';

                    if (smart_links.is_gdrive_url(fileUrl)) {
                        smart_links.debug('Smart Links: Intercepted Google Drive URL from Link attachment:', fileUrl);

                        // Get the doctype and docname from the options or cur_frm
                        const doctype = opts.doctype || (cur_frm && cur_frm.doctype);
                        const docname = opts.docname || (cur_frm && cur_frm.docname);

                        if (doctype && docname && smart_links.config?.enabled_doctypes?.includes(doctype)) {
                            // Use atomic API to delete File and create GDrive Link in one call
                            frappe.call({
                                method: 'integration_hub.features.smart_links.api.convert_file_to_smart_link',
                                args: {
                                    doctype: doctype,
                                    docname: docname,
                                    url: fileUrl,
                                    file_doc_name: file_doc?.name || null
                                },
                                callback: function(r) {
                                    if (r && r.message) {
                                        frappe.show_alert({
                                            message: __('Google Drive linked: {0}', [r.message.file_name || 'File']),
                                            indicator: 'green'
                                        });
                                        // Reload the form to show the new GDrive chip (without the File)
                                        if (cur_frm) {
                                            cur_frm.reload_doc();
                                        }
                                    }
                                },
                                error: function(r) {
                                    frappe.msgprint(__('Failed to link Google Drive file. Error: {0}',
                                        [r?.message || 'Unknown error']));
                                    // Call original on_success anyway since file was created
                                    if (originalOnSuccess) {
                                        originalOnSuccess(file_doc, response);
                                    }
                                }
                            });
                            return; // Don't call original on_success
                        }
                    }

                    // Not a Google Drive URL or not an enabled doctype - proceed normally
                    if (originalOnSuccess) {
                        originalOnSuccess(file_doc, response);
                    }
                };

                super(opts);
            }
        };

        // Copy static properties
        frappe.ui.FileUploader.UploadOptions = OriginalFileUploader.UploadOptions || [];

        smart_links.upload_intercepted = true;
        smart_links.debug('Smart Links: File upload interception ready');
    };

    // ============================================================================
    // CHECK IF URL IS A GOOGLE DRIVE URL
    // ============================================================================
    smart_links.is_gdrive_url = function(url) {
        if (!url || typeof url !== 'string') return false;
        return /drive\.google\.com|docs\.google\.com/.test(url);
    };

    // ============================================================================
    // SHOW PASTE DIALOG (for adding Google Drive links)
    // ============================================================================
    smart_links.show_paste_dialog = function(doctype, docname, callback) {
        const dialog = new frappe.ui.Dialog({
            title: __('Add Google Drive Link'),
            fields: [
                {
                    fieldname: 'url',
                    fieldtype: 'Data',
                    label: __('Google Drive URL'),
                    reqd: 1,
                    description: __('Paste a Google Drive file or folder URL')
                }
            ],
            primary_action_label: __('Add Link'),
            primary_action: function(values) {
                if (!values.url) return;

                // Validate URL
                if (!/drive\.google\.com|docs\.google\.com/.test(values.url)) {
                    frappe.msgprint(__('Please enter a valid Google Drive URL'));
                    return;
                }

                dialog.disable_primary_action();

                frappe.call({
                    method: 'integration_hub.features.smart_links.api.add_link',
                    args: {
                        doctype: doctype,
                        docname: docname,
                        url: values.url
                    },
                    callback: function(r) {
                        if (r && r.message) {
                            frappe.show_alert({
                                message: __('Linked: {0}', [r.message.file_name || 'File']),
                                indicator: 'green'
                            });
                            dialog.hide();
                            if (callback) callback();
                        }
                    },
                    error: function() {
                        dialog.enable_primary_action();
                    }
                });
            }
        });

        dialog.show();

        // Focus the input and handle paste
        setTimeout(function() {
            const input = dialog.fields_dict.url.$input;
            if (input && input.length) {
                input.focus();
            }
        }, 100);
    };

    // ============================================================================
    // ADD INTEGRATED CHIPS (chips inside attachments section)
    // ============================================================================
    smart_links.add_integrated_chips = function(frm) {
        try {
            if (!frm || typeof frm !== 'object') return;

            // Get sidebar and attachments section first (for scoped removal)
            let sidebar = null;
            if (frm.sidebar && frm.sidebar.sidebar && frm.sidebar.sidebar.length) {
                sidebar = frm.sidebar.sidebar;
            } else if (frm.page && frm.page.sidebar) {
                sidebar = jQuery(frm.page.sidebar).find('.form-sidebar');
                if (!sidebar.length) sidebar = jQuery(frm.page.sidebar);
            } else {
                sidebar = jQuery('.form-sidebar');
            }

            if (!sidebar || !sidebar.length) {
                smart_links.debug('Smart Links: Sidebar not found for integrated mode');
                return;
            }

            // Remove existing gdrive elements - scoped to sidebar to avoid affecting other forms
            sidebar.find('.gdrive-attachment-row').remove();
            sidebar.find('.gdrive-separator').remove();

            const attachmentsSection = sidebar.find('.form-attachments');
            if (!attachmentsSection.length) {
                smart_links.debug('Smart Links: Attachments section not found');
                return;
            }

            // Get gdrive links
            const links = (frm.doc && frm.doc.smart_links) ? frm.doc.smart_links : [];
            smart_links.debug('Smart Links: Rendering', links.length, 'integrated chips');

            if (links.length === 0) {
                smart_links.setup_attachment_observer(frm, attachmentsSection);
                return;
            }

            // Find the last local attachment row (Frappe's .attachment-row that's not ours)
            // Local attachments appear after .attachments-actions
            const localAttachments = attachmentsSection.find('.attachment-row:not(.gdrive-attachment-row)');
            const hasLocalAttachments = localAttachments.length > 0;

            // Determine insert point: after last local attachment, or after attachments-actions if none
            let insertPoint;
            if (hasLocalAttachments) {
                insertPoint = localAttachments.last();
            } else {
                insertPoint = attachmentsSection.find('.attachments-actions');
            }

            // Add separator line if there are local attachments
            if (hasLocalAttachments) {
                const $separator = jQuery('<div class="gdrive-separator"></div>');
                insertPoint.after($separator);
                insertPoint = $separator;
            }

            // Add GDrive link rows after the separator (or after attachments-actions if no local files)
            links.forEach(function(link) {
                const $row = smart_links.create_attachment_row(frm, link);
                insertPoint.after($row);
                insertPoint = $row;
            });

            // Hook into Frappe's attachment rendering to persist our chips
            smart_links.setup_attachment_observer(frm, attachmentsSection);

        } catch (e) {
            console.warn('Smart Links: Error adding integrated chips', e);
        }
    };

    // ============================================================================
    // OBSERVE ATTACHMENT CHANGES - Re-render GDrive chips when attachments update
    // ============================================================================
    smart_links.setup_attachment_observer = function(frm, attachmentsSection) {
        // Disconnect existing observer to prevent duplicates
        if (smart_links._attachmentObserver) {
            smart_links._attachmentObserver.disconnect();
        }

        // Clear any pending re-render timeout
        if (smart_links._reRenderTimeout) {
            clearTimeout(smart_links._reRenderTimeout);
        }

        // Create a MutationObserver to watch for attachment section changes
        // Optimized: only watch direct children, not entire subtree
        smart_links._attachmentObserver = new MutationObserver(function(mutations) {
            // Quick check if config is enabled
            if (!smart_links.config || !smart_links.config.enabled) return;

            // Check if our GDrive elements were removed (only if we should have them)
            const links = (frm.doc && frm.doc.smart_links) ? frm.doc.smart_links : [];
            const shouldHaveElements = links.length > 0;
            const gdriveElementsExist = attachmentsSection.find('.gdrive-attachment-row').length > 0;

            // Only re-render if our elements are missing when they shouldn't be
            if (shouldHaveElements && !gdriveElementsExist) {
                clearTimeout(smart_links._reRenderTimeout);
                smart_links._reRenderTimeout = setTimeout(function() {
                    smart_links.debug('Smart Links: Re-rendering after attachment change');
                    smart_links.add_integrated_chips(frm);
                }, 150);  // Slightly longer debounce for stability
                return;
            }

            // Check if separator needs updating (local attachments changed)
            const localAttachmentCount = attachmentsSection.find('.attachment-row:not(.gdrive-attachment-row)').length;
            const hasSeparator = attachmentsSection.find('.gdrive-separator').length > 0;
            const shouldHaveSeparator = localAttachmentCount > 0 && links.length > 0;

            if (shouldHaveSeparator !== hasSeparator) {
                clearTimeout(smart_links._reRenderTimeout);
                smart_links._reRenderTimeout = setTimeout(function() {
                    smart_links.debug('Smart Links: Re-rendering to update separator');
                    smart_links.add_integrated_chips(frm);
                }, 150);
            }
        });

        // Observe the attachments section - childList only, no subtree
        // This significantly reduces the number of mutation events
        smart_links._attachmentObserver.observe(attachmentsSection[0], {
            childList: true,
            subtree: false
        });
    };

    // ============================================================================
    // CREATE ATTACHMENT ROW (styled like Frappe attachments)
    // ============================================================================
    smart_links.create_attachment_row = function(frm, link) {
        if (!link || typeof link !== 'object') {
            return jQuery('<div></div>');
        }

        const escapeHtml = frappe.utils.escape_html || function(str) {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };

        const fileName = escapeHtml(link.file_name || 'Unknown');
        const fileId = link.file_id || '';
        const webViewLink = link.web_view_link || '';
        const fileType = link.file_type || 'File';
        const isFolder = fileType === 'Folder';
        let iconLink = link.icon_link || '';

        // Request higher resolution icon (64px)
        if (iconLink && iconLink.includes('/16/')) {
            iconLink = iconLink.replace('/16/', '/64/');
        }

        // Folder icon SVG (Google Drive folder style)
        const folderIconSvg = `<svg viewBox="0 0 24 24" width="16" height="16" style="margin-right: 4px;">
            <path fill="#5f6368" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
            <path fill="#1967d2" d="M10 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z" opacity="0.8"/>
        </svg>`;

        // Default Google Drive icon
        const defaultIconSvg = `<svg viewBox="0 0 24 24" width="14" height="14" fill="#4285f4" style="margin-right: 4px;"><path d="M7.71 3.5L1.15 15l3.43 6 3.43-6-3.43-6h6.85L7.71 3.5zm8.58 0l-3.43 6 3.43 6h-6.86l3.43-6 3.43-6zm-4.29 7.5l-3.43 6h6.86l3.43-6H12z"/></svg>`;

        // Determine which icon to use
        let iconHtml;
        if (isFolder) {
            iconHtml = folderIconSvg;
        } else if (iconLink) {
            iconHtml = `<img src="${iconLink}" alt="" width="16" height="16" style="margin-right: 4px;">`;
        } else {
            iconHtml = defaultIconSvg;
        }

        // Create row styled like Frappe's attachment rows
        const $row = jQuery(`
            <div class="gdrive-attachment-row attachment-row" data-file-id="${fileId}">
                <div class="ellipsis">
                    <span class="gdrive-attachment-icon">
                        ${iconHtml}
                    </span>
                    <a href="${webViewLink}" target="_blank" title="${fileName}" class="attachment-file-label ellipsis">
                        <span>${fileName}</span>
                    </a>
                </div>
                <div class="gdrive-attachment-actions">
                    <button class="btn btn-xs btn-link gdrive-copy-btn" title="${__('Copy link')}">
                        <svg class="icon icon-xs"><use href="#icon-link"></use></svg>
                    </button>
                    <button class="btn btn-xs btn-link gdrive-remove-btn" title="${__('Remove')}">
                        <svg class="icon icon-xs"><use href="#icon-close"></use></svg>
                    </button>
                </div>
            </div>
        `);

        // Bind copy link button
        $row.find('.gdrive-copy-btn').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            if (navigator.clipboard && webViewLink) {
                navigator.clipboard.writeText(webViewLink).then(function() {
                    frappe.show_alert({ message: __('Link copied'), indicator: 'green' });
                }).catch(function() {
                    frappe.show_alert({ message: __('Failed to copy'), indicator: 'red' });
                });
            } else {
                // Fallback for older browsers
                const temp = document.createElement('input');
                temp.value = webViewLink;
                document.body.appendChild(temp);
                temp.select();
                document.execCommand('copy');
                document.body.removeChild(temp);
                frappe.show_alert({ message: __('Link copied'), indicator: 'green' });
            }
        });

        // Bind remove button
        $row.find('.gdrive-remove-btn').on('click', function(e) {
            e.preventDefault();
            e.stopPropagation();

            frappe.confirm(__('Remove this Google Drive link?'), function() {
                $row.addClass('removing');

                frappe.call({
                    method: 'integration_hub.features.smart_links.api.remove_link',
                    args: {
                        doctype: frm.doctype,
                        docname: frm.docname,
                        file_id: fileId
                    },
                    callback: function(r) {
                        $row.remove();
                    }
                });
            });
        });

        return $row;
    };

    // ============================================================================
    // ADD SIDEBAR WIDGET (Separate Mode)
    // ============================================================================
    smart_links.add_widget = function(frm) {
        try {
            if (!frm || typeof frm !== 'object') return;

            // Debug: Check what sidebar references exist
            smart_links.debug('Smart Links: frm.sidebar exists?', !!frm.sidebar);
            smart_links.debug('Smart Links: frm.sidebar.sidebar exists?', frm.sidebar && !!frm.sidebar.sidebar);
            smart_links.debug('Smart Links: frm.page exists?', !!frm.page);
            smart_links.debug('Smart Links: frm.page.sidebar exists?', frm.page && !!frm.page.sidebar);

            // Find sidebar - try multiple approaches
            let sidebar = null;

            // Approach 1: frm.sidebar.sidebar (the jQuery element created in form_sidebar.js)
            if (frm.sidebar && frm.sidebar.sidebar && frm.sidebar.sidebar.length) {
                sidebar = frm.sidebar.sidebar;
                smart_links.debug('Smart Links: Using frm.sidebar.sidebar');
            }
            // Approach 2: frm.page.sidebar (the page's sidebar container)
            else if (frm.page && frm.page.sidebar) {
                sidebar = jQuery(frm.page.sidebar).find('.form-sidebar');
                if (!sidebar.length) {
                    sidebar = jQuery(frm.page.sidebar);
                }
                smart_links.debug('Smart Links: Using frm.page.sidebar, found:', sidebar.length);
            }
            // Approach 3: Direct DOM query
            else {
                sidebar = jQuery('.form-sidebar');
                smart_links.debug('Smart Links: Using direct DOM query, found:', sidebar.length);
            }

            if (!sidebar || !sidebar.length) {
                smart_links.debug('Smart Links: Sidebar not found after all attempts');
                return;
            }

            // Remove existing widget - scoped to this sidebar
            sidebar.find('.gdrive-link-section').remove();

            smart_links.debug('Smart Links: Sidebar HTML preview:', sidebar.html().substring(0, 200));

            // Get links
            const links = (frm.doc && frm.doc.smart_links) ? frm.doc.smart_links : [];
            
            // Create widget
            const widget = jQuery(`
                <div class="gdrive-link-section sidebar-section">
                    <div class="gdrive-link-header">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="#4285f4" style="margin-right:8px">
                            <path d="M7.71 3.5L1.15 15l3.43 6 3.43-6-3.43-6h6.85L7.71 3.5zm8.58 0l-3.43 6 3.43 6h-6.86l3.43-6 3.43-6zm-4.29 7.5l-3.43 6h6.86l3.43-6H12z"/>
                        </svg>
                        <span>Google Drive</span>
                        <span class="gdrive-count ${links.length ? '' : 'hidden'}">${links.length}</span>
                        ${links.length ? '<button class="gdrive-refresh-btn" title="Refresh file names"><i class="fa fa-refresh"></i></button>' : ''}
                    </div>
                    <div class="gdrive-chips-container"></div>
                    <input type="text" class="gdrive-paste-input" placeholder="Paste Drive link...">
                    <button class="gdrive-browse-btn">Browse Google Drive</button>
                </div>
            `);
            
            // Insert widget after attachments section
            const attachments = sidebar.find('.form-attachments');
            smart_links.debug('Smart Links: Found attachments section:', attachments.length);
            if (attachments.length) {
                attachments.after(widget);
                smart_links.debug('Smart Links: Widget inserted after attachments');
            } else {
                // Try form-tags as fallback (next section after attachments in sidebar)
                const tags = sidebar.find('.form-tags');
                if (tags.length) {
                    tags.before(widget);
                    smart_links.debug('Smart Links: Widget inserted before tags');
                } else {
                    sidebar.append(widget);
                    smart_links.debug('Smart Links: Widget appended to sidebar');
                }
            }
            
            // Render chips
            const container = widget.find('.gdrive-chips-container');
            if (container.length) {
                links.forEach(function(link) {
                    container.append(smart_links.create_chip(link));
                });
            }
            
            // Bind events - use .off() before .on() to prevent listener accumulation
            const pasteInput = widget.find('.gdrive-paste-input');
            if (pasteInput.length) {
                pasteInput.off('paste').on('paste', function(e) {
                    const url = (e.originalEvent.clipboardData || window.clipboardData).getData('text');
                    if (/drive\.google\.com|docs\.google\.com/.test(url)) {
                        e.preventDefault();
                        smart_links.add_link(frm, url, jQuery(this));
                    }
                });
            }

            const browseBtn = widget.find('.gdrive-browse-btn');
            if (browseBtn.length) {
                browseBtn.off('click').on('click', function() {
                    smart_links.show_file_browser(frm);
                });
            }

            const refreshBtn = widget.find('.gdrive-refresh-btn');
            if (refreshBtn.length) {
                refreshBtn.off('click').on('click', function() {
                    smart_links.refresh_file_names(frm, widget);
                });
            }

            if (container.length) {
                container.off('click', '.gdrive-chip').on('click', '.gdrive-chip', function(e) {
                    if (!jQuery(e.target).closest('.gdrive-chip-remove').length) {
                        const url = jQuery(this).data('url');
                        if (url) window.open(url, '_blank');
                    }
                });

                container.off('click', '.gdrive-chip-remove').on('click', '.gdrive-chip-remove', function(e) {
                    e.stopPropagation();
                    const chip = jQuery(this).closest('.gdrive-chip');
                    const fileId = chip.data('file-id');
                    smart_links.remove_link(frm, fileId, chip);
                });
            }
        } catch (e) {
            console.warn('Smart Links: Error adding widget', e);
        }
    };
    
    // ============================================================================
    // CREATE CHIP
    // ============================================================================
    smart_links.create_chip = function(link) {
        if (!link || typeof link !== 'object') {
            return jQuery('<div></div>');
        }

        const escapeHtml = frappe.utils.escape_html || function(str) {
            if (!str) return '';
            const div = document.createElement('div');
            div.textContent = str;
            return div.innerHTML;
        };

        const fileName = escapeHtml(link.file_name || 'Unknown');
        const fileId = link.file_id || '';
        const webViewLink = link.web_view_link || '';
        let iconLink = link.icon_link || '';

        // Request higher resolution icon from Google (64px instead of 16px)
        // Google icon URLs look like: https://drive-thirdparty.googleusercontent.com/16/type/...
        // We replace the /16/ with /64/ for crisp display on retina screens
        if (iconLink && iconLink.includes('/16/')) {
            iconLink = iconLink.replace('/16/', '/64/');
        }

        // Always use Google's icon - they provide icons for all file types
        const iconHtml = iconLink
            ? `<img src="${iconLink}" alt="" onerror="this.style.display='none'" />`
            : `<svg viewBox="0 0 24 24" fill="#5f6368"><path d="M14 2H6c-1.1 0-2 .9-2 2v16c0 1.1.9 2 2 2h12c1.1 0 2-.9 2-2V8l-6-6zM6 20V4h7v5h5v11H6z"/></svg>`;

        const $chip = jQuery(`
            <div class="gdrive-chip" data-file-id="${fileId}" data-url="${webViewLink}" title="${fileName}">
                <div class="gdrive-chip-icon">${iconHtml}</div>
                <span class="gdrive-chip-name">${fileName}</span>
                <button class="gdrive-chip-remove" title="Remove">×</button>
            </div>
        `);

        return $chip;
    };
    
    // ============================================================================
    // ADD LINK
    // ============================================================================
    smart_links.add_link = function(frm, url, input) {
        if (!frm || !frm.doctype || !frm.docname) return;
        if (!input || typeof input.prop !== 'function') return;
        
        input.prop('disabled', true).val('Loading...');
        
        frappe.call({
            method: 'integration_hub.features.smart_links.api.add_link',
            args: {
                doctype: frm.doctype,
                docname: frm.docname,
                url: url
            },
            callback: function(r) {
                if (r && r.message) {
                    frm.reload_doc();
                    frappe.show_alert({
                        message: __('Linked: {0}', [r.message.file_name || 'File']),
                        indicator: 'green'
                    });
                }
            },
            error: function() {
                input.prop('disabled', false).val('');
            },
            always: function() {
                input.prop('disabled', false).val('');
            }
        });
    };
    
    // ============================================================================
    // REMOVE LINK
    // ============================================================================
    smart_links.remove_link = function(frm, fileId, chip) {
        if (!frm || !frm.doctype || !frm.docname || !fileId) return;

        frappe.confirm(__('Remove this link?'), function() {
            if (chip && chip.length) {
                chip.addClass('removing');
            }

            frappe.call({
                method: 'integration_hub.features.smart_links.api.remove_link',
                args: {
                    doctype: frm.doctype,
                    docname: frm.docname,
                    file_id: fileId
                },
                callback: function(r) {
                    if (chip && chip.length) {
                        chip.remove();
                    }
                    // Update count - scoped to the widget containing the chip
                    const widget = chip ? chip.closest('.gdrive-link-section') : null;
                    if (widget && widget.length) {
                        const count = widget.find('.gdrive-chips-container .gdrive-chip').length;
                        const countEl = widget.find('.gdrive-count');
                        if (countEl.length) {
                            countEl.text(count).toggleClass('hidden', count === 0);
                        }
                        if (count === 0) {
                            widget.find('.gdrive-refresh-btn').remove();
                        }
                    }
                }
            });
        });
    };
    
    // ============================================================================
    // REFRESH FILE NAMES
    // ============================================================================
    smart_links.refresh_file_names = function(frm, widget) {
        if (!frm || !frm.doctype || !frm.docname) return;
        if (!widget || !widget.length) return;

        const btn = widget.find('.gdrive-refresh-btn');
        const icon = btn.find('i');

        if (!btn.length) return;

        btn.prop('disabled', true);
        if (icon.length) {
            icon.addClass('fa-spin');
        }

        frappe.call({
            method: 'integration_hub.features.smart_links.api.refresh_file_names',
            args: {
                doctype: frm.doctype,
                docname: frm.docname
            },
            callback: function(r) {
                if (r && r.message) {
                    const reloadPromise = (typeof frm.reload_doc === 'function' && frm.reload_doc().then)
                        ? frm.reload_doc()
                        : Promise.resolve();

                    reloadPromise.then(function() {
                        const container = widget.find('.gdrive-chips-container');
                        if (container.length) {
                            container.empty();
                            const links = (frm.doc && frm.doc.smart_links) ? frm.doc.smart_links : [];
                            links.forEach(function(link) {
                                container.append(smart_links.create_chip(link));
                            });
                            const count = links.length;
                            const countEl = widget.find('.gdrive-count');
                            if (countEl.length) {
                                countEl.text(count).toggleClass('hidden', count === 0);
                            }
                            if (count === 0 && btn.length) {
                                btn.remove();
                            }
                        }

                        if (typeof frappe !== 'undefined' && frappe.show_alert) {
                            frappe.show_alert({
                                message: r.message.message || __('Refreshed {0} file(s)', [r.message.updated || 0]),
                                indicator: 'green'
                            });
                        }
                    }).catch(function(err) {
                        smart_links.debug('Smart Links: Error reloading', err);
                    });
                }
            },
            error: function(r) {
                if (typeof frappe !== 'undefined' && frappe.msgprint) {
                    frappe.msgprint(__('Error: {0}', [r.message || 'Unknown error']));
                }
            },
            always: function() {
                if (btn.length) {
                    btn.prop('disabled', false);
                }
                if (icon.length) {
                    icon.removeClass('fa-spin');
                }
            }
        });
    };

    // ============================================================================
    // GOOGLE PICKER API - Native Google Drive File Picker
    // ============================================================================

    // Track if Picker API is loaded
    smart_links.picker_api_loaded = false;
    smart_links.picker_api_loading = false;
    smart_links.picker_config_cached = null;

    // Preload Picker API and config (called on page load for faster opening)
    smart_links.preload_picker_api = function() {
        smart_links.debug('Smart Links: Preloading Google Picker API...');

        // Load the Picker API script in background
        smart_links.load_picker_api(function() {
            smart_links.debug('Smart Links: Picker API preloaded');
        });

        // Also preload the picker config (access token, etc.)
        frappe.call({
            method: 'integration_hub.features.smart_links.api.get_picker_config',
            async: true,
            callback: function(r) {
                if (r && r.message) {
                    smart_links.picker_config_cached = r.message;
                    // Cache expires after 50 minutes (tokens typically expire in 60 min)
                    smart_links.picker_config_timestamp = Date.now();
                    smart_links.debug('Smart Links: Picker config preloaded');
                }
            }
        });
    };

    // Load Google Picker API - uses Promise pattern instead of setInterval polling
    smart_links.load_picker_api = function(callback) {
        if (smart_links.picker_api_loaded) {
            if (callback) callback();
            return;
        }

        // If already loading, wait for the existing promise
        if (smart_links.picker_api_loading && smart_links._pickerLoadPromise) {
            smart_links._pickerLoadPromise.then(function() {
                if (callback) callback();
            }).catch(function() {
                // Already handled in original promise
            });
            return;
        }

        smart_links.picker_api_loading = true;

        // Create a promise that resolves when the API loads
        smart_links._pickerLoadPromise = new Promise(function(resolve, reject) {
            const script = document.createElement('script');
            script.src = 'https://apis.google.com/js/api.js';
            script.onload = function() {
                gapi.load('picker', function() {
                    smart_links.picker_api_loaded = true;
                    smart_links.picker_api_loading = false;
                    smart_links.debug('Smart Links: Google Picker API loaded');
                    resolve();
                    if (callback) callback();
                });
            };
            script.onerror = function() {
                smart_links.picker_api_loading = false;
                console.error('Smart Links: Failed to load Google Picker API');
                frappe.msgprint(__('Failed to load Google Picker. Please check your internet connection.'));
                reject(new Error('Failed to load Google Picker API'));
            };
            document.head.appendChild(script);
        });
    };

    // Show Google Picker
    smart_links.show_file_browser = function(frm) {
        if (!frm || !frm.doctype || !frm.docname) {
            frappe.msgprint(__('Invalid document'));
            return;
        }

        // Check if document is saved (not new)
        if (frm.is_new() || !frm.docname || frm.docname.startsWith('new-')) {
            frappe.msgprint(__('Please save the document before adding Google Drive links'));
            return;
        }

        if (!smart_links.config || !smart_links.config.is_connected) {
            frappe.msgprint(__('Please authorize Google Drive first in GDrive Link Settings'));
            return;
        }

        // Check if we have a valid cached config (less than 50 minutes old)
        const cacheMaxAge = 50 * 60 * 1000; // 50 minutes in milliseconds
        const cacheValid = smart_links.picker_config_cached &&
            smart_links.picker_config_timestamp &&
            (Date.now() - smart_links.picker_config_timestamp) < cacheMaxAge;

        // If Picker API and config are both ready, open immediately
        if (smart_links.picker_api_loaded && cacheValid) {
            smart_links.debug('Smart Links: Opening picker immediately (preloaded)');
            smart_links.create_picker(frm, smart_links.picker_config_cached);
            return;
        }

        // Show loading only if we need to fetch something
        frappe.show_alert({ message: __('Loading Google Drive...'), indicator: 'blue' });

        // Load Picker API if not loaded
        smart_links.load_picker_api(function() {
            // Use cached config if valid, otherwise fetch fresh
            if (cacheValid) {
                smart_links.create_picker(frm, smart_links.picker_config_cached);
            } else {
                // Get picker configuration from server
                frappe.call({
                    method: 'integration_hub.features.smart_links.api.get_picker_config',
                    callback: function(r) {
                        if (r && r.message) {
                            // Update cache
                            smart_links.picker_config_cached = r.message;
                            smart_links.picker_config_timestamp = Date.now();
                            smart_links.create_picker(frm, r.message);
                        }
                    },
                    error: function(r) {
                        frappe.msgprint(__('Failed to initialize Google Picker. Please check settings.'));
                    }
                });
            }
        });
    };

    // Create and show the Google Picker
    smart_links.create_picker = function(frm, config) {
        if (!window.google || !google.picker) {
            frappe.msgprint(__('Google Picker API not available'));
            return;
        }

        try {
            // Recent files (default - most useful for quick access)
            const recentView = new google.picker.DocsView(google.picker.ViewId.RECENTLY_PICKED);

            // My Drive - all files
            const myDriveView = new google.picker.DocsView(google.picker.ViewId.DOCS)
                .setIncludeFolders(true)
                .setSelectFolderEnabled(true)
                .setOwnedByMe(true);

            // Shared with me
            const sharedWithMeView = new google.picker.DocsView(google.picker.ViewId.DOCS)
                .setIncludeFolders(true)
                .setSelectFolderEnabled(true)
                .setOwnedByMe(false);

            // Shared Drives
            const sharedDrivesView = new google.picker.DocsView(google.picker.ViewId.DOCS)
                .setIncludeFolders(true)
                .setSelectFolderEnabled(true)
                .setEnableDrives(true);

            // Build the picker - Recent first
            const picker = new google.picker.PickerBuilder()
                .setAppId(config.app_id)
                .setDeveloperKey(config.api_key)
                .setOAuthToken(config.access_token)
                .addView(recentView)
                .addView(myDriveView)
                .addView(sharedWithMeView)
                .addView(sharedDrivesView)
                .enableFeature(google.picker.Feature.MULTISELECT_ENABLED)
                .enableFeature(google.picker.Feature.SUPPORT_DRIVES)
                .setTitle(__('Select files from Google Drive'))
                .setCallback(function(data) {
                    smart_links.picker_callback(frm, data);
                })
                .build();

            picker.setVisible(true);

        } catch (e) {
            console.error('Smart Links: Error creating picker', e);
            frappe.msgprint(__('Error creating file picker: {0}', [e.message]));
        }
    };

    // Handle picker callback
    smart_links.picker_callback = function(frm, data) {
        if (data.action === google.picker.Action.PICKED) {
            const files = data.docs || [];

            if (files.length === 0) {
                return;
            }

            // Show progress
            frappe.show_alert({
                message: __('Linking {0} file(s)...', [files.length]),
                indicator: 'blue'
            });

            // Use batch API for efficient multi-file linking (single request)
            frappe.call({
                method: 'integration_hub.features.smart_links.api.add_links_batch',
                args: {
                    doctype: frm.doctype,
                    docname: frm.docname,
                    file_ids: files.map(function(f) { return f.id; })
                },
                callback: function(r) {
                    if (r && r.message) {
                        const linkedCount = (r.message.linked || []).length;
                        const errors = r.message.errors || [];

                        if (linkedCount > 0) {
                            frappe.show_alert({
                                message: __('Linked {0} file(s)', [linkedCount]),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }

                        if (errors.length > 0) {
                            const errorMessages = errors.map(function(e) {
                                return e.file_id + ': ' + e.error;
                            });
                            frappe.msgprint({
                                title: __('Some files could not be linked'),
                                message: errorMessages.join('<br>'),
                                indicator: 'orange'
                            });
                        }
                    }
                },
                error: function(r) {
                    // Check for auth errors and clear cached config
                    if (r && r.exc_type && r.exc_type.includes('AuthenticationError')) {
                        smart_links.picker_config_cached = null;
                        smart_links.picker_config_timestamp = null;
                    }
                    frappe.msgprint(__('Error linking files. Please try again.'));
                }
            });

        } else if (data.action === google.picker.Action.CANCEL) {
            // User cancelled - do nothing
            smart_links.debug('Smart Links: Picker cancelled');
        }
    };

    // ============================================================================
    // FALLBACK: URL Paste Dialog (when Picker not available)
    // ============================================================================
    smart_links.show_url_dialog = function(frm) {
        const dialog = new frappe.ui.Dialog({
            title: __('Link Google Drive File'),
            fields: [
                {
                    fieldname: 'url',
                    fieldtype: 'Data',
                    label: __('Google Drive URL'),
                    description: __('Paste a Google Drive file URL'),
                    reqd: 1
                }
            ],
            primary_action_label: __('Link'),
            primary_action: function() {
                const url = dialog.get_value('url');
                if (!url) return;

                // Check if it's a valid Google Drive URL
                if (!/drive\.google\.com|docs\.google\.com/.test(url)) {
                    frappe.msgprint(__('Please enter a valid Google Drive URL'));
                    return;
                }

                dialog.disable_primary_action();

                frappe.call({
                    method: 'integration_hub.features.smart_links.api.add_link',
                    args: {
                        doctype: frm.doctype,
                        docname: frm.docname,
                        url: url
                    },
                    callback: function(r) {
                        if (r && r.message) {
                            dialog.hide();
                            frappe.show_alert({
                                message: __('Linked: {0}', [r.message.file_name]),
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    },
                    error: function() {
                        dialog.enable_primary_action();
                    }
                });
            }
        });

        dialog.show();
    };

})();
