# -*- coding: utf-8 -*-
"""Entrée MIDI (synthé branché en USB ou par une interface), clavier de l'ordinateur,
et import de fichiers .mid."""

from __future__ import annotations

import sys
from pathlib import Path

from .modele import Morceau, Note


class EntreeMidi:
    """Écoute un port MIDI et appelle rappel(hauteur, appuyee) pour chaque note."""

    def __init__(self):
        self.port = None
        self.nom = None

    @staticmethod
    def ports() -> list[str]:
        try:
            import rtmidi
            return rtmidi.MidiIn().get_ports()
        except Exception:
            return []

    def ouvrir(self, nom: str, rappel) -> None:
        import rtmidi

        self.fermer()
        port = rtmidi.MidiIn()
        noms = port.get_ports()
        if nom not in noms:
            raise ValueError(f"Port MIDI introuvable : {nom}")
        port.open_port(noms.index(nom))
        port.ignore_types(sysex=True, timing=True, active_sense=True)

        def recevoir(message, _donnees):
            octets, _delta = message
            if len(octets) < 3:
                return
            statut, hauteur, velocite = octets[0] & 0xF0, octets[1], octets[2]
            if statut == 0x90 and velocite > 0:
                rappel(hauteur, True)
            elif statut == 0x80 or (statut == 0x90 and velocite == 0):
                rappel(hauteur, False)

        port.set_callback(recevoir)
        self.port, self.nom = port, nom

    def fermer(self) -> None:
        if self.port is not None:
            self.port.cancel_callback()
            self.port.close_port()
            self.port = None
            self.nom = None


# --- Clavier de l'ordinateur ------------------------------------------------
# Par position des touches, quelle que soit la disposition (AZERTY, QWERTY…) :
# rangée du bas = une octave (Z S X D C V G B H N J M sur un QWERTY), rangée du
# haut = l'octave au-dessus (Q 2 W 3 E R 5 T 6 Y 7 U I).

_TOUCHES = ["Z", "S", "X", "D", "C", "V", "G", "B", "H", "N", "J", "M", ",",
            "Q", "2", "W", "3", "E", "R", "5", "T", "6", "Y", "7", "U", "I"]
_DEMI_TONS = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24]

_MAC = {"Z": 0x06, "S": 0x01, "X": 0x07, "D": 0x02, "C": 0x08, "V": 0x09, "G": 0x05, "B": 0x0B, "H": 0x04,
        "N": 0x2D, "J": 0x26, "M": 0x2E, ",": 0x2B, "Q": 0x0C, "2": 0x13, "W": 0x0D, "3": 0x14, "E": 0x0E,
        "R": 0x0F, "5": 0x17, "T": 0x11, "6": 0x16, "Y": 0x10, "7": 0x1A, "U": 0x20, "I": 0x22}
_PC = {"Z": 0x2C, "S": 0x1F, "X": 0x2D, "D": 0x20, "C": 0x2E, "V": 0x2F, "G": 0x22, "B": 0x30, "H": 0x23,
       "N": 0x31, "J": 0x24, "M": 0x32, ",": 0x33, "Q": 0x10, "2": 0x03, "W": 0x11, "3": 0x04, "E": 0x12,
       "R": 0x13, "5": 0x06, "T": 0x14, "6": 0x07, "Y": 0x15, "7": 0x08, "U": 0x16, "I": 0x17}

if sys.platform == "darwin":
    _CODES = {_MAC[t]: d for t, d in zip(_TOUCHES, _DEMI_TONS)}
elif sys.platform.startswith("win"):
    _CODES = {_PC[t]: d for t, d in zip(_TOUCHES, _DEMI_TONS)}
else:  # X11 et Wayland : code evdev + 8
    _CODES = {_PC[t] + 8: d for t, d in zip(_TOUCHES, _DEMI_TONS)}


def demi_ton_de_la_touche(evenement) -> int | None:
    """Demi-ton (0 à 24) joué par une touche, ou None si ce n'est pas une touche de piano."""
    code = evenement.nativeVirtualKey() if sys.platform == "darwin" else evenement.nativeScanCode()
    return _CODES.get(code)


# --- Import d'un fichier .mid ------------------------------------------------


def importer(chemin: Path) -> Morceau:
    """Place les parties d'un MIDI sur les voix, avec autant de SID qu'il en faut (3 au plus).

    La batterie (canal 10) va sur la voix 3. Une voix du SID ne joue qu'une note à
    la fois : quand une partie en joue plusieurs, la plus aiguë l'emporte.
    """
    import mido

    from .modele import MAX_SID, PREREGLAGES

    fichier = mido.MidiFile(str(chemin))
    par_temps = fichier.ticks_per_beat
    tempo = None
    parties: dict[int, list[Note]] = {}
    for piste in fichier.tracks:
        ticks = 0
        ouvertes: dict[tuple[int, int], int] = {}
        for msg in piste:
            ticks += msg.time
            if msg.type == "set_tempo" and tempo is None:
                tempo = mido.tempo2bpm(msg.tempo)
            elif msg.type == "note_on" and msg.velocity > 0:
                ouvertes[(msg.channel, msg.note)] = ticks
            elif msg.type in ("note_off", "note_on"):
                debut = ouvertes.pop((msg.channel, msg.note), None)
                if debut is not None and ticks > debut:
                    parties.setdefault(msg.channel, []).append(
                        Note(debut / par_temps, (ticks - debut) / par_temps, msg.note))
    if not parties:
        raise ValueError("Aucune note dans ce fichier MIDI.")

    morceau = Morceau(titre=Path(chemin).stem, tempo=round(tempo or 120.0, 2))
    batterie = parties.pop(9, None)
    places = 3 * MAX_SID - (1 if batterie is not None else 0)
    melodiques = sorted(parties.values(), key=len, reverse=True)[:places]
    melodiques.sort(key=lambda notes: sum(n.hauteur for n in notes) / len(notes))  # du grave à l'aigu
    total = len(melodiques) + (1 if batterie is not None else 0)
    morceau.regler_nb_sid(-(-total // 3))
    voix_libres = [v for v in range(len(morceau.pistes)) if not (batterie is not None and v == 2)]
    for rang, (voix, notes) in enumerate(zip(voix_libres, melodiques)):
        nom = "Basse" if rang == 0 else "Mélodie" if rang == len(melodiques) - 1 else "Nappe"
        morceau.pistes[voix].notes = notes
        morceau.pistes[voix].instrument = PREREGLAGES[nom]()
    for voix in voix_libres[len(melodiques):]:
        morceau.pistes[voix].notes = []
    if batterie is not None:
        morceau.pistes[2].notes = batterie
        morceau.pistes[2].instrument = PREREGLAGES["Batterie"]()
    fin = max(n.debut + n.duree for p in morceau.pistes for n in p.notes)
    morceau.mesures = max(1, int(-(-fin // morceau.temps_par_mesure)))
    return morceau
