"""
Leech Manager Menu for Anki Browser
Adds a "Leech Manager" menu to the browser with export functionality.
"""

import os
import logging
from typing import Optional

try:
    from aqt import mw, gui_hooks
    from aqt.browser import Browser
    from aqt.qt import QAction, QMenu, QInputDialog
    from aqt.utils import showInfo, showCritical
except ImportError as e:
    print(f"Failed to import Anki modules: {e}")
    raise

# Get logger from leech_columns module
try:
    from . import leech_columns
    logger = leech_columns.logger
except ImportError:
    # Fallback logging if leech_columns not available
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)


def export_leech_info():
    """Export leech information to a pipe-delimited text file using direct SQL queries."""
    logger.info("Export Leech Info action triggered")

    try:
        # Import extract module with error handling
        try:
            from . import extract
        except ImportError as e:
            error_msg = f"Failed to import extract module: {str(e)}"
            logger.error(error_msg)
            showCritical(error_msg)
            return

        # Get the addon directory
        addon_dir = os.path.dirname(__file__)
        logger.info(f"Using addon directory: {addon_dir}")

        # Validate directory exists
        if not os.path.exists(addon_dir):
            error_msg = f"Addon directory not found: {addon_dir}"
            logger.error(error_msg)
            showCritical(error_msg)
            return

        # Call the export function (now runs synchronously with direct SQL)
        try:
            logger.info("Starting direct SQL export...")
            success, message = extract.export_leech_data(addon_dir)
        except Exception as export_error:
            error_msg = f"Export function error: {str(export_error)}"
            logger.error(error_msg)
            logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")
            showCritical(f"Export function error:\n\n{error_msg}")
            return

        # Handle result
        if success:
            logger.info("Export completed successfully")
            # Success message is already shown by export_leech_data via showInfo
        else:
            logger.error(f"Export failed: {message}")
            showCritical(f"Export failed!\n\n{message}")

    except Exception as e:
        error_msg = f"Unexpected error during export: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")
        showCritical(f"Unexpected error:\n\n{error_msg}")


def show_info():
    """Show informational popup with workflow suggestions."""
    logger.info("Show Info action triggered")

    info_text = """<h3>Leech Manager - Suggested Workflow</h3>

<p><b>1. Filter by Age:</b><br>
Click the "Filter by Age" submenu to filter cards returned by enough time for the card to have been matured and properly tested.<br>
<i>Recommendation: 7 days</i></p>

<p><b>2. Sort and Archive:</b><br>
Sort on the <b>RecentIFR</b> column to find your hardest cards. Drag whatever amount you want to archive to a separate "Archived Leeches" deck that you don't study.<br>
<i>Recommendation: Language learners should keep their Archived Leeches deck ~10-40% the size of their main study deck for the most time-efficient vocabulary growth.</i></p>

<p><b>Column Descriptions:</b><br>
• <b>LifetimeIFR</b>: Initial Fail Rate (first daily review) across the card's full history<br>
• <b>RecentIFR</b>: Fail rate for the 10 most recent initial reviews (general IFR for cards with &lt;10)<br>
• <b>Age</b>: Days since first review<br>
• <b>DailyTimeSpent</b>: Average daily time investment per card</p>

<hr>
<p><i>Github: <a href="https://github.com/SagaSkoyere/Anki-Leech-Manager">https://github.com/SagaSkoyere/Anki-Leech-Manager</a></i></p>
"""

    showInfo(info_text)


