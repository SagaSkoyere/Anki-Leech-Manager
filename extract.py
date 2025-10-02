"""
Export functionality for Leech Manager
Exports leech information to pipe-delimited text files using direct SQL queries.
"""

import os
import math
from datetime import datetime
from typing import Tuple

try:
    from aqt import mw
    from aqt.utils import showInfo
except ImportError as e:
    print(f"Failed to import Anki modules: {e}")
    raise

# Get logger from leech_columns module
try:
    from . import leech_columns
    logger = leech_columns.logger
except ImportError:
    # Fallback logging if leech_columns not available
    import logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


def export_leech_data(addon_dir: str) -> Tuple[bool, str]:
    """
    Export leech data using direct SQL queries against the Anki collection database.

    Args:
        addon_dir: Directory where the addon is located

    Returns:
        Tuple of (success: bool, message: str)
    """
    logger.info("Starting direct SQL leech data export")
    logger.info(f"Addon directory: {addon_dir}")

    try:
        # Validate addon directory
        if not os.path.exists(addon_dir):
            logger.error(f"Addon directory does not exist: {addon_dir}")
            return False, f"Addon directory not found: {addon_dir}"

        if not os.access(addon_dir, os.W_OK):
            logger.error(f"No write permission to addon directory: {addon_dir}")
            return False, f"No write permission to: {addon_dir}"

        # Check if Anki collection is available
        if not mw or not mw.col:
            return False, "Anki collection is not available"

        # Use Anki's existing database connection to avoid "database is locked" error
        db = mw.col.db
        logger.info(f"Using Anki's database connection")

        # Setup output file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"leech_export_{timestamp}.txt"
        filepath = os.path.join(addon_dir, filename)

        logger.info(f"Writing export to: {filepath}")

        with open(filepath, 'w', encoding='utf-8') as f:
            # Write header
            header = [
                "Unique Card ID",
                "Sort Field for Card",
                "First Review",
                "Interval",
                "Reviews (count)",
                "Age",
                "DailyTimeSpent(avg)",
                "LifetimeIFR",
                "Ease",
                "Initial Fail Count",
                "Initial Daily Reviews",
                "Status",
                "Card Type",
                "Current Deck",
                "IFR at 7 days",
                "RecentIFR"
            ]
            f.write("|".join(header) + "\n")

            # Direct SQL query to get all reviewed cards with their data
            # This single query gets everything we need
            query = """
            WITH card_reviews AS (
                SELECT
                    c.id as card_id,
                    c.ivl as interval,
                    c.factor as ease_factor,
                    c.type as card_status,
                    c.ord as card_ord,
                    c.nid as note_id,
                    c.did as deck_id,
                    n.flds as note_fields,
                    n.mid as note_type_id,
                    MIN(r.id) as first_review_ts,
                    COUNT(r.id) as review_count,
                    SUM(r.time) as total_time_ms,
                    julianday('now') - julianday(MIN(r.id)/1000.0, 'unixepoch') as age_days
                FROM cards c
                INNER JOIN revlog r ON c.id = r.cid
                INNER JOIN notes n ON c.nid = n.id
                GROUP BY c.id, c.ivl, c.factor, c.type, c.ord, c.nid, c.did, n.flds, n.mid
            ),
            daily_first_reviews AS (
                SELECT
                    cid,
                    COUNT(*) as total_days,
                    SUM(CASE WHEN ease = 1 THEN 1 ELSE 0 END) as fail_days
                FROM (
                    SELECT r1.cid, r1.ease
                    FROM revlog r1
                    INNER JOIN (
                        SELECT cid,
                               date(id/1000.0, 'unixepoch', 'localtime') as review_date,
                               MIN(id) as first_id
                        FROM revlog
                        GROUP BY cid, date(id/1000.0, 'unixepoch', 'localtime')
                    ) r2 ON r1.id = r2.first_id AND r1.cid = r2.cid
                )
                GROUP BY cid
            ),
            daily_first_reviews_7day AS (
                SELECT
                    cid,
                    COUNT(*) as total_days_7,
                    SUM(CASE WHEN ease = 1 THEN 1 ELSE 0 END) as fail_days_7
                FROM (
                    SELECT r1.cid, r1.ease, r1.id
                    FROM revlog r1
                    INNER JOIN (
                        SELECT cid,
                               date(id/1000.0, 'unixepoch', 'localtime') as review_date,
                               MIN(id) as first_id,
                               ROW_NUMBER() OVER (PARTITION BY cid ORDER BY date(id/1000.0, 'unixepoch', 'localtime')) as day_num
                        FROM revlog
                        GROUP BY cid, date(id/1000.0, 'unixepoch', 'localtime')
                    ) r2 ON r1.id = r2.first_id AND r1.cid = r2.cid
                    WHERE r2.day_num <= 7
                )
                GROUP BY cid
            ),
            daily_first_reviews_10day AS (
                SELECT
                    cid,
                    COUNT(*) as total_days_10,
                    SUM(CASE WHEN ease = 1 THEN 1 ELSE 0 END) as fail_days_10
                FROM (
                    SELECT r1.cid, r1.ease, r1.id
                    FROM revlog r1
                    INNER JOIN (
                        SELECT cid,
                               date(id/1000.0, 'unixepoch', 'localtime') as review_date,
                               MIN(id) as first_id,
                               ROW_NUMBER() OVER (PARTITION BY cid ORDER BY date(id/1000.0, 'unixepoch', 'localtime') DESC) as day_num
                        FROM revlog
                        GROUP BY cid, date(id/1000.0, 'unixepoch', 'localtime')
                    ) r2 ON r1.id = r2.first_id AND r1.cid = r2.cid
                    WHERE r2.day_num <= 10
                )
                GROUP BY cid
            )
            SELECT
                cr.card_id,
                cr.note_fields,
                cr.first_review_ts,
                cr.interval,
                cr.review_count,
                cr.age_days,
                cr.total_time_ms,
                COALESCE(dfr.fail_days, 0) as fail_days,
                COALESCE(dfr.total_days, 0) as total_days,
                cr.ease_factor,
                cr.card_status,
                cr.card_ord,
                cr.note_type_id,
                cr.deck_id,
                COALESCE(dfr7.fail_days_7, 0) as fail_days_7,
                COALESCE(dfr7.total_days_7, 0) as total_days_7,
                COALESCE(dfr10.fail_days_10, 0) as fail_days_10,
                COALESCE(dfr10.total_days_10, 0) as total_days_10
            FROM card_reviews cr
            LEFT JOIN daily_first_reviews dfr ON cr.card_id = dfr.cid
            LEFT JOIN daily_first_reviews_7day dfr7 ON cr.card_id = dfr7.cid
            LEFT JOIN daily_first_reviews_10day dfr10 ON cr.card_id = dfr10.cid
            ORDER BY cr.card_id
            """

            logger.info("Executing SQL query...")
            results = db.all(query)
            logger.info(f"Query returned {len(results)} cards")

            processed_count = 0
            error_count = 0

            # Process each row
            for row_num, row in enumerate(results, start=1):
                try:
                    card_id, note_fields, first_review_ts, interval, review_count, age_days, total_time_ms, fail_days, total_days, ease_factor, card_status, card_ord, note_type_id, deck_id, fail_days_7, total_days_7, fail_days_10, total_days_10 = row

                    # Extract sort field (first field from note)
                    fields = note_fields.split('\x1f')
                    sort_field = fields[0].strip() if fields else "N/A"
                    # Clean sort field for pipe-delimited format
                    sort_field = sort_field.replace('|', '_').replace('\n', ' ').replace('\r', '')

                    # Format first review date
                    if first_review_ts:
                        first_review_date = datetime.fromtimestamp(first_review_ts / 1000)
                        first_review = first_review_date.strftime("%Y-%m-%d")
                    else:
                        first_review = "N/A"

                    # Calculate age (days since first review)
                    if age_days is None:
                        age_bucket = "Unreviewed"
                    else:
                        age_bucket = str(int(age_days))

                    # Calculate daily time spent
                    if total_time_ms and age_days and age_days > 0:
                        total_time_seconds = total_time_ms / 1000.0
                        avg_daily_seconds = total_time_seconds / max(1, age_days)
                        daily_time_spent = f"{avg_daily_seconds:.1f}"
                    else:
                        daily_time_spent = "N/A"

                    # Calculate IFR percentage
                    if total_days and total_days > 0:
                        ifr_percentage = (fail_days / total_days) * 100
                        ifr = f"{ifr_percentage:.1f}%"
                    else:
                        ifr = "N/A"

                    # Format Ease as percentage (Anki stores as integer, e.g., 2500 = 250%)
                    if ease_factor is not None:
                        ease = f"{ease_factor / 10.0:.0f}%"
                    else:
                        ease = "N/A"

                    # Format Initial Fail Count (numerator of IFR)
                    initial_fail_count = str(fail_days) if fail_days is not None else "0"

                    # Format Initial Daily Reviews (denominator of IFR)
                    initial_daily_reviews = str(total_days) if total_days is not None else "0"

                    # Format Status (0=new, 1=learning, 2=review, 3=relearning)
                    status_map = {0: "New", 1: "Learning", 2: "Review", 3: "Relearning"}
                    status_str = status_map.get(card_status, "Unknown") if card_status is not None else "N/A"

                    # Get Card Type (template name from note type)
                    if note_type_id is not None and card_ord is not None:
                        try:
                            note_type = mw.col.models.get(note_type_id)
                            if note_type and 'tmpls' in note_type and card_ord < len(note_type['tmpls']):
                                template = note_type['tmpls'][card_ord]
                                card_type_name = template['name']
                                # Clean card type name for pipe-delimited format
                                card_type_name = card_type_name.replace('|', '_').replace('\n', ' ').replace('\r', '')
                            else:
                                card_type_name = f"Template_{card_ord}"
                        except:
                            card_type_name = f"Template_{card_ord}"
                    else:
                        card_type_name = "N/A"

                    # Get Current Deck name from deck_id
                    if deck_id is not None:
                        try:
                            deck_name = mw.col.decks.name(deck_id)
                            # Clean deck name for pipe-delimited format
                            deck_name = deck_name.replace('|', '_').replace('\n', ' ').replace('\r', '')
                        except:
                            deck_name = f"Deck_{deck_id}"
                    else:
                        deck_name = "N/A"

                    # Calculate IFR at 7 days
                    if total_days_7 and total_days_7 > 0:
                        ifr_7day_percentage = (fail_days_7 / total_days_7) * 100
                        ifr_7day = f"{ifr_7day_percentage:.1f}%"
                    else:
                        ifr_7day = "N/A"

                    # Calculate RecentIFR (10 most recent days, or lifetime IFR if < 10 days)
                    if total_days_10 and total_days_10 >= 10:
                        # Use the 10 most recent days - always divide by 10
                        recent_ifr_percentage = (fail_days_10 / 10) * 100
                        recent_ifr = f"{recent_ifr_percentage:.1f}%"
                    elif total_days and total_days > 0:
                        # Fall back to lifetime IFR if fewer than 10 days
                        recent_ifr_percentage = (fail_days / total_days) * 100
                        recent_ifr = f"{recent_ifr_percentage:.1f}%"
                    else:
                        recent_ifr = "N/A"

                    # Write row
                    output_row = [
                        str(row_num),              # Unique Card ID
                        sort_field,
                        first_review,
                        str(interval) if interval is not None else "N/A",
                        str(review_count) if review_count else "0",
                        age_bucket,
                        daily_time_spent,
                        ifr,
                        ease,                      # Ease
                        initial_fail_count,        # Initial Fail Count
                        initial_daily_reviews,     # Initial Daily Reviews
                        status_str,                # Status
                        card_type_name,            # Card Type
                        deck_name,                 # Current Deck
                        ifr_7day,                  # IFR at 7 days
                        recent_ifr                 # RecentIFR
                    ]
                    f.write("|".join(output_row) + "\n")

                    processed_count += 1

                    # Log progress every 1000 cards
                    if processed_count % 1000 == 0:
                        logger.info(f"Processed {processed_count} cards...")

                except Exception as e:
                    logger.error(f"Error processing card: {e}")
                    error_count += 1
                    continue

        # Success message
        message = (
            f"Export completed successfully!\n\n"
            f"Processed: {processed_count} cards\n"
            f"Errors: {error_count} cards\n"
            f"File: {filepath}"
        )
        logger.info(f"Export completed: {processed_count} processed, {error_count} errors")
        showInfo(message)

        return True, message

    except Exception as e:
        error_message = f"Export failed: {str(e)}"
        logger.error(f"Critical export error: {error_message}")
        try:
            logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")
        except:
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
        return False, error_message


# Log that the module was loaded
logger.info("✓ extract.py module loaded successfully")