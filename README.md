<img src="plugin.png" width="128" align="right" />

# Flight Planner for Litchi Missions (QGIS Plugin)

A comprehensive QGIS Processing Plugin to design professional photogrammetry flight plans compatible with **Litchi**.

Unlike simple waypoint converters, this plugin features a powerful **Grid Generator** that builds flight paths based on Ground Sampling Distance (GSD) and camera specifications, handling irregular polygon shapes with advanced geometric logic.

## Key Features

### 🚀 Litchi Flight Plan Generator
The core tool of the suite. Inputs a Polygon AOI and generates a ready-to-fly Litchi CSV.
*   **GSD-Driven**: Input your desired cm/px, and it calculates the optimal Flight Altitude.
*   **Smart Coverage**:
    *   **Core Lines**: Follow the exact contour of your polygon.
    *   **Clone Neighbor Extensions**: Adds extra approach/departure lines that are perfectly parallel to your area's edge.
    *   **Ray-Cast Filtering**: Prevents valid lines from being discarded due to rotation artifacts.
*   **Visual feedback**: Outputs Waypoints, connected Flight Lines (visualizing turns), and individual Photo Centroids.
### 🛠 Professional Optimizations (Advanced)
*   **Auto-Split Engines**: Automatically breaks down large missions (>99 waypoints) into multiple CSV files to comply with DJI/Litchi limits.
*   **Motion Blur Safety**: Integrated calculator that warns you if your **Flight Speed** and **Shutter Speed** will result in blurry images (Blur > GSD).
*   **Stop-and-Shoot Mode**: Forces the drone to stop at every waypoint for a photo, ensuring 0% motion blur and maximum precision (ideal for steep terrain).
*   **Terrain Tracking Midpoints**: Option to insert waypoints at photo centroids to force the drone to re-evaluate altitude in "Ground Follow" mode.
*   **Battery Management**: Estimates the number of battery cycles needed based on total mission distance and flight time.

### 📷 Camera Database Manager
*   Includes a pre-loaded database of popular mapping drones:
    *   DJI Mavic 3 Enterprise
    *   DJI Phantom 4 Pro / RTK (and Standard)
    *   DJI Air 2S
    *   DJI Mini 3 Pro
    *   Autel EVO II Pro
*   **Add Camera Tool**: Easily register custom sensors/cameras via a dedicated QGIS tool.

## Installation

1.  **Download/Clone**:
    Clone this repository into your QGIS plugins directory.
    *   **Linux**: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/LitchiFlightPlanner`
    *   **Windows**: `C:\Users\{User}\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins\LitchiFlightPlanner`

2.  **Activate**:
    Restart QGIS and enable **Flight Planner for Litchi Missions** in `Plugins > Manage and Install Plugins`.

## Usage

1.  **Generate a Mission**:
    *   Open **Processing Toolbox** > **Litchi Converter** > **Litchi Flight Plan Generator**.
    *   Select your **AOI** (Polygon layer).
    *   Choose your **Camera** and target **GSD**.
    *   Adjust **Heading** and **Overlaps**.
    *   (Optional) Add **Extra Lines** at Start/End for better approach.
    *   Run!

2.  **Export to Litchi**:
    *   The tool calculates "Litchi CSV" compliant fields (latitude, longitude, altitude, heading, curvesize, rotationdir, etc.).
    *   Export the resulting Point Layer to CSV.
    *   Import into [Litchi Mission Hub](https://flylitchi.com/hub).

## 💡 Pro Tips: Mapping Checklist

### Understanding Shutter Speed (Exposure)
To ensure the **Motion Blur Safety** check works correctly, you must coordinate the script with your drone settings:
*   **The Value**: Enter the denominator of your shutter speed (e.g., if flying at **1/1000**, enter **1000**).
*   **Recommendations**:
    *   **Sunny Day**: Use **1/1000** or faster (**1/1600**, **1/2000**).
    *   **Cloudy Day**: Minimum **1/800**. If you must go slower (e.g. 1/500), consider lowering the drone's **Flight Speed** in the plugin.
*   **Motion Blur Warn**: If the plugin logs a warning, it means the drone moves more than half a pixel while the shutter is open. This can cause WebODM to fail during image alignment.

### Managing Large Areas (Auto-Split)
If your mission has more than 99 waypoints:
1.  Check **Auto-Split Missions**.
2.  Assign a **Folder for Split Missions**.
3.  The plugin will create `mission_part1.csv`, `mission_part2.csv`, etc.
4.  Upload these as separate missions to Litchi. Land and change batteries between parts if necessary.

## License

GNU General Public License v3.0 (GPLv3).
