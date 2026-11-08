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
    assert son.shape == (80 * 960, 2)
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
    assert all(s.shape == (960, 2) for s in sons)
    assert mo.position() > 0
    mo.note_directe(0, 60, m.pistes[0].instrument)
    son = np.concatenate([mo.generer_trame() for _ in range(5)])
    assert np.abs(son).max() > 0


def test_deux_sid_voix_4_sur_le_second(tmp_path):
    m = Morceau(tempo=150, mesures=1)
    m.regler_nb_sid(2)
    assert len(m.pistes) == 6 and len(m.filtres) == 2
    m.pistes[3].notes = [Note(0, 2, 60)]
    m.filtres[1].coupure = 1500
    emu = moteur.C64Sid(nb_sid=2)
    ecrits = {}
    emu.memoire.subscribe_to_write(range(0xD400, 0xD460), lambda a, v: ecrits.__setitem__(a, v))
    emu.charger(export.image(m))
    for _ in range(5):
        emu.trame()
    f = moteur.frequence_sid(60)
    assert (ecrits[0xD421] << 8 | ecrits[0xD420]) == f and ecrits[0xD424] & 1  # voix 4 = voix 1 du SID 2
    assert ecrits[0xD416] == 1024 >> 3 and ecrits[0xD436] == 1500 >> 3  # un filtre par SID
    assert ecrits[0xD438] & 15 == 15 and ecrits[0xD418] & 15 == 15
    son = emu.echantillons()
    assert son.shape == (960, 2) and abs(son[:, 1]).max() > abs(son[:, 0]).max()  # SID 2 à droite
    export.ecrire_sid(m, tmp_path / "a.sid")
    entete = (tmp_path / "a.sid").read_bytes()
    assert struct.unpack(">H", entete[4:6])[0] == 3 and entete[0x7A] == 0x42 and entete[0x7B] == 0


def test_trois_sid_psid_v4(tmp_path):
    m = Morceau(titre="T", auteur="A", publie="2026 LABBEJ27")
    m.regler_nb_sid(3)
    m.pistes[8].notes = [Note(0, 1, 72)]
    export.ecrire_sid(m, tmp_path / "a.sid")
    d = (tmp_path / "a.sid").read_bytes()
    assert struct.unpack(">H", d[4:6])[0] == 4 and d[0x7A] == 0x42 and d[0x7B] == 0x44
    assert d[0x56:0x56 + 13] == b"2026 LABBEJ27"
    export.ecrire_prg(m, tmp_path / "a.prg")
    assert b"T\rA\r2026 LABBEJ27\r\rSID : $D400 $D420 $D440\0" in (tmp_path / "a.prg").read_bytes()
    emu = moteur.C64Sid(nb_sid=3)
    emu.charger(export.image(m))
    ecrits = {}
    emu.memoire.subscribe_to_write(range(0xD400, 0xD460), lambda a, v: ecrits.__setitem__(a, v))
    for _ in range(3):
        emu.trame()
    assert (ecrits[0xD44F] << 8 | ecrits[0xD44E]) == moteur.frequence_sid(72)  # voix 9


def test_ancien_fichier_un_filtre(tmp_path):
    import json
    m = Morceau()
    d = m.vers_dict()
    del d["filtres"]
    d.update(version=1, filtre_type="passe-haut", filtre_coupure=300, filtre_resonance=9)
    (tmp_path / "v1.asid").write_text(json.dumps(d))
    relu = Morceau.ouvrir(tmp_path / "v1.asid")
    assert relu.filtres[0].type == "passe-haut" and relu.filtres[0].coupure == 300 and relu.nb_sid == 1


def test_reduire_les_sid():
    m = Morceau()
    m.regler_nb_sid(3)
    m.regler_nb_sid(1)
    assert len(m.pistes) == 3 and len(m.filtres) == 1
