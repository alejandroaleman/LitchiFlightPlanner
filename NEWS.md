# Flight Planner for Litchi Missions - Changelog

## Version 0.1.1 (Professional Optimization) - 2025-12-20

Significant upgrade focusing on precision, safety, and workflow automation.

### New Features
*   **Precision Projection System**: Automatic detection of the correct UTM zone based on the AOI centroid. Metric calculations (GSD, distances) are now performed in a local CRS for absolute accuracy.
*   **Professional Reporting**: The log tab now shows a complete flight report including:
    - Total flight distance.
    - Estimated mission time.
    - Necessary battery cycles (based on camera-specific max flight time).
*   **Safety & Compliance Checks**:
    - **Waypoint Limit**: Warnings if waypoints exceed 99 (Litchi hardware limit).
    - **Photo Limit**: Warnings if photos exceed 999 (standard free-tier processing limit).
    - **Motion Blur Safety**: Integrated calculator that warns if Flight Speed vs Shutter Speed will result in blurry images.
*   **Advanced Flight Modes**:
    - **Auto-Split Engine**: Automatically generates multiple `.csv` files for large missions.
    - **Stop-and-Shoot Mode**: High-precision mode with triggers at every waypoint and 0% motion blur.
    - **Aligned Midpoints**: Centroid-aligned waypoints for enhanced terrain following in Litchi's ground follow mode.

### Improvements
*   **User Interface**: New parameters for Shutter Speed, Auto-split destinations, and Stop-and-Shoot mode.
*   **Camera Database**: Added `max_flight_time` field for battery estimation.
*   **Documentation**: Resized README icon and added a "Pro Tips: Mapping Checklist" section.

---

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
