import os
import inspect
from qgis.core import QgsApplication
from .litchi_provider import LitchiProvider

class LitchiPlugin:
    def __init__(self, iface):
        self.provider = None

    def initGui(self):
        self.initProcessing()

    def initProcessing(self):
        self.provider = LitchiProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)
