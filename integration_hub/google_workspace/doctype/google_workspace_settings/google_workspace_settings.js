// Copyright (c) 2024, Swiss Cluster AG and contributors
// For license information, please see license.txt

frappe.ui.form.on('Google Workspace Settings', {
	refresh: function(frm) {
		if (frm.doc.enabled && frm.doc.client_id && frm.doc.client_secret) {
			// Check connection status and add appropriate button
			frappe.call({
				method: 'integration_hub.oauth.get_connection_status',
				callback: function(r) {
					if (r.message) {
						if (r.message.is_connected) {
							// Show connected status and disconnect button
							frm.dashboard.set_headline(
								__('Connected to Google Workspace'),
								'green'
							);
							frm.add_custom_button(__('Disconnect'), function() {
								frappe.confirm(
									__('Are you sure you want to disconnect from Google Workspace?'),
									function() {
										frappe.call({
											method: 'integration_hub.oauth.disconnect',
											callback: function(r) {
												if (r.message) {
													frappe.show_alert({
														message: __('Disconnected from Google Workspace'),
														indicator: 'green'
													});
													frm.reload_doc();
												}
											}
										});
									}
								);
							}, __('Actions'));
						} else {
							// Show authorize button
							frm.dashboard.set_headline(
								__('Not connected to Google Workspace'),
								'orange'
							);
							frm.add_custom_button(__('Authorize with Google'), function() {
								frappe.call({
									method: 'integration_hub.oauth.get_authorization_url',
									callback: function(r) {
										if (r.message) {
											// Open Google OAuth in same window
											window.location.href = r.message;
										}
									}
								});
							}, __('Actions'));
						}
					}
				}
			});
		} else if (!frm.doc.enabled) {
			frm.dashboard.set_headline(
				__('Google Workspace integration is disabled'),
				'grey'
			);
		} else {
			frm.dashboard.set_headline(
				__('Please configure Client ID and Client Secret'),
				'orange'
			);
		}

		// Check if we just completed authorization
		const urlParams = new URLSearchParams(window.location.search);
		if (urlParams.get('authorized') === '1') {
			frappe.show_alert({
				message: __('Successfully authorized with Google Workspace!'),
				indicator: 'green'
			}, 5);
			// Clean up URL
			window.history.replaceState({}, document.title, window.location.pathname);
		}
	}
});
