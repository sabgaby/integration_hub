# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
Smart Links module - redirects to features.smart_links for backward compatibility.
This allows Frappe to find the module when loading doctypes with module="Smart Links".
"""

# This module exists to satisfy Frappe's module resolution when it looks for
# integration_hub.smart_links based on the module name "Smart Links" in doctype JSON files.
# The actual implementation is in integration_hub.features.smart_links

__all__ = []
