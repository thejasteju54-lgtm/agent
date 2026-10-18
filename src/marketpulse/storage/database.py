"""Database connection management and initialization for MarketPulse AI."""

import os
from contextlib import contextmanager
from typing import Generator, Optional
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from marketpulse.config import mp_settings
from marketpulse.storage.models import Base, Company, Sector, SourceRegistry, ScheduleDefinition


def _build_engine(url: Optional[str] = None) -> Engine:
    """Create configured SQLAlchemy engine for PostgreSQL or SQLite."""
    db_url = url or mp_settings.database_url

    connect_args = {}
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        connect_args["timeout"] = 15.0

        # Auto-create SQLite parent directory
        clean_path = db_url.replace("sqlite:///", "").replace("sqlite://", "")
        if clean_path and clean_path != ":memory:":
            try:
                from pathlib import Path
                Path(clean_path).resolve().parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass

    engine = create_engine(
        db_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )

    # Enable SQLite WAL and foreign key constraints
    if db_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
            except Exception:
                pass
            finally:
                cursor.close()

    return engine


_DEFAULT_ENGINE: Optional[Engine] = None
_SESSION_FACTORY: Optional[sessionmaker] = None


def get_engine(url: Optional[str] = None) -> Engine:
    """Retrieve or build singleton database engine."""
    global _DEFAULT_ENGINE, _SESSION_FACTORY
    target_url = url or mp_settings.database_url
    if _DEFAULT_ENGINE is None or str(_DEFAULT_ENGINE.url) != target_url:
        _DEFAULT_ENGINE = _build_engine(target_url)
        _SESSION_FACTORY = sessionmaker(bind=_DEFAULT_ENGINE, autoflush=False, autocommit=False)
    return _DEFAULT_ENGINE


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker:
    """Retrieve session factory."""
    global _SESSION_FACTORY
    eng = engine or get_engine()
    if _SESSION_FACTORY is None or _SESSION_FACTORY.kw.get("bind") != eng:
        _SESSION_FACTORY = sessionmaker(bind=eng, autoflush=False, autocommit=False)
    return _SESSION_FACTORY


@contextmanager
def get_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """Context manager for scoped SQLAlchemy session with auto-rollback on error."""
    factory = get_session_factory(engine)
    session: Session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(engine: Optional[Engine] = None) -> None:
    """Create all MarketPulse database tables and apply pending schema migrations."""
    from marketpulse.storage.migrations import apply_migrations

    eng = engine or get_engine()
    apply_migrations(eng)


