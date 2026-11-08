# -*- coding: utf-8 -*-
"""Le piano roll : les notes d'une voix sur une grille temps × hauteur, à la souris."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QAbstractScrollArea

from ..modele import Morceau, Note

NOMS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NOIRES = {1, 3, 6, 8, 10}
HAUTE, BASSE = 96, 24  # C7 à C1
CLAVIER = 52
REGLE = 22
LIGNE = 13
BORD = 6  # pixels près du bord droit d'une note : on la redimensionne

COULEURS_VOIX = [QColor(c) for c in ("#4fa3ff", "#ffb347", "#7ee081", "#c792ea", "#ff6f91", "#4dd0e1",
                                      "#e6d36b", "#a1887f", "#90a4ae")]


def nom_note(hauteur: int) -> str:
    return f"{NOMS[hauteur % 12]}{hauteur // 12 - 1}"


class PianoRoll(QAbstractScrollArea):
    modifie = Signal()  # après une modification à la souris (pour annuler)
    avant_modif = Signal()  # juste avant : la fenêtre mémorise l'état
    note_ecoutee = Signal(int)  # clic sur le clavier ou nouvelle note
    note_lachee = Signal()
    position_choisie = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.morceau: Morceau | None = None
        self.voix = 0
        self.grille = 0.25
        self.px_temps = 64.0
        self.position: float | None = None
        self.curseur = 0.0
        self.selection: Note | None = None
        self._action = None  # ("deplacer", note, dt, dh) ou ("etirer", note)
        self.duree_nouvelle = 0.25
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumSize(400, 300)
        self.verticalScrollBar().setSingleStep(LIGNE)
        self.horizontalScrollBar().setSingleStep(16)

    # --- Géométrie ---

    def x_de(self, temps: float) -> float:
        return CLAVIER + temps * self.px_temps - self.horizontalScrollBar().value()

    def temps_de(self, x: float) -> float:
        return (x - CLAVIER + self.horizontalScrollBar().value()) / self.px_temps

    def y_de(self, hauteur: int) -> float:
        return REGLE + (HAUTE - hauteur) * LIGNE - self.verticalScrollBar().value()

    def hauteur_de(self, y: float) -> int:
        return HAUTE - int((y - REGLE + self.verticalScrollBar().value()) // LIGNE)

    def caler(self, temps: float) -> float:
        return max(0.0, round(temps / self.grille) * self.grille)

    def maj_barres(self) -> None:
        if not self.morceau:
            return
        largeur = self.morceau.duree * self.px_temps + 40
        self.horizontalScrollBar().setRange(0, max(0, int(largeur - (self.viewport().width() - CLAVIER))))
        self.horizontalScrollBar().setPageStep(self.viewport().width())
        hauteur = (HAUTE - BASSE + 1) * LIGNE
        self.verticalScrollBar().setRange(0, max(0, hauteur - (self.viewport().height() - REGLE)))
        self.verticalScrollBar().setPageStep(self.viewport().height())

    def resizeEvent(self, evenement):
        super().resizeEvent(evenement)
        self.maj_barres()

    def centrer_sur(self, hauteur: int) -> None:
        self.maj_barres()
        self.verticalScrollBar().setValue(int((HAUTE - hauteur) * LIGNE - self.viewport().height() / 2))

    def definir(self, morceau: Morceau, voix: int) -> None:
        self.morceau = morceau
        self.voix = voix
        if self.selection not in morceau.pistes[voix].notes:
            self.selection = None
        self.maj_barres()
        self.viewport().update()

    # --- Dessin ---

    def paintEvent(self, _evenement):
        if not self.morceau:
            return
        p = QPainter(self.viewport())
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        largeur, hauteur = self.viewport().width(), self.viewport().height()
        p.fillRect(0, 0, largeur, hauteur, QColor("#1b1d23"))

        # lignes de hauteur
        for h in range(BASSE, HAUTE + 1):
            y = self.y_de(h)
            if y + LIGNE < REGLE or y > hauteur:
                continue
            couleur = QColor("#16181d") if h % 12 in NOIRES else QColor("#20232a")
            p.fillRect(QRectF(CLAVIER, y, largeur, LIGNE), couleur)
            if h % 12 == 0:
                p.setPen(QColor("#33373f"))
                p.drawLine(QPointF(CLAVIER, y + LIGNE), QPointF(largeur, y + LIGNE))

        # grille du temps
        fin = self.morceau.duree
        tpm = self.morceau.temps_par_mesure
        t = math.floor(self.temps_de(CLAVIER) / self.grille) * self.grille
        while t <= min(fin, self.temps_de(largeur)):
            x = self.x_de(t)
            if abs(t / tpm - round(t / tpm)) < 1e-6:
                p.setPen(QPen(QColor("#5a606c"), 1))
            elif abs(t - round(t)) < 1e-6:
                p.setPen(QPen(QColor("#3a3f48"), 1))
            else:
                p.setPen(QPen(QColor("#2a2e35"), 1))
            p.drawLine(QPointF(x, REGLE), QPointF(x, hauteur))
            t += self.grille
        x_fin = self.x_de(fin)
        if x_fin < largeur:
            p.fillRect(QRectF(x_fin, REGLE, largeur - x_fin, hauteur), QColor(0, 0, 0, 110))

        # notes des autres voix, en transparence, puis celles de la voix éditée
        for voix, piste in enumerate(self.morceau.pistes):
            if voix == self.voix:
                continue
            couleur = QColor(COULEURS_VOIX[voix])
            couleur.setAlpha(55)
            for n in piste.notes:
                p.fillRect(self._rect(n), couleur)
        couleur = COULEURS_VOIX[self.voix]
        p.setFont(QFont(p.font().family(), 8))
        for n in self.morceau.pistes[self.voix].notes:
            for autre in n.autres:  # accord joué en arpège : notes en pointillé
                r = QRectF(self.x_de(n.debut), self.y_de(autre) + 2, max(3.0, n.duree * self.px_temps), LIGNE - 4)
                p.setPen(QPen(couleur, 1, Qt.PenStyle.DashLine))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRect(r)
            r = self._rect(n)
            p.fillRect(r, couleur.lighter(140) if n is self.selection else couleur)
            p.setPen(QColor("#0d0e11"))
            p.drawRect(r)
            if r.width() > 28:
                texte = nom_note(n.hauteur) + (" + accord" if n.autres and r.width() > 80 else "")
                p.drawText(r.adjusted(3, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, texte)

        # tête de lecture et curseur de départ
        for temps, couleur in ((self.curseur, QColor("#e0e0e0")), (self.position, QColor("#ff5a5a"))):
            if temps is not None:
                x = self.x_de(temps)
                if x >= CLAVIER:
                    p.setPen(QPen(couleur, 2 if couleur.red() == 255 else 1))
                    p.drawLine(QPointF(x, 0), QPointF(x, hauteur))

        # clavier
        p.fillRect(0, REGLE, CLAVIER, hauteur, QColor("#111216"))
        for h in range(BASSE, HAUTE + 1):
            y = self.y_de(h)
            if y + LIGNE < REGLE or y > hauteur:
                continue
            noire = h % 12 in NOIRES
            p.fillRect(QRectF(0, y, CLAVIER - 1, LIGNE - 1), QColor("#2b2d33") if noire else QColor("#d8d8d8"))
            if h % 12 == 0:
                p.setPen(QColor("#202020"))
                p.drawText(QRectF(2, y, CLAVIER - 4, LIGNE), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, nom_note(h))

        # règle des mesures
        p.fillRect(0, 0, largeur, REGLE, QColor("#2a2d34"))
        p.setPen(QColor("#c8c8c8"))
        mesure = 0
        while mesure * tpm <= fin:
            x = self.x_de(mesure * tpm)
            if x >= CLAVIER - 1:
                p.drawLine(QPointF(x, REGLE - 8), QPointF(x, REGLE))
                p.drawText(QPointF(x + 3, REGLE - 7), str(mesure + 1))
            mesure += 1
        p.fillRect(0, 0, CLAVIER, REGLE, QColor("#2a2d34"))
        p.end()

    def _rect(self, n: Note) -> QRectF:
        return QRectF(self.x_de(n.debut), self.y_de(n.hauteur) + 1, max(3.0, n.duree * self.px_temps), LIGNE - 2)

    # --- Souris ---

    def _note_sous(self, pos) -> Note | None:
        for n in reversed(self.morceau.pistes[self.voix].notes):
            if self._rect(n).adjusted(0, -1, 0, 1).contains(QPointF(pos)):
                return n
        return None

    def mousePressEvent(self, evenement):
        if not self.morceau:
            return
        pos = evenement.position()
        if pos.y() < REGLE:
            if pos.x() > CLAVIER:
                temps = self.caler(self.temps_de(pos.x()))
                self.curseur = min(temps, self.morceau.duree)
                self.position_choisie.emit(self.curseur)
                self.viewport().update()
            return
        if pos.x() < CLAVIER:
            self.note_ecoutee.emit(self.hauteur_de(pos.y()))
            self._action = ("clavier",)
            return
        note = self._note_sous(pos)
        if evenement.button() == Qt.MouseButton.RightButton:
            if note is not None:
                self.avant_modif.emit()
                self.morceau.pistes[self.voix].notes.remove(note)
                self.selection = None
                self.modifie.emit()
                self.viewport().update()
            return
        self.avant_modif.emit()
        if note is None:
            hauteur = self.hauteur_de(pos.y())
            debut = math.floor(self.temps_de(pos.x()) / self.grille) * self.grille
            if not (BASSE <= hauteur <= HAUTE) or debut >= self.morceau.duree:
                return
            note = Note(debut, self.duree_nouvelle, hauteur)
            self.morceau.pistes[self.voix].notes.append(note)
            self._action = ("etirer", note, debut)
            self.note_ecoutee.emit(hauteur)
        elif self._rect(note).right() - pos.x() <= BORD:
            self._action = ("etirer", note, note.debut)
        else:
            self._action = ("deplacer", note, self.temps_de(pos.x()) - note.debut, note.hauteur)
            self.note_ecoutee.emit(note.hauteur)
        self.selection = note
        self.viewport().update()

    def mouseMoveEvent(self, evenement):
        pos = evenement.position()
        if not self.morceau:
            return
        if self._action is None:
            note = self._note_sous(pos) if pos.y() > REGLE and pos.x() > CLAVIER else None
            pres_du_bord = note is not None and self._rect(note).right() - pos.x() <= BORD
            self.viewport().setCursor(Qt.CursorShape.SizeHorCursor if pres_du_bord else Qt.CursorShape.ArrowCursor)
            return
        libre = evenement.modifiers() & Qt.KeyboardModifier.AltModifier
        if self._action[0] == "etirer":
            _, note, debut = self._action
            fin = self.temps_de(pos.x())
            fin = fin if libre else math.ceil(fin / self.grille - 1e-6) * self.grille
            note.duree = max(self.grille if not libre else 0.02, fin - debut)
            note.duree = min(note.duree, self.morceau.duree - note.debut)
            self.duree_nouvelle = note.duree
        elif self._action[0] == "deplacer":
            _, note, ecart, _ = self._action
            debut = self.temps_de(pos.x()) - ecart
            note.debut = min(max(0.0, debut if libre else self.caler(debut)), self.morceau.duree - self.grille)
            hauteur = min(HAUTE, max(BASSE, self.hauteur_de(pos.y())))
            if hauteur != note.hauteur:
                note.autres = [a + hauteur - note.hauteur for a in note.autres]  # l'accord suit
                note.hauteur = hauteur
                self.note_ecoutee.emit(hauteur)
        self.viewport().update()

    def mouseReleaseEvent(self, _evenement):
        if self._action is not None:
            fini = self._action[0] != "clavier"
            self._action = None
            self.note_lachee.emit()
            if fini:
                self.modifie.emit()

    def keyPressEvent(self, evenement):
        if evenement.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace) and self.selection is not None:
            self.avant_modif.emit()
            notes = self.morceau.pistes[self.voix].notes
            if self.selection in notes:
                notes.remove(self.selection)
            self.selection = None
            self.modifie.emit()
            self.viewport().update()
            return
        evenement.ignore()

    def keyReleaseEvent(self, evenement):
        evenement.ignore()

    def wheelEvent(self, evenement):
        modifs = evenement.modifiers()
        delta = evenement.angleDelta()
        if modifs & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            ancien = self.temps_de(evenement.position().x())
            self.px_temps = min(400.0, max(12.0, self.px_temps * (1.15 if delta.y() > 0 else 1 / 1.15)))
            self.maj_barres()
            self.horizontalScrollBar().setValue(int(ancien * self.px_temps - (evenement.position().x() - CLAVIER)))
            self.viewport().update()
            return
        if modifs & Qt.KeyboardModifier.ShiftModifier or delta.x():
            pas = delta.x() or delta.y()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - pas)
        else:
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
        self.viewport().update()

    def scrollContentsBy(self, _dx, _dy):
        self.viewport().update()

    def suivre(self, position: float | None) -> None:
        """Déplace la tête de lecture, et fait défiler si elle sort de l'écran."""
        self.position = position
        if position is not None:
            x = self.x_de(position)
            if x > self.viewport().width() - 40 or x < CLAVIER:
                self.horizontalScrollBar().setValue(int(position * self.px_temps - 40))
        self.viewport().update()
