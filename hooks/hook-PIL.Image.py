from PIL import _plugins

# Windows 托盘图标使用 ICO，ICO 编解码依赖 BMP 和 PNG。
hiddenimports = ['PIL.BmpImagePlugin', 'PIL.IcoImagePlugin', 'PIL.PngImagePlugin']
excludedimports = ['PIL.' + plugin for plugin in _plugins if 'PIL.' + plugin not in hiddenimports]
