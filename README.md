# Flight Planner for Litchi Missions (QGIS Plugin)

![Icon](plugin.png)

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
*   **Customizable**: Control Heading, Overlaps (Forward/Side), Speed, and Gimbal Pitch.

### 📷 Camera Database Manager
*   Includes a pre-loaded database of popular mapping drones:
    *   DJI Mavic 3 Enterprise
    *   DJI Phantom 4 Pro / RTK
    *   DJI Air 2S
    *   DJI Mini 3 Pro
    *   Autel EVO II Pro
*   **Add Camera Tool**: Easily register custom sensors/cameras via a dedicated GPU tool.

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

## License

GNU General Public License v3.0 (GPLv3).
