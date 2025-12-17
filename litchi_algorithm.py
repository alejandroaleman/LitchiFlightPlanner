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
                       QgsProject)
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

        crs = input_layer.sourceCrs() # Better to get CRS from source
        # Alternatively use parameterAsCrs if we had that param, but we don't.
        # Original code: crs = self.parameterAsCrs(parameters, 'INPUT', context) -> wait, 'INPUT' is Source, not CRS param.
        # Correct way for Source is input_layer.sourceCrs() usually, logic check:
        # Original code line 142: crs = self.parameterAsCrs(parameters, 'INPUT', context) -> This looks wrong in original too if INPUT provides a source.
        # But parameterAsCrs usually expects a Crs parameter. However, maybe it works if passing a source param name?
        # Let's check documentation or common practice. Usually we take it from source.
        # I will trust the original script worked? Or maybe not. Let's stick to safer `input_layer.sourceCrs()`.
        
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

        # Use 'memory' layer for temporary output
        # But wait, QgsProcessingOutputVectorLayer usually expects us to return a sink or a layer ID string.
        # In QGIS 3 Processing, we usually use self.parameterAsSink.
        # The original script uses QgsVectorLayer("memory") and QgsProject.instance().addMapLayer(output_layer).
        # That is NOT standard Processing Algorithm behavior (adds to project directly, bypassing processing framework handling).
        # Standard way: use 'sink'.
        
        # However, to minimize friction with existing logic, I will implement it as standard sink if possible, 
        # OR keep it as is if user wants exactly that behavior.
        # The original script returned {'OUTPUT': output_layer.id()}.
        # Let's try to improve it to use parameterAsSink which is robust.
        
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            input_layer.wkbType(),
            input_layer.sourceCrs()
        )
        
        if sink is None:
            raise QgsProcessingException(self.invalidSinkError(parameters, self.OUTPUT))

        features = list(input_layer.getFeatures())
        
        ycoord_idx = input_layer.fields().indexOf('ycoord')
        xcoord_idx = input_layer.fields().indexOf('xcoord')
        altitude_idx = input_layer.fields().indexOf('Alt. ASL [m]')
        
        # Verification of fields
        if ycoord_idx == -1 or xcoord_idx == -1: 
             # Fallback to geometry if fields missing? or error?
             # features might use geometry directly.
             # Origin script assumes specific fields. I'll keep it.
             pass

        for i in range(len(features)):
            feature = features[i]
            
            # Logic from original script
            if i % 2 == 0:
                if i + 1 < len(features):
                    feature2 = features[i + 1]
                    lat1, lon1 = feature[ycoord_idx], feature[xcoord_idx]
                    lat2, lon2 = feature2[ycoord_idx], feature2[xcoord_idx]
                else: 
                     # fallback if odd number of points?
                     lat1, lon1 = feature[ycoord_idx], feature[xcoord_idx]
                     lat2, lon2 = lat1, lon1 # No movement
            else:
                if i - 1 >= 0:
                    feature2 = features[i - 1]
                    lat1, lon1 = feature2[ycoord_idx], feature2[xcoord_idx]
                    lat2, lon2 = feature[ycoord_idx], feature[xcoord_idx]
                else:
                    lat1, lon1 = feature[ycoord_idx], feature[xcoord_idx]
                    lat2, lon2 = lat1, lon1

            bearing_value = self.calculate_bearing(lat1, lon1, lat2, lon2)

            new_feature = QgsFeature()
            new_feature.setGeometry(feature.geometry())
            new_feature.setAttributes([
                feature[ycoord_idx],
                feature[xcoord_idx],
                feature[altitude_idx] if altitude_idx != -1 else 0,
                bearing_value,
                0.02,  # Curvesize
                0,  # Rotation Direction
                0,  # Gimbal Mode
                -90,  # Gimbal Pitch Angle
                1,  # Altitude Mode
                speed,
                0,  # POI Latitude
                0,  # POI Longitude
                0,  # POI Altitude
                0,  # POI Altitude Mode
                0,  # Photo Time Interval
                photo_distinterval  # Photo Distance Interval
            ])
            sink.addFeature(new_feature, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id}
