"""
Leech Management Columns for Anki Browser
Adds IFR, Age, and DailyTimeSpent columns to help manage leeches.

Features:
- Initial Fail Rate: Percentage of days where first review was failed (SORTABLE)
- Age: Days since first review as integer (SORTABLE)
- Daily Time Spent: Average daily review time per card (SORTABLE)

Sorting Implementation:
- Standalone implementation copying Advanced Browser sorting logic
- Custom SQL ORDER BY clauses for optimal performance
- Compatible with Anki 25.09.2+

Updated: 2025-09-28 v7 - Added debug flag control
"""

# DEBUG CONTROL: Set to 1 to enable debug logging, 0 to disable
DEBUG = 0

import time
import math
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta
from typing import Any, Sequence, Dict, Optional

# Get addon directory dynamically
ADDON_DIR = os.path.dirname(__file__)
DEBUG_LOG_FILE = os.path.join(ADDON_DIR, "leech_columns_debug.log")

# Setup logging based on DEBUG flag
if DEBUG:
    # Full debug logging to file and console
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s [%(levelname)8s] %(funcName)s:%(lineno)d - %(message)s',
        handlers=[
            logging.FileHandler(DEBUG_LOG_FILE, mode='w', encoding='utf-8'),
            logging.StreamHandler()  # Also to console
        ],
        force=True  # Override any existing logging config
    )
    logger = logging.getLogger(__name__)
else:
    # Minimal logging - only errors to console, no debug file
    logging.basicConfig(
        level=logging.ERROR,
        format='%(levelname)s: %(message)s',
        handlers=[logging.StreamHandler()],
        force=True
    )
    # Save reference to the real logger before wrapping it
    _real_logger = logging.getLogger(__name__)

    # Create a null logger for debug/info messages when DEBUG=0
    class NullLogger:
        def debug(self, msg, *args, **kwargs): pass
        def info(self, msg, *args, **kwargs): pass
        def warning(self, msg, *args, **kwargs): pass
        def error(self, msg, *args, **kwargs): _real_logger.error(msg, *args, **kwargs)

    # Only replace logger if DEBUG is off
    if not DEBUG:
        logger = NullLogger()

# Log startup information
logger.info("=" * 80)
logger.info(f"LEECH COLUMNS DEBUG LOG - {datetime.now()}")
logger.info(f"Addon Directory: {ADDON_DIR}")
logger.info(f"Debug Log File: {DEBUG_LOG_FILE}")
logger.info(f"Python Version: {sys.version}")
logger.info("=" * 80)

try:
    import anki
    logger.info(f"Anki Version: {anki.version}")
except Exception as e:
    logger.warning(f"Could not get Anki version: {e}")

try:
    from aqt import mw
    logger.info("✓ Imported aqt.mw")

    from aqt.browser import Browser, Column
    logger.info("✓ Imported Browser, Column")

    from aqt.browser.table import Cell, CellRow
    logger.info("✓ Imported Cell, CellRow")

    from anki.collection import Collection
    logger.info("✓ Imported Collection")

    # Try to import BrowserColumns - this might fail in newer Anki versions
    try:
        from anki.collection import BrowserColumns
        logger.info("✓ Imported BrowserColumns from anki.collection")
    except ImportError:
        try:
            from anki.browser import BrowserColumns
            logger.info("✓ Imported BrowserColumns from anki.browser")
        except ImportError:
            try:
                from aqt.browser import BrowserColumns
                logger.info("✓ Imported BrowserColumns from aqt.browser")
            except ImportError:
                logger.error("✗ Could not import BrowserColumns from any location")
                # Define fallback constants
                class BrowserColumns:
                    SORTING_ASCENDING = 1
                    SORTING_NONE = 0
                    ALIGNMENT_START = 0
                logger.warning("⚠️  Using fallback BrowserColumns constants")

    from anki.cards import Card
    logger.info("✓ Imported Card")

    from anki.utils import ids2str
    logger.info("✓ Imported ids2str")

    from aqt import gui_hooks
    logger.info("✓ Imported gui_hooks")

    logger.info("✅ ALL ANKI MODULES IMPORTED SUCCESSFULLY")

except Exception as e:
    logger.error(f"💥 CRITICAL: Failed to import Anki modules: {e}")
    logger.error(f"Full traceback: {traceback.format_exc()}")
    raise


