"""Validation utilities for youtube_crypto package"""

from typing import List


def validate_required_fields(data: dict, required_fields: List[str]) -> None:
    """
    Validate that all required fields are present and non-null in data.

    Args:
        data: Dictionary to validate
        required_fields: List of field names that must be present

    Raises:
        ValueError: If any required field is missing or None
    """
    for field in required_fields:
        if field not in data:
            raise ValueError(f"Missing required field: {field}")
        if data[field] is None:
            raise ValueError(f"Required field cannot be None: {field}")