def filter_by_age(browser: Browser):
    """Filter browser by card age (days since first review)."""
    logger.info("Filter by Age action triggered")

    try:
        # Prompt user for minimum age with QInputDialog
        age, ok = QInputDialog.getInt(
            browser,
            "Filter by Age",
            "Show cards with age >= (days):",
            7,      # default value
            0,      # minimum
            10000,  # maximum
            1       # step
        )

        if not ok:
            logger.info("User cancelled age filter")
            return

        logger.info(f"Filtering cards with age >= {age} days")

        # Use SQL to find card IDs matching criteria
        # This matches the Age column calculation exactly (using localtime)
        query = """
        SELECT DISTINCT c.id
        FROM cards c
        INNER JOIN revlog r ON c.id = r.cid
        GROUP BY c.id
        HAVING (julianday('now') - julianday(MIN(r.id)/1000.0, 'unixepoch', 'localtime')) >= ?
        """

        card_ids = mw.col.db.list(query, age)

        if not card_ids:
            showInfo(f"No cards found with age >= {age} days")
            return

        # Get current browser search to preserve deck/filter context
        current_search = browser.current_search()

        # Construct search query with card IDs
        # Use comma-separated card IDs (Anki supports: cid:123,456,789)
        id_search = f"cid:{','.join(str(cid) for cid in card_ids)}"

        # Combine with current search if it exists
        if current_search and current_search.strip():
            # Combine current search with age filter using AND
            combined_search = f"({current_search}) AND ({id_search})"
            logger.info(f"Combining with existing search: {current_search}")
        else:
            combined_search = id_search

        # Apply the search to browser
        browser.search_for(combined_search)

        logger.info(f"Filtered to {len(card_ids)} cards with age >= {age} days")
        showInfo(f"Filtered to cards with learned age >= {age} days")

    except Exception as e:
        error_msg = f"Error filtering by age: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")
        showCritical(error_msg)


def time_analysis(browser: Browser):
    """Analyze time spent on cards by percentile."""
    logger.info("Time analysis action triggered")

    try:
        # Get the currently displayed card IDs from the browser
        card_ids = browser.table.get_selected_card_ids() if hasattr(browser.table, 'get_selected_card_ids') else []

        # If no cards selected or method doesn't exist, get all displayed cards
        if not card_ids:
            # Get all card IDs from current browser search
            card_ids = browser.table.get_card_ids() if hasattr(browser.table, 'get_card_ids') else []

        # Fallback: try getting from browser state
        if not card_ids and hasattr(browser, 'card_ids'):
            card_ids = browser.card_ids

        if not card_ids:
            showInfo("No cards currently displayed in browser.\n\nPlease select a deck or search for cards first.")
            return

        logger.info(f"Analyzing {len(card_ids)} cards")

        # Get deck name from current search
        current_search = browser.current_search()
        deck_name = "the current selection"

        # Try to extract deck name from search
        if current_search and "deck:" in current_search.lower():
            # Simple extraction - just get the deck name if it's in the search
            try:
                deck_part = [part for part in current_search.split() if part.lower().startswith("deck:")]
                if deck_part:
                    deck_name = deck_part[0].split(":", 1)[1].strip('"\'')
            except:
                pass

        # Query to get DailyTimeSpent for each card (in seconds)
        # Uses the same logic as the DailyTimeSpent column
        query = """
        SELECT
            c.id as card_id,
            (CASE
                WHEN MIN(r.id) IS NULL THEN NULL
                ELSE (SUM(r.time) / 1000.0) /
                     MAX(1, (julianday('now') - julianday(MIN(r.id)/1000.0, 'unixepoch')))
            END) as daily_time_spent
        FROM cards c
        LEFT JOIN revlog r ON c.id = r.cid
        WHERE c.id IN ({})
        GROUP BY c.id
        """.format(','.join('?' * len(card_ids)))

        results = mw.col.db.all(query, *card_ids)

        # Filter out cards with no review data (NULL time spent)
        card_times = [(card_id, time_spent) for card_id, time_spent in results if time_spent is not None]

        if not card_times:
            showInfo(f"No reviewed cards found in {deck_name}.\n\nCards must have review history to analyze time spent. Please make sure to select the rows of cards you want to analyze (or Cntrl+A to select all)")
            return

        logger.info(f"Found {len(card_times)} cards with review history")

        # Sort by time spent (ascending - easiest first)
        card_times.sort(key=lambda x: x[1])

        total_cards = len(card_times)
        total_time = sum(time for _, time in card_times)

        # Calculate percentiles (10th, 20th, ..., 100th)
        percentile_stats = []

        for percentile in range(10, 101, 10):
            # Get the cards in this percentile bucket (e.g., 0-10%, 10-20%, etc.)
            start_idx = int((percentile - 10) / 100 * total_cards)
            end_idx = int(percentile / 100 * total_cards)

            percentile_cards = card_times[start_idx:end_idx]

            if percentile_cards:
                # Average time for this percentile
                avg_time = sum(time for _, time in percentile_cards) / len(percentile_cards)

                # Total time for this percentile
                percentile_total_time = sum(time for _, time in percentile_cards)

                # Percentage of total time
                time_percentage = (percentile_total_time / total_time * 100) if total_time > 0 else 0

                percentile_stats.append({
                    'percentile': percentile,
                    'avg_time': avg_time,
                    'time_percentage': time_percentage
                })

        # Format output message
        message = f"<h3>Time Analysis for {deck_name}</h3>\n"
        message += f"<p><i>Analyzed {total_cards} cards with review history</i></p>\n"
        message += "<p>Your time is spent in the following time averages per card:</p>\n"
        message += "<pre>\n"
        message += "(easiest)\n"

        for stat in percentile_stats:
            message += f"Your {stat['percentile']:2d}th percentile cards take {stat['avg_time']:5.2f} seconds, and {stat['time_percentage']:4.1f}% of total time\n"

        message += "(hardest)\n"
        message += "</pre>"

        showInfo(message)
        logger.info("Time analysis completed successfully")

    except Exception as e:
        error_msg = f"Error in time analysis: {str(e)}"
        logger.error(error_msg)
        logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")
        showCritical(error_msg)


