"""
Better Leech Management Addon for Anki
Adds custom columns to the browser for better leech management.
Includes export functionality through browser menu.
"""

from . import leech_columns
from . import leech_manager_menu

# Initialize the addon components
leech_columns.init_addon()
leech_manager_menu.init_menu_system()