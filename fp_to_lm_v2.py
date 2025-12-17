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
                       QgsFeatureSink,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterFileDestination,
                       # QgsProcessingParameterFeatureSink,
                       # QgsProcessingParameterVectorDestination,
                       QgsProcessingParameterNumber,
                       QgsProcessingParameterBoolean,
                       QgsProcessingOutputVectorLayer,
                       QgsField,
                       QgsFeature,
                       QgsVectorLayer,
                       QgsProject)
import math

class LitchiFormatterAlgorithm(QgsProcessingAlgorithm):
    """
    This algorithm convert the flight planner plugin ouput format to a Litchi mission format.
    """

    INPUT = 'Input_Layer'
    SPEED = 'speed(m/s)'
    PHOTO_DISTINTERVAL = 'photo_distinterval'
    OUTPUT = 'Output_Layer'

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
                'INPUT',
                self.tr('Input vector layer'),
                types=[QgsProcessing.TypeVectorAnyGeometry]
            )
        )
        
        # self.addParameter(
        #     QgsProcessingParameterFeatureSource(
        #         self.INPUT,
        #         self.tr('Input Layer'),
        #         [QgsProcessing.SourceType.TypeVectorAnyGeometry]
        #     )
        # )
        
        self.addParameter(
            QgsProcessingParameterNumber(
                'SPEED',
                self.tr('Speed (m/s)'),
                defaultValue=8.3333,
                type=QgsProcessingParameterNumber.Double
            )
        )

        self.addParameter(
            QgsProcessingParameterNumber(
                'PHOTO_DISTINTERVAL',
                self.tr('Photo Distance Interval'),
                defaultValue=40,
                type=QgsProcessingParameterNumber.Double
            )
        )
        
        self.addOutput(
            QgsProcessingOutputVectorLayer(
                'OUTPUT',
                self.tr('Output Layer')
            )
        )
        
        # self.addParameter(
        #     QgsProcessingParameterVectorDestination(
        #         'OUTPUT',
        #         self.tr('Output Layer'),
        #         optional=True#,
        #         # createByDefault = False
        #     )
        # )
        
        # self.addParameter(
        #     QgsProcessingParameterFeatureSink(
        #         self.OUTPUT,
        #         self.tr('Output Layer')
        #     )
        # )

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
        # Obtenemos el ID de la capa de entrada directamente de los parámetros
        input_layer = self.parameterAsSource(parameters, 'INPUT', context)
        if input_layer is None:
            raise QgsProcessingException(self.invalidSourceError(parameters, 'INPUT'))

        # # Obtener la capa original desde el ID de la fuente de características
        # input_layer = QgsProject.instance().mapLayer(input_layer_id)  # Cambia este método

        # if input_layer is None:
        #     raise QgsProcessingException(self.invalidSourceError(parameters, self.INPUT))

        crs = self.parameterAsCrs(parameters, 'INPUT', context)
        speed = self.parameterAsDouble(parameters, 'SPEED', context)
        photo_distinterval = self.parameterAsDouble(parameters, 'PHOTO_DISTINTERVAL', context)

        # Creamos el layer de salida
        output_fields = [
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

        output_layer = QgsVectorLayer(f"Point?crs={crs.authid()}", "Output", "memory")
        output_layer_data = output_layer.dataProvider()

        output_layer_data.addAttributes(output_fields)
        output_layer.updateFields()

        features = list(input_layer.getFeatures())
        new_features = []

        ycoord_idx = input_layer.fields().indexOf('ycoord')
        xcoord_idx = input_layer.fields().indexOf('xcoord')
        altitude_idx = input_layer.fields().indexOf('Alt. ASL [m]')

        for i in range(len(features)):
            feature = features[i]
            
            if i % 2 == 0:
                feature2 = features[i + 1]
                lat1, lon1 = feature[ycoord_idx], feature[xcoord_idx]
                lat2, lon2 = feature2[ycoord_idx], feature2[xcoord_idx]
            else:
                feature2 = features[i - 1]
                lat1, lon1 = feature2[ycoord_idx], feature2[xcoord_idx]
                lat2, lon2 = feature[ycoord_idx], feature[xcoord_idx]

            # if i < len(features) - 1:
            #     feature2 = features[i + 1]
            # else:
            #     feature2 = features[0]

            # lat1, lon1 = feature[ycoord_idx], feature[xcoord_idx]
            # lat2, lon2 = feature2[ycoord_idx], feature2[xcoord_idx]

            bearing_value = self.calculate_bearing(lat1, lon1, lat2, lon2)

            new_feature = QgsFeature()
            new_feature.setGeometry(feature.geometry())
            new_feature.setAttributes([
                feature[ycoord_idx],
                feature[xcoord_idx],
                feature[altitude_idx],
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
            new_features.append(new_feature)

        # Agregar nuevas características al layer de salida
        output_layer_data.addFeatures(new_features)
        output_layer.updateFields()

        # Mensaje de depuración
        # feedback.pushInfo(f"Generated {len(new_features)} new features.")

        if output_layer.featureCount() > 0:
            QgsProject.instance().addMapLayer(output_layer)
            feedback.pushInfo("Output layer has been successfully created and added to the project.")
        else:
            feedback.pushWarning("No features were added to the output layer.")
        
        return {'OUTPUT': output_layer.id()}
