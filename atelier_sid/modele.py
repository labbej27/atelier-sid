# -*- coding: utf-8 -*-
"""Le morceau : trois pistes (les trois voix du SID), leurs instruments et leurs notes.

Les temps sont en temps musicaux (noires) : le tempo peut changer sans toucher aux
notes. La conversion en trames de 1/50 s se fait à l'export.
"""

from __future__ import annotations

import copy
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

FORMES = ("triangle", "dents de scie", "impulsion", "bruit")
BITS_FORME = {"triangle": 0x10, "dents de scie": 0x20, "impulsion": 0x40, "bruit": 0x80}
FILTRES = {"passe-bas": 0x10, "passe-bande": 0x20, "passe-haut": 0x40}
BATTERIE = ("grosse caisse", "caisse claire", "charleston", "tom")

# Sur une piste de batterie, la note jouée choisit le son, d'après sa place dans l'octave :
# do = grosse caisse ; ré, mi = caisse claire ; fa#, sol#, la# = charleston ; fa, sol, la, si = tom.
SON_DE_LA_NOTE = {0: 0, 1: 1, 2: 1, 3: 1, 4: 1, 5: 3, 6: 2, 7: 3, 8: 2, 9: 3, 10: 2, 11: 3}

VERSION_FICHIER = 2
MAX_SID = 3  # SID 1 en $D400, SID 2 en $D420, SID 3 en $D440
ADRESSES_SID = (0xD400, 0xD420, 0xD440)


@dataclass
class Instrument:
    nom: str = "Impulsion"
    formes: list[str] = field(default_factory=lambda: ["impulsion"])
    attaque: int = 0  # 0 à 15, comme les registres du SID
    declin: int = 9
    maintien: int = 10
    relache: int = 4
    largeur: int = 2048  # largeur d'impulsion, 0 à 4095 (2048 = carré)
    variation: int = 0  # vitesse de variation de la largeur d'impulsion, 0 à 255
    vibrato: int = 0  # profondeur, 0 à 4
    vibrato_vitesse: int = 3  # trames par pas, 1 à 15
    filtre: bool = False
    relance: bool = True  # relâche d'une trame avant chaque attaque : chaque note est nette
    batterie: bool = False

    def octets(self) -> bytes:
        """Les 8 octets lus par le lecteur 6502 (voir lecteur/player.s)."""
        forme = 0
        for nom in self.formes:
            forme |= BITS_FORME[nom]
        drapeaux = (1 if self.filtre else 0) | (4 if self.relance else 0)
        largeur = max(0, min(4095, self.largeur))
        vib = (max(0, min(4, self.vibrato)) << 4) | max(1, min(15, self.vibrato_vitesse))
        return bytes([
            forme or 0x40,
            (self.attaque & 15) << 4 | (self.declin & 15),
            (self.maintien & 15) << 4 | (self.relache & 15),
            largeur & 0xFF, largeur >> 8,
            max(0, min(255, self.variation)),
            vib if self.vibrato else 0,
            drapeaux,
        ])


@dataclass
class Note:
    debut: float  # en noires
    duree: float
    hauteur: int  # numéro MIDI


@dataclass
class Piste:
    nom: str
    instrument: Instrument
    notes: list[Note] = field(default_factory=list)
    muette: bool = False

    def notes_triees(self) -> list[Note]:
        """Notes dans l'ordre, sans chevauchement : une voix du SID ne joue qu'une note."""
        notes = sorted((n for n in self.notes if n.duree > 0), key=lambda n: (n.debut, -n.hauteur))
        propres: list[Note] = []
        for note in notes:
            if propres and propres[-1].debut == note.debut:
                continue  # deux notes au même instant : on garde la plus aiguë
            if propres and propres[-1].debut + propres[-1].duree > note.debut:
                precedente = propres[-1]
                propres[-1] = Note(precedente.debut, note.debut - precedente.debut, precedente.hauteur)
            propres.append(note)
        return propres


@dataclass
class Filtre:
    """Le filtre d'une puce SID, partagé par celles de ses trois voix qui y passent."""
    type: str = "passe-bas"
    coupure: int = 1024  # 0 à 2047
    resonance: int = 4  # 0 à 15


