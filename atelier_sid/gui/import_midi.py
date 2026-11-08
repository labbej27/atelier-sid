# -*- coding: utf-8 -*-
"""Fenêtre d'import MIDI : chaque partie du fichier, la voix qu'elle prendra et comment la jouer."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QHBoxLayout, QHeaderView, QLabel, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from .. import midi
from ..modele import MAX_SID, Morceau


class ImportMidi(QDialog):
    def __init__(self, chemin: Path, nb_sid: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Importer « {chemin.name} »")
        self.resize(940, 440)
        self.chemin = chemin
        self.parties, self.tempo = midi.analyser(chemin)

        colonne = QVBoxLayout(self)
        haut = QHBoxLayout()
        haut.addWidget(QLabel(f"{len(self.parties)} parties · {self.tempo:g} bpm"))
        haut.addStretch()
        haut.addWidget(QLabel("Puces"))
        self.nb_sid = QComboBox()
        self.nb_sid.addItems([f"{n} SID · {3 * n} voix" for n in range(1, MAX_SID + 1)])
        self.nb_sid.setCurrentIndex(nb_sid - 1)
        self.nb_sid.currentIndexChanged.connect(self._proposer)
        haut.addWidget(self.nb_sid)
        colonne.addLayout(haut)

        aide = QLabel("Chaque voix du SID joue une note à la fois. Les accords peuvent être joués en "
                      "arpège rapide, comme dans les musiques de jeux C64. Plusieurs parties peuvent "
                      "partager une voix (les percussions avec la batterie, par exemple).")
        aide.setWordWrap(True)
        aide.setStyleSheet("color: gray;")
        colonne.addWidget(aide)

        self.table = QTableWidget(len(self.parties), 6)
        self.table.setHorizontalHeaderLabels(["Canal", "Instrument", "Notes", "Ensemble", "Voix", "Jeu"])
        self.table.verticalHeader().hide()
        entete = self.table.horizontalHeader()
        entete.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for colonne_t in (0, 2, 3):
            entete.setSectionResizeMode(colonne_t, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setColumnWidth(4, 150)
        self.table.setColumnWidth(5, 190)
        self.voix: list[QComboBox] = []
        self.modes: list[QComboBox] = []
        for rang, partie in enumerate(self.parties):
            for colonne_t, texte in enumerate((str(partie.canal + 1), partie.nom, str(len(partie.notes)),
                                               f"{partie.polyphonie} note(s)")):
                case = QTableWidgetItem(texte)
                case.setFlags(Qt.ItemFlag.ItemIsEnabled)
                self.table.setItem(rang, colonne_t, case)
            voix = QComboBox()
            self.voix.append(voix)
            self.table.setCellWidget(rang, 4, voix)
            mode = QComboBox()
            for cle in midi.MODES:
                mode.addItem(midi.NOMS_MODES[cle], cle)
            mode.setEnabled(not partie.percussion)
            self.modes.append(mode)
            self.table.setCellWidget(rang, 5, mode)
        colonne.addWidget(self.table, 1)

        boutons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        boutons.button(QDialogButtonBox.StandardButton.Ok).setText("Importer")
        boutons.button(QDialogButtonBox.StandardButton.Cancel).setText("Annuler")
        boutons.accepted.connect(self.accept)
        boutons.rejected.connect(self.reject)
        colonne.addWidget(boutons)
        self._proposer()

    def _proposer(self, *_):
        nb = self.nb_sid.currentIndex() + 1
        choix = midi.repartir(self.parties, nb)
        for partie, voix, mode in zip(self.parties, self.voix, self.modes):
            voix.clear()
            voix.addItem("Ignorée", None)
            for v in range(3 * nb):
                voix.addItem(f"Voix {v + 1} (SID {v // 3 + 1})", v)
            v, m = choix.get(partie.canal, (None, "haute"))
            voix.setCurrentIndex(0 if v is None else v + 1)
            mode.setCurrentIndex(midi.MODES.index(m))

    def morceau(self) -> Morceau:
        choix = {p.canal: (v.currentData(), m.currentData()) for p, v, m in zip(self.parties, self.voix, self.modes)}
        return midi.construire(self.parties, choix, self.nb_sid.currentIndex() + 1, self.tempo, self.chemin.stem)
