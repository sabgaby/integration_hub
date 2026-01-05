import re
from typing import Optional

# URL patterns for different Google Drive URL types
# Order matters - more specific patterns should come first
PATTERNS = {
    'file': [
        r'drive\.google\.com/file/d/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/open\?id=([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/uc\?.*id=([a-zA-Z0-9_-]+)',  # Direct download links
    ],
    'folder': [
        r'drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/drive/u/\d+/folders/([a-zA-Z0-9_-]+)',
        r'drive\.google\.com/corp/drive/folders/([a-zA-Z0-9_-]+)',  # Workspace domains
    ],
    'document': [
        r'docs\.google\.com/document/d/([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/document/u/\d+/d/([a-zA-Z0-9_-]+)',
    ],
    'spreadsheet': [
        r'docs\.google\.com/spreadsheets/d/([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/spreadsheets/u/\d+/d/([a-zA-Z0-9_-]+)',
    ],
    'presentation': [
        r'docs\.google\.com/presentation/d/([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/presentation/u/\d+/d/([a-zA-Z0-9_-]+)',
    ],
    'form': [
        r'docs\.google\.com/forms/d/([a-zA-Z0-9_-]+)',
        r'docs\.google\.com/forms/u/\d+/d/([a-zA-Z0-9_-]+)',
    ],
    'drawing': [
        r'docs\.google\.com/drawings/d/([a-zA-Z0-9_-]+)',
    ],
}


def extract_file_id(url: str) -> Optional[str]:
    """
    Extract Google Drive file ID from URL.
    
    Args:
        url: Google Drive URL
        
    Returns:
        File ID or None if not found
    """
    for patterns in PATTERNS.values():
        for pattern in patterns:
            match = re.search(pattern, url)
            if match:
                return match.group(1)
    return None


def is_gdrive_url(url: str) -> bool:
    """Check if URL is a valid Google Drive URL."""
    return extract_file_id(url) is not None

