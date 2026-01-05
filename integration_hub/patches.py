# Copyright (c) 2024, Swiss Cluster AG and contributors
# For license information, please see license.txt

"""
Patch to fix namespace package import issue for integration_hub.
This ensures Frappe can find the app even when it's imported as a namespace package.
"""

import frappe
import os
import sys


def patch_get_module():
	"""Patch Frappe's get_module to handle namespace packages."""
	original_get_module = frappe.get_module
	
	def patched_get_module(modulename):
		"""Enhanced get_module that handles namespace packages."""
		# Skip patching for google_workspace - it no longer exists
		if modulename == 'google_workspace' or modulename.startswith('google_workspace.'):
			raise ImportError(f"No module named '{modulename}'")
		
		# Redirect integration_hub.smart_links.doctype.* to integration_hub.doctype.*
		# because doctypes are in integration_hub/doctype/, not integration_hub/smart_links/doctype/
		if modulename.startswith('integration_hub.smart_links.doctype.'):
			redirected_name = modulename.replace('integration_hub.smart_links.doctype.', 'integration_hub.doctype.', 1)
			try:
				return original_get_module(redirected_name)
			except (ImportError, ModuleNotFoundError):
				# If redirect fails, fall through to try original
				pass
		
		# Redirect integration_hub.smart_links.* to integration_hub.features.smart_links.*
		# for other smart_links imports (like api, utils, etc.)
		if modulename.startswith('integration_hub.smart_links.') and not modulename.startswith('integration_hub.smart_links.doctype.'):
			redirected_name = modulename.replace('integration_hub.smart_links.', 'integration_hub.features.smart_links.', 1)
			try:
				return original_get_module(redirected_name)
			except (ImportError, ModuleNotFoundError):
				# If redirect fails, fall through to try original
				pass
		
		try:
			module = original_get_module(modulename)
			# If module has no __file__ (namespace package), try to find it
			if module and (not hasattr(module, '__file__') or module.__file__ is None):
				if hasattr(module, '__path__'):
					# Search __path__ for the actual package
					for path in module.__path__:
						# Check if there's a subdirectory matching the module name
						subdir = os.path.join(path, modulename.split('.')[-1])
						init_file = os.path.join(subdir, '__init__.py')
						if os.path.exists(init_file):
							# Set __file__ so Frappe can use it
							module.__file__ = init_file
							break
			return module
		except (ImportError, ModuleNotFoundError) as e:
			# If it's google_workspace, don't retry
			if 'google_workspace' in str(modulename):
				raise ImportError(f"No module named '{modulename}'")
			# Re-raise the original exception - don't retry with original_get_module
			# as it will just fail again
			raise
	
	frappe.get_module = patched_get_module


# This will be called when the app is imported
try:
	patch_get_module()
except Exception:
	pass
