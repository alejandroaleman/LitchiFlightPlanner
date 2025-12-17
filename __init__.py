# -*- coding: utf-8 -*-
def classFactory(iface):
    from .plugin import LitchiPlugin
    return LitchiPlugin(iface)