class LeechManagerMenu:
    """Manages the Leech Manager menu in the browser."""

    def __init__(self):
        logger.info("Initializing Leech Manager Menu")
        self.menu_created = False

    def setup_browser_menu(self, browser: Browser):
        """Setup the Leech Manager menu in the browser."""
        logger.info("Setting up Leech Manager menu in browser")

        try:
            # Check if menu already created to avoid duplicates
            if hasattr(browser, '_leech_manager_menu'):
                logger.debug("Leech Manager menu already exists, skipping")
                return

            # Get the browser's menu bar
            menubar = browser.menuBar()

            # Create the "Leech Manager" menu
            leech_menu = QMenu("Leech Manager", browser)

            # Add "Info" action
            info_action = QAction("Info", browser)
            info_action.triggered.connect(show_info)
            info_action.setToolTip("Show workflow suggestions and column descriptions")
            leech_menu.addAction(info_action)

            # Add separator
            leech_menu.addSeparator()

            # Add "Export Leech Info" action
            export_action = QAction("Export Leech Info", browser)
            export_action.triggered.connect(export_leech_info)
            export_action.setToolTip("Export leech information to a pipe-delimited text file")
            leech_menu.addAction(export_action)

            # Add "Filter by Age" action
            filter_action = QAction("Filter by Age", browser)
            filter_action.triggered.connect(lambda: filter_by_age(browser))
            filter_action.setToolTip("Filter browser to show cards with age >= specified days")
            leech_menu.addAction(filter_action)

            # Add "Time Analysis" action
            time_analysis_action = QAction("Time Analysis", browser)
            time_analysis_action.triggered.connect(lambda: time_analysis(browser))
            time_analysis_action.setToolTip("Analyze time spent on cards by percentile (easiest to hardest)")
            leech_menu.addAction(time_analysis_action)

            # Add menu to menu bar (insert before Help menu if it exists)
            help_menu = None
            for action in menubar.actions():
                if action.text() == "&Help":
                    help_menu = action
                    break

            if help_menu:
                menubar.insertMenu(help_menu, leech_menu)
            else:
                menubar.addMenu(leech_menu)

            # Mark that we've created the menu
            browser._leech_manager_menu = leech_menu
            self.menu_created = True

            logger.info("✓ Leech Manager menu created successfully")

        except Exception as e:
            logger.error(f"✗ Error creating Leech Manager menu: {e}")
            logger.error(f"Full traceback: {leech_columns.traceback.format_exc()}")


# Global menu manager instance
menu_manager: Optional[LeechManagerMenu] = None


def on_browser_menus_did_init(browser: Browser):
    """Hook function called when browser menus are initialized."""
    global menu_manager

    logger.debug("Browser menus did init hook called")

    try:
        if menu_manager is None:
            menu_manager = LeechManagerMenu()

        menu_manager.setup_browser_menu(browser)

    except Exception as e:
        logger.error(f"Error in browser menus init hook: {e}")


def init_menu_system():
    """Initialize the leech manager menu system."""
    logger.info("Initializing Leech Manager menu system")

    try:
        # Register the browser menu hook
        gui_hooks.browser_menus_did_init.append(on_browser_menus_did_init)
        logger.info("✓ Registered browser_menus_did_init hook")

    except Exception as e:
        logger.error(f"✗ Error initializing menu system: {e}")
        raise


# Log that the module was loaded
logger.info("✓ leech_manager_menu.py module loaded successfully")