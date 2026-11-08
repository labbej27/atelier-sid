# -*- coding: utf-8 -*-
"""La fenêtre d'Atelier SID : transport, pistes, piano roll, instrument, export."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QKeySequence, QPalette
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QFrame,
    QGroupBox, QHBoxLayout, QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QRadioButton, QScrollArea,
    QSlider, QSpinBox, QSplitter, QToolBar, QVBoxLayout, QWidget,
)

from .. import export, midi, moteur
from ..modele import FILTRES, Morceau, Note
from .instrument import EditeurInstrument
from .pianoroll import COULEURS_VOIX, PianoRoll

CLAVIER_ORDI = "Clavier de l'ordinateur"
GRILLES = {"1/4": 1.0, "1/8": 0.5, "1/16": 0.25, "1/32": 0.125, "Triolet 1/8": 1 / 3}
VERSION = "0.1"


class Relais(QObject):
    """Ramène les notes MIDI, reçues dans un autre fil, sur le fil de la fenêtre."""

    note = Signal(int, bool, float)


class LignePiste(QFrame):
    choisie = Signal(int)
    muette = Signal(int, bool)

    def __init__(self, voix: int, groupe: QButtonGroup):
        super().__init__()
        self.voix = voix
        self.setFrameShape(QFrame.Shape.StyledPanel)
        ligne = QHBoxLayout(self)
        ligne.setContentsMargins(6, 4, 6, 4)
        pastille = QLabel()
        pastille.setFixedSize(10, 28)
        pastille.setStyleSheet(f"background: {COULEURS_VOIX[voix].name()}; border-radius: 3px;")
        ligne.addWidget(pastille)
        self.bouton = QRadioButton(f"Voix {voix + 1}")
        groupe.addButton(self.bouton, voix)
        self.bouton.toggled.connect(lambda actif: actif and self.choisie.emit(self.voix))
        ligne.addWidget(self.bouton)
        self.instrument = QLabel()
        self.instrument.setStyleSheet("color: gray;")
        ligne.addWidget(self.instrument, 1)
        self.case_muette = QCheckBox("Muette")
        self.case_muette.toggled.connect(lambda m: self.muette.emit(self.voix, m))
        ligne.addWidget(self.case_muette)

    def definir(self, piste) -> None:
        self.instrument.setText(piste.instrument.nom + (" · batterie" if piste.instrument.batterie else ""))
        self.case_muette.blockSignals(True)
        self.case_muette.setChecked(piste.muette)
        self.case_muette.blockSignals(False)


class Fenetre(QMainWindow):
    def __init__(self, audio: bool = True):
        super().__init__()
        self.setWindowTitle("Atelier SID")
        self.resize(1280, 780)
        self.morceau = Morceau()
        self.chemin: Path | None = None
        self.voix = 0
        self.historique: list[Morceau] = []
        self.refaire: list[Morceau] = []
        self.enregistrement = None  # {"debut", "notes", "tenue"}
        self.notes_tenues: set[int] = set()
        self.reglages = QSettings("AtelierSID", "AtelierSID")

        self.moteur = moteur.Moteur(str(self.reglages.value("puce", "6581")))
        self.entree = midi.EntreeMidi()
        self.relais = Relais()
        self.relais.note.connect(self._note_recue)

        self._construire()
        self._charger_morceau(self.morceau)
        self.roll.centrer_sur(52)

        self.erreur_audio = None
        if audio:
            try:
                self.moteur.demarrer_audio()
            except Exception as erreur:  # pas de carte son, pilote absent…
                self.erreur_audio = str(erreur)
                self.statusBar().showMessage(f"Pas de sortie audio : {erreur}")
        self.minuterie = QTimer(self)
        self.minuterie.timeout.connect(self._suivre_lecture)
        self.minuterie.start(30)
        self._remplir_entrees()

    # --- Construction ---

    def _construire(self) -> None:
        barre = QToolBar("Transport")
        barre.setMovable(False)
        self.addToolBar(barre)
        self.bouton_lecture = QPushButton("▶  Lecture")
        self.bouton_lecture.setToolTip("Espace")
        self.bouton_lecture.clicked.connect(self.basculer_lecture)
        self.bouton_enreg = QPushButton("●  Enregistrer")
        self.bouton_enreg.setToolTip("R : une mesure de décompte, puis tu joues sur la voix choisie")
        self.bouton_enreg.clicked.connect(self.basculer_enregistrement)
        self.bouton_enreg.setStyleSheet("QPushButton:checked { background: #c0392b; color: white; }")
        self.bouton_enreg.setCheckable(True)
        barre.addWidget(self.bouton_lecture)
        barre.addWidget(self.bouton_enreg)
        barre.addSeparator()
        self.case_boucle = QCheckBox("Boucle")
        self.case_metronome = QCheckBox("Métronome")
        self.case_metronome.setChecked(True)
        self.case_metronome.toggled.connect(lambda v: setattr(self.moteur, "metronome", v))
        self.moteur.metronome = True
        barre.addWidget(self.case_boucle)
        barre.addWidget(self.case_metronome)
        barre.addSeparator()
        barre.addWidget(QLabel(" Tempo "))
        self.tempo = QDoubleSpinBox()
        self.tempo.setRange(30, 300)
        self.tempo.setDecimals(1)
        self.tempo.setSuffix(" bpm")
        self.tempo.valueChanged.connect(self._tempo_change)
        barre.addWidget(self.tempo)
        barre.addWidget(QLabel(" Mesures "))
        self.mesures = QSpinBox()
        self.mesures.setRange(1, 999)
        self.mesures.valueChanged.connect(self._mesures_change)
        barre.addWidget(self.mesures)
        barre.addWidget(QLabel(" Grille "))
        self.grille = QComboBox()
        self.grille.addItems(list(GRILLES))
        self.grille.setCurrentText("1/16")
        self.grille.currentTextChanged.connect(self._grille_change)
        barre.addWidget(self.grille)
        self.case_calage = QCheckBox("Caler l'enregistrement")
        self.case_calage.setChecked(True)
        self.case_calage.setToolTip("Les notes jouées sont posées sur la grille")
        barre.addWidget(self.case_calage)
        self.addToolBarBreak()
        barre = QToolBar("Entrée")
        barre.setMovable(False)
        self.addToolBar(barre)
        barre.addWidget(QLabel(" Entrée "))
        self.choix_entree = QComboBox()
        self.choix_entree.setMinimumWidth(180)
        self.choix_entree.activated.connect(self._entree_choisie)
        barre.addWidget(self.choix_entree)
        actualiser = QPushButton("↻")
        actualiser.setToolTip("Chercher les claviers MIDI branchés")
        actualiser.clicked.connect(self._remplir_entrees)
        barre.addWidget(actualiser)
        barre.addWidget(QLabel(" Octave "))
        self.octave = QSpinBox()
        self.octave.setRange(0, 7)
        self.octave.setValue(3)
        self.octave.setToolTip("Octave du clavier de l'ordinateur")
        barre.addWidget(self.octave)

        # gauche : pistes + piano roll
        centre = QWidget()
        colonne = QVBoxLayout(centre)
        colonne.setContentsMargins(6, 6, 6, 6)
        self.groupe_voix = QButtonGroup(self)
        self.lignes = []
        for voix in range(3):
            ligne = LignePiste(voix, self.groupe_voix)
            ligne.choisie.connect(self.choisir_voix)
            ligne.muette.connect(self._muette)
            self.lignes.append(ligne)
            colonne.addWidget(ligne)
        self.roll = PianoRoll()
        self.roll.avant_modif.connect(self.memoriser)
        self.roll.modifie.connect(self._notes_modifiees)
        self.roll.note_ecoutee.connect(self._ecouter_note)
        self.roll.note_lachee.connect(self._lacher_note)
        self.roll.position_choisie.connect(lambda _t: self._afficher_position())
        colonne.addWidget(self.roll, 1)
        aide = QLabel("Clic : ajouter · glisser : déplacer · bord droit : allonger · clic droit : supprimer · "
                      "Alt : hors grille · Ctrl + molette : zoom · règle : point de départ")
        aide.setStyleSheet("color: gray;")
        colonne.addWidget(aide)

        # droite : instrument, filtre, morceau
        droite = QWidget()
        cote = QVBoxLayout(droite)
        self.titre_instrument = QLabel()
        self.titre_instrument.setStyleSheet("font-weight: bold; font-size: 14px;")
        cote.addWidget(self.titre_instrument)
        self.editeur = EditeurInstrument()
        self.editeur.change.connect(self._instrument_change)
        cote.addWidget(self.editeur)

        filtre = QGroupBox("Filtre (commun aux voix qui y passent)")
        formu = QFormLayout(filtre)
        self.filtre_type = QComboBox()
        self.filtre_type.addItems(list(FILTRES))
        self.filtre_type.currentTextChanged.connect(self._filtre_change)
        self.filtre_coupure = QSlider(Qt.Orientation.Horizontal)
        self.filtre_coupure.setRange(0, 2047)
        self.filtre_coupure.valueChanged.connect(self._filtre_change)
        self.filtre_resonance = QSlider(Qt.Orientation.Horizontal)
        self.filtre_resonance.setRange(0, 15)
        self.filtre_resonance.valueChanged.connect(self._filtre_change)
        formu.addRow("Type", self.filtre_type)
        formu.addRow("Coupure", self.filtre_coupure)
        formu.addRow("Résonance", self.filtre_resonance)
        cote.addWidget(filtre)

        infos = QGroupBox("Morceau")
        formu = QFormLayout(infos)
        self.champ_titre = QLineEdit()
        self.champ_titre.textEdited.connect(lambda t: setattr(self.morceau, "titre", t))
        self.champ_auteur = QLineEdit()
        self.champ_auteur.textEdited.connect(lambda t: setattr(self.morceau, "auteur", t))
        self.puce = QComboBox()
        self.puce.addItems(["6581", "8580"])
        self.puce.setCurrentText(str(self.reglages.value("puce", "6581")))
        self.puce.setToolTip("Le modèle de SID émulé. Le filtre sonne très différemment de l'un à l'autre.")
        self.puce.currentTextChanged.connect(self._puce_change)
        formu.addRow("Titre", self.champ_titre)
        formu.addRow("Auteur", self.champ_auteur)
        formu.addRow("Puce SID", self.puce)
        cote.addWidget(infos)

        defilement = QScrollArea()
        defilement.setWidget(droite)
        defilement.setWidgetResizable(True)
        defilement.setMinimumWidth(330)
        separation = QSplitter()
        separation.addWidget(centre)
        separation.addWidget(defilement)
        separation.setStretchFactor(0, 1)
        separation.setSizes([920, 360])
        self.setCentralWidget(separation)

        self.etiquette_position = QLabel()
        self.statusBar().addPermanentWidget(self.etiquette_position)

        menu = self.menuBar().addMenu("Fichier")
        for nom, raccourci, action in (
            ("Nouveau", QKeySequence.StandardKey.New, self.nouveau),
            ("Ouvrir…", QKeySequence.StandardKey.Open, self.ouvrir),
            ("Enregistrer", QKeySequence.StandardKey.Save, self.enregistrer),
            ("Enregistrer sous…", QKeySequence.StandardKey.SaveAs, self.enregistrer_sous),
            (None, None, None),
            ("Importer un fichier MIDI…", None, self.importer_midi),
            ("Exporter en .sid…", "Ctrl+E", lambda: self.exporter("sid")),
            ("Exporter en .prg (C64)…", None, lambda: self.exporter("prg")),
            ("Exporter en .wav…", None, lambda: self.exporter("wav")),
        ):
            if nom is None:
                menu.addSeparator()
                continue
            a = QAction(nom, self)
            if raccourci:
                a.setShortcut(QKeySequence(raccourci))
            a.triggered.connect(action)
            menu.addAction(a)
        edition = self.menuBar().addMenu("Édition")
        self.action_annuler = QAction("Annuler", self)
        self.action_annuler.setShortcut(QKeySequence.StandardKey.Undo)
        self.action_annuler.triggered.connect(self.annuler)
        self.action_refaire = QAction("Rétablir", self)
        self.action_refaire.setShortcut(QKeySequence.StandardKey.Redo)
        self.action_refaire.triggered.connect(self.retablir)
        effacer = QAction("Effacer la voix", self)
        effacer.triggered.connect(self.effacer_voix)
        edition.addActions([self.action_annuler, self.action_refaire, effacer])
        aide = self.menuBar().addMenu("Aide")
        a = QAction("Raccourcis et clavier", self)
        a.triggered.connect(self.aide)
        aide.addAction(a)

    # --- Morceau ---

    def _charger_morceau(self, morceau: Morceau) -> None:
        self.arreter()
        self.morceau = morceau
        for widget, valeur in ((self.tempo, morceau.tempo), (self.mesures, morceau.mesures)):
            widget.blockSignals(True)
            widget.setValue(valeur)
            widget.blockSignals(False)
        self.champ_titre.setText(morceau.titre)
        self.champ_auteur.setText(morceau.auteur)
        for widget in (self.filtre_type, self.filtre_coupure, self.filtre_resonance):
            widget.blockSignals(True)
        self.filtre_type.setCurrentText(morceau.filtre_type)
        self.filtre_coupure.setValue(morceau.filtre_coupure)
        self.filtre_resonance.setValue(morceau.filtre_resonance)
        for widget in (self.filtre_type, self.filtre_coupure, self.filtre_resonance):
            widget.blockSignals(False)
        for ligne, piste in zip(self.lignes, morceau.pistes):
            ligne.definir(piste)
        self.roll.curseur = 0.0
        self.roll.grille = GRILLES[self.grille.currentText()]
        self.choisir_voix(self.voix)
        self.lignes[self.voix].bouton.setChecked(True)
        for voix in range(3):
            self.moteur.appliquer_instrument(morceau, voix)
        self._maj_titre()

    def choisir_voix(self, voix: int) -> None:
        self.voix = voix
        bouton = self.lignes[voix].bouton
        if not bouton.isChecked():
            bouton.blockSignals(True)
            bouton.setChecked(True)
            bouton.blockSignals(False)
        piste = self.morceau.pistes[voix]
        self.titre_instrument.setText(f"Voix {voix + 1} : {piste.instrument.nom}")
        self.editeur.definir(piste.instrument)
        self.roll.definir(self.morceau, voix)

    def memoriser(self) -> None:
        self.historique.append(self.morceau.copie())
        del self.historique[:-100]
        self.refaire.clear()

    def _notes_modifiees(self) -> None:
        self._maj_titre(modifie=True)

    def annuler(self) -> None:
        if self.historique:
            self.refaire.append(self.morceau.copie())
            self._restaurer(self.historique.pop())

    def retablir(self) -> None:
        if self.refaire:
            self.historique.append(self.morceau.copie())
            self._restaurer(self.refaire.pop())

    def _restaurer(self, morceau: Morceau) -> None:
        curseur = self.roll.curseur
        self._charger_morceau(morceau)
        self.roll.curseur = curseur
        self._maj_titre(modifie=True)

    def effacer_voix(self) -> None:
        self.memoriser()
        self.morceau.pistes[self.voix].notes.clear()
        self.roll.definir(self.morceau, self.voix)
        self._maj_titre(modifie=True)

    def _instrument_change(self) -> None:
        self.lignes[self.voix].definir(self.morceau.pistes[self.voix])
        self.titre_instrument.setText(f"Voix {self.voix + 1} : {self.morceau.pistes[self.voix].instrument.nom}")
        self.moteur.appliquer_instrument(self.morceau, self.voix)
        self._maj_titre(modifie=True)

    def _filtre_change(self, *_):
        self.morceau.filtre_type = self.filtre_type.currentText()
        self.morceau.filtre_coupure = self.filtre_coupure.value()
        self.morceau.filtre_resonance = self.filtre_resonance.value()
        self.moteur.appliquer_filtre(self.morceau)
        self._maj_titre(modifie=True)

    def _tempo_change(self, valeur: float) -> None:
        self.morceau.tempo = valeur
        self._maj_titre(modifie=True)

    def _mesures_change(self, valeur: int) -> None:
        self.morceau.mesures = valeur
        self.roll.definir(self.morceau, self.voix)
        self._maj_titre(modifie=True)

    def _grille_change(self, texte: str) -> None:
        self.roll.grille = GRILLES[texte]
        self.roll.duree_nouvelle = GRILLES[texte]
        self.roll.viewport().update()

    def _muette(self, voix: int, muette: bool) -> None:
        self.morceau.pistes[voix].muette = muette

    def _puce_change(self, puce: str) -> None:
        self.reglages.setValue("puce", puce)
        lecture = self.moteur.lecture
        self.arreter()
        audio = self.moteur.flux_audio is not None
        self.moteur.fermer()
        self.moteur = moteur.Moteur(puce)
        self.moteur.metronome = self.case_metronome.isChecked()
        for voix in range(3):
            self.moteur.appliquer_instrument(self.morceau, voix)
        if audio:
            self.moteur.demarrer_audio()
        if lecture:
            self.basculer_lecture()

    def _maj_titre(self, modifie: bool = False) -> None:
        nom = self.chemin.name if self.chemin else "Sans titre"
        self.setWindowModified(modifie)
        self.setWindowTitle(f"{nom}[*] — Atelier SID")

    # --- Transport ---

    def basculer_lecture(self) -> None:
        if self.moteur.lecture or self.enregistrement:
            self.arreter()
            return
        try:
            self.moteur.jouer(self.morceau, self.roll.curseur, boucle=self.case_boucle.isChecked())
        except export.ErreurExport as erreur:
            QMessageBox.warning(self, "Atelier SID", str(erreur))
            return
        self.bouton_lecture.setText("■  Stop")

    def basculer_enregistrement(self) -> None:
        if self.enregistrement:
            self.arreter()
            return
        self.arreter()
        if self.morceau.pistes[self.voix].muette:
            self.lignes[self.voix].case_muette.setChecked(False)
        self.enregistrement = {"debut": self.roll.curseur, "notes": [], "tenue": None}
        try:
            self.moteur.jouer(self.morceau, self.roll.curseur, ignorer=self.voix, decompte=1)
        except export.ErreurExport as erreur:
            self.enregistrement = None
            QMessageBox.warning(self, "Atelier SID", str(erreur))
            return
        self.bouton_enreg.setChecked(True)
        self.bouton_lecture.setText("■  Stop")
        self.statusBar().showMessage(f"Enregistrement sur la voix {self.voix + 1} : une mesure de décompte…")

    def arreter(self) -> None:
        position = self.moteur.position_entendue()
        self.moteur.arreter()
        self.bouton_lecture.setText("▶  Lecture")
        self.bouton_enreg.setChecked(False)
        self.roll.suivre(None)
        if self.enregistrement:
            self._finir_enregistrement(position)
        self.statusBar().clearMessage()

    def _finir_enregistrement(self, position: float) -> None:
        enreg, self.enregistrement = self.enregistrement, None
        if enreg["tenue"] is not None:
            hauteur, debut = enreg["tenue"]
            enreg["notes"].append(Note(debut, max(0.0, position - debut), hauteur))
        notes = [n for n in enreg["notes"] if n.duree > 0.01]
        if not notes:
            return
        grille = self.roll.grille
        if self.case_calage.isChecked():
            for n in notes:
                fin = n.debut + n.duree
                n.debut = max(0.0, round(n.debut / grille) * grille)
                n.duree = max(grille, round((fin - n.debut) / grille) * grille)
        debut = min(n.debut for n in notes)
        fin = max(n.debut + n.duree for n in notes)
        self.memoriser()
        piste = self.morceau.pistes[self.voix]
        piste.notes = [n for n in piste.notes if n.debut + n.duree <= debut or n.debut >= fin] + notes
        self.roll.definir(self.morceau, self.voix)
        self._maj_titre(modifie=True)
        self.statusBar().showMessage(f"{len(notes)} notes enregistrées sur la voix {self.voix + 1}.", 4000)

    def _suivre_lecture(self) -> None:
        if self.moteur.lecture:
            position = self.moteur.position_entendue()
            self.roll.suivre(max(position, self.roll.curseur) if position >= self.roll.curseur else None)
            if self.enregistrement and position >= self.enregistrement["debut"]:
                self.statusBar().showMessage(f"● Enregistrement sur la voix {self.voix + 1}")
            self._afficher_position(position)
        elif self.bouton_lecture.text().startswith("■"):
            self.arreter()

    def _afficher_position(self, position: float | None = None) -> None:
        t = self.roll.curseur if position is None else max(0.0, position)
        tpm = self.morceau.temps_par_mesure
        self.etiquette_position.setText(f"Mesure {int(t // tpm) + 1} · temps {int(t % tpm) + 1}  ")

    # --- Notes jouées (synthé, clavier de l'ordinateur, piano roll) ---

    def _remplir_entrees(self) -> None:
        actuelle = self.entree.nom or self.reglages.value("entree", CLAVIER_ORDI)
        self.choix_entree.clear()
        self.choix_entree.addItem(CLAVIER_ORDI)
        ports = self.entree.ports()
        self.choix_entree.addItems(ports)
        if actuelle in ports:
            self.choix_entree.setCurrentText(actuelle)
            self._entree_choisie()
        elif ports and not self.entree.nom:
            self.choix_entree.setCurrentIndex(1)
            self._entree_choisie()

    def _entree_choisie(self, *_):
        nom = self.choix_entree.currentText()
        self.entree.fermer()
        if nom and nom != CLAVIER_ORDI:
            try:
                self.entree.ouvrir(nom, lambda h, appui: self.relais.note.emit(h, appui, self.moteur.position_entendue()))
                self.statusBar().showMessage(f"Clavier MIDI : {nom}", 3000)
            except Exception as erreur:
                QMessageBox.warning(self, "Atelier SID", f"Impossible d'ouvrir « {nom} » : {erreur}")
                self.choix_entree.setCurrentIndex(0)
                return
        self.reglages.setValue("entree", nom)

    def _note_recue(self, hauteur: int, appuyee: bool, position: float) -> None:
        instrument = self.morceau.pistes[self.voix].instrument
        enreg = self.enregistrement
        if appuyee:
            self.notes_tenues.add(hauteur)
            self.moteur.note_directe(self.voix, hauteur, instrument)
            if enreg and position >= enreg["debut"]:
                if enreg["tenue"] is not None:  # une voix ne joue qu'une note : la précédente s'arrête
                    h, d = enreg["tenue"]
                    enreg["notes"].append(Note(d, position - d, h))
                enreg["tenue"] = (hauteur, position)
        else:
            self.notes_tenues.discard(hauteur)
            if not self.notes_tenues:
                self.moteur.relacher_directe(self.voix, instrument)
            elif enreg is None or enreg["tenue"] is None or enreg["tenue"][0] == hauteur:
                # on revient sur une note encore tenue, comme un synthé monophonique
                autre = max(self.notes_tenues)
                self.moteur.note_directe(self.voix, autre, instrument)
            if enreg and enreg["tenue"] is not None and enreg["tenue"][0] == hauteur:
                h, d = enreg["tenue"]
                enreg["notes"].append(Note(d, position - d, h))
                enreg["tenue"] = None

    def _ecouter_note(self, hauteur: int) -> None:
        self.moteur.note_directe(self.voix, hauteur, self.morceau.pistes[self.voix].instrument)

    def _lacher_note(self) -> None:
        self.moteur.relacher_directe(self.voix, self.morceau.pistes[self.voix].instrument)

    def keyPressEvent(self, evenement):
        if evenement.isAutoRepeat():
            return
        if evenement.key() == Qt.Key.Key_Space and not evenement.modifiers():
            self.basculer_lecture()
            return
        demi_ton = midi.demi_ton_de_la_touche(evenement)
        if demi_ton is not None and not (evenement.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)):
            self._note_recue(12 * (self.octave.value() + 1) + demi_ton, True, self.moteur.position_entendue())
            return
        if evenement.key() == Qt.Key.Key_R and not evenement.modifiers():
            self.basculer_enregistrement()
            return
        super().keyPressEvent(evenement)

    def keyReleaseEvent(self, evenement):
        if evenement.isAutoRepeat():
            return
        demi_ton = midi.demi_ton_de_la_touche(evenement)
        if demi_ton is not None:
            self._note_recue(12 * (self.octave.value() + 1) + demi_ton, False, self.moteur.position_entendue())
            return
        super().keyReleaseEvent(evenement)

    # --- Fichiers ---

    def _dossier(self) -> str:
        return str(self.reglages.value("dossier", str(Path.home())))

    def nouveau(self) -> None:
        if self._confirmer_abandon():
            self.chemin = None
            self.historique.clear()
            self._charger_morceau(Morceau())

    def _confirmer_abandon(self) -> bool:
        if not self.isWindowModified():
            return True
        reponse = QMessageBox.question(self, "Atelier SID", "Le morceau a été modifié. Continuer sans l'enregistrer ?")
        return reponse == QMessageBox.StandardButton.Yes

    def ouvrir(self) -> None:
        if not self._confirmer_abandon():
            return
        chemin, _ = QFileDialog.getOpenFileName(self, "Ouvrir un morceau", self._dossier(), "Atelier SID (*.asid)")
        if chemin:
            try:
                morceau = Morceau.ouvrir(Path(chemin))
            except Exception as erreur:
                QMessageBox.warning(self, "Atelier SID", f"Impossible d'ouvrir ce fichier : {erreur}")
                return
            self.chemin = Path(chemin)
            self.reglages.setValue("dossier", str(self.chemin.parent))
            self.historique.clear()
            self._charger_morceau(morceau)

    def enregistrer(self) -> bool:
        if self.chemin is None:
            return self.enregistrer_sous()
        self.morceau.enregistrer(self.chemin)
        self._maj_titre()
        self.statusBar().showMessage(f"Enregistré : {self.chemin}", 3000)
        return True

    def enregistrer_sous(self) -> bool:
        chemin, _ = QFileDialog.getSaveFileName(
            self, "Enregistrer le morceau", str(Path(self._dossier()) / f"{self.morceau.titre}.asid"), "Atelier SID (*.asid)")
        if not chemin:
            return False
        self.chemin = Path(chemin).with_suffix(".asid")
        self.reglages.setValue("dossier", str(self.chemin.parent))
        return self.enregistrer()

    def importer_midi(self) -> None:
        if not self._confirmer_abandon():
            return
        chemin, _ = QFileDialog.getOpenFileName(self, "Importer un fichier MIDI", self._dossier(), "MIDI (*.mid *.midi)")
        if not chemin:
            return
        try:
            morceau = midi.importer(Path(chemin))
        except Exception as erreur:
            QMessageBox.warning(self, "Atelier SID", f"Import impossible : {erreur}")
            return
        self.chemin = None
        self.historique.clear()
        self._charger_morceau(morceau)
        self._maj_titre(modifie=True)

    def exporter(self, format_: str) -> None:
        filtres = {"sid": "Musique SID (*.sid)", "prg": "Programme C64 (*.prg)", "wav": "Son WAV (*.wav)"}
        nom = f"{self.morceau.titre or 'morceau'}.{format_}"
        chemin, _ = QFileDialog.getSaveFileName(self, "Exporter", str(Path(self._dossier()) / nom), filtres[format_])
        if not chemin:
            return
        chemin = Path(chemin).with_suffix(f".{format_}")
        try:
            if format_ == "sid":
                export.ecrire_sid(self.morceau, chemin)
            elif format_ == "prg":
                export.ecrire_prg(self.morceau, chemin)
            else:
                QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
                try:
                    moteur.rendre_wav(self.morceau, chemin, self.puce.currentText())
                finally:
                    QApplication.restoreOverrideCursor()
        except export.ErreurExport as erreur:
            QMessageBox.warning(self, "Atelier SID", str(erreur))
            return
        self.statusBar().showMessage(f"Exporté : {chemin}", 5000)

    def aide(self) -> None:
        QMessageBox.information(self, "Atelier SID", (
            f"Atelier SID {VERSION}\n\n"
            "Espace : lecture / stop\nR : enregistrer sur la voix choisie (une mesure de décompte)\n\n"
            "Clavier de l'ordinateur, comme un piano :\n"
            "  rangée du bas (W/Z S X D C V G B H N J ,) : une octave\n"
            "  rangée du haut (A/Q 2 Z/W 3 E R 5 T 6 Y 7 U I) : l'octave au-dessus\n\n"
            "Piano roll : clic pour ajouter, glisser pour déplacer, bord droit pour allonger,\n"
            "clic droit pour supprimer, Alt pour sortir de la grille, Ctrl + molette pour zoomer.\n"
            "Clic dans la règle : point de départ de la lecture et de l'enregistrement.\n\n"
            "Batterie : do = grosse caisse, ré/mi = caisse claire, fa#/sol#/la# = charleston, fa/sol/la/si = tom."
        ))

    def closeEvent(self, evenement):
        if not self._confirmer_abandon():
            evenement.ignore()
            return
        self.arreter()
        self.entree.fermer()
        self.moteur.fermer()
        super().closeEvent(evenement)


def appliquer_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    for role, couleur in (
        (QPalette.ColorRole.Window, "#25272d"), (QPalette.ColorRole.WindowText, "#e6e6e6"),
        (QPalette.ColorRole.Base, "#1b1d22"), (QPalette.ColorRole.AlternateBase, "#25272d"),
        (QPalette.ColorRole.Text, "#e6e6e6"), (QPalette.ColorRole.Button, "#30333a"),
        (QPalette.ColorRole.ButtonText, "#e6e6e6"), (QPalette.ColorRole.Highlight, "#4fa3ff"),
        (QPalette.ColorRole.HighlightedText, "#101010"), (QPalette.ColorRole.ToolTipBase, "#30333a"),
        (QPalette.ColorRole.ToolTipText, "#e6e6e6"),
    ):
        palette.setColor(role, QColor(couleur))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#777"))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#777"))
    app.setPalette(palette)


def auto_test(dossier: Path) -> int:
    """Vérification de l'application compilée : son, MIDI, fenêtre et exports."""
    from ..modele import Note

    fenetre = Fenetre()
    m = fenetre.morceau
    m.titre = "Auto-test"
    m.pistes[0].notes = [Note(i * 0.5, 0.5, 36 + (i % 4) * 3) for i in range(16)]
    m.pistes[1].notes = [Note(0, 2, 60), Note(2, 2, 64)]
    m.pistes[2].notes = [Note(i, 0.25, 36) for i in range(8)]
    dossier.mkdir(parents=True, exist_ok=True)
    export.ecrire_sid(m, dossier / "test.sid")
    export.ecrire_prg(m, dossier / "test.prg")
    moteur.rendre_wav(m, dossier / "test.wav")
    fenetre.basculer_lecture()
    import time
    QApplication.processEvents()
    time.sleep(1.0)
    QApplication.processEvents()
    ok = fenetre.moteur.position_entendue() > 0.5 if fenetre.moteur.flux_audio is not None else True
    print("audio:", fenetre.moteur.flux_audio is not None, "| ports MIDI:", midi.EntreeMidi.ports(),
          "| lecture:", ok, flush=True)
    fenetre.arreter()
    fenetre.setWindowModified(False)
    fenetre.close()
    tailles = [(dossier / f"test.{e}").stat().st_size for e in ("sid", "prg", "wav")]
    return 0 if ok and all(tailles) else 1


def main() -> int:
    app = QApplication(sys.argv)
    if len(sys.argv) == 3 and sys.argv[1] == "--auto-test":
        return auto_test(Path(sys.argv[2]))
    app.setApplicationName("Atelier SID")
    appliquer_theme(app)

    def panne(type_, erreur, trace):
        traceback.print_exception(type_, erreur, trace)
        QMessageBox.critical(None, "Atelier SID", f"Erreur inattendue : {erreur}")

    sys.excepthook = panne
    fenetre = Fenetre()
    fenetre.show()
    if fenetre.erreur_audio:
        QMessageBox.warning(fenetre, "Atelier SID", f"Aucune sortie audio : {fenetre.erreur_audio}\n"
                            "Tu peux composer et exporter, mais pas écouter.")
    return app.exec()
