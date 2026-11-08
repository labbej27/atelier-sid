# Atelier SID

**Composer pour le SID du Commodore 64, simplement.** Atelier SID est un petit logiciel de musique
pour la puce sonore du C64 : tu branches ton synthé en MIDI (ou tu joues sur le clavier de
l'ordinateur), tu enregistres chaque voix, tu règles le son, et tu exportes en `.sid` ou en `.prg`
pour un vrai C64. Il s'inspire de DefleMask, en plus léger, avec un piano roll plutôt qu'un tracker.

*English summary below.*

## Ce qu'il fait

- **Jusqu'à 9 voix** : une puce SID a 3 voix ; on peut en utiliser 2 ou 3 (« stéréo SID »), en
  $D400, $D420 et $D440, soit 6 ou 9 voix. Chaque voix a son instrument et joue une note à la
  fois ; chaque SID a son filtre. À l'écoute, le SID 1 est à gauche, le SID 2 à droite, le SID 3 au
  centre. Pour le jouer sur un vrai C64, il faut ces puces à ces adresses : sur un C64 Ultimate,
  réglages « SID Addressing » (puces dans les supports ou UltiSID).
- **Titre, auteur, publié** (en haut à droite) : repris dans le `.sid`, 32 caractères au plus, sans
  accents, et affichés sur l'écran du `.prg`. Pour « Publié », l'usage est l'année et le groupe,
  par exemple « 2026 LABBEJ27 ».
- **Enregistrement en direct** depuis un clavier MIDI ou le clavier de l'ordinateur, avec une mesure
  de décompte, un métronome et le calage sur la grille.
- **Piano roll** pour corriger à la souris : ajouter, déplacer, allonger, supprimer ; annuler et
  rétablir.
- **Instruments** : forme d'onde (triangle, dents de scie, impulsion, bruit), enveloppe ADSR avec sa
  courbe et ses durées réelles, largeur d'impulsion et sa variation, vibrato, filtre (passe-bas,
  passe-bande, passe-haut, coupure, résonance), et une batterie (grosse caisse, caisse claire,
  charleston, tom). Préréglages pour démarrer.
- **Le son est celui du C64** : la musique est jouée par le lecteur 6502 qui sera exporté, exécuté
  dans un 6502 émulé ([py65](https://github.com/mnaberez/py65)), et le son vient de
  [reSIDfp](https://github.com/libsidplayfp/libsidplayfp), l'émulateur SID de VICE et de sidplayfp.
  On choisit la puce, 6581 ou 8580.
- **Exports** : `.sid` (PSID version 2, 3 ou 4 selon le nombre de SID ; lecteur SID du C64
  Ultimate, VICE, sidplay…), `.prg` qui se lance sur un C64
  PAL, et `.wav`. Import de fichiers `.mid`. Morceaux enregistrés au format `.asid` (JSON).

## Utilisation

| Action | Comment |
|---|---|
| Lecture / stop | Espace |
| Enregistrer la voix choisie | R, ou le bouton ● : une mesure de décompte, puis on joue |
| Point de départ | Clic dans la règle des mesures |
| Ajouter une note | Clic sur la grille (glisser pour l'allonger) |
| Déplacer / allonger / supprimer | Glisser la note / glisser son bord droit / clic droit |
| Hors de la grille, zoom | Alt en déplaçant, Ctrl + molette |

**Clavier de l'ordinateur** : les touches sont lues par leur position, quelle que soit la
disposition. La rangée du bas joue une octave (Z S X D C V G B H N J M sur un clavier QWERTY,
W S X D C V G B H N J , sur un AZERTY), la rangée du haut l'octave au-dessus.

**Batterie** : sur une piste dont l'instrument est une batterie, la note choisit le son : do =
grosse caisse ; ré, mi = caisse claire ; fa#, sol#, la# = charleston ; fa, sol, la, si = tom.

## Téléchargement

Les versions compilées sont dans les [Releases](https://github.com/labbej27/atelier-sid/releases) :
macOS (Apple Silicon), Linux (x64 et ARM64) et Windows (x64). Elles ne sont signées ni par Apple
ni par Microsoft :

- **macOS** : décompresse, glisse **Atelier SID** dans Applications. Au premier lancement, macOS
  peut dire que l'app est « endommagée » ou d'un « développeur non identifié » : ouvre-la avec un
  clic droit > Ouvrir, ou lance une fois `xattr -dr com.apple.quarantine "/Applications/Atelier SID.app"`.
- **Windows** : décompresse et lance `Atelier SID.exe`. Si SmartScreen s'affiche : « Informations
  complémentaires » > « Exécuter quand même ».
- **Linux** : décompresse et lance `Atelier SID/Atelier SID`. Il faut PortAudio et quelques
  bibliothèques de Qt : `sudo apt install libportaudio2 libxcb-cursor0 libxkbcommon-x11-0`.

## Installation depuis les sources

Il faut Python 3.12 : python-rtmidi n'a pas encore de paquet pour les versions suivantes.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python atelier_sid.py
```

Sous Linux, il faut aussi PortAudio et ALSA : `sudo apt install libportaudio2 libasound2`.

## Compilation

- **macOS** (Apple Silicon testé) : `./compiler_mac.sh` passe les tests, compile, vérifie
  l'application obtenue et l'installe dans `/Applications`.
- **Windows et Linux** : `python -m PyInstaller atelier_sid.spec` dans le venv.
- **GitHub Actions** : [.github/workflows/compiler.yml](.github/workflows/compiler.yml) compile les
  quatre versions, lance l'auto-test de chaque application compilée, et publie une version à chaque
  étiquette `v…`.

L'application n'est pas signée par Apple ni par Microsoft : au premier lancement, il faut
l'autoriser (Réglages Système > Confidentialité et sécurité sur Mac).

## Lecteur 6502

Le lecteur ([lecteur/player.s](lecteur/player.s)) est appelé 50 fois par seconde et lit un flux
d'événements par voix (notes, silences, batterie, changements d'instrument). Ses binaires sont dans
`atelier_sid/bin` ; pour les réassembler avec cc65 : `make`.

Limites : le tempo est arrondi à la trame (1/50 s) ; les fichiers `.prg` sont prévus pour un C64
PAL ; un morceau doit tenir entre $1000 et $CFFF.

## Tests

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest -v tests
```

## Licence

GPL 3.0 ou ultérieure, voir [LICENSE](LICENSE) : le logiciel s'appuie sur reSIDfp (GPL 2.0 ou
ultérieure).

## English summary

Atelier SID is a small, friendly music editor for the Commodore 64 SID chip, inspired by DefleMask but
lighter, with a piano roll instead of a tracker. Plug in a MIDI keyboard (or use the computer keyboard),
record each of the 3 SID voices, shape the sound (waveform, ADSR with its curve, pulse width, vibrato,
filter, drums) and export to `.sid`, to a `.prg` for a real PAL C64, or to `.wav`. Playback runs the
exported 6502 player in an emulated 6502 (py65) driving reSIDfp, so you hear what the C64 will play.
Python 3.12 + PySide6, builds for macOS, Windows and Linux with PyInstaller. The interface is in
French. GPL-3.0-or-later.