@dataclass
class Morceau:
    titre: str = "Sans titre"
    auteur: str = ""
    publie: str = ""  # champ « released » des .sid : année, groupe…
    tempo: float = 120.0
    mesures: int = 8
    temps_par_mesure: int = 4
    pistes: list[Piste] = field(default_factory=list)
    filtres: list[Filtre] = field(default_factory=list)
    volume: int = 15

    def __post_init__(self):
        if not self.pistes:
            self.pistes = [
                Piste("Voix 1", PREREGLAGES["Basse"]()),
                Piste("Voix 2", PREREGLAGES["Mélodie"]()),
                Piste("Voix 3", PREREGLAGES["Batterie"]()),
            ]
        if not self.filtres:
            self.filtres = [Filtre() for _ in range(self.nb_sid)]

    @property
    def nb_sid(self) -> int:
        return max(1, min(MAX_SID, (len(self.pistes) + 2) // 3))

    def regler_nb_sid(self, nb: int) -> None:
        """Ajoute ou retire des puces SID : trois voix et un filtre par puce."""
        nb = max(1, min(MAX_SID, nb))
        while len(self.pistes) < 3 * nb:
            voix = len(self.pistes)
            nom = ("Basse", "Mélodie", "Nappe")[voix % 3]
            self.pistes.append(Piste(f"Voix {voix + 1}", PREREGLAGES[nom]()))
        del self.pistes[3 * nb:]
        while len(self.filtres) < nb:
            self.filtres.append(Filtre())
        del self.filtres[nb:]

    @property
    def duree(self) -> float:
        """Durée en noires."""
        return float(self.mesures * self.temps_par_mesure)

    def secondes(self, temps: float) -> float:
        return temps * 60.0 / self.tempo

    def copie(self) -> "Morceau":
        return copy.deepcopy(self)

    # --- Fichier .asid (JSON) ---

    def vers_dict(self) -> dict:
        return {"format": "atelier-sid", "version": VERSION_FICHIER, **asdict(self)}

    def enregistrer(self, chemin: Path) -> None:
        Path(chemin).write_text(json.dumps(self.vers_dict(), ensure_ascii=False, indent=1), encoding="utf-8")

    @classmethod
    def depuis_dict(cls, donnees: dict) -> "Morceau":
        if donnees.get("format") != "atelier-sid":
            raise ValueError("Ce fichier n'est pas un morceau d'Atelier SID.")
        champs = {k: v for k, v in donnees.items() if k in cls.__dataclass_fields__ and k not in ("pistes", "filtres")}
        if "filtres" in donnees:
            filtres = [Filtre(**f) for f in donnees["filtres"]]
        else:  # version 1 : un seul filtre
            filtres = [Filtre(donnees.get("filtre_type", "passe-bas"), donnees.get("filtre_coupure", 1024),
                              donnees.get("filtre_resonance", 4))]
        pistes = []
        for p in donnees["pistes"]:
            instrument = Instrument(**{k: v for k, v in p["instrument"].items() if k in Instrument.__dataclass_fields__})
            notes = [Note(**n) for n in p.get("notes", [])]
            pistes.append(Piste(p.get("nom", "Voix"), instrument, notes, p.get("muette", False)))
        return cls(**champs, pistes=pistes[:3 * MAX_SID], filtres=filtres)

    @classmethod
    def ouvrir(cls, chemin: Path) -> "Morceau":
        return cls.depuis_dict(json.loads(Path(chemin).read_text(encoding="utf-8")))


# --- Préréglages ------------------------------------------------------------

PREREGLAGES = {
    "Basse": lambda: Instrument("Basse", ["impulsion"], 0, 8, 10, 3, 1024, 0, 0, 3, True, True),
    "Basse douce": lambda: Instrument("Basse douce", ["triangle"], 0, 9, 12, 4),
    "Mélodie": lambda: Instrument("Mélodie", ["impulsion"], 1, 9, 11, 6, 1536, 24, 2, 3),
    "Lead dents de scie": lambda: Instrument("Lead dents de scie", ["dents de scie"], 0, 9, 10, 6, 2048, 0, 2, 2),
    "Nappe": lambda: Instrument("Nappe", ["impulsion"], 9, 9, 12, 10, 800, 40, 1, 4, True),
    "Cloche": lambda: Instrument("Cloche", ["triangle"], 0, 10, 0, 10),
    "Batterie": lambda: Instrument("Batterie", ["impulsion"], 0, 9, 0, 9, 2048, 0, 0, 3, False, False, True),
}
