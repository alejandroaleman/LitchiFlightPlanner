from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterString,
                       QgsProcessingParameterNumber)
import os
import json

class LitchiAddCameraAlgorithm(QgsProcessingAlgorithm):
    CAMERA_NAME = 'CAMERA_NAME'
    SENSOR_WIDTH = 'SENSOR_WIDTH'
    SENSOR_HEIGHT = 'SENSOR_HEIGHT'
    FOCAL_LENGTH = 'FOCAL_LENGTH'
    IMAGE_WIDTH = 'IMAGE_WIDTH'
    IMAGE_HEIGHT = 'IMAGE_HEIGHT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return LitchiAddCameraAlgorithm()

    def name(self):
        return 'addcamera'

    def displayName(self):
        return self.tr('Add Camera to Database')

    def group(self):
        return self.tr('Custom Scripts')

    def groupId(self):
        return 'customscripts'

    def shortHelpString(self):
        return self.tr("Adds a new camera definition to the local cameras.json database for use in the Generator.")

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterString(self.CAMERA_NAME, self.tr('Camera Name')))
        self.addParameter(QgsProcessingParameterNumber(self.SENSOR_WIDTH, self.tr('Sensor Width (mm)'), type=QgsProcessingParameterNumber.Double, defaultValue=13.2))
        self.addParameter(QgsProcessingParameterNumber(self.SENSOR_HEIGHT, self.tr('Sensor Height (mm)'), type=QgsProcessingParameterNumber.Double, defaultValue=8.8))
        self.addParameter(QgsProcessingParameterNumber(self.FOCAL_LENGTH, self.tr('Focal Length (mm)'), type=QgsProcessingParameterNumber.Double, defaultValue=8.8))
        self.addParameter(QgsProcessingParameterNumber(self.IMAGE_WIDTH, self.tr('Image Width (px)'), type=QgsProcessingParameterNumber.Integer, defaultValue=5472))
        self.addParameter(QgsProcessingParameterNumber(self.IMAGE_HEIGHT, self.tr('Image Height (px)'), type=QgsProcessingParameterNumber.Integer, defaultValue=3648))

    def processAlgorithm(self, parameters, context, feedback):
        name = self.parameterAsString(parameters, self.CAMERA_NAME, context)
        sw = self.parameterAsDouble(parameters, self.SENSOR_WIDTH, context)
        sh = self.parameterAsDouble(parameters, self.SENSOR_HEIGHT, context)
        fl = self.parameterAsDouble(parameters, self.FOCAL_LENGTH, context)
        iw = self.parameterAsInt(parameters, self.IMAGE_WIDTH, context)
        ih = self.parameterAsInt(parameters, self.IMAGE_HEIGHT, context)

        if not name:
             feedback.reportError("Camera name cannot be empty.")
             return {}

        new_cam = {
            "name": name,
            "sensor_width_mm": sw,
            "sensor_height_mm": sh,
            "focal_length_mm": fl,
            "image_width_px": iw,
            "image_height_px": ih
        }

        # Path to cameras.json (same dir as this script)
        script_dir = os.path.dirname(__file__)
        json_path = os.path.join(script_dir, 'cameras.json')

        data = {"cameras": []}
        if os.path.exists(json_path):
            with open(json_path, 'r') as f:
                try:
                    data = json.load(f)
                except:
                    feedback.pushInfo("Existing cameras.json was corrupt or empty. Creating new.")
        
        # Check duplicate name
        for cam in data.get("cameras", []):
            if cam['name'] == name:
                feedback.reportError(f"A camera with name '{name}' already exists. Please choose a different name.")
                return {}

        data.setdefault("cameras", []).append(new_cam)

        with open(json_path, 'w') as f:
            json.dump(data, f, indent=4)

        feedback.pushInfo(f"Successfully added camera: {name}")

        return {}
