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


def test_import_midi(tmp_path, app):
    import mido
    from atelier_sid import midi
    from atelier_sid.gui.import_midi import ImportMidi
    fichier = mido.MidiFile(ticks_per_beat=480)
    piste = mido.MidiTrack()
    piste.append(mido.MetaMessage("set_tempo", tempo=mido.bpm2tempo(100)))
    piste.append(mido.Message("program_change", channel=3, program=88, time=0))
    evenements = []
    for i in range(8):
        evenements.append((i * 480, "on", 0, 36 + (i % 2) * 3))
        evenements.append((i * 480 + 400, "off", 0, 36 + (i % 2) * 3))
        evenements.append((i * 480, "on", 1, 72 + i))
        evenements.append((i * 480 + 400, "off", 1, 72 + i))
        evenements.append((i * 480, "on", 9, 36 if i % 2 == 0 else 38))
        evenements.append((i * 480 + 100, "off", 9, 36 if i % 2 == 0 else 38))
        for h in (60, 64, 67):  # accord, canal 4
            evenements.append((i * 480, "on", 3, h))
            evenements.append((i * 480 + 450, "off", 3, h))
    t = 0
    for instant, sens, canal, h in sorted(evenements, key=lambda e: (e[0], e[1] == "on")):
        piste.append(mido.Message("note_on" if sens == "on" else "note_off", channel=canal, note=h,
                                  velocity=90 if sens == "on" else 0, time=instant - t))
        t = instant
    fichier.tracks.append(piste)
    fichier.save(str(tmp_path / "a.mid"))

    m = midi.importer(tmp_path / "a.mid")
    assert m.tempo == 100 and m.nb_sid == 2
    assert [n.hauteur for n in m.pistes[0].notes][:2] == [36, 39]  # basse
    assert m.pistes[1].notes[0].hauteur == 72  # mélodie
    assert m.pistes[2].instrument.batterie and len(m.pistes[2].notes) == 8
    assert m.pistes[3].notes[0].hauteur == 67 and m.pistes[3].notes[0].autres == [60, 64]  # arpège
    assert m.pistes[0].instrument.nom == "Basse" and m.pistes[3].instrument.nom == "Nappe"

    d = ImportMidi(tmp_path / "a.mid", 1)
    assert d.voix[[p.canal for p in d.parties].index(3)].currentData() is None  # 1 SID : pas de place
    d.nb_sid.setCurrentIndex(1)
    assert d.voix[[p.canal for p in d.parties].index(3)].currentData() == 3
    assert d.morceau().pistes[3].notes[0].autres == [60, 64]


def test_passer_a_deux_sid_et_infos(fen):
    fen.nb_sid.setCurrentIndex(1)
    fen._nb_sid_change(1)
    assert len(fen.lignes) == 6 and fen.morceau.nb_sid == 2
    fen.choisir_voix(4)
    assert "SID 2" in fen.groupe_filtre.title()
    fen.filtre_coupure.setValue(1800)
    assert fen.morceau.filtres[1].coupure == 1800 and fen.morceau.filtres[0].coupure != 1800
    fen.champs_infos["publie"].setText("2026 LABBEJ27")
    fen._info_change("publie", "2026 LABBEJ27")
    assert fen.morceau.publie == "2026 LABBEJ27" and fen.champs_infos["titre"].maxLength() == 32
    fen.annuler()
    assert fen.morceau.nb_sid == 1 and len(fen.lignes) == 3
