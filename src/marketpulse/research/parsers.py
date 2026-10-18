"""Robust parsers for financial RSS feeds, regulatory disclosures, and market publications."""

from abc import ABC, abstractmethod
from datetime import datetime
import html
import re
from typing import Any, Dict, List, Optional
import xml.etree.ElementTree as ET

from marketpulse.logging.setup import get_logger
from marketpulse.storage.normalizer import (
    detect_incomplete_data,
    normalize_financial_text,
    normalize_timestamp,
    normalize_url,
)

logger = get_logger(__name__)


class ParsedItem:
    """Standardized output of a source parser."""

    def __init__(
        self,
        title: str,
        content: str,
        url: str,
        published_at: Optional[datetime] = None,
        author: Optional[str] = None,
        company_symbol: Optional[str] = None,
        categories: Optional[List[str]] = None,
        raw_metadata: Optional[Dict[str, Any]] = None,
        is_incomplete: bool = False,
        incomplete_reasons: Optional[List[str]] = None,
    ):
        self.title = title
        self.content = content
        self.url = url
        self.published_at = published_at
        self.author = author
        self.company_symbol = company_symbol
        self.categories = categories or []
        self.raw_metadata = raw_metadata or {}
        self.is_incomplete = is_incomplete
        self.incomplete_reasons = incomplete_reasons or []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "author": self.author,
            "company_symbol": self.company_symbol,
            "categories": self.categories,
            "is_incomplete": self.is_incomplete,
            "incomplete_reasons": self.incomplete_reasons,
        }


class BaseSourceParser(ABC):
    """Abstract base parser with guaranteed exception containment."""

    @abstractmethod
    def parse(self, raw_content: str, base_url: Optional[str] = None) -> List[ParsedItem]:
        """Parse raw content string into list of ParsedItem objects."""
        pass


