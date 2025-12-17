"""
***************************************************************************
*                                                                         *
*   This program is free software; you can redistribute it and/or modify  *
*   it under the terms of the GNU General Public License as published by  *
*   the Free Software Foundation; either version 2 of the License, or     *
*   (at your option) any later version.                                   *
*                                                                         *
***************************************************************************
"""

from qgis.PyQt.QtCore import QCoreApplication, QMetaType
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingOutputVectorLayer,
                       QgsProcessingParameterNumber,
                       QgsProcessingException,
                       QgsField,
                       QgsFeature,
                       QgsFeatureSink,
                       QgsVectorLayer,
                       QgsProject,
                       QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform)
import math

class LitchiFormatterAlgorithm(QgsProcessingAlgorithm):
    """
    This algorithm convert the flight planner plugin ouput format to a Litchi mission format.
    """

    INPUT = 'INPUT'
    SPEED = 'SPEED'
    PHOTO_DISTINTERVAL = 'PHOTO_DISTINTERVAL'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LitchiFormatterAlgorithm()

    def name(self):
        return 'litchiformat'

    def displayName(self):
        return self.tr('Flight planner to Litchi mission')

    def group(self):
        return self.tr('Custom Scripts')

    def groupId(self):
        return 'customscripts'

    def shortHelpString(self):
        return self.tr("Convert flight planner atributes table to Litchi missions format")

    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT,
                self.tr('Input vector layer'),
                types=[QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterNumber(
                self.SPEED,
                self.tr('Speed (m/s)'),
                defaultValue=8.3333,
                type=QgsProcessingParameterNumber.Double
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                self.PHOTO_DISTINTERVAL,
                self.tr('Photo Distance Interval'),
                defaultValue=40,
                type=QgsProcessingParameterNumber.Double
            )
        )
        
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                self.OUTPUT,
                self.tr('Output Layer')
            )
        )

    def calculate_bearing(self, lat1, lon1, lat2, lon2):
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        lon_diff_rad = math.radians(lon2 - lon1)

        y = math.sin(lon_diff_rad) * math.cos(lat2_rad)
        x = (math.cos(lat1_rad) * math.sin(lat2_rad) -
             math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(lon_diff_rad))

        bearing = math.degrees(math.atan2(y, x))
        return (bearing + 360) % 360

    def processAlgorithm(self, parameters, context, feedback):
        input_layer = self.parameterAsSource(parameters, self.INPUT, context)
        if input_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        source_crs = input_layer.sourceCrs()
        target_crs = QgsCoordinateReferenceSystem("EPSG:4326")
        transform = QgsCoordinateTransform(source_crs, target_crs, context.project())

        speed = self.parameterAsDouble(parameters, self.SPEED, context)
        photo_distinterval = self.parameterAsDouble(parameters, self.PHOTO_DISTINTERVAL, context)

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

        # Use WGS84 for the output layer
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            input_layer.wkbType(),
            target_crs 
        )
        
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        features = list(input_layer.getFeatures())
        
        # We only need altitude from attributes now.
        altitude_idx = input_layer.fields().indexOf('Alt. ASL [m]')

        for i in range(len(features)):
            feature = features[i]
            
            # Helper to get transformed point (lat, lon) for any index
            def get_pt(idx):
                feat = features[idx]
                geom = feat.geometry()
                if not geom:
                    return 0, 0
                pt = geom.asPoint()
                tr_pt = transform.transform(pt)
                return tr_pt.y(), tr_pt.x()

            current_lat, current_lon = get_pt(i)

            # Pairing logic for Heading
            # If current index is even (0, 2, 4...), pairing with next (i+1)
            # If current index is odd (1, 3, 5...), pairing with prev (i-1)
            # The direction is always EVEN -> ODD.
            
            lat1, lon1, lat2, lon2 = 0, 0, 0, 0
            
            if i % 2 == 0:
                # Even: Start of line. Heading is towards next point.
                if i + 1 < len(features):
                    lat1, lon1 = current_lat, current_lon
                    lat2, lon2 = get_pt(i+1)
                else: 
                     # Orphan point at end? Maintain previous behavior or 0.
                     lat1, lon1 = current_lat, current_lon
                     lat2, lon2 = current_lat, current_lon
            else:
                # Odd: End of line. Heading is SAME as previous point (from prev to this).
                # Logic in original script:
                # feature2 = features[i - 1]
                # lat1, lon1 = feature2...
                # lat2, lon2 = feature...
                if i - 1 >= 0:
                    lat1, lon1 = get_pt(i-1)
                    lat2, lon2 = current_lat, current_lon
                else:
                    # Should not happen for odd index
                    lat1, lon1 = current_lat, current_lon
                    lat2, lon2 = current_lat, current_lon

            bearing_value = self.calculate_bearing(lat1, lon1, lat2, lon2)

            new_feature = QgsFeature()
            # Reuse geometry? Need to ensure it is transformed if we want output to be 4326.
            # sink is initialized with target_crs (4326).
            # So we must write 4326 geometry.
            
            orig_geom = feature.geometry()
            if orig_geom:
                 orig_pt = orig_geom.asPoint()
                 tr_pt = transform.transform(orig_pt)
                 new_geom = type(orig_geom).fromPointXY(tr_pt) # Reconstruct geometry
                 new_feature.setGeometry(new_geom)
            
            # Use 'Alt. ASL [m]' if present, else 0 or maybe z from geometry?
            # Sticking to attribute as per legacy behavior.
            alt_val = feature[altitude_idx] if altitude_idx != -1 else 0

            new_feature.setAttributes([
                current_lat,        # latitude
                current_lon,        # longitude
                alt_val,            # altitude(m)
                bearing_value,      # heading(deg)
                0.02,               # curvesize(m)
                0,                  # rotationdir
                0,                  # gimbalmode
                -90,                # gimbalpitchangle
                1,                  # altitudemode
                speed,              # speed(m/s)
                0,                  # poi_latitude
                0,                  # poi_longitude
                0,                  # poi_altitude(m)
                0,                  # poi_altitudemode
                0,                  # photo_timeinterval
                photo_distinterval  # photo_distinterval
            ])
            sink.addFeature(new_feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}
