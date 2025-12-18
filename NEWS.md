# Flight Planner for Litchi Missions - Changelog

## Version 0.1.0 (Development Release) - 2025-12-18

First functional release of the integrated suite.

### New Features
*   **Litchi Flight Plan Generator**: New processing algorithm to generate missions from scratch.
    - **Grid-Centric Logic**: Calculates flight lines based on best-practice photogrammetry grids.
    - **GSD Calculation**: Automatically estimates Altitude based on Camera Sensor and desired GSD (cm/px).
    - **Smart Trimming**: Core flight lines strictly follow the AOI contour.
    - **Clone Neighbor Extensions**: Extra lines (Start/End) are generated as parallel geometric clones of the core area edge.
    - **Ray-Cast Validation**: Ensures geometric robustness for irregular polygons.
    - **Visual Outputs**: Generates Mission Waypoints, Flight Lines (with turns), and Photo Centroids.
*   **Add Camera Utility**: New tool to easily register new camera models into the database (`cameras.json`).
*   **Comprehensive Camera DB**: Pre-loaded with specs for Mavic 3E, Phantom 4 Pro/RTK, Air 2S, Mini 3 Pro, and Autel EVO II.

### Improvements
*   **Plugin Architecture**: Refactored into a proper QGIS Provider structure.
*   **Metadata**: Project renamed to "Flight Planner for Litchi Missions".
*   **Documentation**: Complete rewrite of the README.

### Deprecated
*   Legacy `fp_to_lm.py` scripts have been superseded by the internal algorithms but kept in `original_scripts` for reference.
