"""Le vrai lecteur 6502, joué par py65, doit écrire les bonnes notes aux bons moments."""
import struct

import numpy as np
import pytest

from atelier_sid import export, moteur
from atelier_sid.modele import Instrument, Morceau, Note, Piste


def morceau_simple():
    m = Morceau(tempo=150, mesures=1)  # 150 BPM : une noire = 20 trames
    m.pistes[0].notes = [Note(0, 1, 48), Note(2, 1, 50)]
    m.pistes[1].notes = [Note(1, 2, 72)]
    m.pistes[2].notes = [Note(0, 0.5, 36), Note(1, 0.5, 38)]
    return m


def journal(morceau, nb_trames):
    """Joue nb_trames et note, trame par trame, fréquence et gâchette de chaque voix."""
    emu = moteur.C64Sid()
    etat = {}
    emu.memoire.subscribe_to_write(range(0xD400, 0xD419), lambda a, v: etat.__setitem__(a - 0xD400, v))
    emu.charger(export.image(morceau))
    lignes = []
    for _ in range(nb_trames):
        emu.trame()
        lignes.append([((etat.get(7 * v + 1, 0) << 8) | etat.get(7 * v, 0), etat.get(7 * v + 4, 0) & 1) for v in range(3)])
    return lignes


def test_notes_aux_bons_moments():
    lignes = journal(morceau_simple(), 80)
    f48, f50, f72 = (moteur.frequence_sid(h) for h in (48, 50, 72))
    assert lignes[1][0] == (f48, 1)  # attaque une trame après la relâche
    assert lignes[10][0] == (f48, 1)
    assert lignes[25][0][1] == 0  # silence entre la 1re et la 2e note
    assert lignes[41][0] == (f50, 1)
    assert lignes[10][1][1] == 0 and lignes[21][1] == (f72, 1)


def test_vibrato_fait_osciller_la_frequence():
    m = Morceau(tempo=150, mesures=1)
    m.pistes[1].instrument = Instrument(vibrato=3, vibrato_vitesse=1)
    m.pistes[1].notes = [Note(0, 4, 60)]
    frequences = {ligne[1][0] for ligne in journal(m, 40)[2:]}
    base = moteur.frequence_sid(60)
    assert len(frequences) >= 4 and min(frequences) < base < max(frequences)
    assert max(frequences) - base < base * 0.05


def test_batterie_et_son_audible():
    emu = moteur.C64Sid()
    emu.charger(export.image(morceau_simple()))
    son = []
    for _ in range(80):
        emu.trame()
        son.append(emu.echantillons())
    son = np.concatenate(son)
    assert son.size == 80 * 960
    assert np.abs(son).max() > 1000


def test_flux_note_longue_et_depart_au_milieu():
    m = Morceau(tempo=60, mesures=4)  # une noire = 50 trames
    m.pistes[0].notes = [Note(0, 8, 60)]  # 400 trames
    flux = export.flux_piste(m, m.pistes[0])
    assert flux[:5] == bytes([48, 255, 0x65, 48, 145])
    milieu = export.flux_piste(m, m.pistes[0], debut=2)  # départ dans la note : liée
    assert milieu[:3] == bytes([0x65, 48, 255])


def test_notes_qui_se_chevauchent_sont_coupees():
    p = Piste("v", Instrument(), [Note(0, 4, 60), Note(1, 1, 64), Note(1, 1, 50)])
    assert [(n.debut, n.duree, n.hauteur) for n in p.notes_triees()] == [(0, 1, 60), (1, 1, 64)]


def test_sid_et_prg(tmp_path):
    m = morceau_simple()
    m.titre, m.auteur = "Mon essai é", "Moi"
    export.ecrire_sid(m, tmp_path / "a.sid")
    export.ecrire_prg(m, tmp_path / "a.prg")
    sid = (tmp_path / "a.sid").read_bytes()
    assert struct.unpack(">4sHHHHH", sid[:14]) == (b"PSID", 2, 0x7C, 0, 0x1000, 0x1003)
    assert sid[0x16:0x16 + 11] == b"Mon essai e"
    prg = (tmp_path / "a.prg").read_bytes()
    assert prg[:2] == b"\x01\x08" and prg[2 + 0x1000 - 0x0801:] == sid[0x7E:]
    assert b"MON ESSAI E\rMOI\0" in prg


def test_wav(tmp_path):
    moteur.rendre_wav(morceau_simple(), tmp_path / "a.wav")
    assert (tmp_path / "a.wav").stat().st_size > 44 + 2 * 48000


def test_morceau_enregistre_et_relu(tmp_path):
    m = morceau_simple()
    m.pistes[1].instrument.vibrato = 2
    m.enregistrer(tmp_path / "m.asid")
    relu = Morceau.ouvrir(tmp_path / "m.asid")
    assert relu == m


def test_metronome_et_direct():
    mo = moteur.Moteur()
    m = morceau_simple()
    mo.metronome = True
    mo.jouer(m, decompte=1)
    sons = [mo.generer_trame() for _ in range(100)]
    assert all(s.size == 960 for s in sons)
    assert mo.position() > 0
    mo.note_directe(0, 60, m.pistes[0].instrument)
    son = np.concatenate([mo.generer_trame() for _ in range(5)])
    assert np.abs(son).max() > 0
