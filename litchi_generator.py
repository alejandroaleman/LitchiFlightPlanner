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
    BUFFER_SIDE_PCT = 'BUFFER_SIDE_PCT'
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
        return self.tr("Generates a photogrammetry flight plan for Litchi. Inputs: GSD (calculates Altitude), Heading (rotates Grid), Buffers (Side % and Ends).")

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
        self.addParameter(QgsProcessingParameterNumber(self.SPEED, self.tr('Speed (m/s)'), defaultValue=5.0))
        self.addParameter(QgsProcessingParameterNumber(self.HEADING, self.tr('Flight Direction (Degrees)'), defaultValue=0.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_FWD, self.tr('Forward Overlap (%)'), defaultValue=80.0))
        self.addParameter(QgsProcessingParameterNumber(self.OVERLAP_SIDE, self.tr('Side Overlap (%)'), defaultValue=70.0))
        
        # Advanced Buffers
        self.addParameter(QgsProcessingParameterNumber(self.BUFFER_SIDE_PCT, self.tr('Structure Buffer (Side widening %)'), defaultValue=20.0))
        self.addParameter(QgsProcessingParameterNumber(self.EXTRA_PHOTOS_END, self.tr('Extra Photos at Ends (N)'), defaultValue=0, type=QgsProcessingParameterNumber.Integer))

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
        buffer_side_pct = self.parameterAsDouble(parameters, self.BUFFER_SIDE_PCT, context) / 100.0
        extra_photos_end = self.parameterAsInt(parameters, self.EXTRA_PHOTOS_END, context)
        
        # Get Camera Specs
        if not self.cameras:
             raise QgsProcessingException("No cameras defined in cameras.json")
        cam = self.cameras[camera_idx]
        sw, sh = cam['sensor_width_mm'], cam['sensor_height_mm']
        fl = cam['focal_length_mm']
        im_w, im_h = cam['image_width_px'], cam['image_height_px']
        
        # GSD to Altitude Calculation
        # H = (GSD_m * f_mm * im_w_px) / sw_mm
        # GSD in m/px
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
        
        # SIDE BUFFERING (Widening the AOI for filtering/Grid generation)
        # Calculate a size proxy for relative buffer.
        size_proxy = math.sqrt(abs(original_aoi_geom.area()))
        
        # Or should we just apply buffer_side_pct of the width?
        # User defined as %. Let's use sqrt(area) * pct.
        buf_dist = size_proxy * buffer_side_pct
        
        buffered_aoi_geom = original_aoi_geom.buffer(buf_dist, 5) # 5 segments approximation
        
        # Grid Generation BBox (from Buffered)
        bbox_buffered = buffered_aoi_geom.boundingBox()
        cx, cy = bbox_buffered.center().x(), bbox_buffered.center().y()
        
        # Rotate logic
        # We align heading with X-axis to scan easier.
        rotation_to_horizontal = 90 - heading_angle
        
        geom_buffered_rotated = QgsGeometry(buffered_aoi_geom)
        geom_buffered_rotated.rotate(rotation_to_horizontal, QgsPointXY(cx, cy))
        
        r_bbox = geom_buffered_rotated.boundingBox()
        
        # Grid Points Generation
        # Extend slightly to ensure coverage?
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
            
        # Filter Points against the BUFFERED Rotated AOI
        # Note: We can filter directly in rotated space if we rotated the Geometry too.
        # Yes, geom_buffered_rotated is already rotated.
        
        strips = {} # Key: strip_index (y index), Value: [points...]
        
        total_photos_initial = 0
        
        for j, y_coord in enumerate(ys):
            points_in_strip = []
            for i, x_coord in enumerate(xs):
                pt = QgsPointXY(x_coord, y_coord)
                if geom_buffered_rotated.contains(QgsGeometry.fromPointXY(pt)):
                     # Inside the Buffered AOI
                     points_in_strip.append(pt)
            
            if points_in_strip:
                strips[j] = points_in_strip
                total_photos_initial += len(points_in_strip)

        feedback.pushInfo(f"Calculated {total_photos_initial} initial valid photos (inside structure buffer).")

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

        # Process Strips and Output
        sorted_indices = sorted(strips.keys())
        reverse = False
        
        # Transformation Helper
        def transform_back(pt_proj):
            px, py = pt_proj.x() - cx, pt_proj.y() - cy
            rad = math.radians(-rotation_to_horizontal)
            nx = px * math.cos(rad) - py * math.sin(rad)
            ny = px * math.sin(rad) + py * math.cos(rad)
            fx, fy = nx + cx, ny + cy
            return tr_to_wgs84.transform(QgsPointXY(fx, fy))
            
        def convert_proj(pt_rotated):
            # Rotated -> Projected
            px, py = pt_rotated.x() - cx, pt_rotated.y() - cy
            rad = math.radians(-rotation_to_horizontal)
            nx = px * math.cos(rad) - py * math.sin(rad)
            ny = px * math.sin(rad) + py * math.cos(rad)
            fx, fy = nx + cx, ny + cy
            return QgsPointXY(fx, fy)

        for strip_idx in sorted_indices:
            pts = strips[strip_idx]
            if not pts: continue
            
            # Determine logic start/end based on 'reverse' (Snake)
            if reverse:
                # Flying backwards (Right to Left in X-axis of Rotated space)
                # pts are sorted by X ascending.
                # So start is last point, end is first point.
                logic_start_pt = pts[-1]
                logic_end_pt = pts[0]
                
                # Ordered list for centroids
                ordered_pts = list(reversed(pts))
            else:
                logic_start_pt = pts[0]
                logic_end_pt = pts[-1]
                ordered_pts = pts
            
            # Extend Ends Logic (EXTRA_PHOTOS_END)
            # We are in Rotated Space (X aligned with Flight Path)
            # logic_start_pt -> logic_end_pt direction is purely X (if perfect grid)
            # Actually, calculate vector to be safe
            dx = logic_end_pt.x() - logic_start_pt.x()
            dy = logic_end_pt.y() - logic_start_pt.y()
            len_seg = math.sqrt(dx*dx + dy*dy)
            
            if len_seg > 0:
                ux = dx / len_seg
                uy = dy / len_seg
            else:
                ux, uy = 1, 0 # Default if single point?
                
            extension_dist = extra_photos_end * dist_between_photos
            
            # Extend Start backwards
            start_ext_x = logic_start_pt.x() - (ux * extension_dist)
            start_ext_y = logic_start_pt.y() - (uy * extension_dist)
            final_start_proj = convert_proj(QgsPointXY(start_ext_x, start_ext_y))
            
            # Extend End forwards
            end_ext_x = logic_end_pt.x() + (ux * extension_dist)
            end_ext_y = logic_end_pt.y() + (uy * extension_dist)
            final_end_proj = convert_proj(QgsPointXY(end_ext_x, end_ext_y))
            
            # Convert to WGS84 for Output
            final_start_wgs = tr_to_wgs84.transform(final_start_proj)
            final_end_wgs = tr_to_wgs84.transform(final_end_proj)
            
            # Calculate Heading
            d = QgsDistanceArea()
            d.setSourceCrs(wgs84, context.project().transformContext())
            bearing = d.bearing(final_start_wgs, final_end_wgs) 
            bearing_deg = math.degrees(bearing)
            if bearing_deg < 0: bearing_deg += 360
            
            # Output Litchi Waypoints
            if sink_litchi:
                for pt_wgs in [final_start_wgs, final_end_wgs]:
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPointXY(pt_wgs))
                    f.setAttributes([
                        pt_wgs.y(), pt_wgs.x(), altitude,
                        bearing_deg, 
                        0.0, 0, 0, -90, 1, speed, 0,0,0,0,0,
                        dist_between_photos
                    ])
                    sink_litchi.addFeature(f, QgsFeatureSink.FastInsert)
            
            # Output Lines
            if sink_lines:
                lf = QgsFeature()
                lf.setGeometry(QgsGeometry.fromPolylineXY([final_start_wgs, final_end_wgs]))
                lf.setAttributes([strip_idx])
                sink_lines.addFeature(lf, QgsFeatureSink.FastInsert)
                
            # Output Centroids (Valid photos inside AOI only)
            if sink_cent:
                for i, pt_rot in enumerate(ordered_pts):
                    pt_proj = convert_proj(pt_rot)
                    pt_wgs = tr_to_wgs84.transform(pt_proj)
                    cf = QgsFeature()
                    cf.setGeometry(QgsGeometry.fromPointXY(pt_wgs))
                    cf.setAttributes([strip_idx, i])
                    sink_cent.addFeature(cf, QgsFeatureSink.FastInsert)
            
            reverse = not reverse

        return {
            self.OUTPUT_LITCHI: dest_id_litchi,
            self.OUTPUT_LINES: dest_id_lines,
            self.OUTPUT_CENTROIDS: dest_id_cent
        }
