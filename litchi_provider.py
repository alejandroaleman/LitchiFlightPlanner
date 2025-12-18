from qgis.core import QgsProcessingProvider
from .litchi_generator import LitchiGeneratorAlgorithm
from .litchi_add_camera import LitchiAddCameraAlgorithm

class LitchiProvider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(LitchiGeneratorAlgorithm())
        self.addAlgorithm(LitchiAddCameraAlgorithm())

    def id(self):
        return 'litchiconverter'

    def name(self):
        return 'Litchi Converter'

    def icon(self):
        import os
        from qgis.PyQt.QtGui import QIcon
        return QIcon(os.path.join(os.path.dirname(__file__), 'plugin.png'))
