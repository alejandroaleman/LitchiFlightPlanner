from qgis.PyQt.QtCore import QCoreApplication, QMetaType, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterNumber,
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
    
    OUTPUT_LITCHI = 'OUTPUT_LITCHI'
    OUTPUT_LINES = 'OUTPUT_LINES'
    OUTPUT_CENTROIDS = 'OUTPUT_CENTROIDS'

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

        self.addParameter(QgsProcessingParameterNumber(self.GSD, self.tr('Target GSD (cm/px)'), defaultValue=2.5))
        self.addParameter(QgsProcessingParameterNumber(self.SPEED, self.tr('Speed (m/s)'), defaultValue=8.0))
        self.addParameter(QgsProcessingParameterNumber(self.HEADING, self.tr('Flight Direction (Degrees)'), defaultValue=-13.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_FWD, self.tr('Forward Overlap (%)'), defaultValue=70.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_SIDE, self.tr('Side Overlap (%)'), defaultValue=65.0))
        
        # Advanced Buffers (Explicit Lines)
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_LINES_START, self.tr('Extra Lines at Start (N)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_LINES_END, self.tr('Extra Lines at End (M)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_PHOTOS_END, self.tr('Extra Photos at Ends (N)'), defaultValue=2, type=QgsProcessingParameterNumber.Integer))

        # Outputs
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LITCHI, self.tr('Litchi Mission (Waypoints)')))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LINES, self.tr('Flight Lines'), optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_CENTROIDS, self.tr('Photo Centroids (QC)'), optional=True))

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
        
        # Get Camera Specs
        if not self.cameras:
             raise QgsProcessingException("No cameras defined in cameras.json")
        cam = self.cameras[camera_idx]
        sw, sh = cam['sensor_width_mm'], cam['sensor_height_mm']
        fl = cam['focal_length_mm']
        im_w, im_h = cam['image_width_px'], cam['image_height_px']
        
        # GSD to Altitude Calculation
        gsd_m = gsd_cm / 100.0
        altitude = (gsd_m * fl * im_w) / sw
        
        feedback.pushInfo(f"Camera: {cam['name']}")
        feedback.pushInfo(f"GSD: {gsd_cm} cm/px -> Calculated Altitude: {altitude:.2f} m")
        
        # Calculations (Ground Footprint)
        fp_width = (sw * altitude) / fl
        fp_height = (sh * altitude) / fl
        
        dist_between_lines = fp_width * (1 - overlap_side)
        dist_between_photos = fp_height * (1 - overlap_fwd) 
        
        feedback.pushInfo(f"Footprint: {fp_width:.2f}m x {fp_height:.2f}m")
        feedback.pushInfo(f"Line Spacing: {dist_between_lines:.2f}m")
        feedback.pushInfo(f"Photo Interval: {dist_between_photos:.2f}m")

        # CRS Setup
        source_crs = aoi_layer.sourceCrs()
        if source_crs.isGeographic():
             feedback.pushInfo("Input CRS is Geographic. Reprojecting to Web Mercator for grid generation.")
             projected_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        else:
             projected_crs = source_crs 
        
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        
        tr_to_proj = QgsCoordinateTransform(source_crs, projected_crs, context.project())
        tr_to_wgs84 = QgsCoordinateTransform(projected_crs, wgs84, context.project())
        
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
        
        original_aoi_geom.transform(tr_to_proj)
        
        # Rotation Center and Limits from Original AOI
        bbox_world = original_aoi_geom.boundingBox()
        cx, cy = bbox_world.center().x(), bbox_world.center().y()
        rotation_center = QgsPointXY(cx, cy)
        
        # Rotation Angle
        rotation_to_horizontal = 90 - heading_angle
        
        # Transformation Helper (Moved up for scope access)
        def rotated_rel_to_world(rx, ry):
            rad = math.radians(-rotation_to_horizontal)
            wx = rx * math.cos(rad) - ry * math.sin(rad)
            wy = rx * math.sin(rad) + ry * math.cos(rad)
            final_x = wx + cx
            final_y = wy + cy
            return QgsPointXY(final_x, final_y)
        
        # 1. Rotated Buffered AOI (for Y limits reference, though we use diagonal for grid loop)
        # geom_buffered_rotated = QgsGeometry(buffered_aoi_geom)
        # geom_buffered_rotated.rotate(rotation_to_horizontal, rotation_center)
        
        # 2. Rotated ORIGINAL AOI (For Longitudinal X Limits constraint)
        geom_original_rotated = QgsGeometry(original_aoi_geom)
        geom_original_rotated.rotate(rotation_to_horizontal, rotation_center)
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
        
        # Construct Core Ys (from center outwards to ensure symmetry? Or just bottom-up covering?)
        # Let's use Bottom-Up for simpler index logic.
        # Start Y: Smallest Y such that Y >= rel_y_min_core? 
        # Actually, let's just generate a minimal set of lines covering the range.
        # Start at rel_y_min_core + offset?
        # Let's stick to the "Centered Grid" approach: 0 is a line.
        # Generate lines outwards from 0 until they exceed rel_y_max_core / rel_y_min_core.
        
        core_ys = []
        # Positive (and 0)
        curr = 0
        # Relaxed bounds just to gather candidates, but we will filter them strictly next.
        while curr <= rel_y_max_core + dist_between_lines: 
            if curr >= rel_y_min_core - dist_between_lines: 
               core_ys.append(curr)
            curr += dist_between_lines
            
        # Negative
        curr = -dist_between_lines
        while curr >= rel_y_min_core - dist_between_lines:
            if curr <= rel_y_max_core + dist_between_lines:
                core_ys.append(curr)
            curr -= dist_between_lines
            
        core_ys = sorted(list(set(core_ys)))
        
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
        litchi_fields.append(QgsField('latitude', QMetaType.Type.Double))
        litchi_fields.append(QgsField('longitude', QMetaType.Type.Double))
        litchi_fields.append(QgsField('altitude(m)', QMetaType.Type.Double))
        litchi_fields.append(QgsField('heading(deg)', QMetaType.Type.Double))
        litchi_fields.append(QgsField('curvesize(m)', QMetaType.Type.Double))
        litchi_fields.append(QgsField('rotationdir', QMetaType.Type.Int))
        litchi_fields.append(QgsField('gimbalmode', QMetaType.Type.Int))
        litchi_fields.append(QgsField('gimbalpitchangle', QMetaType.Type.Int))
        litchi_fields.append(QgsField('altitudemode', QMetaType.Type.Int))
        litchi_fields.append(QgsField('speed(m/s)', QMetaType.Type.Double))
        litchi_fields.append(QgsField('poi_latitude', QMetaType.Type.Double))
        litchi_fields.append(QgsField('poi_longitude', QMetaType.Type.Double))
        litchi_fields.append(QgsField('poi_altitude(m)', QMetaType.Type.Double))
        litchi_fields.append(QgsField('poi_altitudemode', QMetaType.Type.Int))
        litchi_fields.append(QgsField('photo_timeinterval', QMetaType.Type.Int))
        litchi_fields.append(QgsField('photo_distinterval', QMetaType.Type.Double))

        line_fields = QgsFields()
        line_fields.append(QgsField('strip_id', QMetaType.Type.Int))
        line_fields.append(QgsField('type', QVariant.String))

        centroid_fields = QgsFields()
        centroid_fields.append(QgsField('strip_id', QMetaType.Type.Int))
        centroid_fields.append(QgsField('photo_id', QMetaType.Type.Int))
        centroid_fields.append(QgsField('type', QVariant.String))

        (sink_litchi, dest_id_litchi) = self.parameterAsSink(parameters, self.OUTPUT_LITCHI, context, litchi_fields, QgsWkbTypes.Point, wgs84)
        (sink_lines, dest_id_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, line_fields, QgsWkbTypes.LineString, wgs84)
        (sink_cent, dest_id_cent) = self.parameterAsSink(parameters, self.OUTPUT_CENTROIDS, context, centroid_fields, QgsWkbTypes.Point, wgs84)

        # Absolute Rotated (centered at cx, cy) check
        # Our Xs, Ys are RELATIVE to cx, cy.
        # But our x_min_constraint is ABSOLUTE in rotated space (because QgsGeometry.rotate does absolute rotation).
        # We need to map relative xs to absolute rotated X to compare.
        # Rotated Points are: (cx + rx', cy + ry') where we rotate (rx,ry) back? 
        # Wait, QgsGeometry.rotate rotates A point P around Center C.
        # P_new = C + R(P-C).
        # Our grid construction: We defined a coordinate system (X', Y') aligned with rotated axes centered at C.
        # So a point x_rel, y_rel (relative to C) IS (P-C) in the rotated frame.
        # So its absolute coordinate in the Rotated Frame is C + (x_rel, y_rel).
        # X_abs = cx + x_rel.
        # Y_abs = cy + y_rel.
        # Wait, rotating a geometry around C changes its coordinates. 
        # If I have a point P that is (cx+10, cy) and I rotate geometry 90 deg around C.
        # P becomes (cx, cy+10).
        # So my 'rotated' coordinates (from the geom) are indeed centered at cx, cy roughly.
        # BUT: BoundingBox.xMinimum() gives min X in that systems.
        # Yes.
        # However, `rotate` function might not align Local Axis X with Global X.
        # It rotates the SHAPE against the fixed global axes.
        # So if we rotate by `90 - Heading`, we are aligning the "Heading Axis" of the shape to be Horizontal (Global X).
        # So checking X coordinates in this transformed state is checking position along the "Heading-Aligned" axis.
        # And my `xs` loop corresponds to relative offsets along that same axis?
        # Yes, because I built `xs` simply as a linear range.
        # BUT I have to offset them by `cx` to compare with `x_min_constraint`!
        # Because `x_min_constraint` is from an Absolute coordinate system.
        
        strips = {}
        total_valid = 0
        
        
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
            
            # OUTPUT LITCHI
            if sink_litchi:
                for pt in [final_start_wgs, final_end_wgs]:
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPointXY(pt))
                    f.setAttributes([
                        pt.y(), pt.x(), altitude,
                        bearing_deg, 
                        0.0, 0, 0, -90, 1, speed, 0,0,0,0,0,
                        dist_between_photos
                    ])
                    sink_litchi.addFeature(f, QgsFeatureSink.FastInsert)
            
            # OUTPUT FLIGHT LINE
            if sink_lines:
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPolylineXY([final_start_wgs, final_end_wgs]))
                f.setAttributes([strip_idx, 'Flight'])
                sink_lines.addFeature(f, QgsFeatureSink.FastInsert)
                
                # OUTPUT CONNECTION LINE (Turn from previous end)
                if previous_strip_end_wgs:
                    f_turn = QgsFeature()
                    f_turn.setGeometry(QgsGeometry.fromPolylineXY([previous_strip_end_wgs, final_start_wgs]))
                    f_turn.setAttributes([strip_idx, 'Turn'])
                    sink_lines.addFeature(f_turn, QgsFeatureSink.FastInsert)
            
            previous_strip_end_wgs = final_end_wgs
            reverse = not reverse

        return {
            self.OUTPUT_LITCHI: dest_id_litchi,
            self.OUTPUT_LINES: dest_id_lines,
            self.OUTPUT_CENTROIDS: dest_id_cent
        }