class RSSFeedParser(BaseSourceParser):
    """Parses standard RSS 2.0 and Atom XML feeds (e.g. RBI, Economic Times, SEBI)."""

    def parse(self, raw_content: str, base_url: Optional[str] = None) -> List[ParsedItem]:
        items: List[ParsedItem] = []
        if not raw_content or not raw_content.strip():
            logger.warning("RSSFeedParser received empty raw content")
            return items

        # Clean any potential leading/trailing junk before XML declaration
        content_clean = raw_content.strip()
        start_idx = content_clean.find("<")
        if start_idx > 0:
            content_clean = content_clean[start_idx:]

        try:
            root = ET.fromstring(content_clean)
        except ET.ParseError as pe:
            logger.warning("XML ParseError in RSSFeedParser: %s. Attempting regex fallback...", pe)
            return self._regex_fallback(content_clean, base_url)

        # 1. Standard RSS 2.0 (<channel><item>...)
        channel = root.find("channel")
        if channel is not None:
            for item_elem in channel.findall("item"):
                try:
                    parsed_item = self._parse_rss_item(item_elem, base_url)
                    if parsed_item:
                        items.append(parsed_item)
                except Exception as e:
                    logger.warning("Error parsing individual RSS item: %s", e)
            return items

        # 2. Atom Feed (<feed><entry>...)
        entries = root.findall("{http://www.w3.org/2005/Atom}entry") or root.findall("entry")
        if entries:
            for entry_elem in entries:
                try:
                    parsed_entry = self._parse_atom_entry(entry_elem, base_url)
                    if parsed_entry:
                        items.append(parsed_entry)
                except Exception as e:
                    logger.warning("Error parsing individual Atom entry: %s", e)
            return items

        # 3. Direct item elements under root
        for item_elem in root.findall("item"):
            parsed_item = self._parse_rss_item(item_elem, base_url)
            if parsed_item:
                items.append(parsed_item)

        return items

    def _parse_rss_item(self, elem: ET.Element, base_url: Optional[str]) -> Optional[ParsedItem]:
        title = elem.findtext("title") or ""
        link = elem.findtext("link") or ""
        desc = elem.findtext("description") or elem.findtext("encoded") or ""
        pub_date_str = elem.findtext("pubDate") or elem.findtext("date")
        author = elem.findtext("author") or elem.findtext("creator")

        categories = [cat.text.strip() for cat in elem.findall("category") if cat.text]

        # Extract URL
        clean_url = normalize_url(link or (base_url or ""))
        norm_title = normalize_financial_text(title)
        norm_content = normalize_financial_text(desc)
        pub_dt = normalize_timestamp(pub_date_str)

        # Incomplete data check
        is_inc, reasons = detect_incomplete_data(norm_title, norm_content, clean_url)

        return ParsedItem(
            title=norm_title,
            content=norm_content,
            url=clean_url,
            published_at=pub_dt,
            author=author,
            categories=categories,
            is_incomplete=is_inc,
            incomplete_reasons=reasons,
        )

    def _parse_atom_entry(self, elem: ET.Element, base_url: Optional[str]) -> Optional[ParsedItem]:
        title = (
            elem.findtext("{http://www.w3.org/2005/Atom}title")
            or elem.findtext("title")
            or ""
        )
        link_elem = elem.find("{http://www.w3.org/2005/Atom}link") or elem.find("link")
        link = link_elem.get("href") if link_elem is not None else ""
        content = (
            elem.findtext("{http://www.w3.org/2005/Atom}summary")
            or elem.findtext("{http://www.w3.org/2005/Atom}content")
            or elem.findtext("summary")
            or ""
        )
        updated_str = (
            elem.findtext("{http://www.w3.org/2005/Atom}updated")
            or elem.findtext("{http://www.w3.org/2005/Atom}published")
            or elem.findtext("updated")
        )

        clean_url = normalize_url(link or (base_url or ""))
        norm_title = normalize_financial_text(title)
        norm_content = normalize_financial_text(content)
        pub_dt = normalize_timestamp(updated_str)
        is_inc, reasons = detect_incomplete_data(norm_title, norm_content, clean_url)

        return ParsedItem(
            title=norm_title,
            content=norm_content,
            url=clean_url,
            published_at=pub_dt,
            is_incomplete=is_inc,
            incomplete_reasons=reasons,
        )

    def _regex_fallback(self, content: str, base_url: Optional[str]) -> List[ParsedItem]:
        """Regex-based fallback if XML structure is partially broken or contains invalid entities."""
        items: List[ParsedItem] = []
        item_blocks = re.findall(r"<item\b[^>]*>(.*?)</item>", content, flags=re.DOTALL | re.IGNORECASE)

        for block in item_blocks:
            title_m = re.search(r"<title\b[^>]*>(.*?)</title>", block, flags=re.DOTALL | re.IGNORECASE)
            link_m = re.search(r"<link\b[^>]*>(.*?)</link>", block, flags=re.DOTALL | re.IGNORECASE)
            desc_m = re.search(r"<description\b[^>]*>(.*?)</description>", block, flags=re.DOTALL | re.IGNORECASE)
            date_m = re.search(r"<pubDate\b[^>]*>(.*?)</pubDate>", block, flags=re.DOTALL | re.IGNORECASE)

            title = title_m.group(1) if title_m else ""
            link = link_m.group(1) if link_m else (base_url or "")
            desc = desc_m.group(1) if desc_m else ""
            date_str = date_m.group(1) if date_m else None

            # Clean CDATA tags
            title = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", title, flags=re.DOTALL)
            desc = re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", desc, flags=re.DOTALL)

            norm_title = normalize_financial_text(title)
            norm_desc = normalize_financial_text(desc)
            clean_url = normalize_url(link)
            pub_dt = normalize_timestamp(date_str)
            is_inc, reasons = detect_incomplete_data(norm_title, norm_desc, clean_url)

            if norm_title:
                items.append(
                    ParsedItem(
                        title=norm_title,
                        content=norm_desc,
                        url=clean_url,
                        published_at=pub_dt,
                        is_incomplete=is_inc,
                        incomplete_reasons=reasons,
                    )
                )
        return items


class OfficialDisclosureParser(BaseSourceParser):
    """Parses regulatory press releases, circulars, and structured filings."""

    def parse(self, raw_content: str, base_url: Optional[str] = None) -> List[ParsedItem]:
        # If content appears to be XML / RSS (like RBI feed), delegate to RSSFeedParser
        if "<rss" in raw_content or "<feed" in raw_content or "<channel" in raw_content:
            return RSSFeedParser().parse(raw_content, base_url)

        items: List[ParsedItem] = []
        cleaned = normalize_financial_text(raw_content)
        if len(cleaned) < 50:
            return items

        # Create structured single disclosure item
        title = cleaned.split("\n")[0][:150]
        url = normalize_url(base_url or "https://official.disclosure.gov.in")
        now_dt = datetime.now()
        is_inc, reasons = detect_incomplete_data(title, cleaned, url)

        items.append(
            ParsedItem(
                title=title,
                content=cleaned,
                url=url,
                published_at=now_dt,
                is_incomplete=is_inc,
                incomplete_reasons=reasons,
            )
        )
        return items


def get_parser_for_source(parser_name: str) -> BaseSourceParser:
    """Parser factory mapping source registry config to parser implementation."""
    p_name = parser_name.lower().strip()
    if "rss" in p_name:
        return RSSFeedParser()
    return OfficialDisclosureParser()
