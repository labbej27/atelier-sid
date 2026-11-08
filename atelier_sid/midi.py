# -*- coding: utf-8 -*-
"""Entrée MIDI (synthé branché en USB ou par une interface), clavier de l'ordinateur,
et import de fichiers .mid."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
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

INSTRUMENTS_GM = [
    "Piano", "Piano brillant", "Piano électrique", "Piano bastringue", "Piano Rhodes", "Piano chorus",
    "Clavecin", "Clavinet", "Célesta", "Glockenspiel", "Boîte à musique", "Vibraphone", "Marimba",
    "Xylophone", "Cloches tubulaires", "Dulcimer", "Orgue Hammond", "Orgue percussif", "Orgue rock",
    "Orgue d'église", "Harmonium", "Accordéon", "Harmonica", "Bandonéon", "Guitare nylon", "Guitare acier",
    "Guitare jazz", "Guitare claire", "Guitare étouffée", "Guitare saturée", "Guitare distorsion",
    "Harmoniques", "Basse acoustique", "Basse aux doigts", "Basse au médiator", "Basse fretless",
    "Basse slap 1", "Basse slap 2", "Basse synthé 1", "Basse synthé 2", "Violon", "Alto", "Violoncelle",
    "Contrebasse", "Cordes trémolo", "Cordes pizzicato", "Harpe", "Timbales", "Cordes", "Cordes 2",
    "Cordes synthé 1", "Cordes synthé 2", "Chœur aah", "Voix ooh", "Voix synthé", "Coup d'orchestre",
    "Trompette", "Trombone", "Tuba", "Trompette bouchée", "Cor", "Cuivres", "Cuivres synthé 1",
    "Cuivres synthé 2", "Sax soprano", "Sax alto", "Sax ténor", "Sax baryton", "Hautbois", "Cor anglais",
    "Basson", "Clarinette", "Piccolo", "Flûte", "Flûte à bec", "Flûte de Pan", "Bouteille", "Shakuhachi",
    "Sifflet", "Ocarina", "Lead carré", "Lead dents de scie", "Lead calliope", "Lead chiff", "Lead charang",
    "Lead voix", "Lead quintes", "Lead basse", "Nappe new age", "Nappe chaude", "Nappe polysynth",
    "Nappe chœur", "Nappe archet", "Nappe métal", "Nappe halo", "Nappe balayée", "Pluie", "Bande son",
    "Cristal", "Atmosphère", "Brillance", "Gobelins", "Échos", "Science-fiction", "Sitar", "Banjo",
    "Shamisen", "Koto", "Kalimba", "Cornemuse", "Violon folk", "Shanai", "Clochette", "Agogo",
    "Steel drum", "Wood-block", "Taiko", "Tom mélodique", "Batterie synthé", "Cymbale inversée",
    "Frette de guitare", "Souffle", "Vagues", "Oiseaux", "Téléphone", "Hélicoptère", "Applaudissements",
    "Coup de feu",
]
PROGRAMMES_PERCUSSION = {113, 115, 116, 117, 118, 119}  # agogo, wood-block, taiko, toms, cymbale
MODES = ("haute", "basse", "arpege")
NOMS_MODES = {"haute": "Note la plus haute", "basse": "Note la plus basse", "arpege": "Accords en arpège"}


@dataclass
class Partie:
    """Une partie d'un fichier MIDI : les notes d'un canal."""
    canal: int  # 0 à 15 (le canal 10 des musiciens est le 9 ici)
    programme: int
    notes: list = field(default_factory=list)  # (début, durée, hauteur) en noires

    @property
    def batterie(self) -> bool:
        return self.canal == 9

    @property
    def percussion(self) -> bool:
        return self.batterie or self.programme in PROGRAMMES_PERCUSSION

    @property
    def nom(self) -> str:
        return "Batterie" if self.batterie else INSTRUMENTS_GM[self.programme]

    @property
    def hauteur_moyenne(self) -> float:
        return sum(n[2] for n in self.notes) / len(self.notes)

    @property
    def polyphonie(self) -> int:
        evenements = sorted([(d, 1) for d, _, _ in self.notes] + [(d + l, -1) for d, l, _ in self.notes])
        courant = maximum = 0
        for _, sens in evenements:
            courant += sens
            maximum = max(maximum, courant)
        return maximum

    @property
    def accords(self) -> bool:
        """Joue de vrais accords, pas seulement des octaves."""
        for groupe in grouper(self.notes):
            hauteurs = {h % 12 for _, _, h in groupe}
            if len(hauteurs) >= 2:
                return True
        return False


def grouper(notes, tolerance: float = 1 / 32):
    """Regroupe les notes qui commencent ensemble (à une triple croche près)."""
    groupes = []
    for note in sorted(notes):
        if groupes and note[0] - groupes[-1][0][0] <= tolerance:
            groupes[-1].append(note)
        else:
            groupes.append([note])
    return groupes


def analyser(chemin: Path) -> tuple[list[Partie], float]:
    """Lit un .mid : ses parties (une par canal) et son tempo."""
    import mido

    fichier = mido.MidiFile(str(chemin))
    par_temps = fichier.ticks_per_beat
    tempo = None
    parties: dict[int, Partie] = {}
    for piste in fichier.tracks:
        ticks = 0
        ouvertes: dict[tuple[int, int], int] = {}
        programmes: dict[int, int] = {}
        for msg in piste:
            ticks += msg.time
            if msg.type == "set_tempo" and tempo is None:
                tempo = mido.tempo2bpm(msg.tempo)
            elif msg.type == "program_change":
                programmes.setdefault(msg.channel, msg.program)
            elif msg.type == "note_on" and msg.velocity > 0:
                ouvertes[(msg.channel, msg.note)] = ticks
            elif msg.type in ("note_off", "note_on"):
                debut = ouvertes.pop((msg.channel, msg.note), None)
                if debut is not None and ticks > debut:
                    partie = parties.setdefault(msg.channel, Partie(msg.channel, programmes.get(msg.channel, 0)))
                    partie.notes.append((debut / par_temps, (ticks - debut) / par_temps, msg.note))
        for canal, programme in programmes.items():
            if canal in parties and parties[canal].programme == 0:
                parties[canal].programme = programme
    if not parties:
        raise ValueError("Aucune note dans ce fichier MIDI.")
    return sorted(parties.values(), key=lambda p: p.canal), round(tempo or 120.0, 2)


def repartir(parties: list[Partie], nb_sid: int) -> dict[int, tuple[int | None, str]]:
    """Propose une voix et une façon de jouer pour chaque partie : {canal: (voix ou None, mode)}.

    La batterie et les percussions se partagent la voix 3. Ensuite viennent la basse
    (la partie la plus grave), la mélodie (la plus aiguë), puis les parties les plus
    fournies. Les petites parties restent de côté s'il n'y a plus de voix.
    """
    choix: dict[int, tuple[int | None, str]] = {}
    nb_voix = 3 * nb_sid
    percussions = [p for p in parties if p.percussion]
    melodiques = [p for p in parties if not p.percussion]
    voix_libres = list(range(nb_voix))
    if percussions:
        voix_libres.remove(2)
        for p in percussions:
            choix[p.canal] = (2, "haute")

    if melodiques:
        plus_fournie = max(len(p.notes) for p in melodiques)
        importantes = [p for p in melodiques if len(p.notes) >= 0.1 * plus_fournie] or melodiques
        basse = min(importantes, key=lambda p: p.hauteur_moyenne)
        restantes = [p for p in importantes if p is not basse]
        melodie = max(restantes, key=lambda p: p.hauteur_moyenne) if restantes else None
        ordre = [basse] + ([melodie] if melodie else [])
        ordre += sorted((p for p in melodiques if p not in ordre), key=lambda p: len(p.notes), reverse=True)
        for p in ordre:
            mode = "arpege" if p.accords and p is not basse else "haute"
            choix[p.canal] = (voix_libres.pop(0) if voix_libres else None, mode)
    return choix


def construire(parties: list[Partie], choix: dict, nb_sid: int, tempo: float, titre: str) -> Morceau:
    """Crée le morceau à partir des parties et de la voix choisie pour chacune."""
    from .modele import PREREGLAGES

    morceau = Morceau(titre=titre, tempo=tempo)
    morceau.regler_nb_sid(nb_sid)
    for piste in morceau.pistes:
        piste.notes = []
    par_voix: dict[int, list[Partie]] = {}
    for partie in parties:
        voix, _ = choix.get(partie.canal, (None, "haute"))
        if voix is not None and voix < len(morceau.pistes):
            par_voix.setdefault(voix, []).append(partie)

    melodiques = [v for v in par_voix if not any(p.percussion for p in par_voix[v])]
    graves = sorted(melodiques, key=lambda v: min(p.hauteur_moyenne for p in par_voix[v]))
    for voix, liste in par_voix.items():
        piste = morceau.pistes[voix]
        if any(p.percussion for p in liste):
            piste.instrument = PREREGLAGES["Batterie"]()
        else:
            mode = choix[liste[0].canal][1]
            nom = "Nappe" if mode == "arpege" else "Basse" if voix == graves[0] else "Mélodie"
            piste.instrument = PREREGLAGES[nom]()
        for partie in liste:
            mode = choix[partie.canal][1]
            if partie.percussion and not partie.batterie:
                # taiko, toms… joués comme un tom ; cymbale inversée comme un charleston
                hauteur = 42 if partie.programme == 119 else 41
                piste.notes += [Note(d, l, hauteur) for d, l, _ in partie.notes]
                continue
            for groupe in grouper(partie.notes):
                hauteurs = sorted({h for _, _, h in groupe})
                debut = groupe[0][0]
                duree = max(l for _, l, _ in groupe)
                if partie.batterie or mode == "haute":
                    piste.notes.append(Note(debut, duree, hauteurs[-1]))
                elif mode == "basse":
                    piste.notes.append(Note(debut, duree, hauteurs[0]))
                else:
                    piste.notes.append(Note(debut, duree, hauteurs[-1], hauteurs[:-1][-3:]))
    fin = max((n.debut + n.duree for p in morceau.pistes for n in p.notes), default=4.0)
    morceau.mesures = max(1, int(-(-fin // morceau.temps_par_mesure)))
    return morceau


def importer(chemin: Path, nb_sid: int | None = None) -> Morceau:
    """Import automatique : autant de SID qu'il en faut (3 au plus), répartition proposée."""
    from .modele import MAX_SID

    parties, tempo = analyser(chemin)
    if nb_sid is None:
        besoin = len([p for p in parties if not p.percussion]) + (1 if any(p.percussion for p in parties) else 0)
        nb_sid = max(1, min(MAX_SID, -(-besoin // 3)))
    return construire(parties, repartir(parties, nb_sid), nb_sid, tempo, Path(chemin).stem)
