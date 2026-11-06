"""El cargador de la base (``bd cargar``, DEV31 F3; sección 5.7 del acta de F0).

Cada carpeta o archivo publicado se convierte en una **unidad**: sus archivos con su huella y las
filas que salen de ellos. Una unidad entra entera o no entra (una transacción). Lo que ya está con
el mismo contenido se salta; una clave que llega con otro contenido no se escribe y queda en
``control.conflictos``. Las filas se copian de los archivos: el cargador no calcula métricas (B10).
"""