def get_initial_fail_rate(card_id: int, col: Collection) -> str:
    """
    Calculate Initial (daily) Fail Rate for a card (Lifetime).
    Logic: For each day, check the first review and see if it was Again (Fail) or Hard/Good/Easy (Pass).
    Returns percentage as string.
    """
    logger.debug(f"get_initial_fail_rate called with card_id={card_id}")
    try:
        # Get all reviews for this card, ordered by time
        reviews = col.db.all("""
            SELECT ease, id FROM revlog
            WHERE cid = ?
            ORDER BY id
        """, card_id)
        logger.debug(f"Found {len(reviews) if reviews else 0} reviews for card {card_id}")

        if not reviews:
            logger.debug(f"No reviews found for card {card_id}, returning N/A")
            return "N/A"

        # Group reviews by day (using timestamp to determine day)
        daily_first_reviews = {}
        for ease, review_id in reviews:
            # Convert review_id (timestamp in milliseconds) to date
            review_date = datetime.fromtimestamp(review_id / 1000).date()

            # Only keep the first review of each day
            if review_date not in daily_first_reviews:
                daily_first_reviews[review_date] = ease

        if not daily_first_reviews:
            logger.debug(f"No daily reviews found for card {card_id}, returning N/A")
            return "N/A"

        # Count fails (ease = 1) vs passes (ease > 1)
        total_days = len(daily_first_reviews)
        fail_days = sum(1 for ease in daily_first_reviews.values() if ease == 1)

        fail_rate = (fail_days / total_days) * 100
        result = f"{fail_rate:.1f}%"
        logger.debug(f"Lifetime IFR for card {card_id}: {result} ({fail_days}/{total_days} fail days)")
        return result

    except Exception as e:
        logger.error(f"Error calculating Lifetime IFR for card {card_id}: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return "Error"


def get_recent_ifr(card_id: int, col: Collection) -> str:
    """
    Calculate Recent IFR for a card (10 most recent unique review days).
    Falls back to lifetime IFR if fewer than 10 days of reviews exist.
    Returns percentage as string.
    """
    logger.debug(f"get_recent_ifr called with card_id={card_id}")
    try:
        # Get all reviews for this card, ordered by time
        reviews = col.db.all("""
            SELECT ease, id FROM revlog
            WHERE cid = ?
            ORDER BY id
        """, card_id)
        logger.debug(f"Found {len(reviews) if reviews else 0} reviews for card {card_id}")

        if not reviews:
            logger.debug(f"No reviews found for card {card_id}, returning N/A")
            return "N/A"

        # Group reviews by day (using timestamp to determine day)
        daily_first_reviews = {}
        for ease, review_id in reviews:
            # Convert review_id (timestamp in milliseconds) to date
            review_date = datetime.fromtimestamp(review_id / 1000).date()

            # Only keep the first review of each day
            if review_date not in daily_first_reviews:
                daily_first_reviews[review_date] = ease

        if not daily_first_reviews:
            logger.debug(f"No daily reviews found for card {card_id}, returning N/A")
            return "N/A"

        # Sort dates in descending order (most recent first)
        sorted_dates = sorted(daily_first_reviews.keys(), reverse=True)

        # Check if we have at least 10 days
        if len(sorted_dates) >= 10:
            # Take the 10 most recent days
            recent_10_dates = sorted_dates[:10]
            recent_10_reviews = {date: daily_first_reviews[date] for date in recent_10_dates}

            total_days = len(recent_10_reviews)
            fail_days = sum(1 for ease in recent_10_reviews.values() if ease == 1)

            fail_rate = (fail_days / total_days) * 100
            result = f"{fail_rate:.1f}%"
            logger.debug(f"Recent IFR (10 days) for card {card_id}: {result} ({fail_days}/{total_days} fail days)")
            return result
        else:
            # Fall back to lifetime IFR
            total_days = len(daily_first_reviews)
            fail_days = sum(1 for ease in daily_first_reviews.values() if ease == 1)

            fail_rate = (fail_days / total_days) * 100
            result = f"{fail_rate:.1f}%"
            logger.debug(f"Recent IFR (fallback to lifetime) for card {card_id}: {result} ({fail_days}/{total_days} fail days)")
            return result

    except Exception as e:
        logger.error(f"Error calculating Recent IFR for card {card_id}: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return "Error"


def get_card_age_days(card_id: int, col: Collection) -> str:
    """
    Calculate age for a card based on time since first review.
    Returns number of days since first review as a string, or "Unreviewed" if never reviewed.
    """
    logger.debug(f"get_card_age_days called with card_id={card_id}")
    try:
        # Get the first review timestamp
        first_review = col.db.scalar("""
            SELECT MIN(id) FROM revlog
            WHERE cid = ?
        """, card_id)
        logger.debug(f"First review timestamp for card {card_id}: {first_review}")

        if not first_review:
            logger.debug(f"No first review found for card {card_id}, returning Unreviewed")
            return "Unreviewed"

        # Calculate days since first review
        first_review_date = datetime.fromtimestamp(first_review / 1000)
        current_date = datetime.now()
        days_since_first = (current_date - first_review_date).days
        logger.debug(f"Card {card_id} age: {days_since_first} days since first review")

        result = str(days_since_first)
        logger.debug(f"Age for card {card_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Error calculating age for card {card_id}: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return "Error"


def get_daily_time_spent_avg(card_id: int, col: Collection) -> str:
    """
    Calculate average daily time spent on a card.
    Logic: Total time spent in review divided by age since first review.
    Returns rounded-up seconds.
    """
    logger.debug(f"get_daily_time_spent_avg called with card_id={card_id}")
    try:
        # Get all review times and first review timestamp
        reviews = col.db.all("""
            SELECT time, id FROM revlog
            WHERE cid = ?
            ORDER BY id
        """, card_id)
        logger.debug(f"Found {len(reviews) if reviews else 0} reviews for daily time calc on card {card_id}")

        if not reviews:
            logger.debug(f"No reviews found for card {card_id}, returning N/A for daily time")
            return "N/A"

        # Calculate total time spent (in milliseconds)
        total_time_ms = sum(time for time, _ in reviews)
        logger.debug(f"Total time for card {card_id}: {total_time_ms}ms")

        # Get first and determine age in days
        first_review_timestamp = reviews[0][1]
        first_review_date = datetime.fromtimestamp(first_review_timestamp / 1000)
        current_date = datetime.now()
        age_days = max(1, (current_date - first_review_date).days)  # Minimum 1 day
        logger.debug(f"Card {card_id} age for time calc: {age_days} days")

        # Calculate average daily time in seconds and round up
        total_time_seconds = total_time_ms / 1000
        avg_daily_seconds = total_time_seconds / age_days
        rounded_up_seconds = math.ceil(avg_daily_seconds)

        result = f"{rounded_up_seconds}s"
        logger.debug(f"Daily time spent for card {card_id}: {result}")
        return result

    except Exception as e:
        logger.error(f"Error calculating daily time for card {card_id}: {str(e)}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        return "Error"


# ============================================================================
# COPIED FROM ADVANCED BROWSER - CustomColumn class and sorting logic
# ============================================================================

class CustomColumn:
    """A custom browser column (copied from Advanced Browser)."""

    def __init__(self, type, name, onData, onSort=None, sortTableFunction=False, setData=None):
        """
        type = Internally used key to identify the column.
        name = Name of column, visible to the user.
        onData = Function that returns the value of a card for this column.
        onSort = Optional function that returns the ORDER BY clause for sorting.
        """
        self.type = type
        self.name = name
        self.onData = onData
        self.onSort = onSort if onSort else lambda: None
        self.sortTableFunction = sortTableFunction
        self._setData = setData

    def setData(self, *args, **kwargs):
        if self._setData is None:
            return False
        return self._setData(*args, **kwargs)

    def __hash__(self):
        return hash(self.name)


class LeechColumnManager:
    """Standalone column manager copying Advanced Browser's sorting implementation."""

    def __init__(self):
        logger.info("Creating LeechColumnManager")
        # Store custom columns like Advanced Browser does
        self.customTypes: Dict[str, CustomColumn] = {}
        self.setup_columns()

    def setup_columns(self):
        """Setup custom columns and register hooks."""
        logger.info("Setting up leech columns")

        try:
            # Create custom columns with data and sort functions
            self.customTypes["leech_lifetime_ifr"] = CustomColumn(
                type="leech_lifetime_ifr",
                name="LifetimeIFR",
                onData=lambda c, n, t: get_initial_fail_rate(c.id, mw.col),
                onSort=lambda: """(
                    select
                    (case when count(*) = 0 then -1
                     else (count(case when ease = 1 then 1 end) * 100.0) /
                          count(*)
                    end)
                    from (
                        select r1.ease
                        from revlog r1
                        inner join (
                            select date(id/1000, 'unixepoch', 'localtime') as review_date,
                                   min(id) as first_id
                            from revlog
                            where cid = c.id
                            group by date(id/1000, 'unixepoch', 'localtime')
                        ) r2 on r1.id = r2.first_id
                        where r1.cid = c.id
                    )
                ) asc nulls last"""
            )

            self.customTypes["leech_age"] = CustomColumn(
                type="leech_age",
                name="Age",
                onData=lambda c, n, t: get_card_age_days(c.id, mw.col),
                onSort=lambda: """(
                    select
                    (case when min(id) is null then 0
                     else (julianday('now') - julianday(min(id)/1000, 'unixepoch'))
                    end)
                    from revlog where cid = c.id
                ) asc nulls last"""
            )

            self.customTypes["leech_daily_time"] = CustomColumn(
                type="leech_daily_time",
                name="DailyTimeSpent(avg)",
                onData=lambda c, n, t: get_daily_time_spent_avg(c.id, mw.col),
                onSort=lambda: """(
                    select
                    (case when min(id) is null then -1
                     else (sum(time) / 1000.0) /
                          max(1, (julianday('now') - julianday(min(id)/1000, 'unixepoch')))
                    end)
                    from revlog where cid = c.id
                ) asc nulls last"""
            )

            self.customTypes["leech_recent_ifr"] = CustomColumn(
                type="leech_recent_ifr",
                name="RecentIFR",
                onData=lambda c, n, t: get_recent_ifr(c.id, mw.col),
                onSort=lambda: """(
                    select
                    (case
                        when (select count(distinct date(id/1000, 'unixepoch', 'localtime'))
                              from revlog where cid = c.id) >= 10 then
                            -- Use 10 most recent days if available - always divide by 10
                            (select
                                (case when count(*) = 0 then -1
                                 else (count(case when ease = 1 then 1 end) * 100.0) / 10.0
                                end)
                            from (
                                select r1.ease
                                from revlog r1
                                inner join (
                                    select date(id/1000, 'unixepoch', 'localtime') as review_date,
                                           min(id) as first_id,
                                           row_number() over (order by date(id/1000, 'unixepoch', 'localtime') desc) as day_num
                                    from revlog
                                    where cid = c.id
                                    group by date(id/1000, 'unixepoch', 'localtime')
                                ) r2 on r1.id = r2.first_id and r1.cid = c.id
                                where r2.day_num <= 10
                            ))
                        else
                            -- Fall back to lifetime IFR if < 10 days
                            (select
                                (case when count(*) = 0 then -1
                                 else (count(case when ease = 1 then 1 end) * 100.0) / count(*)
                                end)
                            from (
                                select r1.ease
                                from revlog r1
                                inner join (
                                    select date(id/1000, 'unixepoch', 'localtime') as review_date,
                                           min(id) as first_id
                                    from revlog
                                    where cid = c.id
                                    group by date(id/1000, 'unixepoch', 'localtime')
                                ) r2 on r1.id = r2.first_id
                                where r1.cid = c.id
                            ))
                    end)
                ) asc nulls last"""
            )

            logger.info(f"✓ Created {len(self.customTypes)} custom columns")

            # Register hooks
            self.register_hooks()

        except Exception as e:
            logger.error(f"✗ Error setting up columns: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    def register_hooks(self):
        """Register Anki hooks for column display and sorting."""
        logger.info("Registering Anki hooks")

        try:
            # Check if gui_hooks has the methods we need
            if not hasattr(gui_hooks, 'browser_did_fetch_columns'):
                logger.error("✗ browser_did_fetch_columns hook not available in this Anki version")
                return

            if not hasattr(gui_hooks, 'browser_will_search'):
                logger.error("✗ browser_will_search hook not available in this Anki version")
                return

            if not hasattr(gui_hooks, 'browser_did_fetch_row'):
                logger.error("✗ browser_did_fetch_row hook not available in this Anki version")
                return

            # Register hooks one by one with individual error handling
            try:
                gui_hooks.browser_did_fetch_columns.append(self.on_browser_did_fetch_columns)
                logger.info("✓ Registered browser_did_fetch_columns hook")
            except Exception as e:
                logger.error(f"✗ Failed to register browser_did_fetch_columns: {e}")

            try:
                gui_hooks.browser_will_search.append(self.will_search)
                logger.info("✓ Registered browser_will_search hook")
            except Exception as e:
                logger.error(f"✗ Failed to register browser_will_search: {e}")

            try:
                gui_hooks.browser_did_fetch_row.append(self.column_data)
                logger.info("✓ Registered browser_did_fetch_row hook")
            except Exception as e:
                logger.error(f"✗ Failed to register browser_did_fetch_row: {e}")

        except Exception as e:
            logger.error(f"✗ Critical error in register_hooks: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    def on_browser_did_fetch_columns(self, columns: Dict[str, Column]):
        """Register our custom columns with the browser (copied from Advanced Browser logic)."""
        logger.info("🔥 BROWSER OPENED - Registering custom columns!")
        logger.info(f"Total existing columns: {len(columns)}")
        logger.debug(f"Existing columns: {list(columns.keys())}")

        # Define tooltips for each column
        tooltips = {
            "leech_lifetime_ifr": "Lifetime Initial Fail Rate: Percentage of unique review days where the first review was failed (Again button). Calculated across all review history.",
            "leech_age": "Age: Number of days since the card's first review. Helps identify mature vs. new cards.",
            "leech_daily_time": "Daily Time Spent (Average): Total review time divided by card age in days. Shows average daily time investment per card.",
            "leech_recent_ifr": "Recent IFR: Initial Fail Rate for the 10 most recent unique review days (or lifetime IFR if fewer than 10 days). Divides fail count by 10 when ≥10 days exist."
        }

        try:
            # Register each custom column
            for key, custom_col in self.customTypes.items():
                logger.info(f"Creating column: {key} ({custom_col.name})")

                # Create Anki Column object like Advanced Browser does
                sorting_enabled = BrowserColumns.SORTING_ASCENDING if custom_col.onSort() else BrowserColumns.SORTING_NONE
                logger.debug(f"Sorting enabled for {key}: {sorting_enabled}")

                # Get tooltip for this column
                tooltip = tooltips.get(key, f"{custom_col.name} - Leech management column")

                anki_column = Column(
                    key=key,
                    cards_mode_label=custom_col.name,
                    notes_mode_label=custom_col.name,
                    sorting_cards=sorting_enabled,
                    sorting_notes=BrowserColumns.SORTING_NONE,
                    uses_cell_font=False,
                    alignment=BrowserColumns.ALIGNMENT_START,
                    cards_mode_tooltip=tooltip,
                    notes_mode_tooltip=tooltip
                )

                columns[key] = anki_column
                logger.info(f"✅ SUCCESS: Registered column {key} ({custom_col.name})")

            logger.info(f"🎉 COLUMN REGISTRATION COMPLETE - Added {len(self.customTypes)} columns")
            logger.info(f"Total columns now: {len(columns)}")

        except Exception as e:
            logger.error(f"💥 CRITICAL ERROR registering columns: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    def will_search(self, search_context):
        """Handle sorting by custom columns (copied from Advanced Browser logic)."""
        logger.debug(f"Browser will search - checking for custom column sorting")
        logger.debug(f"Search context order type: {type(search_context.order)}")

        try:
            # Check if sorting by one of our custom columns (like Advanced Browser does)
            if hasattr(search_context.order, 'key') and search_context.order.key in self.customTypes:
                column_key = search_context.order.key
                custom_col = self.customTypes[column_key]
                logger.info(f"✓ Sorting by custom column: {column_key}")

                # Get the custom SQL ORDER BY clause
                order = custom_col.onSort()
                if not order:
                    logger.warning(f"No sort function for column {column_key}")
                    search_context.order = None
                else:
                    # Handle reverse sorting - improved logic
                    if hasattr(search_context.order, 'reverse') and search_context.order.reverse:
                        # Replace "asc nulls last" with "desc nulls first" for proper reverse sorting
                        order = order.replace(" asc nulls last", " desc nulls first")
                        logger.debug("Applied reverse sorting (DESC)")

                    # Replace the order with our custom SQL
                    search_context.order = order
                    logger.debug(f"Set custom SQL order: {order[:100]}...")

        except Exception as e:
            logger.error(f"✗ Error in will_search: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")

    def column_data(self, card_or_note_id: int, is_note: bool, row: CellRow, columns: Sequence[str]):
        """Populate data for custom columns (copied from Advanced Browser logic)."""

        # Check if any of our columns are active
        our_columns = [col for col in columns if col in self.customTypes]
        if our_columns:
            logger.info(f"📊 POPULATING DATA for card {card_or_note_id} - Our columns: {our_columns}")

        if not mw or not mw.col:
            logger.warning("mw or mw.col is None, skipping column data")
            return

        # Only handle cards for now
        if is_note:
            logger.debug("Skipping note mode (addon handles cards only)")
            return

        try:
            # Get card object
            card = mw.col.get_card(card_or_note_id)
            note = card.note()

            # Populate custom column data
            for index, column_key in enumerate(columns):
                if column_key in self.customTypes:
                    custom_col = self.customTypes[column_key]
                    logger.info(f"📝 Calculating {column_key} for card {card_or_note_id}")

                    # Get cell content using onData function
                    value = custom_col.onData(card, note, column_key)

                    # Update the cell
                    if index < len(row.cells):
                        row.cells[index].text = value
                        logger.info(f"✅ Set {column_key} = '{value}'")
                    else:
                        logger.warning(f"⚠️  Index {index} out of range for row with {len(row.cells)} cells")

        except Exception as e:
            logger.error(f"💥 Error populating column data: {e}")
            logger.error(f"Full traceback: {traceback.format_exc()}")


# Global column manager instance
column_manager: Optional[LeechColumnManager] = None


def init_addon():
    """Initialize the leech columns addon with comprehensive debug logging."""
    global column_manager

    logger.info("=" * 50)
    logger.info("INITIALIZING LEECH COLUMNS ADDON")
    logger.info("=" * 50)

    try:
        # Check if already initialized (to prevent double initialization)
        if column_manager is not None:
            logger.warning("⚠️  Addon already initialized, skipping duplicate initialization")
            return

        # SAFE MODE: Check if we should run in minimal mode to avoid conflicts
        import os
        safe_mode_file = os.path.join(ADDON_DIR, "safe_mode.txt")
        if os.path.exists(safe_mode_file):
            logger.warning("🛡️  SAFE MODE: safe_mode.txt found, skipping addon initialization")
            logger.warning("🛡️  To re-enable addon, delete safe_mode.txt from addon directory")
            return

        logger.info("Creating column manager...")
        column_manager = LeechColumnManager()

        logger.info("✓ Leech Columns addon initialized successfully!")
        logger.info("=" * 50)

    except Exception as e:
        logger.error(f"✗ CRITICAL ERROR initializing addon: {e}")
        logger.error(f"Full traceback: {traceback.format_exc()}")
        logger.error("=" * 50)

        # Create safe mode file to prevent future crashes
        try:
            safe_mode_file = os.path.join(ADDON_DIR, "safe_mode.txt")
            with open(safe_mode_file, 'w') as f:
                f.write(f"Safe mode activated due to error: {e}\n")
                f.write(f"Delete this file to re-enable the addon\n")
                f.write(f"Error occurred at: {datetime.now()}\n")
            logger.error(f"✓ Created safe_mode.txt to prevent future crashes")
        except Exception:
            pass

        raise

# Log that the module was loaded
logger.info("✓ leech_columns.py module loaded successfully")

# Add a safety check to catch any uncaught exceptions
import sys
def exception_handler(exc_type, exc_value, exc_traceback):
    """Log any uncaught exceptions to our debug file."""
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return

    logger.error("💥 UNCAUGHT EXCEPTION:")
    logger.error(f"Type: {exc_type.__name__}")
    logger.error(f"Value: {exc_value}")
    logger.error(f"Traceback: {''.join(traceback.format_tb(exc_traceback))}")

    # Call the original exception handler
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

# Install our exception handler
sys.excepthook = exception_handler
logger.info("✓ Exception handler installed")
