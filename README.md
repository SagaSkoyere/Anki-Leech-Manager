# Better Leech Management - Anki Add-on

## Overview

This add-on is intended to help users quickly help identify and manage leech cards more effectively in Anki as an SRS program. The main columns I'd expect users to make use of are LifetimeIFR and RecentIFR, neither of which Anki currently exposes well in it's current leech management system.

Ankiweb addon location = https://ankiweb.net/shared/info/929264386

### Custom Columns - Summarized Logic

#### 1. IFR (Initial Fail Rate%)
- **Purpose**: Measures how often a card is failed on the first review of each day
- **Calculation**: For each day with reviews, checks if the chronologically first review was failed by the user
- **Interpretation**:
  - High IFR: Likely leech card requiring attention
  - Low IFR: Well-learned card
  - N/A: No review history available

#### 2. Age
- **Purpose**: Shows days since first review
- **Usage**: Identify how long you've been working with a card, used to help let newer cards mature before filtering or analyzing for leech status

#### 3. DailyTimeSpent(avg)
- **Purpose**: Shows average daily time investment per card, over it's lifetime
- **Display**: Time in seconds (e.g., "8.7")
- **Calculation**: Total review time divided by card age (days since it's first review)
- **Interpretation**: High values indicate time-intensive cards that may need modification or deletion, unless recent improvements.

### Leech Manager Menu Functions

#### Export Leech Info
- Exports all leech data to a pipe-delimited text file for statistical analysis

#### Filter by Age
- Filter browser view to cards with age >= specified days
- Default: 7 days (configurable via dialog)
- Automatically excludes unreviewed cards
- Preserves current deck and search context
- Example: If viewing "deck:Japanese", filter applies only to Japanese deck cards
- Used to speed up filtering workflow

## Installation

### Method 1: From Anki's Add-on Manager (recommended)
1. Open Anki
2. Go to Tools → Add-ons
3. Click "Get Add-ons..."
4. Enter the add-on code 929264386
5. Restart Anki

### Method 2: Manual Installation
1. Download the release (right hand sidebar)
2. Locate your Anki add-ons folder
3. Create a new folder in the add-ons directory (e.g., `anki_leech_management`)
4. Copy all the add-on files into the folder
5. Restart Anki

## Usage

### Enabling Columns
1. Open the Anki Browser (Browse → Cards)
2. Right-click on any column header
3. Enable the desired columns
4. Click column headers to sort by that metric

### Database Implementation

- Uses Anki's internal SQLite database (`revlog` table)
- Optimized SQL queries for minimal performance impact
- Custom SQL sorting for efficient browser performance
- On-demand calculations when columns are visible
- Local timezone support for consistent day boundaries

## Debug Mode
Enable detailed logging by editing `leech_columns.py`:
```python
DEBUG = 1  # Set to 1 to enable debug logging
```

Debug logs are written to `leech_columns_debug.log` in the add-on directory.

## Contributing
Contributions are welcome! I'm not around on GitHub much, so ping me on Discord.
