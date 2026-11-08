# -*- coding: utf-8 -*-
"""L'éditeur d'instrument : forme d'onde, enveloppe (avec sa courbe), impulsion, vibrato, filtre."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget,
)

from ..modele import FORMES, PREREGLAGES, Instrument

# Durées du SID (ms) pour les valeurs 0 à 15 d'attaque ; déclin et relâche durent trois fois plus.
ATTAQUE_MS = [2, 8, 16, 24, 38, 56, 68, 80, 100, 250, 500, 800, 1000, 3000, 5000, 8000]


def texte_ms(ms: float) -> str:
    return f"{ms / 1000:.1f} s" if ms >= 1000 else f"{ms:.0f} ms"


class CourbeADSR(QWidget):
    """Dessine l'enveloppe : attaque, déclin jusqu'au maintien, note tenue, relâche."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.valeurs = (0, 9, 10, 4)
        self.setMinimumHeight(70)

    def definir(self, attaque, declin, maintien, relache):
        self.valeurs = (attaque, declin, maintien, relache)
        self.update()

    def paintEvent(self, _evenement):
        a, d, s, r = self.valeurs
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor("#16181d"))
        l, h = self.width() - 8, self.height() - 8
        # échelle racine : les durées vont de 2 ms à 24 s
        ta, td, tr = (ATTAQUE_MS[a] ** 0.5, (3 * ATTAQUE_MS[d]) ** 0.5, (3 * ATTAQUE_MS[r]) ** 0.5)
        tenue = 40.0
        echelle = l / (ta + td + tenue + tr)
        niveau = s / 15.0
        x0, y_bas = 4.0, 4.0 + h
        points = [
            (x0, y_bas), (x0 + ta * echelle, 4.0),
            (x0 + (ta + td) * echelle, 4.0 + h * (1 - niveau)),
            (x0 + (ta + td + tenue) * echelle, 4.0 + h * (1 - niveau)),
            (x0 + (ta + td + tenue + tr) * echelle, y_bas),
        ]
        chemin = QPainterPath(QPointF(*points[0]))
        for point in points[1:]:
            chemin.lineTo(QPointF(*point))
        rempli = QPainterPath(chemin)
        rempli.closeSubpath()
        p.fillPath(rempli, QColor(79, 163, 255, 60))
        p.setPen(QPen(QColor("#4fa3ff"), 2))
        p.drawPath(chemin)
        p.setPen(QPen(QColor("#555"), 1, Qt.PenStyle.DashLine))
        x_relache = points[3][0]
        p.drawLine(QPointF(x_relache, 4), QPointF(x_relache, y_bas))
        p.end()


def curseur(minimum, maximum, valeur):
    c = QSlider(Qt.Orientation.Horizontal)
    c.setRange(minimum, maximum)
    c.setValue(valeur)
    return c


