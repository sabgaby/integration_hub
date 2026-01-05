__version__ = "0.0.1"

# Apply patch for namespace package support
try:
	from integration_hub.patches import patch_get_module
	patch_get_module()
except Exception:
	pass
