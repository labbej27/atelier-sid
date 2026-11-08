"""Interface : piano roll, enregistrement simulé, instrument, fichiers."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, QPointF, QSettings, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

from atelier_sid.gui import fenetre as f
from atelier_sid.gui.pianoroll import CLAVIER, REGLE
from atelier_sid.modele import Morceau, Note


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def fen(app, tmp_path, monkeypatch):
    monkeypatch.setattr(f, "QSettings", lambda *a: QSettings(str(tmp_path / "r.ini"), QSettings.Format.IniFormat))
    w = f.Fenetre(audio=False)
    w.resize(1200, 760)
    w.show()
    app.processEvents()
    yield w
    w.setWindowModified(False)
    w.close()


def cliquer(roll, x, y, bouton=Qt.MouseButton.LeftButton, fin=None):
    def ev(type_, pos):
        return QMouseEvent(type_, QPointF(*pos), QPointF(*pos), bouton, bouton, Qt.KeyboardModifier.NoModifier)
    roll.mousePressEvent(ev(QMouseEvent.Type.MouseButtonPress, (x, y)))
    if fin:
        roll.mouseMoveEvent(ev(QMouseEvent.Type.MouseMove, fin))
    roll.mouseReleaseEvent(ev(QMouseEvent.Type.MouseButtonRelease, fin or (x, y)))


def test_ajouter_allonger_deplacer_supprimer(fen):
    roll = fen.roll
    roll.horizontalScrollBar().setValue(0)
    y = roll.y_de(60) + 5
    cliquer(roll, CLAVIER + 2, y, fin=(CLAVIER + roll.px_temps * 1.0 - 1, y))  # une noire
    notes = fen.morceau.pistes[0].notes
    assert [(n.debut, n.duree, n.hauteur) for n in notes] == [(0.0, 1.0, 60)]
    cliquer(roll, CLAVIER + 10, y, fin=(CLAVIER + 10 + roll.px_temps * 2, roll.y_de(62) + 5))
    assert (notes[0].debut, notes[0].hauteur) == (2.0, 62)
    fen.annuler()
    assert [(n.debut, n.hauteur) for n in fen.morceau.pistes[0].notes] == [(0.0, 60)]
    fen.retablir()
    n = fen.morceau.pistes[0].notes[0]
    cliquer(fen.roll, fen.roll.x_de(n.debut) + 5, fen.roll.y_de(n.hauteur) + 5, Qt.MouseButton.RightButton)
    assert fen.morceau.pistes[0].notes == []


def test_enregistrement_simule(fen):
    fen.choisir_voix(1)
    fen.basculer_enregistrement()
    m = fen.moteur
    assert m.lecture and m.trames < 0  # décompte d'une mesure
    fen._note_recue(64, True, 0.02)
    fen._note_recue(67, True, 0.98)  # nouvelle note : la précédente s'arrête
    fen._note_recue(64, False, 1.1)
    fen._note_recue(67, False, 1.6)
    fen.enregistrement["notes"]  # toujours en cours
    fen._finir_enregistrement(2.0)
    fen.moteur.arreter()
    notes = [(n.debut, n.duree, n.hauteur) for n in fen.morceau.pistes[1].notes]
    assert notes == [(0.0, 1.0, 64), (1.0, 0.5, 67)]  # calées sur la grille de 1/16


def test_instrument_et_prereglage(fen):
    fen.choisir_voix(0)
    fen.editeur.adsr["attaque"][0].setValue(7)
    assert fen.morceau.pistes[0].instrument.attaque == 7
    fen.editeur.prereglage.setCurrentIndex(fen.editeur.prereglage.findText("Lead dents de scie"))
    fen.editeur._prereglage(fen.editeur.prereglage.findText("Lead dents de scie"))
    assert fen.morceau.pistes[0].instrument.formes == ["dents de scie"]
    assert "Lead" in fen.lignes[0].instrument.text()


def test_lecture_produit_du_son(fen):
    fen.morceau.pistes[0].notes = [Note(0, 2, 48)]
    fen.basculer_lecture()
    import numpy as np
    son = np.concatenate([fen.moteur.generer_trame() for _ in range(30)])
    assert np.abs(son).max() > 1000
    fen.basculer_lecture()
    assert not fen.moteur.lecture


def test_enregistrer_et_rouvrir(fen, tmp_path):
    fen.morceau.pistes[2].notes = [Note(0, 0.5, 36)]
    fen.chemin = tmp_path / "x.asid"
    fen.enregistrer()
    assert Morceau.ouvrir(tmp_path / "x.asid") == fen.morceau


def test_import_midi(tmp_path):
    import mido
    from atelier_sid import midi
    fichier = mido.MidiFile(ticks_per_beat=480)
    for canal, notes in ((0, [36, 38]), (1, [72, 74, 76]), (9, [36, 38])):
        piste = mido.MidiTrack()
        if canal == 0:
            piste.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100)))
        for h in notes:
            piste.append(mido.Message("note_on", channel=canal, note=h, velocity=90, time=0))
            piste.append(mido.Message("note_off", channel=canal, note=h, velocity=0, time=480))
        fichier.tracks.append(piste)
    fichier.save(str(tmp_path / "a.mid"))
    m = midi.importer(tmp_path / "a.mid")
    assert m.tempo == 100
    assert [n.hauteur for n in m.pistes[0].notes] == [36, 38]
    assert [n.hauteur for n in m.pistes[1].notes] == [72, 74, 76]
    assert m.pistes[2].instrument.batterie and len(m.pistes[2].notes) == 2
