frappe.query_reports["All Smart Links"] = {
    filters: [
        {
            fieldname: "doctype",
            label: __("Document Type"),
            fieldtype: "Link",
            options: "DocType",
            get_query: function() {
                return {
                    filters: {
                        name: ["in", frappe.boot.smart_links_enabled_doctypes || []]
                    }
                };
            }
        },
        {
            fieldname: "added_by",
            label: __("Added By"),
            fieldtype: "Link",
            options: "User"
        },
        {
            fieldname: "file_type",
            label: __("File Type"),
            fieldtype: "Select",
            options: "\nFile\nFolder\nDocument\nSpreadsheet\nPresentation\nPDF\nImage"
        },
        {
            fieldname: "from_date",
            label: __("From Date"),
            fieldtype: "Date"
        },
        {
            fieldname: "to_date",
            label: __("To Date"),
            fieldtype: "Date"
        }
    ],

    onload: function(report) {
        // Load enabled doctypes for the filter
        frappe.call({
            method: "integration_hub.features.smart_links.api.get_config",
            callback: function(r) {
                if (r.message && r.message.enabled_doctypes) {
                    frappe.boot.smart_links_enabled_doctypes = r.message.enabled_doctypes;
                }
            }
        });
    }
};
