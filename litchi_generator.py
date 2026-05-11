from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingParameterFileDestination,
                       QgsProcessingParameterString,
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingException,
                       QgsField,
                       QgsFields,
                       QgsFeature,
                       QgsFeatureSink,
                       QgsGeometry,
                       QgsPointXY,
                       QgsWkbTypes,
                       QgsProject,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform,
                       QgsDistanceArea)
import math
import json
import os
import csv

class LitchiGeneratorAlgorithm(QgsProcessingAlgorithm):
    AOI = 'AOI'
    CAMERA = 'CAMERA'
    GSD = 'GSD'
    SPEED = 'SPEED'
    HEADING = 'HEADING'
    OVERLAP_FWD = 'OVERLAP_FWD'
    OVERLAP_SIDE = 'OVERLAP_SIDE'
    EXTRA_LINES_START = 'EXTRA_LINES_START'
    EXTRA_LINES_END = 'EXTRA_LINES_END'
    EXTRA_PHOTOS_END = 'EXTRA_PHOTOS_END'
    EXTRA_PHOTOS_FIRST_STRIP = 'EXTRA_PHOTOS_FIRST_STRIP'
    EXTRA_PHOTOS_LAST_STRIP = 'EXTRA_PHOTOS_LAST_STRIP'
    ADD_MID_POINT = 'ADD_MID_POINT'
    SHUTTER_SPEED = 'SHUTTER_SPEED'
    STOP_AND_SHOOT = 'STOP_AND_SHOOT'
    AUTO_SPLIT = 'AUTO_SPLIT'
    
    OUTPUT_LITCHI = 'OUTPUT_LITCHI'
    OUTPUT_LINES = 'OUTPUT_LINES'
    OUTPUT_CENTROIDS = 'OUTPUT_CENTROIDS'
    OUTPUT_FOLDER = 'OUTPUT_FOLDER'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LitchiGeneratorAlgorithm()

    def name(self):
        return 'litchigenerator'

    def displayName(self):
        return self.tr('Litchi Flight Plan Generator')

    def group(self):
        return self.tr('Custom Scripts')

    def groupId(self):
        return 'customscripts'

    def shortHelpString(self):
        return self.tr("Generates a photogrammetry flight plan for Litchi. Inputs: GSD, Heading, Buffers. Uses Grid-Centric World-Filtered logic with Side constraints.")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.AOI,
                self.tr('Area of Interest (Polygon)'),
                types=[QgsProcessing.TypeVectorPolygon]
            )
        )
        
        # Load Cameras
        self.cameras = []
        json_path = os.path.join(os.path.dirname(__file__), 'cameras.json')
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                data = json.load(f)
                self.cameras = data.get('cameras', [])
        
        camera_names = [c['name'] for c in self.cameras] if self.cameras else ['Default']
        
        self.addParameter(
            QgsProcessingParameterEnum(
                self.CAMERA,
                self.tr('Camera Model'),
                options=camera_names,
                defaultValue=0
            )
        )

        self.addParameter(QgsProcessingParameterNumber(self.GSD, self.tr('Target GSD (cm/px)'), type=QgsProcessingParameterNumber.Double, defaultValue=2.5))
        self.addParameter(QgsProcessingParameterNumber(self.SPEED, self.tr('Speed (m/s)'), type=QgsProcessingParameterNumber.Double, defaultValue=8.0))
        self.addParameter(QgsProcessingParameterNumber(self.HEADING, self.tr('Flight Direction (Degrees)'), type=QgsProcessingParameterNumber.Double, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_FWD, self.tr('Forward Overlap (%)'), type=QgsProcessingParameterNumber.Double, defaultValue=70.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_SIDE, self.tr('Side Overlap (%)'), type=QgsProcessingParameterNumber.Double, defaultValue=65.0))
        
        # Advanced Buffers (Explicit Lines)
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_LINES_START, self.tr('Extra Lines at Start (N)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_LINES_END, self.tr('Extra Lines at End (M)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_PHOTOS_END, self.tr('Extra Photos at Ends (N)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_PHOTOS_FIRST_STRIP, self.tr('Extra Photos First Strip (N)'), defaultValue=0, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_PHOTOS_LAST_STRIP, self.tr('Extra Photos Last Strip (N)'), defaultValue=0, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterBoolean(self.ADD_MID_POINT, self.tr('Add Midpoint to Flight Lines'), defaultValue=False))
        
        self.addParameter(QgsProcessingParameterNumber(self.SHUTTER_SPEED, self.tr('Shutter Speed (1/X sec)'), defaultValue=1000, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterBoolean(self.STOP_AND_SHOOT, self.tr('Stop-and-Shoot Mode (Max Precision)'), defaultValue=False))
        self.addParameter(QgsProcessingParameterBoolean(self.AUTO_SPLIT, self.tr('Auto-Split Missions (99 WP chunks)'), defaultValue=True))

        # Outputs
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LITCHI, self.tr('Litchi Mission (Waypoints)')))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LINES, self.tr('Flight Lines'), optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_CENTROIDS, self.tr('Photo Centroids (QC)'), optional=True))
        self.addParameter(QgsProcessingParameterFileDestination(self.OUTPUT_FOLDER, self.tr('Folder for Split Missions'), optional=True, fileFilter='Folder'))

    def processAlgorithm(self, parameters, context, feedback):
        aoi_layer = self.parameterAsSource(parameters, self.AOI, context)
        if not aoi_layer:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.AOI))

        camera_idx = self.parameterAsEnum(parameters, self.CAMERA, context)
        gsd_cm = self.parameterAsDouble(parameters, self.GSD, context)
        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        heading_angle = self.parameterAsDouble(parameters, self.HEADING, context)
        overlap_fwd = self.parameterAsDouble(parameters, self.OVERLAP_FWD, context) / 100.0
        overlap_side = self.parameterAsDouble(parameters, self.OVERLAP_SIDE, context) / 100.0
        extra_lines_start = self.parameterAsInt(parameters, self.EXTRA_LINES_START, context)
        extra_lines_end = self.parameterAsInt(parameters, self.EXTRA_LINES_END, context)
        extra_photos_end = self.parameterAsInt(parameters, self.EXTRA_PHOTOS_END, context)
        extra_photos_first_strip = self.parameterAsInt(parameters, self.EXTRA_PHOTOS_FIRST_STRIP, context)
        extra_photos_last_strip = self.parameterAsInt(parameters, self.EXTRA_PHOTOS_LAST_STRIP, context)
        add_mid_point = self.parameterAsBool(parameters, self.ADD_MID_POINT, context)
        shutter_denom = self.parameterAsInt(parameters, self.SHUTTER_SPEED, context)
        stop_and_shoot = self.parameterAsBool(parameters, self.STOP_AND_SHOOT, context)
        auto_split = self.parameterAsBool(parameters, self.AUTO_SPLIT, context)
        output_folder = self.parameterAsString(parameters, self.OUTPUT_FOLDER, context)
        
        # Get Camera Specs
        if not self.cameras:
             raise QgsProcessingException("No cameras defined in cameras.json")
        cam = self.cameras[camera_idx]
        sw, sh = cam['sensor_width_mm'], cam['sensor_height_mm']
        fl = cam['focal_length_mm']
        im_w, im_h = cam['image_width_px'], cam['image_height_px']
        
        # 1. Base Parameters
        gsd_m = gsd_cm / 100.0
        altitude = (gsd_m * fl * im_w) / sw
        
        feedback.pushInfo(f"Camera: {cam['name']}")
        feedback.pushInfo(f"GSD: {gsd_cm} cm/px -> Calculated Altitude: {altitude:.2f} m")
        
        # 2. Footprint & Grid Spacing
        fp_width = (sw * altitude) / fl
        fp_height = (sh * altitude) / fl
        
        dist_between_lines = fp_width * (1 - overlap_side)
        dist_between_photos = fp_height * (1 - overlap_fwd) 
        
        feedback.pushInfo(f"Footprint: {fp_width:.2f} m x {fp_height:.2f} m")
        feedback.pushInfo(f"Line Spacing: {dist_between_lines:.2f} m")
        feedback.pushInfo(f"Photo Interval: {dist_between_photos:.2f} m")

        # CRS Setup
        source_crs = aoi_layer.sourceCrs()
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        
        # Calculate Centroid for UTM Zone Selection to ensure Metric Accuracy
        # We need the centroid in WGS84 to pick the zone
        tr_source_to_wgs84 = QgsCoordinateTransform(source_crs, wgs84, context.project())
        
        # Combine Geometries (Original AOI)
        original_aoi_geom = None
        for feat in aoi_layer.getFeatures():
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                if original_aoi_geom is None:
                    original_aoi_geom = QgsGeometry(geom)
                else:
                    original_aoi_geom = original_aoi_geom.combine(geom)
        
        if original_aoi_geom is None or original_aoi_geom.isEmpty():
             raise QgsProcessingException("Input AOI layer contains no valid geometries.")

        # Transform to WGS84 to find centroid
        geom_wgs84 = QgsGeometry(original_aoi_geom)
        geom_wgs84.transform(tr_source_to_wgs84)
        centroid_wgs84 = geom_wgs84.boundingBox().center()
        
        # UTM Zone Calculation
        lon = centroid_wgs84.x()
        lat = centroid_wgs84.y()
        zone_number = math.floor((lon + 180) / 6) + 1
        is_southern = lat < 0
        
        if is_southern:
            epsg_code = 32700 + zone_number
        else:
            epsg_code = 32600 + zone_number
            
        projected_crs = QgsCoordinateReferenceSystem(f"EPSG:{epsg_code}")
        feedback.pushInfo(f"Auto-detected UTM Zone {zone_number}{'S' if is_southern else 'N'} (EPSG:{epsg_code}) for metric calculation.")

        tr_to_proj = QgsCoordinateTransform(source_crs, projected_crs, context.project())
        tr_to_wgs84 = QgsCoordinateTransform(projected_crs, wgs84, context.project())
        
        # Transform Original AOI to Projected CRS
        original_aoi_geom.transform(tr_to_proj)
        
        # Rotation Angle: To align the desired bearing with the horizontal X-axis (0 deg),
        # we need to rotate the world by (heading - 90).
        rotation_to_horizontal = heading_angle - 90
        
        # Pre-calculate Rotation Constants for Performance
        # To go from relative (rx, ry) back to world, we rotate by (90 - heading)
        rad_rot = math.radians(90 - heading_angle)
        cos_rot = math.cos(rad_rot)
        sin_rot = math.sin(rad_rot)
        
        # Rotation Center and Limits from Original AOI
        bbox_world = original_aoi_geom.boundingBox()
        cx, cy = bbox_world.center().x(), bbox_world.center().y()
        
        # Transformation Helper
        def rotated_rel_to_world(rx, ry):
            wx = rx * cos_rot - ry * sin_rot
            wy = rx * sin_rot + ry * cos_rot
            return QgsPointXY(wx + cx, wy + cy)
        
        # 1. Rotated Buffered AOI (for Y limits reference, though we use diagonal for grid loop)
        # geom_buffered_rotated = QgsGeometry(buffered_aoi_geom)
        # geom_buffered_rotated.rotate(rotation_to_horizontal, rotation_center)
        
        # 2. Rotated ORIGINAL AOI (For Longitudinal X Limits constraint)
        geom_original_rotated = QgsGeometry(original_aoi_geom)
        geom_original_rotated.rotate(rotation_to_horizontal, QgsPointXY(cx, cy))
        r_orig_bbox = geom_original_rotated.boundingBox()
        x_min_constraint = r_orig_bbox.xMinimum()
        x_max_constraint = r_orig_bbox.xMaximum()
        y_min_core = r_orig_bbox.yMinimum()
        y_max_core = r_orig_bbox.yMaximum()
        
        # Grid Generation Loop in Rotated Space
        # Max radius relative to center
        w = bbox_world.width()
        h = bbox_world.height()
        radius = math.sqrt(w*w + h*h) / 2.0
        
        # Relative Limits
        r_min_x = -radius
        r_max_x = radius
        
        # GENERATE Ys (Explicit Lines Logic)
        # We need to cover [y_min_core, y_max_core] with lines spaced by dist_between_lines.
        # Center the grid on the AOI center Y (cy).
        # Relative core range: [y_min_core - cy, y_max_core - cy]
        
        rel_y_min_core = y_min_core - cy
        rel_y_max_core = y_max_core - cy
        
        # Generate Y coordinates covering the core AOI range
        # Start at 0 and go up/down to ensure symmetric grid alignment relative to center
        core_ys = [0]
        # Up
        curr = dist_between_lines
        while curr <= rel_y_max_core + dist_between_lines:
            core_ys.append(curr)
            curr += dist_between_lines
        # Down
        curr = -dist_between_lines
        while curr >= rel_y_min_core - dist_between_lines:
            core_ys.append(curr)
            curr -= dist_between_lines
            
        core_ys = sorted(core_ys)
        
        # VALIDATE CORE Ys: Filter to those that ACTUALLY intersect the Original AOI.
        # This prevents "floating" core lines that don't touch the polygon (which would be treated as auto-side-strips).
        validated_core_ys = []
        for y_c in core_ys:
            # Construct a "Scan Ray" for this Y-line across the whole X-range
            p1_w = rotated_rel_to_world(r_min_x, y_c)
            p2_w = rotated_rel_to_world(r_max_x, y_c)
            scan_line = QgsGeometry.fromPolylineXY([p1_w, p2_w])
            
            if scan_line.intersects(original_aoi_geom):
                validated_core_ys.append(y_c)
        
        core_ys = validated_core_ys
        
        # core_ys now contains only validated core lines.
        # Extra lines will be generated in the Strip Processing phase using Clone Logic.
        
        # Xs Generation (Standard Covering)
        xs = []
        curr = 0
        while curr <= r_max_x:
            xs.append(curr)
            curr += dist_between_photos
        curr = -dist_between_photos
        while curr >= r_min_x:
            xs.append(curr)
            curr -= dist_between_photos
        xs.sort()
        
        # Prepare Sinks
        litchi_fields = QgsFields()
        litchi_fields.append(QgsField('latitude', QVariant.Double))
        litchi_fields.append(QgsField('longitude', QVariant.Double))
        litchi_fields.append(QgsField('altitude(m)', QVariant.Double))
        litchi_fields.append(QgsField('heading(deg)', QVariant.Double))
        litchi_fields.append(QgsField('curvesize(m)', QVariant.Double))
        litchi_fields.append(QgsField('rotationdir', QVariant.Int))
        litchi_fields.append(QgsField('gimbalmode', QVariant.Int))
        litchi_fields.append(QgsField('gimbalpitchangle', QVariant.Int))
        litchi_fields.append(QgsField('altitudemode', QVariant.Int))
        litchi_fields.append(QgsField('speed(m/s)', QVariant.Double))
        litchi_fields.append(QgsField('poi_latitude', QVariant.Double))
        litchi_fields.append(QgsField('poi_longitude', QVariant.Double))
        litchi_fields.append(QgsField('poi_altitude(m)', QVariant.Double))
        litchi_fields.append(QgsField('poi_altitudemode', QVariant.Int))
        litchi_fields.append(QgsField('photo_timeinterval', QVariant.Int))
        litchi_fields.append(QgsField('photo_distinterval', QVariant.Double))
        
        # Add 15 Action Pairs (Litchi Standard)
        for i in range(1, 16):
            litchi_fields.append(QgsField(f'actiontype{i}', QVariant.Int))
            litchi_fields.append(QgsField(f'actionparam{i}', QVariant.Double))

        line_fields = QgsFields()
        line_fields.append(QgsField('strip_id', QVariant.Int))
        line_fields.append(QgsField('type', QVariant.String))

        centroid_fields = QgsFields()
        centroid_fields.append(QgsField('strip_id', QVariant.Int))
        centroid_fields.append(QgsField('photo_id', QVariant.Int))
        centroid_fields.append(QgsField('type', QVariant.String))

        # Create Feature Sinks
        (sink_litchi, dest_id_litchi) = self.parameterAsSink(parameters, self.OUTPUT_LITCHI, context, litchi_fields, QgsWkbTypes.Point, wgs84)
        (sink_lines, dest_id_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, line_fields, QgsWkbTypes.LineString, wgs84)
        (sink_cent, dest_id_cent) = self.parameterAsSink(parameters, self.OUTPUT_CENTROIDS, context, centroid_fields, QgsWkbTypes.Point, wgs84)
 
        # Grid loop variables
        strips = {}
        total_valid = 0
        total_distance_m = 0.0 # Accumulate total flight distance
        total_waypoints_count = 0
        total_photos_count = 0
        
        # NEW: Collect waypoints in a list for auto-splitting logic
        all_waypoints_data = [] 
        
        # STRIP GENERATION - CLONE NEIGHBOR LOGIC
        # 1. Process Core Strips (Strictly Validated)
        core_strips_data = [] # List of (y_rel, points_list)
        
        for y_rel in core_ys:
            points_in_strip = []
            for x_rel in xs:
                pt_world = rotated_rel_to_world(x_rel, y_rel)
                
                # Check Intersection (Strict Core)
                if original_aoi_geom.contains(QgsGeometry.fromPointXY(pt_world)):
                    points_in_strip.append( (x_rel, y_rel, pt_world) )
            
            if points_in_strip:
                core_strips_data.append( (y_rel, points_in_strip) )

        if not core_strips_data:
             feedback.reportError("No valid core strips generated inside AOI. Check AOI or spacing.")
             return {}
             
        # Store Core Strips in Map
        # Note: core_ys indices might not be contiguous if we filtered some out. 
        # But we want to key them by Y or Index?
        # Let's use a simple counter for now, but we need to know "order".
        
        # We will collect ALL strips in order: [ExtraStart ... Core ... ExtraEnd]
        final_strip_list = []
        
        # Reference Core Strips
        first_core = core_strips_data[0] # (y, pts)
        last_core = core_strips_data[-1]
        
        # --- NEW LOGIC: Extend FIRST core strip before cloning ---
        if first_core[1] and extra_photos_first_strip != 0:
            f_x_min = first_core[1][0][0]
            f_x_max = first_core[1][-1][0]
            f_y = first_core[0]
            
            if extra_photos_first_strip < 0:
                # Add to the BEGINNING (negative value)
                num_photos = abs(extra_photos_first_strip)
                new_start_pts = []
                for k in range(num_photos, 0, -1):
                    rx = f_x_min - (k * dist_between_photos)
                    pw = rotated_rel_to_world(rx, f_y)
                    new_start_pts.append((rx, f_y, pw))
                first_core[1][0:0] = new_start_pts
            else:
                # Add to the END (positive value)
                new_end_pts = []
                for k in range(1, extra_photos_first_strip + 1):
                    rx = f_x_max + (k * dist_between_photos)
                    pw = rotated_rel_to_world(rx, f_y)
                    new_end_pts.append((rx, f_y, pw))
                first_core[1].extend(new_end_pts)
        
        # 2. Generate Extra Start Strips (Clones of First Core)
        # We clone the X-structure of the first core strip.
        ref_pts = first_core[1]
        if ref_pts:
             ref_x_min = ref_pts[0][0] # x_rel of first point
             ref_x_max = ref_pts[-1][0] # x_rel of last point
             
             # Calculate exact Xs used in ref? 
             # Actually, we can just use the indices of xs that matched?
             # Or more simply: Generate new points for the Extra Ys using the SAME x_rel values present in Ref.
             ref_xs = [p[0] for p in ref_pts]
             
             # Generate N lines BEFORE first core Y
             first_core_y = first_core[0]
             for k in range(extra_lines_start, 0, -1):
                 new_y = first_core_y - (k * dist_between_lines)
                 new_strip_pts = []
                 for rx in ref_xs:
                     p_w = rotated_rel_to_world(rx, new_y)
                     new_strip_pts.append( (rx, new_y, p_w) )
                 final_strip_list.append(new_strip_pts)

        # 3. Add Core Strips
        for item in core_strips_data:
            final_strip_list.append(item[1])
            
        # --- NEW LOGIC: Extend last core strip before cloning ---
        if last_core[1] and extra_photos_last_strip != 0:
            last_x_min = last_core[1][0][0]
            last_x_max = last_core[1][-1][0]
            last_y = last_core[0]
            
            if extra_photos_last_strip < 0:
                # Add to the BEGINNING (negative value)
                num_photos = abs(extra_photos_last_strip)
                new_start_pts = []
                for k in range(num_photos, 0, -1):
                    rx = last_x_min - (k * dist_between_photos)
                    pw = rotated_rel_to_world(rx, last_y)
                    new_start_pts.append((rx, last_y, pw))
                last_core[1][0:0] = new_start_pts
            else:
                # Add to the END (positive value)
                new_end_pts = []
                for k in range(1, extra_photos_last_strip + 1):
                    rx = last_x_max + (k * dist_between_photos)
                    pw = rotated_rel_to_world(rx, last_y)
                    new_end_pts.append((rx, last_y, pw))
                last_core[1].extend(new_end_pts)
            
        # 4. Generate Extra End Strips (Clones of Last Core)
        ref_pts = last_core[1]
        if ref_pts:
             ref_xs = [p[0] for p in ref_pts]
             last_core_y = last_core[0]
             
             for k in range(1, extra_lines_end + 1):
                 new_y = last_core_y + (k * dist_between_lines)
                 new_strip_pts = []
                 for rx in ref_xs:
                     p_w = rotated_rel_to_world(rx, new_y)
                     new_strip_pts.append( (rx, new_y, p_w) )
                 final_strip_list.append(new_strip_pts)
        
        # Convert List to Map for existing processing logic
        for idx, pts in enumerate(final_strip_list):
            strips[idx] = pts
            total_valid += len(pts)

        feedback.pushInfo(f"Calculated {total_valid} valid structure photos.")

        # Process Strips
        sorted_indices = sorted(strips.keys())
        reverse = False
        previous_strip_end_wgs = None
        previous_strip_end_proj = None

        for strip_idx in sorted_indices:
            pts_data = strips[strip_idx]
            if not pts_data: continue
            
            # Logic: pts_data is sorted by x_rel (since xs was sorted).
            # Extract tuples
            
            if reverse:
                # Snake: Fly Backwards
                logic_start_data = pts_data[-1] 
                logic_end_data = pts_data[0]
                ordered_data = list(reversed(pts_data))
                
                # Vector Logic: Start is "Right" (High X), End is "Left" (Low X)
                # Direction is -X relative.
                ux_rel, uy_rel = -1, 0
            else:
                logic_start_data = pts_data[0]
                logic_end_data = pts_data[-1]
                ordered_data = pts_data
                
                # Direction is +X relative.
                ux_rel, uy_rel = 1, 0
                
            # EXPLICIT EXTENSION LIST
            final_centroids_list = [] # Stores QgsPointXY (World)
            
            # 1. Prepend Extensions
            # We iterate k=Extra...1.
            # Point = Start - k*interval.
            # But we work in relative rotated space to keep line straight easily?
            # Yes. 
            # logic_start_data = (x_rel, y_rel, pt_world)
            sx_rel, sy_rel = logic_start_data[0], logic_start_data[1]
            
            for k in range(extra_photos_end, 0, -1):
                # Backwards from start
                dist = k * dist_between_photos
                new_x_rel = sx_rel - (ux_rel * dist)
                new_y_rel = sy_rel - (uy_rel * dist)
                
                pt_w = rotated_rel_to_world(new_x_rel, new_y_rel)
                final_centroids_list.append(pt_w)
                
                # Output to Centroids sink immediately? Or collect?
                # Let's collect to be safe.
                if sink_cent:
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPointXY(tr_to_wgs84.transform(pt_w)))
                    f.setAttributes([strip_idx, -k, 'Extension_Start'])
                    sink_cent.addFeature(f, QgsFeatureSink.FastInsert)
            
            # 2. Add Structure Points
            for idx, d in enumerate(ordered_data):
                pt_w = d[2]
                final_centroids_list.append(pt_w)
                if sink_cent:
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPointXY(tr_to_wgs84.transform(pt_w)))
                    f.setAttributes([strip_idx, idx, 'Structure'])
                    sink_cent.addFeature(f, QgsFeatureSink.FastInsert)
                    
            # 3. Append Extensions
            ex_rel, ey_rel = logic_end_data[0], logic_end_data[1]
            for k in range(1, extra_photos_end + 1):
                dist = k * dist_between_photos
                new_x_rel = ex_rel + (ux_rel * dist)
                new_y_rel = ey_rel + (uy_rel * dist)
                
                pt_w = rotated_rel_to_world(new_x_rel, new_y_rel)
                final_centroids_list.append(pt_w)
                
                if sink_cent:
                     f = QgsFeature()
                     f.setGeometry(QgsGeometry.fromPointXY(tr_to_wgs84.transform(pt_w)))
                     f.setAttributes([strip_idx, len(ordered_data)+k, 'Extension_End'])
                     sink_cent.addFeature(f, QgsFeatureSink.FastInsert)
            
            # WAYPOINTS (World)
            final_start_wgs = tr_to_wgs84.transform(final_centroids_list[0])
            final_end_wgs = tr_to_wgs84.transform(final_centroids_list[-1])
            
            # HEADING
            d = QgsDistanceArea()
            d.setSourceCrs(wgs84, context.project().transformContext())
            bearing = d.bearing(final_start_wgs, final_end_wgs)
            bearing_deg = math.degrees(bearing)
            if bearing_deg < 0: bearing_deg += 360
            
            total_photos_count += len(final_centroids_list)
            
            # COLLECT WAYPOINTS DATA (For list-based processing)
            # Each entry is a dict matching Litchi CSV columns
            
            def create_wp(pt, bearing):
                # If Stop-and-Shoot, we add action "Take Photo" (1) at each waypoint
                actions = {}
                if stop_and_shoot:
                    # Litchi CSV actions: actiontype1, actionparam1, ...
                    actions['actiontype1'] = 1 # Take Photo
                    actions['actionparam1'] = 0
                
                wp = {
                    'latitude': pt.y(),
                    'longitude': pt.x(),
                    'altitude(m)': altitude,
                    'heading(deg)': bearing,
                    'curvesize(m)': dist_between_lines * 0.15 if not stop_and_shoot else 0.0,
                    'rotationdir': 0,
                    'gimbalmode': 0,
                    'gimbalpitchangle': -90,
                    'altitudemode': 1,
                    'speed(m/s)': speed if not stop_and_shoot else 0.0,
                    'poi_latitude': 0,
                    'poi_longitude': 0,
                    'poi_altitude(m)': 0,
                    'poi_altitudemode': 0,
                    'photo_timeinterval': 0,
                    'photo_distinterval': dist_between_photos if not stop_and_shoot else 0.0
                }
                wp.update(actions)
                return wp

            # Add Start
            all_waypoints_data.append(create_wp(final_start_wgs, bearing_deg))
            
            # Optional Midpoint
            if add_mid_point and final_centroids_list:
                n_pts = len(final_centroids_list)
                mid_idx = (n_pts - 1) // 2
                mid_pt_proj = final_centroids_list[mid_idx]
                mid_pt_wgs = tr_to_wgs84.transform(mid_pt_proj)
                all_waypoints_data.append(create_wp(mid_pt_wgs, bearing_deg))
                
            # Add End
            all_waypoints_data.append(create_wp(final_end_wgs, bearing_deg))

            # Calculate Distance for Report (Projected Metric)
            strip_len_proj = 0
            for i in range(len(final_centroids_list) - 1):
                p1 = final_centroids_list[i]
                p2 = final_centroids_list[i+1]
                strip_len_proj += math.sqrt((p1.x()-p2.x())**2 + (p1.y()-p2.y())**2)
            
            total_distance_m += strip_len_proj

            # OUTPUT FLIGHT LINE
            if sink_lines:
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPolylineXY([final_start_wgs, final_end_wgs]))
                f.setAttributes([strip_idx, 'Flight'])
                sink_lines.addFeature(f, QgsFeatureSink.FastInsert)

            if previous_strip_end_proj:
                # Distance from prev end to current start
                curr_start_proj = final_centroids_list[0]
                turn_dist = math.sqrt((curr_start_proj.x()-previous_strip_end_proj.x())**2 + (curr_start_proj.y()-previous_strip_end_proj.y())**2)
                total_distance_m += turn_dist
                
                if sink_lines:
                     f_turn = QgsFeature()
                     f_turn.setGeometry(QgsGeometry.fromPolylineXY([previous_strip_end_wgs, final_start_wgs]))
                     f_turn.setAttributes([strip_idx, 'Turn'])
                     sink_lines.addFeature(f_turn, QgsFeatureSink.FastInsert)

            previous_strip_end_wgs = final_end_wgs
            previous_strip_end_proj = final_centroids_list[-1]
            reverse = not reverse

        # Populate Sink (Full Mission)
        if sink_litchi:
            for wp_dict in all_waypoints_data:
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(wp_dict['longitude'], wp_dict['latitude'])))
                # Attributes must match litchi_fields defined earlier
                attrs = [
                    wp_dict['latitude'], wp_dict['longitude'], wp_dict['altitude(m)'],
                    wp_dict['heading(deg)'], wp_dict['curvesize(m)'], wp_dict['rotationdir'],
                    wp_dict['gimbalmode'], wp_dict['gimbalpitchangle'], wp_dict['altitudemode'],
                    wp_dict['speed(m/s)'], wp_dict['poi_latitude'], wp_dict['poi_longitude'],
                    wp_dict['poi_altitude(m)'], wp_dict['poi_altitudemode'],
                    wp_dict['photo_timeinterval'], wp_dict['photo_distinterval']
                ]
                # Always add 15 Action Pairs to match fields definition
                if stop_and_shoot:
                    attrs += [wp_dict.get('actiontype1', 1), wp_dict.get('actionparam1', 0)]
                else:
                    attrs += [-1, 0]
                
                # Remaining 14 actions
                for _ in range(14):
                    attrs += [-1, 0]
                
                f.setAttributes(attrs)
                sink_litchi.addFeature(f, QgsFeatureSink.FastInsert)
        
        total_waypoints_count = len(all_waypoints_data)

        # AUTO-SPLIT LOGIC (File based)
        if auto_split and total_waypoints_count > 99:
             # We try to determine a base name from the output sink if possible, or use a default
             # In processing, we don't always have a real file path for the sink unless it was specified.
             # Let's check feedback or use a temp path? 
             # Better: Use the same directory where the report would have gone, or provide a log info.
             feedback.pushInfo(f"Auto-split enabled. Mission has {total_waypoints_count} waypoints. Splitting into {math.ceil(total_waypoints_count/99)} parts.")
             
             # Chunking
             for i in range(0, total_waypoints_count, 99):
                 chunk = all_waypoints_data[i : i + 99]
                 part_num = (i // 99) + 1
                 
                 if output_folder:
                     # ensure directory exists (user might provide a placeholder file path)
                     folder = os.path.dirname(output_folder) if not os.path.isdir(output_folder) else output_folder
                     if not os.path.exists(folder):
                         os.makedirs(folder, exist_ok=True)
                     
                     file_path = os.path.join(folder, f"mission_part{part_num}.csv")
                     with open(file_path, 'w', newline='') as csvfile:
                         # Use all columns present in the first wp
                         fieldnames = [
                            'latitude', 'longitude', 'altitude(m)', 'heading(deg)', 'curvesize(m)',
                            'rotationdir', 'gimbalmode', 'gimbalpitchangle', 'altitudemode', 'speed(m/s)',
                            'poi_latitude', 'poi_longitude', 'poi_altitude(m)', 'poi_altitudemode',
                            'photo_timeinterval', 'photo_distinterval'
                         ]
                         # Add all 15 action cols
                         for j in range(1, 16):
                             fieldnames += [f'actiontype{j}', f'actionparam{j}']
                             
                         writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                         writer.writeheader()
                         for wp in chunk:
                             # Fill missing action cols for the CSV
                             full_wp = wp.copy()
                             for j in range(1, 16):
                                 full_wp.setdefault(f'actiontype{j}', -1)
                                 full_wp.setdefault(f'actionparam{j}', 0)
                             writer.writerow({k: full_wp[k] for k in fieldnames})
                     
                     feedback.pushInfo(f"Saved part {part_num} to: {file_path}")

        # Full Report Generation (Log)
        total_time_seconds = total_distance_m / speed
        total_time_min = total_time_seconds / 60.0
        
        # 5. Safety & Motion Blur Check
        shutter_sec = 1.0 / shutter_denom
        motion_blur = speed * shutter_sec # Meters per exposure
        blur_status = "OK"
        if motion_blur > gsd_m:
            blur_status = "CRITICAL (Blur > GSD)"
        elif motion_blur > gsd_m / 2.0:
            blur_status = "WARNING (Blur > GSD/2)"
        
        cam_battery_max = cam.get('max_flight_time_minutes', 0)
        if cam_battery_max > 0:
            safe_flight_time = cam_battery_max * 0.8 # 20% safety margin
            batteries_needed = total_time_min / safe_flight_time
            battery_str = f"{batteries_needed:.2f} (approx {math.ceil(batteries_needed)})"
            safe_margin_str = f"(assuming {safe_flight_time:.1f} min safe flight time per battery)"
        else:
            battery_str = "N/A (Update cameras.json)"
            safe_margin_str = ""

        feedback.pushInfo("")
        feedback.pushInfo("=== Litchi Mission Report ===")
        feedback.pushInfo(f"Camera: {cam['name']}")
        feedback.pushInfo(f"Area: {original_aoi_geom.area():.2f} sq m (approx)")
        feedback.pushInfo("Mission Statistics:")
        feedback.pushInfo(f"- Total Distance: {total_distance_m:.2f} m")
        feedback.pushInfo(f"- Speed: {speed} m/s")
        feedback.pushInfo(f"- Estimated Flight Time: {total_time_min:.2f} minutes")
        feedback.pushInfo(f"- Batteries Required: {battery_str} {safe_margin_str}")
        feedback.pushInfo(f"- Waypoints: {total_waypoints_count}")
        if total_waypoints_count > 99:
            feedback.reportError(f"WARNING: Waypoint count ({total_waypoints_count}) exceeds Litchi limit of 99!")
            if not auto_split:
                 feedback.reportError("Tip: Enable 'Auto-Split Missions' for easier management.")
        
        feedback.pushInfo(f"- Photos: {total_photos_count}")
        if total_photos_count > 999:
            feedback.reportError(f"WARNING: Photo count ({total_photos_count}) exceeds WebODM free tier limit of 999!")

        feedback.pushInfo(f"- Motion Blur: {motion_blur*1000:.2f} mm ({blur_status})")
        if blur_status != "OK":
             feedback.reportError(f"Motion Blur {blur_status}. Increase shutter speed or decrease flight speed.")

        feedback.pushInfo("")
        feedback.pushInfo("Detailed Settings:")
        feedback.pushInfo(f"- GSD: {gsd_cm} cm/px")
        feedback.pushInfo(f"- Altitude: {altitude:.2f} m")
        feedback.pushInfo(f"- Heading: {heading_angle} deg")
        feedback.pushInfo(f"- Overlap: {overlap_fwd*100:.0f}% Fwd, {overlap_side*100:.0f}% Side")
        feedback.pushInfo(f"- Projection Used: EPSG:{epsg_code}")
        feedback.pushInfo("")

        return {
            self.OUTPUT_LITCHI: dest_id_litchi,
            self.OUTPUT_LINES: dest_id_lines,
            self.OUTPUT_CENTROIDS: dest_id_cent
        }
