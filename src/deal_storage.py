"""
Storage for deal analyses - persists analysis results to JSON.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import uuid

from .deal_analysis import DealAnalysisResult

logger = logging.getLogger(__name__)

# Storage file path
DATA_DIR = Path(__file__).parent.parent / "data"
STORAGE_FILE = DATA_DIR / "deal_analyses.json"


def _ensure_data_dir() -> None:
    """Ensure data directory exists."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def _load_storage() -> Dict[str, Any]:
    """Load storage from disk."""
    _ensure_data_dir()
    if STORAGE_FILE.exists():
        try:
            with STORAGE_FILE.open("r") as f:
                return json.load(f)
        except Exception as e:
            logger.error("Failed to load deal analyses: %s", e)
            return {"analyses": {}}
    return {"analyses": {}}


def _save_storage(storage: Dict[str, Any]) -> None:
    """Save storage to disk."""
    _ensure_data_dir()
    try:
        with STORAGE_FILE.open("w") as f:
            json.dump(storage, f, indent=2, default=str)
    except Exception as e:
        logger.error("Failed to save deal analyses: %s", e)


def save_deal_analysis(result: DealAnalysisResult) -> str:
    """
    Save a deal analysis result.

    Args:
        result: Deal analysis result to save

    Returns:
        Analysis ID
    """
    storage = _load_storage()

    # Generate unique ID
    analysis_id = str(uuid.uuid4())[:8]

    # Convert to dict and add metadata
    data = result.to_dict()
    data["id"] = analysis_id
    data["saved_at"] = datetime.now().isoformat()

    # Store by ID
    storage["analyses"][analysis_id] = data
    _save_storage(storage)

    logger.info("Saved deal analysis %s for artist %s", analysis_id, result.request.artist_name)
    return analysis_id


def load_deal_analysis(analysis_id: str) -> Optional[DealAnalysisResult]:
    """
    Load a specific deal analysis by ID.

    Args:
        analysis_id: Analysis ID

    Returns:
        Deal analysis result or None if not found
    """
    storage = _load_storage()
    data = storage["analyses"].get(analysis_id)

    if data is None:
        return None

    try:
        return DealAnalysisResult.from_dict(data)
    except Exception as e:
        logger.error("Failed to parse deal analysis %s: %s", analysis_id, e)
        return None


def load_all_analyses() -> List[Dict[str, Any]]:
    """
    Load all saved analyses.

    Returns:
        List of analysis dictionaries with metadata
    """
    storage = _load_storage()
    analyses = list(storage["analyses"].values())

    # Sort by saved_at descending (most recent first)
    analyses.sort(key=lambda x: x.get("saved_at", ""), reverse=True)

    return analyses


def get_analyses_for_artist(artist_id: str) -> List[Dict[str, Any]]:
    """
    Get all analyses for a specific artist.

    Args:
        artist_id: Sodatone artist ID

    Returns:
        List of analysis dictionaries for the artist
    """
    all_analyses = load_all_analyses()
    return [
        a for a in all_analyses
        if a.get("request", {}).get("artist_id") == artist_id
    ]


def delete_analysis(analysis_id: str) -> bool:
    """
    Delete a deal analysis.

    Args:
        analysis_id: Analysis ID to delete

    Returns:
        True if deleted, False if not found
    """
    storage = _load_storage()

    if analysis_id not in storage["analyses"]:
        return False

    del storage["analyses"][analysis_id]
    _save_storage(storage)

    logger.info("Deleted deal analysis %s", analysis_id)
    return True


def get_analyses_summary() -> List[Dict[str, Any]]:
    """
    Get a summary of all analyses (for listing).

    Returns:
        List of summary dictionaries with key fields
    """
    all_analyses = load_all_analyses()
    summaries = []

    for a in all_analyses:
        request = a.get("request", {})
        pricing = a.get("pricing", {})
        label_metrics = a.get("label_metrics", {})

        summaries.append({
            "id": a.get("id"),
            "artist_id": request.get("artist_id"),
            "artist_name": request.get("artist_name"),
            "genre": request.get("genre"),
            "deal_type": request.get("deal_type"),
            "deal_percent": request.get("deal_percent"),
            "irr_15_max_cost": pricing.get("irr_15_max_cost", 0),
            "label_irr": label_metrics.get("label_irr"),
            "label_moic": label_metrics.get("label_moic"),
            "saved_at": a.get("saved_at"),
            "analysis_timestamp": a.get("analysis_timestamp"),
        })

    return summaries


def clear_all_analyses() -> None:
    """Clear all saved analyses."""
    storage = {"analyses": {}}
    _save_storage(storage)
    logger.info("Cleared all deal analyses")
