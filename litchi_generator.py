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
    ALTITUDE = 'ALTITUDE'
    SPEED = 'SPEED'
    HEADING = 'HEADING'
    OVERLAP_FWD = 'OVERLAP_FWD'
    OVERLAP_SIDE = 'OVERLAP_SIDE'
    BUFFER_PCT = 'BUFFER_PCT'
    
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
        return self.tr("Generates a photogrammetry flight plan for Litchi using a Grid-Centric approach. Outputs: Waypoints (CSV ready), Flight Lines, and Photo Centroids.")

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

        self.addParameter(QgsProcessingParameterNumber(self.ALTITUDE, self.tr('Altitude (m)'), defaultValue=50.0))
        self.addParameter(QgsProcessingParameterNumber(self.SPEED, self.tr('Speed (m/s)'), defaultValue=5.0))
        self.addParameter(QgsProcessingParameterNumber(self.HEADING, self.tr('Flight Direction (Degrees)'), defaultValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_FWD, self.tr('Forward Overlap (%)'), defaultValue=80.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_SIDE, self.tr('Side Overlap (%)'), defaultValue=70.0))
        self.addParameter(QgsProcessingParameterNumber(self.BUFFER_PCT, self.tr('Buffer (%)'), defaultValue=0.0))

        # Outputs
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LITCHI, self.tr('Litchi Mission (Waypoints)')))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_LINES, self.tr('Flight Lines'), optional=True))
        self.addParameter(QgsProcessingParameterFeatureSink(self.OUTPUT_CENTROIDS, self.tr('Photo Centroids (QC)'), optional=True))

    def processAlgorithm(self, parameters, context, feedback):
        aoi_layer = self.parameterAsSource(parameters, self.AOI, context)
        if not aoi_layer:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.AOI))

        camera_idx = self.parameterAsEnum(parameters, self.CAMERA, context)
        altitude = self.parameterAsDouble(parameters, self.ALTITUDE, context)
        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        heading_angle = self.parameterAsDouble(parameters, self.HEADING, context)
        overlap_fwd = self.parameterAsDouble(parameters, self.OVERLAP_FWD, context) / 100.0
        overlap_side = self.parameterAsDouble(parameters, self.OVERLAP_SIDE, context) / 100.0
        buffer_pct = self.parameterAsDouble(parameters, self.BUFFER_PCT, context) / 100.0
        
        # Get Camera Specs
        if not self.cameras:
             raise QgsProcessingException("No cameras defined in cameras.json")
        cam = self.cameras[camera_idx]
        sw, sh = cam['sensor_width_mm'], cam['sensor_height_mm']
        fl = cam['focal_length_mm']
        
        # Calculations (Ground Footprint)
        fp_width = (sw * altitude) / fl
        fp_height = (sh * altitude) / fl
        
        dist_between_lines = fp_width * (1 - overlap_side)
        dist_between_photos = fp_height * (1 - overlap_fwd) 
        
        feedback.pushInfo(f"Camera: {cam['name']}")
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
        
        # Combine Geometries
        combined_geom = None
        for feat in aoi_layer.getFeatures():
            geom = feat.geometry()
            if geom and not geom.isEmpty():
                if combined_geom is None:
                    combined_geom = QgsGeometry(geom)
                else:
                    combined_geom = combined_geom.combine(geom)
        
        if combined_geom is None or combined_geom.isEmpty():
             raise QgsProcessingException("Input AOI layer contains no valid geometries.")
        
        combined_geom.transform(tr_to_proj)
        
        # Apply Buffer on AOI to get a larger coverage
        if buffer_pct > 0:
            size_proxy = math.sqrt(abs(combined_geom.area()))
            buf_dist = size_proxy * buffer_pct
            combined_geom = combined_geom.buffer(buf_dist, 5)
        
        bbox = combined_geom.boundingBox()
        cx, cy = bbox.center().x(), bbox.center().y()
        
        # GRID GENERATION LOGIC
        # 1. Rotate AOI by -Heading to align with X/Y axes
        rot_angle = heading_angle - 90 # If we assume Heading 0 is North (Y). We want to transform to X.
        # Actually, let's stick to standard math: 
        # We want to scan along Heading.
        # Rotating AOI by -Heading aligns Heading to Vertical Y? Or Horizontal X?
        # Let's say Heading 0 (North). We want lines Vertical.
        # If we rotate by -0, it's Vertical. We scan X, vary Y. 
        # But standard algorithms usually scan Rows (Horizontal).
        # So let's align Heading to X-axis (Horizontal).
        # Heading 0 (Y). Target (X). Diff is -90.
        # So Rotate by -90 + Heading? Or Heading - 90?
        # Angle from X to Y is +90.
        # Angle from North(Y) to Heading is H.
        # Total rotation?
        # Let's use `rot_angle` as the rotation applied to geometry to make lines Horizontal.
        # If H=0 (North), lines are vertical. We want horizontal. Rotate by 90.
        # If H=90 (East), lines are horizontal. Rotate by 0.
        # So Rotation = 90 - H.
        # Let's verify. H=45. Lines / . Rotate by 45 -> -. Horizontal. Correct.
        # H=180 (South). Lines |. Rotate by -90? Or 270.
        
        rotation_to_horizontal = 90 - heading_angle
        
        geom_rotated = QgsGeometry(combined_geom)
        geom_rotated.rotate(rotation_to_horizontal, QgsPointXY(cx, cy))
        
        r_bbox = geom_rotated.boundingBox()
        
        # 2. Build Grid of Points
        xs = []
        ys = []
        
        curr_x = r_bbox.xMinimum()
        while curr_x <= r_bbox.xMaximum():
            xs.append(curr_x)
            curr_x += dist_between_photos
            
        curr_y = r_bbox.yMinimum()
        while curr_y <= r_bbox.yMaximum():
            ys.append(curr_y)
            curr_y += dist_between_lines
            
        # 3. Filter Points
        # We store valid points in a dict: strips[y_index] = [p1, p2, p3...]
        # Because floats are messy keys, we use the index i, j
        strips = {}
        
        total_photos = 0
        
        for j, y_coord in enumerate(ys):
            points_in_strip = []
            for i, x_coord in enumerate(xs):
                pt = QgsPointXY(x_coord, y_coord)
                if geom_rotated.contains(QgsGeometry.fromPointXY(pt)):
                     # It's inside!
                     points_in_strip.append(pt)
            
            if points_in_strip:
                strips[j] = points_in_strip
                total_photos += len(points_in_strip)

        feedback.pushInfo(f"Generated {total_photos} photo centroids.")

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

        centroid_fields = QgsFields()
        centroid_fields.append(QgsField('strip_id', QMetaType.Type.Int))
        centroid_fields.append(QgsField('photo_id', QMetaType.Type.Int))

        (sink_litchi, dest_id_litchi) = self.parameterAsSink(parameters, self.OUTPUT_LITCHI, context, litchi_fields, QgsWkbTypes.Point, wgs84)
        (sink_lines, dest_id_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, line_fields, QgsWkbTypes.LineString, wgs84)
        (sink_cent, dest_id_cent) = self.parameterAsSink(parameters, self.OUTPUT_CENTROIDS, context, centroid_fields, QgsWkbTypes.Point, wgs84)

        # 4. Process Strips
        # Sort strips by Key (Y index)
        sorted_indices = sorted(strips.keys())
        
        reverse = False
        
        def transform_back(pt_proj):
            # Rotate back around Center
            px, py = pt_proj.x() - cx, pt_proj.y() - cy
            # We rotated by 'rotation_to_horizontal'. So we rotate back by -rotation_to_horizontal.
            rad = math.radians(-rotation_to_horizontal)
            nx = px * math.cos(rad) - py * math.sin(rad)
            ny = px * math.sin(rad) + py * math.cos(rad)
            fx, fy = nx + cx, ny + cy
            # To WGS84
            return tr_to_wgs84.transform(QgsPointXY(fx, fy))

        for strip_idx in sorted_indices:
            pts = strips[strip_idx]
            if not pts: continue
            
            # Snake logic: if reverse, process points in reverse order?
            # Actually, the points in 'pts' are sorted by X.
            # Start/End definition:
            start_proj = pts[0]
            end_proj = pts[-1]
            
            if reverse:
                # If flying backwards (Right to Left on map frame), Start is end_proj, End is start_proj
                wp1_proj = end_proj
                wp2_proj = start_proj
                ordered_pts = list(reversed(pts))
            else:
                wp1_proj = start_proj
                wp2_proj = end_proj
                ordered_pts = pts
            
            # Transform Waypoints
            wp1_wgs = transform_back(wp1_proj)
            wp2_wgs = transform_back(wp2_proj)
            
            # Calculate Heading
            d = QgsDistanceArea()
            d.setSourceCrs(wgs84, context.project().transformContext())
            bearing = d.bearing(wp1_wgs, wp2_wgs) 
            bearing_deg = math.degrees(bearing)
            if bearing_deg < 0: bearing_deg += 360
            
            # Output Litchi Waypoints (Start and End)
            if sink_litchi:
                for pt_wgs in [wp1_wgs, wp2_wgs]:
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPointXY(pt_wgs))
                    f.setAttributes([
                        pt_wgs.y(), pt_wgs.x(), altitude,
                        bearing_deg, # Heading (Coupled)
                        0.0, 0, 0, -90, 1, speed, 0,0,0,0,0,
                        dist_between_photos
                    ])
                    sink_litchi.addFeature(f, QgsFeatureSink.FastInsert)
            
            # Output Lines
            if sink_lines:
                lf = QgsFeature()
                lf.setGeometry(QgsGeometry.fromPolylineXY([wp1_wgs, wp2_wgs]))
                lf.setAttributes([strip_idx])
                sink_lines.addFeature(lf, QgsFeatureSink.FastInsert)
                
            # Output Centroids
            if sink_cent:
                for i, pt_proj in enumerate(ordered_pts):
                    cent_wgs = transform_back(pt_proj)
                    cf = QgsFeature()
                    cf.setGeometry(QgsGeometry.fromPointXY(cent_wgs))
                    cf.setAttributes([strip_idx, i])
                    sink_cent.addFeature(cf, QgsFeatureSink.FastInsert)
            
            reverse = not reverse

        return {
            self.OUTPUT_LITCHI: dest_id_litchi,
            self.OUTPUT_LINES: dest_id_lines,
            self.OUTPUT_CENTROIDS: dest_id_cent
        }
