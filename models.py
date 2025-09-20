from pydantic import BaseModel
from typing import Optional, Literal
from datetime import datetime


class SearchRequest(BaseModel):
    query: str
    depth: Literal["fast", "standard", "deep"] = "standard"
    exclude_marketplaces: bool = True
    min_days: int = 0
    min_active_ads: int = 0


class AdData(BaseModel):
    ad_id: Optional[str] = None
    advertiser_name: Optional[str] = None
    advertiser_url: Optional[str] = None
    landing_url: Optional[str] = None
    headline: Optional[str] = None
    text: Optional[str] = None
    media_type: str = "unknown"
    start_date: Optional[str] = None
    days_active: int = 0
    active_status: str = "active"
    variations_count: int = 1
    advertiser_active_ads_est: int = 0
    is_probable_dropshipping: bool = False
    exclusion_reason: Optional[str] = None
    score: float = 0.0
    ad_library_result_url: Optional[str] = None


class AdOut(BaseModel):
    query: str
    country: str = "BR"
    ad: AdData


class SearchResponse(BaseModel):
    results: list[AdOut] = []
    needs_manual_solve: bool = False
    message: Optional[str] = None


class HealthResponse(BaseModel):
    status: str
    timestamp: datetime