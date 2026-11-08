# -*- coding: utf-8 -*-
"""Le son : le vrai lecteur 6502 tourne dans un 6502 émulé (py65) et pilote un SID
émulé (reSIDfp). Ce qu'on entend est donc ce que jouera le C64.

Les notes jouées en direct au clavier (ou au synthé) sont écrites directement dans
le SID, sur la voix qu'on enregistre.
"""

from __future__ import annotations

import collections
import datetime
import math
import threading
import wave
from pathlib import Path

import numpy as np
from py65.devices.mpu6502 import MPU
from py65.memory import ObservableMemory
from pyresidfp import SoundInterfaceDevice, WritableRegister
from pyresidfp._pyresidfp import ChipModel

from . import export
from .modele import BITS_FORME, SON_DE_LA_NOTE, Instrument, Morceau

FREQ_ECH = 48000
ECH_PAR_TRAME = FREQ_ECH // export.TRAMES_PAR_S  # 960
DUREE_TRAME = datetime.timedelta(microseconds=1_000_000 // export.TRAMES_PAR_S)
SID = 0xD400
RETOUR = 0xFFFF  # adresse de retour factice : l'appel s'arrête quand le 6502 y arrive

# Batterie jouée en direct : mêmes tables que le lecteur 6502
BATT_FRQ = [[0x18, 0x0E, 0x09, 0x06, 0x04], [0x1C, 0x30, 0x28, 0x20, 0x18],
            [0x70, 0x70, 0x70, 0x70, 0x70], [0x0C, 0x0A, 0x08, 0x07, 0x06]]
BATT_ONDE = [[0x41, 0x41, 0x41, 0x41, 0x40], [0x41, 0x81, 0x81, 0x81, 0x80],
             [0x81, 0x80, 0x80, 0x80, 0x80], [0x11, 0x11, 0x11, 0x11, 0x10]]


def frequence_sid(hauteur: int) -> int:
    h = export.hauteur_sid(hauteur) + export.NOTE_MIN
    return min(65535, round(440.0 * 2 ** ((h - 69) / 12) * 16777216 / 985248))


# Registre de base de chaque voix (comme la table « decal » du lecteur 6502)
DECAL = [0, 7, 14, 0x20, 0x27, 0x2E, 0x40, 0x47, 0x4E]
# Place de chaque SID dans la stéréo (gauche, droite) : 1 SID au centre ; 2 SID à gauche et à
# droite, comme les morceaux « stéréo SID » ; le 3e au centre.
PANORAMIQUE = {1: [(1.0, 1.0)], 2: [(1.0, 0.15), (0.15, 1.0)], 3: [(1.0, 0.15), (0.15, 1.0), (0.6, 0.6)]}


class C64Sid:
    """Un 6502 et jusqu'à trois SID émulés ($D400, $D420, $D440), reliés par leurs registres."""

    def __init__(self, puce: str = "6581", nb_sid: int = 1):
        modele = ChipModel.MOS8580 if puce == "8580" else ChipModel.MOS6581
        self.sids = [SoundInterfaceDevice(model=modele, sampling_frequency=FREQ_ECH) for _ in range(3)]
        self.nb_sid = nb_sid
        self.memoire = ObservableMemory()
        for s in range(3):
            self.memoire.subscribe_to_write(range(SID + 0x20 * s, SID + 0x20 * s + 25), self._ecriture_sid)
        self.cpu = MPU(memory=self.memoire)
        self.charge = False
        self._reste = np.zeros((0, 2), dtype=np.int32)

    @property
    def sid(self):
        return self.sids[0]

    def _ecriture_sid(self, adresse: int, valeur: int):
        s, registre = divmod(adresse - SID, 0x20)
        self.sids[s].write_register(WritableRegister(registre), valeur & 0xFF)

    def ecrire(self, registre: int, valeur: int) -> None:
        """registre : décalage depuis $D400 (0x20 de plus par SID)."""
        self.memoire[SID + registre] = valeur & 0xFF

    def appeler(self, adresse: int, a: int = 0, x: int = 0) -> None:
        """JSR adresse : s'arrête au RTS final."""
        cpu = self.cpu
        cpu.sp = 0xFF
        cpu.stPush(RETOUR >> 8)
        cpu.stPush((RETOUR - 1) & 0xFF)
        cpu.a, cpu.x, cpu.pc = a, x, adresse
        for _ in range(200_000):
            if cpu.pc == RETOUR:
                return
            cpu.step()
        raise RuntimeError(f"Le lecteur 6502 ne rend pas la main (appel ${adresse:04X}).")

    def charger(self, image: bytes, nb_sid: int | None = None) -> None:
        if nb_sid is not None:
            self.nb_sid = nb_sid
        for sid in self.sids:
            sid.reset()
        self.memoire[export.ADRESSE:export.ADRESSE + len(image)] = list(image)
        self.appeler(export.ADRESSE)
        self.charge = True

    def trame(self) -> None:
        if self.charge:
            self.appeler(export.ADRESSE + 3)

    def echantillons(self) -> np.ndarray:
        """Exactement une trame de son stéréo (960 × 2) : reSID en donne parfois un de plus."""
        while len(self._reste) < ECH_PAR_TRAME:
            sons = [np.asarray(sid.clock(DUREE_TRAME), dtype=np.float64) for sid in self.sids[:self.nb_sid]]
            n = min(s.size for s in sons)
            stereo = np.zeros((n, 2))
            gains = PANORAMIQUE[self.nb_sid]
            for son, (g, d) in zip(sons, gains):
                stereo[:, 0] += son[:n] * g
                stereo[:, 1] += son[:n] * d
            stereo /= np.array([sum(g for g, _ in gains), sum(d for _, d in gains)])  # pas de saturation
            self._reste = np.concatenate((self._reste, stereo.astype(np.int32)))
        son, self._reste = self._reste[:ECH_PAR_TRAME], self._reste[ECH_PAR_TRAME:]
        return son


class Moteur:
    """Sortie audio, transport (lecture, enregistrement), métronome et jeu en direct."""

    def __init__(self, puce: str = "6581"):
        self.emu = C64Sid(puce)
        self.verrou = threading.RLock()
        self.lecture = False
        self.trames = 0  # trames jouées depuis le début de la lecture (négatif : décompte)
        self.debut = 0.0
        self.fin = 0.0
        self.tempo = 120.0
        self.temps_par_mesure = 4
        self.boucle = False
        self.metronome = False
        self.flux_audio = None
        self.tampon = np.zeros((0, 2), dtype=np.int16)
        self.direct = collections.deque()
        self.batterie_directe: dict[int, list] = {}
        self.ondes = [0x40] * 9
        self.clics = {True: self._clic(1760.0, 9000), False: self._clic(1175.0, 6000)}
        self.a_la_fin = None  # rappel quand la lecture s'arrête seule
        self._reste_clic = np.zeros(0, dtype=np.int32)

    @staticmethod
    def _clic(frequence: float, amplitude: int) -> np.ndarray:
        t = np.arange(int(0.03 * FREQ_ECH)) / FREQ_ECH
        return (amplitude * np.sin(2 * np.pi * frequence * t) * np.exp(-t * 160)).astype(np.int32)

    # --- Audio ---

    def demarrer_audio(self) -> None:
        import sounddevice as sd

        self.flux_audio = sd.OutputStream(
            samplerate=FREQ_ECH, channels=2, dtype="int16", blocksize=ECH_PAR_TRAME,
            latency="low", callback=self._rappel,
        )
        self.flux_audio.start()

    def fermer(self) -> None:
        if self.flux_audio is not None:
            self.flux_audio.stop()
            self.flux_audio.close()
            self.flux_audio = None

    @property
    def latence(self) -> float:
        return float(self.flux_audio.latency) if self.flux_audio is not None else 0.0

    def _rappel(self, sortie, nb, _temps, _etat) -> None:
        while len(self.tampon) < nb:
            self.tampon = np.concatenate((self.tampon, self.generer_trame()))
        sortie[:] = self.tampon[:nb]
        self.tampon = self.tampon[nb:]

    def generer_trame(self) -> np.ndarray:
        fini = False
        with self.verrou:
            while self.direct:
                self.direct.popleft()()
            self._batterie_directe()
            avant = self.position()
            if self.lecture:
                if self.trames >= 0:
                    self.emu.trame()
                self.trames += 1
                if self.position() >= self.fin:
                    if self.boucle:
                        self.trames = 0
                        self.emu.appeler(export.ADRESSE)
                    else:
                        self.lecture = False
                        self._silence()
                        fini = True
            son = self.emu.echantillons()
            if self.metronome and (self.lecture or fini):
                self._metronome(son, avant)
        if fini and self.a_la_fin:
            self.a_la_fin()
        return np.clip(son, -32768, 32767).astype(np.int16)

    def _metronome(self, son: np.ndarray, avant: float) -> None:
        """Ajoute un clic à chaque temps, plus fort au premier temps de la mesure."""
        if self._reste_clic.size:
            n = min(self._reste_clic.size, len(son))
            son[:n] += self._reste_clic[:n, None]
            self._reste_clic = self._reste_clic[n:]
        pas = self.tempo / 60.0 / export.TRAMES_PAR_S
        temps = math.ceil(avant - 1e-9)
        if temps >= avant + pas:
            return
        decalage = min(len(son) - 1, int((temps - avant) / pas * len(son)))
        clic = self.clics[round(temps) % self.temps_par_mesure == 0]
        n = min(clic.size, len(son) - decalage)
        son[decalage:decalage + n] += clic[:n, None]
        self._reste_clic = clic[n:]

    # --- Transport ---

    def position(self) -> float:
        """Position en noires de ce que le moteur génère."""
        return self.debut + self.trames / export.TRAMES_PAR_S * self.tempo / 60.0

    def position_entendue(self) -> float:
        """Position de ce qu'on entend : la sortie audio a un peu de retard."""
        with self.verrou:
            retard = (self.latence + len(self.tampon) / FREQ_ECH) * self.tempo / 60.0
            return self.position() - retard

    def jouer(self, morceau: Morceau, debut: float = 0.0, ignorer: int | None = None,
              decompte: int = 0, boucle: bool = False) -> None:
        """Lance la lecture à `debut` (en noires), après `decompte` mesures de métronome."""
        image = export.image(morceau, debut, ignorer)
        with self.verrou:
            self.emu.charger(image, morceau.nb_sid)
            self.ondes = [p.instrument.octets()[0] for p in morceau.pistes] + [0x40] * (9 - len(morceau.pistes))
            self.tempo = morceau.tempo
            self.temps_par_mesure = morceau.temps_par_mesure
            self.debut = debut
            self.fin = morceau.duree
            self.boucle = boucle
            trames_par_temps = export.TRAMES_PAR_S * 60.0 / morceau.tempo
            self.trames = -int(round(decompte * morceau.temps_par_mesure * trames_par_temps))
            self.lecture = True

    def arreter(self) -> None:
        with self.verrou:
            self.lecture = False
            self._silence()

    def _silence(self) -> None:
        for voix in range(3 * self.emu.nb_sid):
            self.emu.ecrire(DECAL[voix] + 4, self.ondes[voix] & 0xFE)

    # --- Réglages pendant le jeu ---

    def appliquer_instrument(self, morceau: Morceau, voix: int) -> None:
        """Change le son d'une voix tout de suite, même pendant la lecture."""
        octets = morceau.pistes[voix].instrument.octets()
        base = export.ETIQUETTES["instruments"] + 8 * voix
        with self.verrou:
            self.ondes[voix] = octets[0]
            if not self.emu.charge or self.emu.nb_sid != morceau.nb_sid:
                self.emu.charger(export.image(morceau), morceau.nb_sid)
            for i, b in enumerate(octets):
                self.emu.memoire[base + i] = b
            self.emu.appeler(export.ETIQUETTES["charger_instr"], a=voix, x=voix)
            self.appliquer_filtre(morceau)

    def appliquer_filtre(self, morceau: Morceau) -> None:
        with self.verrou:
            if not self.emu.charge or self.emu.nb_sid != morceau.nb_sid:
                self.emu.charger(export.image(morceau), morceau.nb_sid)
            for s, filtre in enumerate(morceau.filtres[:morceau.nb_sid]):
                octets = export.octets_filtre(morceau, filtre)
                base = export.ETIQUETTES["filtre"] + 4 * s
                for i, b in enumerate(octets):
                    self.emu.memoire[base + i] = b
                self.emu.ecrire(0x20 * s + 0x15, octets[0])
                self.emu.ecrire(0x20 * s + 0x16, octets[1])
                self.emu.ecrire(0x20 * s + 0x18, octets[3])
            self.emu.appeler(export.ETIQUETTES["routage"], x=0)

    # --- Jeu en direct ---

    def note_directe(self, voix: int, hauteur: int, instrument: Instrument) -> None:
        octets = instrument.octets()

        def jouer():
            r = DECAL[voix]
            if instrument.batterie:
                self.emu.ecrire(r + 5, octets[1])
                self.emu.ecrire(r + 6, octets[2])
                self.emu.ecrire(r + 2, octets[3])
                self.emu.ecrire(r + 3, octets[4])
                self.batterie_directe[voix] = [SON_DE_LA_NOTE[hauteur % 12], 0]
                return
            self.batterie_directe.pop(voix, None)
            f = frequence_sid(hauteur)
            self.ondes[voix] = octets[0]
            for registre, valeur in ((0, f & 0xFF), (1, f >> 8), (2, octets[3]), (3, octets[4]),
                                     (5, octets[1]), (6, octets[2]), (4, octets[0] & 0xFE), (4, octets[0] | 1)):
                self.emu.ecrire(r + registre, valeur)

        self.direct.append(jouer)

    def relacher_directe(self, voix: int, instrument: Instrument) -> None:
        if instrument.batterie:
            return

        def relacher():
            self.emu.ecrire(DECAL[voix] + 4, self.ondes[voix] & 0xFE)

        self.direct.append(relacher)

    def _batterie_directe(self) -> None:
        for voix, etat in list(self.batterie_directe.items()):
            son, pas = etat
            if pas >= 5:
                del self.batterie_directe[voix]
                continue
            r = DECAL[voix]
            if pas == 0:
                self.emu.ecrire(r + 4, 0)
            self.emu.ecrire(r + 1, BATT_FRQ[son][pas])
            self.emu.ecrire(r, 0)
            self.emu.ecrire(r + 4, BATT_ONDE[son][pas])
            etat[1] += 1


def rendre_wav(morceau: Morceau, chemin: Path, puce: str = "6581", tours: int = 1) -> None:
    """Joue le morceau hors temps réel et l'écrit en WAV (48 kHz, 16 bits, mono)."""
    emu = C64Sid(puce, morceau.nb_sid)
    emu.charger(export.image(morceau))
    nb = export.trame(morceau, morceau.duree) * tours
    morceaux = []
    for _ in range(nb):
        emu.trame()
        morceaux.append(emu.echantillons())
    for _ in range(25):  # une demi-seconde pour les relâches
        morceaux.append(emu.echantillons())
    son = np.clip(np.concatenate(morceaux), -32768, 32767).astype("<i2")
    with wave.open(str(chemin), "wb") as fichier:
        fichier.setnchannels(2)
        fichier.setsampwidth(2)
        fichier.setframerate(FREQ_ECH)
        fichier.writeframes(son.tobytes())
