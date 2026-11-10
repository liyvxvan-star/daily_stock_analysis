"""Manual source-selected snapshot generation and read-only sentiment history."""

from __future__ import annotations

from datetime import date
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from api.deps import get_config_dep, get_db
from api.v1.schemas.sentiment import (
    SentimentGenerateResponse, SentimentListResponse,
    SentimentSnapshotItem, SentimentTrendResponse,
)
from src.data.csmar_daily import CsmarSourceError
from src.config import Config
from src.repositories.sentiment_repo import (
    SentimentRepository, SentimentSnapshotConflict, public_snapshot,
)
from src.services.sentiment_snapshot_service import MARKET, generate_snapshot
from src.services.eastmoney_sentiment import EASTMONEY_MARKET, generate_eastmoney_snapshot


logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/snapshots/{trade_date}/generate", response_model=SentimentGenerateResponse)
def generate_sentiment_snapshot(
    trade_date: date,
    source: Literal["csmar", "eastmoney"] = "csmar",
    session: Session = Depends(get_db),
    config: Config = Depends(get_config_dep),
) -> SentimentGenerateResponse:
    """Read the chosen source only after an explicit API request."""
    if source == "csmar" and not config.csmar_zip_path:
        raise HTTPException(
            status_code=409,
            detail={"error": "source_not_configured", "message": "CSMAR_ZIP_PATH is not configured"},
        )
    try:
        if source == "eastmoney":
            action, record = generate_eastmoney_snapshot(session, trade_date)
        else:
            action, record = generate_snapshot(
                session, source_zip=Path(config.csmar_zip_path), trade_date=trade_date,
            )
    except CsmarSourceError as exc:
        raise HTTPException(
            status_code=422, detail={"error": "source_unavailable", "message": str(exc)},
        ) from exc
    except SentimentSnapshotConflict as exc:
        raise HTTPException(
            status_code=409, detail={"error": "snapshot_conflict", "message": str(exc)},
        ) from exc
    except Exception as exc:
        # Database and workbook exceptions may contain local paths or licensed rows.
        logger.error("Sentiment snapshot generation failed for %s (%s)", trade_date, type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"error": "internal_error", "message": "Sentiment snapshot generation failed"},
        )
    return SentimentGenerateResponse(action=action, snapshot=public_snapshot(record))


@router.get("/snapshots", response_model=SentimentListResponse)
def list_sentiment_snapshots(
    source: Literal["csmar", "eastmoney"] = "csmar",
    end_date: date | None = None,
    limit: int = Query(30, ge=1, le=120),
    session: Session = Depends(get_db),
) -> SentimentListResponse:
    records = SentimentRepository(session).list(EASTMONEY_MARKET if source == "eastmoney" else MARKET, end_date=end_date, limit=limit)
    return SentimentListResponse(items=[public_snapshot(record) for record in records])


@router.get("/snapshots/{trade_date}", response_model=SentimentSnapshotItem)
def get_sentiment_snapshot(
    trade_date: date,
    source: Literal["csmar", "eastmoney"] = "csmar",
    session: Session = Depends(get_db),
) -> SentimentSnapshotItem:
    record = SentimentRepository(session).get(EASTMONEY_MARKET if source == "eastmoney" else MARKET, trade_date)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found", "message": "Sentiment snapshot not found"},
        )
    return SentimentSnapshotItem.model_validate(public_snapshot(record))


@router.get("/trend", response_model=SentimentTrendResponse)
def get_sentiment_trend(
    end_date: date,
    source: Literal["csmar", "eastmoney"] = "csmar",
    limit: int = Query(30, ge=1, le=120),
    session: Session = Depends(get_db),
) -> SentimentTrendResponse:
    records = SentimentRepository(session).list(EASTMONEY_MARKET if source == "eastmoney" else MARKET, end_date=end_date, limit=limit)
    return SentimentTrendResponse(
        end_date=end_date,
        items=[public_snapshot(record) for record in reversed(records)],
    )
