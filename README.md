# Litchi Mission Formatter for QGIS

A QGIS Processing Plugin to convert Flight Planner output (CSV/Shapefile) into Litchi Mission CSV format.

## Description

This plugin streamlines the workflow between flight planning software and the Litchi drone flight app. It takes a vector layer (usually points representing waypoints) containing flight data and converts it into a CSV file compatible with Litchi's mission hub.

Key features:
- Calculates bearing between waypoints automatically.
- Sets default Litchi parameters (Speed, Curve Size, Gimbal Mode, etc.).
- Allows customization of Speed and Photo Intervals.

## Installation

1.  Download this repository or clone it into your QGIS plugins directory.
    - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
    - Windows: `C:\Users\{Username}\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins`
2.  Restart QGIS.
3.  Enable the plugin in **Plugins > Manage and Install Plugins**.

## Usage

1.  Open the **Processing Toolbox** in QGIS.
2.  Navigate to **Custom Scripts > Flight planner to Litchi mission**.
3.  Select your input layer (must contain `xcoord` and `ycoord` fields, or valid geometry).
4.  Set the desired **Speed** and **Photo Distance Interval**.
5.  Run the algorithm. The output will be added to your project as a memory layer (which can then be exported to CSV).

## License

This project is licensed under the GNU General Public License v3.0 (GPLv3).
