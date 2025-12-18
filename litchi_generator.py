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
        return self.tr("Generates a photogrammetry flight plan for Litchi. Outputs: Waypoints (CSV ready), Flight Lines, and Photo Centroids.")

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
        
        if buffer_pct > 0:
            size_proxy = math.sqrt(abs(combined_geom.area()))
            buf_dist = size_proxy * buffer_pct
            combined_geom = combined_geom.buffer(buf_dist, 5)
        
        bbox = combined_geom.boundingBox()
        cx, cy = bbox.center().x(), bbox.center().y()
        
        # Rotation logic
        rot_angle = heading_angle - 90
        
        geom_rotated = QgsGeometry(combined_geom)
        geom_rotated.rotate(rot_angle, QgsPointXY(cx, cy))
        r_bbox = geom_rotated.boundingBox()
        
        # Outputs Setup
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
        line_fields.append(QgsField('id', QMetaType.Type.Int))

        centroid_fields = QgsFields()
        centroid_fields.append(QgsField('line_id', QMetaType.Type.Int))
        centroid_fields.append(QgsField('photo_id', QMetaType.Type.Int))

        (sink_litchi, dest_id_litchi) = self.parameterAsSink(parameters, self.OUTPUT_LITCHI, context, litchi_fields, QgsWkbTypes.Point, wgs84)
        (sink_lines, dest_id_lines) = self.parameterAsSink(parameters, self.OUTPUT_LINES, context, line_fields, QgsWkbTypes.LineString, wgs84)
        (sink_cent, dest_id_cent) = self.parameterAsSink(parameters, self.OUTPUT_CENTROIDS, context, centroid_fields, QgsWkbTypes.Point, wgs84)

        current_y = r_bbox.yMinimum() + (dist_between_lines / 2)
        reverse = False
        line_count = 0
        
        while current_y <= r_bbox.yMaximum():
            p_start = QgsPointXY(r_bbox.xMinimum() - 1000, current_y)
            p_end = QgsPointXY(r_bbox.xMaximum() + 1000, current_y)
            line_geom = QgsGeometry.fromPolylineXY([p_start, p_end])
            
            intersection = line_geom.intersection(geom_rotated)
            
            if not intersection.isEmpty():
                 parts = intersection.asGeometryCollection()
                 for part in parts:
                      length = part.length()
                      if length > 0:
                          line_count += 1
                          
                          # 1. Generate Points for this Segment
                          # Start/End
                          pt_start_proj = part.startPoint()
                          pt_end_proj = part.endPoint()
                          
                          # Litchi Waypoints Logic
                          # We need 2 waypoints per line: Start and End.
                          # Order depends on 'reverse' (Snake pattern).
                          
                          if reverse:
                              wp1_proj = pt_end_proj
                              wp2_proj = pt_start_proj
                          else:
                              wp1_proj = pt_start_proj
                              wp2_proj = pt_end_proj
                          
                          # Transform Logic (Helper)
                          def transform_back(pt_proj):
                                # Rotate back around Center
                                px, py = pt_proj.x() - cx, pt_proj.y() - cy
                                rad = math.radians(-rot_angle)
                                nx = px * math.cos(rad) - py * math.sin(rad)
                                ny = px * math.sin(rad) + py * math.cos(rad)
                                fx, fy = nx + cx, ny + cy
                                # To WGS84
                                return tr_to_wgs84.transform(QgsPointXY(fx, fy))
                          
                          wp1_wgs84 = transform_back(wp1_proj)
                          wp2_wgs84 = transform_back(wp2_proj)
                          
                          # Calculate Heading for this pair (WGS84 Azimuth)
                          # We could use the input 'heading_angle' directly?
                          # If snake pattern, even lines go Heading, odd lines go Heading + 180.
                          # Litchi Heading: Direction drone faces. If mapping, usually aligned with flight.
                          
                          # Calculate true bearing between wp1 and wp2 in WGS84
                          d = QgsDistanceArea()
                          d.setSourceCrs(wgs84, context.project().transformContext())
                          bearing = d.bearing(wp1_wgs84, wp2_wgs84) 
                          bearing_deg = math.degrees(bearing)
                          if bearing_deg < 0: bearing_deg += 360
                          
                          # Add Litchi Waypoints
                          for pt_wgs in [wp1_wgs84, wp2_wgs84]:
                              f = QgsFeature()
                              f.setGeometry(QgsGeometry.fromPointXY(pt_wgs))
                              f.setAttributes([
                                  pt_wgs.y(), pt_wgs.x(), altitude,
                                  bearing_deg, # Heading (Coupled)
                                  0.0, 0, 0, -90, 1, speed, 0,0,0,0,0,
                                  dist_between_photos
                              ])
                              if sink_litchi: sink_litchi.addFeature(f, QgsFeatureSink.FastInsert)
                          
                          # 2. Generate Visual Line
                          if sink_lines:
                              line_feat = QgsFeature()
                              line_geom_wgs = QgsGeometry.fromPolylineXY([wp1_wgs84, wp2_wgs84])
                              line_feat.setGeometry(line_geom_wgs)
                              line_feat.setAttributes([line_count])
                              sink_lines.addFeature(line_feat, QgsFeatureSink.FastInsert)
                          
                          # 3. Generate Centroids (QC)
                          if sink_cent:
                              current_dist = 0
                              # Interpolate along the projected line part, then transform
                              # Use correct direction
                              # part is always min_x to max_x? QgsGeometry intersection result usually ordered.
                              # If reverse, we need to handle interpolation distance carefully.
                              
                              # Easier: Construct a vector from wp1 to wp2
                              while current_dist <= length:
                                  # Interpolate on the projected segment?
                                  # Actually, wp1_proj and wp2_proj are the ends.
                                  # Vector maths on projected plane
                                  ratio = current_dist / length
                                  dx = wp2_proj.x() - wp1_proj.x()
                                  dy = wp2_proj.y() - wp1_proj.y()
                                  
                                  interp_x = wp1_proj.x() + dx * ratio
                                  interp_y = wp1_proj.y() + dy * ratio
                                  
                                  cent_wgs = transform_back(QgsPointXY(interp_x, interp_y))
                                  
                                  cf = QgsFeature()
                                  cf.setGeometry(QgsGeometry.fromPointXY(cent_wgs))
                                  cf.setAttributes([line_count, int(current_dist/dist_between_photos)])
                                  sink_cent.addFeature(cf, QgsFeatureSink.FastInsert)
                                  
                                  current_dist += dist_between_photos

            current_y += dist_between_lines
            reverse = not reverse 
            
        return {
            self.OUTPUT_LITCHI: dest_id_litchi,
            self.OUTPUT_LINES: dest_id_lines,
            self.OUTPUT_CENTROIDS: dest_id_cent
        }