def seed_initial_registry(session: Session) -> None:
    """Idempotently seed standard Indian market sectors, companies, and approved sources."""
    # 1. Standard Nifty Sectors
    sectors_data = [
        ("NIFTY_IT", "Information Technology", "Indian IT services and software technology companies"),
        ("NIFTY_BANK", "Banking & Financials", "Public and private Indian commercial banks"),
        ("NIFTY_AUTO", "Automobile", "Four-wheeler, two-wheeler, and commercial vehicle manufacturers"),
        ("NIFTY_PHARMA", "Pharmaceuticals", "Formulations, generics, and active pharmaceutical ingredients"),
        ("NIFTY_ENERGY", "Energy & Power", "Oil, gas, petrochemicals, power generation, and renewables"),
        ("NIFTY_FMCG", "Fast Moving Consumer Goods", "Consumer household, food, and beverage staples"),
        ("NIFTY_METAL", "Metals & Mining", "Steel, aluminum, zinc, and mining conglomerates"),
    ]

    sector_map = {}
    for code, name, desc in sectors_data:
        existing = session.query(Sector).filter_by(code=code).first()
        if not existing:
            sector_obj = Sector(code=code, name=name, description=desc)
            session.add(sector_obj)
            session.flush()
            sector_map[code] = sector_obj
        else:
            sector_map[code] = existing

    # 2. Key Listed Companies (NSE / BSE Marquee)
    companies_data = [
        ("RELIANCE", "Reliance Industries Limited", "INE002A01018", "500325", "NIFTY_ENERGY", "LARGE_CAP"),
        ("TCS", "Tata Consultancy Services Limited", "INE467B01029", "532540", "NIFTY_IT", "LARGE_CAP"),
        ("HDFCBANK", "HDFC Bank Limited", "INE040A01034", "500180", "NIFTY_BANK", "LARGE_CAP"),
        ("INFY", "Infosys Limited", "INE009A01021", "500209", "NIFTY_IT", "LARGE_CAP"),
        ("ICICIBANK", "ICICI Bank Limited", "INE090A01021", "532174", "NIFTY_BANK", "LARGE_CAP"),
        ("SBIN", "State Bank of India", "INE062A01020", "500112", "NIFTY_BANK", "LARGE_CAP"),
        ("BHARTIARTL", "Bharti Airtel Limited", "INE397D01024", "532454", "NIFTY_IT", "LARGE_CAP"),
        ("ITC", "ITC Limited", "INE154A01025", "500875", "NIFTY_FMCG", "LARGE_CAP"),
        ("LT", "Larsen & Toubro Limited", "INE018A01030", "500510", "NIFTY_ENERGY", "LARGE_CAP"),
        ("MARUTI", "Maruti Suzuki India Limited", "INE585B01010", "532500", "NIFTY_AUTO", "LARGE_CAP"),
        ("SUNPHARMA", "Sun Pharmaceutical Industries Limited", "INE044A01036", "524715", "NIFTY_PHARMA", "LARGE_CAP"),
        ("TATASTEEL", "Tata Steel Limited", "INE081A01020", "500470", "NIFTY_METAL", "LARGE_CAP"),
    ]

    for sym, name, isin, bse, sec_code, cap in companies_data:
        existing = session.query(Company).filter_by(symbol=sym).first()
        if not existing:
            sec = sector_map.get(sec_code)
            session.add(
                Company(
                    symbol=sym,
                    name=name,
                    isin=isin,
                    bse_code=bse,
                    sector_id=sec.id if sec else None,
                    market_cap_tier=cap,
                )
            )

    # 3. Approved Sources
    sources_data = [
        (
            "bse_disclosures",
            "BSE Corporate Announcements",
            "OFFICIAL_DISCLOSURE",
            "https://www.bseindia.com",
            "https://www.bseindia.com/corporates/ann.html",
            "PUBLIC_FEED",
            "HTTP_GET",
            "NONE",
            20,
            "bse_announcement_parser",
            24,
            1.0,
            "Permitted official corporate filing portal for BSE listed entities",
        ),
        (
            "nse_circulars",
            "NSE Circulars & Corporate Filings",
            "OFFICIAL_DISCLOSURE",
            "https://www.nseindia.com",
            "https://www.nseindia.com/companies-listing/corporate-filings",
            "PUBLIC_FEED",
            "HTTP_GET",
            "NONE",
            20,
            "nse_circular_parser",
            24,
            1.0,
            "Official regulatory and listing disclosure portal of NSE India",
        ),
        (
            "sebi_press_releases",
            "SEBI Regulatory Orders & Press Releases",
            "REGULATORY_FEED",
            "https://www.sebi.gov.in",
            "https://www.sebi.gov.in/sebiweb/home/list/3/13/0/0/PR",
            "PUBLIC_FEED",
            "HTTP_GET",
            "NONE",
            30,
            "sebi_pr_parser",
            48,
            1.0,
            "Statutory securities market regulator publications and adjudications",
        ),
        (
            "rbi_press_releases",
            "Reserve Bank of India Press Releases",
            "REGULATORY_FEED",
            "https://www.rbi.org.in",
            "https://www.rbi.org.in/pressreleases_rss.xml",
            "PUBLIC_FEED",
            "RSS_FEED",
            "NONE",
            30,
            "rss_feed_parser",
            24,
            1.0,
            "Official central bank monetary policy and banking sector disclosures",
        ),
        (
            "permitted_financial_rss",
            "Permitted Indian Financial News RSS",
            "PERMITTED_NEWS_RSS",
            "https://economictimes.indiatimes.com",
            "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
            "PUBLIC_FEED",
            "RSS_FEED",
            "NONE",
            60,
            "rss_feed_parser",
            12,
            0.85,
            "Permitted public RSS syndication feed for market developments",
        ),
    ]

    for s_id, s_name, s_type, base, feed, acc_type, ret_m, auth_req, r_limit, p_name, fresh_h, rel, notes in sources_data:
        existing = session.query(SourceRegistry).filter_by(id=s_id).first()
        if not existing:
            session.add(
                SourceRegistry(
                    id=s_id,
                    name=s_name,
                    source_type=s_type,
                    base_url=base,
                    feed_url=feed,
                    access_type=acc_type,
                    retrieval_method=ret_m,
                    auth_required=auth_req,
                    rate_limit_per_minute=r_limit,
                    parser_name=p_name,
                    freshness_max_age_hours=fresh_h,
                    reliability_score=rel,
                    licensing_notes=notes,
                )
            )
        else:
            existing.retrieval_method = ret_m
            existing.auth_required = auth_req
            existing.rate_limit_per_minute = r_limit
            existing.parser_name = p_name
            existing.freshness_max_age_hours = fresh_h
            existing.reliability_score = rel
            existing.feed_url = feed

    # 4. Initial Permitted Automation Schedules
    schedules_data = [
        (
            "daily_market_brief",
            "Daily Indian Market Pre-Session Brief",
            "CRON",
            "30 8 * * 1-5",
            "Asia/Kolkata",
            "MARKET_BRIEF",
            None,
            "Generate Indian market pre-session brief with IST trading calendar",
            True,
            False,
        ),
        (
            "news_polling",
            "Continuous Regulatory & Permitted RSS Polling",
            "INTERVAL_MINUTES",
            "*/15 * * * *",
            "Asia/Kolkata",
            "NEWS_POLLING",
            None,
            "Poll approved financial news and regulatory feeds for fresh disclosures",
            True,
            False,
        ),
        (
            "watchlist_evaluation",
            "Watchlist Material Disclosure Evaluation",
            "INTERVAL_MINUTES",
            "*/30 * * * *",
            "Asia/Kolkata",
            "WATCHLIST_EVALUATION",
            None,
            "Evaluate recent disclosures against monitored symbols and trigger alert events",
            True,
            False,
        ),
        (
            "on_demand_research",
            "On-Demand Company Research Template",
            "ON_DEMAND",
            None,
            "Asia/Kolkata",
            "RESEARCH",
            "RELIANCE",
            "Perform deep financial research and scenario analysis for listed ticker",
            True,
            False,
        ),
    ]

    for sch_id, sch_name, sch_type, cron_exp, tz, task_t, sym, prompt, active, dry_run in schedules_data:
        existing_sch = session.query(ScheduleDefinition).filter_by(id=sch_id).first()
        if not existing_sch:
            session.add(
                ScheduleDefinition(
                    id=sch_id,
                    name=sch_name,
                    schedule_type=sch_type,
                    cron_expression=cron_exp,
                    timezone=tz,
                    task_type=task_t,
                    target_symbol=sym,
                    prompt=prompt,
                    is_active=active,
                    dry_run=dry_run,
                )
            )

    session.flush()
