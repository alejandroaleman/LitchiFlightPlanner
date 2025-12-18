from qgis.PyQt.QtCore import QCoreApplication, QMetaType, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterEnum,
                       QgsProcessingParameterNumber,
                       QgsProcessingOutputVectorLayer,
                       QgsProcessingException,
                       QgsField,
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
    OUTPUT = 'OUTPUT'

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
        return self.tr("Generates a photogrammetry flight plan for Litchi based on an area of interest.")

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

        self.addOutput(QgsProcessingOutputVectorLayer(self.OUTPUT, self.tr('Litchi Mission')))

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
        
        # Calculations (Ground Footprint) in METERS
        # Width (Cross Track) | Height (Along Track) -> Landscape orientation assumed
        fp_width = (sw * altitude) / fl
        fp_height = (sh * altitude) / fl
        
        dist_between_lines = fp_width * (1 - overlap_side)
        dist_between_photos = fp_height * (1 - overlap_fwd) # This is the interval
        
        feedback.pushInfo(f"Camera: {cam['name']}")
        feedback.pushInfo(f"Footprint: {fp_width:.2f}m x {fp_height:.2f}m")
        feedback.pushInfo(f"Line Spacing: {dist_between_lines:.2f}m")
        feedback.pushInfo(f"Photo Interval: {dist_between_photos:.2f}m")

        # Prepare Output
        fields = [
            QgsField('latitude', QMetaType.Type.Double),
            QgsField('longitude', QMetaType.Type.Double),
            QgsField('altitude(m)', QMetaType.Type.Double),
            QgsField('heading(deg)', QMetaType.Type.Double),
            QgsField('curvesize(m)', QMetaType.Type.Double),
            QgsField('rotationdir', QMetaType.Type.Int),
            QgsField('gimbalmode', QMetaType.Type.Int),
            QgsField('gimbalpitchangle', QMetaType.Type.Int),
            QgsField('altitudemode', QMetaType.Type.Int),
            QgsField('speed(m/s)', QMetaType.Type.Double),
            QgsField('poi_latitude', QMetaType.Type.Double),
            QgsField('poi_longitude', QMetaType.Type.Double),
            QgsField('poi_altitude(m)', QMetaType.Type.Double),
            QgsField('poi_altitudemode', QMetaType.Type.Int),
            QgsField('photo_timeinterval', QMetaType.Type.Int),
            QgsField('photo_distinterval', QMetaType.Type.Double)
        ]
        
        # CRS Handling: Internal logic in WGS84 for lat/lon, but for Grid Generation it's better to use Projected.
        # Ideally, we Project AOI to UTM auto-detected or use Source if Projected.
        source_crs = aoi_layer.sourceCrs()
        if source_crs.isGeographic():
             # Crude fallback or warning? Best is to project to a local UTM.
             # For simplicity in V1, we assume user projects or we use QgsDistanceArea for creating points? 
             # Generating grid on LatLon is bad (degrees vs meters).
             # Let's project to Pseudo-Mercator (3857) or finding UTM zone?
             # 3857 is easy but distorts scale at high latitudes.
             # Let's verify input.
             feedback.pushInfo("Input CRS is Geographic. Reprojecting to Web Mercator for grid generation (scale distortion possible).")
             projected_crs = QgsCoordinateReferenceSystem("EPSG:3857")
        else:
             projected_crs = source_crs # Assume input is projected meters
        
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        
        # Transformation Context
        tr_to_proj = QgsCoordinateTransform(source_crs, projected_crs, context.project())
        tr_to_wgs84 = QgsCoordinateTransform(projected_crs, wgs84, context.project())
        
        # Combine all AOI geometries
        combined_geom = QgsGeometry.fromWkt('POLYGON EMPTY')
        for feat in aoi_layer.getFeatures():
            geom = feat.geometry()
            if geom:
                 combined_geom = combined_geom.combine(geom)
        
        # Transform combined geom to projected
        combined_geom.transform(tr_to_proj)
        
        # Apply Buffer
        if buffer_pct > 0:
            # Buffer by diagonal or bounding box size %? 
            # Simple approach: Sqrt(Area) * pct
            size_proxy = math.sqrt(combined_geom.area())
            buf_dist = size_proxy * buffer_pct
            combined_geom = combined_geom.buffer(buf_dist, 5)
        
        bbox = combined_geom.boundingBox()
        
        # Grid Generation Logic (Rotation)
        # Center of bbox
        cx, cy = bbox.center().x(), bbox.center().y()
        
        # We want lines at 'heading_angle'. QGIS rotation is usually CCW? standard math.
        # Flight heading 0 (N) -> Lines Vertical.
        # If we rotate the Geometry by -Angle, we can draw vertical lines, then rotate points back +Angle.
        # Heading (Azimuth) 0 is Y axis. Math 0 is X axis.
        # Azimuth 0 = Math 90. Azimuth 90 = Math 0.
        # Rotation needed to satisfy: We want lines traveling along Azimuth.
        # Actually standard "Lawnmower" generates lines perpendicular to flight path or along it?
        # Usually "Flight Lines" are the path. So lines are ALONG the heading.
        # If Heading is 0 (North), lines should be vertical (scan Y).
        
        # Rotate geom around center by -Heading
        # QgsGeometry.rotate accepts degrees, standard CCW? Azimuth is CW from North.
        # Let's handle math explicitly or use simple geometry rotation.
        # If I rotate geometry so "Flight Line" becomes "X Axis" (Horizontal), I can scan Y.
        # Heading 0 (Vertical). To make it Horizontal (90), I rotate by 90?
        # Let's stick to standard practice: Rotate Points.
        
        # Algorithm:
        # 1. Generate a large Enough Grid of points aligned with Heading.
        # OR
        # 2. Rotate Polygon to axis-aligned (0 deg). Generate Axis-aligned lines. Rotate lines back.
        
        # Heading 0 means travel North. Lines are Vertical.
        # If we rotate Polygon by +Heading (CW) or -Heading?
        # Let's assume Heading is Standard Azimuth (0=N, 90=E).
        # We want lines running N-S.
        # If we rotate Polygon by +90, N becomes E. Lines become Horizontal (E-W).
        # We generate Horizontal lines.
        # Then rotate back by -90.
        
        # Rotation for "Horizontal-izing" the flight path:
        # We want the flight direction (Heading) to map to X-axis (0 deg math).
        # Current Heading (Azimuth H). Math Angle M = 90 - H.
        # We want M -> 0. So rotate by -M = H - 90.
        
        rot_angle = heading_angle - 90
        
        geom_rotated = QgsGeometry(combined_geom)
        geom_rotated.rotate(rot_angle, QgsPointXY(cx, cy))
        
        r_bbox = geom_rotated.boundingBox()
        min_y = r_bbox.yMinimum()
        max_y = r_bbox.yMaximum()
        min_x = r_bbox.xMinimum()
        max_x = r_bbox.xMaximum()
        
        # Generate Lines (Horizontal now, since we aligned Heading to X)
        lines = []
        current_y = min_y + (dist_between_lines / 2) # Start half spacing inside? or edge.
        # Usually centered or edge.
        
        # Direction flip for "Snake" pattern
        reverse = False
        
        waypoints_proj = []
        
        while current_y <= max_y:
            # Create a line from min_x to max_x at current_y
            # We clip this infinite-ish line with the rotated polygon
            # Actually use bbox width to be safe
            p_start = QgsPointXY(min_x - 1000, current_y) # extend a bit
            p_end = QgsPointXY(max_x + 1000, current_y)
            line_geom = QgsGeometry.fromPolylineXY([p_start, p_end])
            
            # Intersect with rotated polygon
            intersection = line_geom.intersection(geom_rotated)
            
            if not intersection.isEmpty():
                 # Intersection might be MultiLineString
                 parts = intersection.asGeometryCollection()
                 for part in parts: # Usually one line if convex, but loop handles complex shapes
                      # Extract segment points
                      # part is a LineString geometry? or abstract.
                      # intersection can be QgsGeometry.
                      # Let's assume it converts to list of points approx.
                      # robust way: interpolate points along the intersection line using dist_between_photos
                      
                      # length
                      length = part.length()
                      if length > 0:
                          # Generate points
                          # Start point? 
                          # Snake logic: If reverse, start from end.
                          
                          # Just uniform points:
                          d = 0
                          seg_points = []
                          while d <= length:
                              pt = part.interpolate(d).asPoint()
                              seg_points.append(pt)
                              d += dist_between_photos
                          
                          if reverse:
                              seg_points.reverse()
                          
                          waypoints_proj.extend(seg_points)
            
            current_y += dist_between_lines
            reverse = not reverse # Toggle direction
            
        # Rotate/Transform back
        final_features = []
        
        (sink, dest_id) = self.parameterAsSink(parameters, self.OUTPUT, context, fields, QgsWkbTypes.Point, wgs84)
        if sink is None:
             raise QgsProcessingException("Output sink failed")

        # Reuse Heading logic from existing algo? Or just constant heading?
        # Litchi Heading: The direction the DRONE faces.
        # Usually defined by "Heading Mode" (Auto vs Custom).
        # We can set specific heading = heading_angle (Fixed).
        
        for idx, pt in enumerate(waypoints_proj):
            # 1. Rotate back
            # We rotated geometry by 'rot_angle' around (cx, cy).
            # We need to rotate Point by -rot_angle around (cx, cy).
            
            # QgsGeometry.fromPointXY(pt).rotate(-rot_angle... but that modifies geom.
            # Math:
            # translate to origin
            px, py = pt.x() - cx, pt.y() - cy
            # rotate
            rad = math.radians(-rot_angle)
            nx = px * math.cos(rad) - py * math.sin(rad)
            ny = px * math.sin(rad) + py * math.cos(rad)
            # translate back
            fx, fy = nx + cx, ny + cy
            
            real_pt = QgsPointXY(fx, fy)
            
            # 2. Transform to WGS84
            wgs_pt = tr_to_wgs84.transform(real_pt)
            
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(wgs_pt))
            feat.setAttributes([
                wgs_pt.y(),         # lat
                wgs_pt.x(),         # lon
                altitude,           # alt
                heading_angle,      # Heading (Fixed to flight path? or 0?)
                                    # Litchi: Heading is orientation of camera. 
                                    # If mapping, usually aligned with path or North.
                                    # Let's use Flight Direction.
                0.0,                # curvesize (0 for straight lines)
                0,                  # rot dir
                0,                  # gimbal mode
                -90,                # gimbal pitch (down)
                1,                  # alt mode
                speed,
                0,0,0,0,0,
                dist_between_photos # interval
            ])
            sink.addFeature(feat, QgsFeatureSink.FastInsert)
            
        return {self.OUTPUT: dest_id}
