"""Dessine l'icône d'Atelier SID (un signal carré sur fond sombre) : creer_icone.py sortie.png"""
import sys

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen

app = QGuiApplication(sys.argv[:1])
taille = 1024
image = QImage(taille, taille, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
p = QPainter(image)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
marge = 90
p.setBrush(QColor("#1d2027"))
p.setPen(Qt.PenStyle.NoPen)
p.drawRoundedRect(QRectF(marge, marge, taille - 2 * marge, taille - 2 * marge), 190, 190)
couleurs = ["#4fa3ff", "#ffb347", "#7ee081"]
for i, couleur in enumerate(couleurs):
    y = 330 + i * 150
    chemin = QPainterPath(QPointF(210, y + 50))
    x, haut = 210, False
    for largeur in (90, 60, 120, 60, 90, 80, 100):
        chemin.lineTo(QPointF(x, y + (0 if haut else 50)))
        x += largeur
        chemin.lineTo(QPointF(x, y + (0 if haut else 50)))
        haut = not haut
    p.setPen(QPen(QColor(couleur), 30, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawPath(chemin)
p.end()
image.save(sys.argv[1])