class EditeurInstrument(QWidget):
    change = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.instrument = Instrument()
        self._charge = False

        colonne = QVBoxLayout(self)
        colonne.setContentsMargins(0, 0, 0, 0)

        haut = QHBoxLayout()
        haut.addWidget(QLabel("Préréglage"))
        self.prereglage = QComboBox()
        self.prereglage.addItem("Choisir…")
        self.prereglage.addItems(list(PREREGLAGES))
        self.prereglage.activated.connect(self._prereglage)
        haut.addWidget(self.prereglage, 1)
        colonne.addLayout(haut)

        ondes = QGroupBox("Forme d'onde")
        grille = QGridLayout(ondes)
        self.formes = {}
        for i, forme in enumerate(FORMES):
            case = QCheckBox(forme.capitalize())
            case.toggled.connect(self._lire)
            self.formes[forme] = case
            grille.addWidget(case, i // 2, i % 2)
        colonne.addWidget(ondes)

        enveloppe = QGroupBox("Enveloppe")
        formu = QFormLayout(enveloppe)
        self.courbe = CourbeADSR()
        formu.addRow(self.courbe)
        self.adsr = {}
        for cle, nom in (("attaque", "Attaque"), ("declin", "Déclin"), ("maintien", "Maintien"), ("relache", "Relâche")):
            ligne = QHBoxLayout()
            c = curseur(0, 15, 0)
            etiquette = QLabel()
            etiquette.setMinimumWidth(52)
            c.valueChanged.connect(self._lire)
            ligne.addWidget(c, 1)
            ligne.addWidget(etiquette)
            self.adsr[cle] = (c, etiquette)
            formu.addRow(nom, ligne)
        colonne.addWidget(enveloppe)

        impulsion = QGroupBox("Impulsion")
        formu = QFormLayout(impulsion)
        self.largeur = curseur(0, 4095, 2048)
        self.largeur.valueChanged.connect(self._lire)
        self.variation = curseur(0, 120, 0)
        self.variation.valueChanged.connect(self._lire)
        formu.addRow("Largeur", self.largeur)
        formu.addRow("Variation", self.variation)
        colonne.addWidget(impulsion)

        effets = QGroupBox("Effets")
        formu = QFormLayout(effets)
        self.vibrato = curseur(0, 4, 0)
        self.vibrato.valueChanged.connect(self._lire)
        self.vibrato_vitesse = curseur(1, 15, 3)
        self.vibrato_vitesse.setInvertedAppearance(True)
        self.vibrato_vitesse.valueChanged.connect(self._lire)
        self.filtre = QCheckBox("Passe par le filtre")
        self.filtre.toggled.connect(self._lire)
        self.relance = QCheckBox("Notes détachées")
        self.relance.setToolTip("Relâche une trame avant chaque note : chaque note est réattaquée.")
        self.relance.toggled.connect(self._lire)
        self.batterie = QCheckBox("Batterie")
        self.batterie.setToolTip("Do : grosse caisse · ré, mi : caisse claire · fa#, sol#, la# : charleston · fa, sol, la, si : tom")
        self.batterie.toggled.connect(self._lire)
        formu.addRow("Vibrato", self.vibrato)
        formu.addRow("Vitesse", self.vibrato_vitesse)
        formu.addRow(self.filtre)
        formu.addRow(self.relance)
        formu.addRow(self.batterie)
        colonne.addWidget(effets)
        colonne.addStretch()

    def definir(self, instrument: Instrument) -> None:
        self.instrument = instrument
        self._charge = True
        for forme, case in self.formes.items():
            case.setChecked(forme in instrument.formes)
        for cle, (c, _) in self.adsr.items():
            c.setValue(getattr(instrument, cle))
        self.largeur.setValue(instrument.largeur)
        self.variation.setValue(instrument.variation)
        self.vibrato.setValue(instrument.vibrato)
        self.vibrato_vitesse.setValue(instrument.vibrato_vitesse)
        self.filtre.setChecked(instrument.filtre)
        self.relance.setChecked(instrument.relance)
        self.batterie.setChecked(instrument.batterie)
        self._charge = False
        self._maj_affichage()

    def _prereglage(self, index: int) -> None:
        if index <= 0:
            return
        modele = PREREGLAGES[self.prereglage.itemText(index)]()
        for champ in Instrument.__dataclass_fields__:
            setattr(self.instrument, champ, getattr(modele, champ))
        self.prereglage.setCurrentIndex(0)
        self.definir(self.instrument)
        self.change.emit()

    def _lire(self, *_):
        if self._charge:
            return
        i = self.instrument
        i.formes = [f for f, case in self.formes.items() if case.isChecked()] or ["impulsion"]
        for cle, (c, _) in self.adsr.items():
            setattr(i, cle, c.value())
        i.largeur = self.largeur.value()
        i.variation = self.variation.value()
        i.vibrato = self.vibrato.value()
        i.vibrato_vitesse = self.vibrato_vitesse.value()
        i.filtre = self.filtre.isChecked()
        i.relance = self.relance.isChecked()
        i.batterie = self.batterie.isChecked()
        self._maj_affichage()
        self.change.emit()

    def _maj_affichage(self) -> None:
        i = self.instrument
        self.courbe.definir(i.attaque, i.declin, i.maintien, i.relache)
        for cle, (c, etiquette) in self.adsr.items():
            v = c.value()
            if cle == "maintien":
                etiquette.setText(f"{round(v / 15 * 100)} %")
            else:
                etiquette.setText(texte_ms(ATTAQUE_MS[v] * (1 if cle == "attaque" else 3)))
        impulsion = "impulsion" in i.formes
        self.largeur.setEnabled(impulsion)
        self.variation.setEnabled(impulsion)
        self.vibrato_vitesse.setEnabled(i.vibrato > 0)
