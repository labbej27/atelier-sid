# -*- coding: utf-8 -*-
"""Transforme un morceau en image mémoire pour le lecteur 6502, puis en .sid et .prg."""

from __future__ import annotations

import re
import struct
import unicodedata
from pathlib import Path

from .modele import FILTRES, SON_DE_LA_NOTE, Morceau, Piste

ICI = Path(__file__).resolve().parent
LECTEUR = (ICI / "bin" / "player.bin").read_bytes()
LANCEUR = (ICI / "bin" / "stub.bin").read_bytes()
ETIQUETTES = {
    m.group(2): int(m.group(1), 16)
    for m in re.finditer(r"al ([0-9A-F]+) \.(\w+)", (ICI / "bin" / "player.lbl").read_text())
}

ADRESSE = 0x1000
ADRESSE_LANCEUR = 0x0801
FIN_MEMOIRE = 0xD000
TRAMES_PAR_S = 50
DUREE_MAX = 255

REPOS, LIEE, FIN = 0x60, 0x65, 0xFF
BATTERIE = 0x70
NOTE_MIN, NOTE_MAX = 12, 12 + 0x5F  # C0 à B7

# Position des champs dans l'en-tête du lecteur
FLUX = ETIQUETTES["flux"] - ADRESSE
INSTR_VOIX = ETIQUETTES["instr_voix"] - ADRESSE
FILTRE = ETIQUETTES["filtre"] - ADRESSE
INSTRUMENTS = ETIQUETTES["instruments"] - ADRESSE


class ErreurExport(Exception):
    pass


def trame(morceau: Morceau, temps: float) -> int:
    return int(round(morceau.secondes(temps) * TRAMES_PAR_S))


def hauteur_sid(hauteur: int) -> int:
    while hauteur < NOTE_MIN:
        hauteur += 12
    while hauteur > NOTE_MAX:
        hauteur -= 12
    return hauteur - NOTE_MIN


def flux_piste(morceau: Morceau, piste: Piste, debut: float = 0.0, ignorer: bool = False) -> bytes:
    """Le flux d'événements d'une voix, à partir du temps `debut`."""
    origine = trame(morceau, debut)
    fin_morceau = trame(morceau, morceau.duree) - origine
    flux = bytearray()
    curseur = 0

    def ajouter(commande: bytes, duree: int, suite: bytes | None = None):
        while duree > 0:
            morceau_duree = min(duree, DUREE_MAX)
            flux.extend(commande + bytes([morceau_duree]))
            duree -= morceau_duree
            if suite is not None:
                commande = suite

    if not (piste.muette or ignorer):
        for note in piste.notes_triees():
            d = trame(morceau, note.debut) - origine
            f = trame(morceau, note.debut + note.duree) - origine
            if f <= 0:
                continue
            tronquee = d < 0
            d = max(d, 0)
            f = min(f, fin_morceau)
            if f <= d or d < curseur:
                continue
            if d > curseur:
                ajouter(bytes([REPOS]), d - curseur)
            h = hauteur_sid(note.hauteur)
            if piste.instrument.batterie:
                ajouter(bytes([BATTERIE + SON_DE_LA_NOTE[note.hauteur % 12]]), f - d, bytes([REPOS]))
            else:
                debut_note = bytes([LIEE, h]) if tronquee else bytes([h])
                ajouter(debut_note, f - d, bytes([LIEE, h]))
            curseur = f
    if fin_morceau > curseur:
        ajouter(bytes([REPOS]), fin_morceau - curseur)
    if not flux:
        flux.extend(bytes([REPOS, 1]))
    flux.append(FIN)
    return bytes(flux)


def octets_filtre(morceau: Morceau) -> bytes:
    coupure = max(0, min(2047, morceau.filtre_coupure))
    return bytes([
        coupure & 7, coupure >> 3,
        (max(0, min(15, morceau.filtre_resonance)) << 4),
        FILTRES[morceau.filtre_type] | (max(0, min(15, morceau.volume))),
    ])


def image(morceau: Morceau, debut: float = 0.0, ignorer: int | None = None) -> bytes:
    """Lecteur + instruments + flux, prêt à charger en $1000.

    `ignorer` : numéro d'une voix à laisser muette (celle qu'on enregistre).
    """
    lecteur = bytearray(LECTEUR)
    for i, piste in enumerate(morceau.pistes[:3]):
        lecteur[INSTRUMENTS + 8 * i:INSTRUMENTS + 8 * i + 8] = piste.instrument.octets()
    lecteur[INSTR_VOIX:INSTR_VOIX + 3] = bytes([0, 1, 2])
    lecteur[FILTRE:FILTRE + 4] = octets_filtre(morceau)

    flux = [flux_piste(morceau, p, debut, i == ignorer) for i, p in enumerate(morceau.pistes[:3])]
    adresse = ADRESSE + len(lecteur)
    for voix, donnees in enumerate(flux):
        struct.pack_into("<H", lecteur, FLUX + 2 * voix, adresse)
        adresse += len(donnees)
    resultat = bytes(lecteur) + b"".join(flux)
    if ADRESSE + len(resultat) > FIN_MEMOIRE:
        raise ErreurExport(f"Morceau trop long pour la mémoire du C64 ({len(resultat)} octets).")
    return resultat


def texte_c64(texte: str, longueur: int | None = None) -> bytes:
    sans_accents = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode()
    octets = "".join(c if 32 <= ord(c) < 127 else " " for c in sans_accents).encode("ascii")
    return octets if longueur is None else octets[:longueur].ljust(longueur, b"\0")


def ecrire_sid(morceau: Morceau, chemin: Path) -> None:
    """PSID v2 : chargé en $1000, init et play lus dans les étiquettes du lecteur, PAL."""
    donnees = image(morceau)
    entete = struct.pack(
        ">4sHHHHHHHI32s32s32sHBBBB",
        b"PSID", 2, 0x7C, 0, ADRESSE, ADRESSE + 3, 1, 1, 0,
        texte_c64(morceau.titre, 32), texte_c64(morceau.auteur, 32), texte_c64("Atelier SID", 32),
        0x34, 0, 0, 0, 0,
    )
    Path(chemin).write_bytes(entete + struct.pack("<H", ADRESSE) + donnees)


def ecrire_prg(morceau: Morceau, chemin: Path) -> None:
    donnees = image(morceau)
    titre = texte_c64(morceau.titre).upper()[:39]
    auteur = texte_c64(morceau.auteur).upper()[:39]
    debut = LANCEUR + titre + (b"\r" + auteur if auteur else b"") + b"\0"
    if ADRESSE_LANCEUR + len(debut) > ADRESSE:
        raise ErreurExport("Titre trop long.")
    remplissage = bytes(ADRESSE - ADRESSE_LANCEUR - len(debut))
    Path(chemin).write_bytes(struct.pack("<H", ADRESSE_LANCEUR) + debut + remplissage + donnees)
