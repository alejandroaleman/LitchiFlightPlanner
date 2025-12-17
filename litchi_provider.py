from qgis.core import QgsProcessingProvider
from .litchi_algorithm import LitchiFormatterAlgorithm

class LitchiProvider(QgsProcessingProvider):
    def loadAlgorithms(self, *args, **kwargs):
        self.addAlgorithm(LitchiFormatterAlgorithm())

    def id(self):
        return 'litchiconverter'

    def name(self):
        return 'Litchi Converter'

    def icon(self):
        return QgsProcessingProvider.icon(self)
