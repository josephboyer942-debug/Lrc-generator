# Générateur LRC

Crée un fichier de paroles synchronisées `.lrc` à partir d'un **audio** et de ses **paroles**.

Deux outils complémentaires :

| Outil | Rôle |
|---|---|
| `lrc_generator.py` | **Automatique** : aligne les paroles sur l'audio avec Whisper (alignement forcé via [stable-ts](https://github.com/jianfch/stable-ts)). |
| `editor.html` | **Manuel / correction** : synchronisation au clavier (touche Espace) et ajustement fin d'un `.lrc` existant. S'ouvre dans n'importe quel navigateur, rien à installer. |

Le flux conseillé : générer avec le script, puis ouvrir le `.lrc` dans l'éditeur pour corriger les quelques lignes mal placées.

## Installation (script)

Python 3.9+ et [FFmpeg](https://ffmpeg.org/) sont nécessaires.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows : .venv\Scripts\activate
pip install -r requirements.txt
```

Au premier lancement, le modèle Whisper choisi est téléchargé (≈ 460 Mo pour `small`).

## Utilisation

Le fichier de paroles est du texte brut : **une ligne de texte = une ligne LRC**. Les lignes vides et les repères du type `[Refrain]` ou `(x2)` sont ignorés. Un `.lrc` existant est aussi accepté (ses horodatages sont retirés puis recalculés).

```bash
python lrc_generator.py chanson.mp3 paroles.txt -l fr
```

Crée `chanson.lrc` à côté de l'audio :

```
[ti:Ma chanson]
[ar:Mon artiste]
[length:03:12]
[by:lrc-generator]

[00:12.48]Sous les néons de minuit
[00:16.02]La ville parle tout bas
...
```

### Sans paroles : détection automatique

Si vous n'avez pas les paroles, omettez simplement le fichier texte : le script écoute la chanson, **détecte la langue et les paroles**, puis les découpe en lignes.

```bash
python lrc_generator.py chanson.mp3
```

Il produit `chanson.lrc` et `chanson.paroles.txt`. La transcription d'un chant n'est jamais parfaite (mots mal compris, voix couverte par la musique). Pour un résultat propre, corrigez `chanson.paroles.txt` puis relancez en mode alignement :

```bash
python lrc_generator.py chanson.mp3 chanson.paroles.txt
```

Conseils pour la détection : `-m large-v3` ou `-m turbo` et `--isolate-vocals` améliorent beaucoup la reconnaissance. `--max-chars` règle la longueur maximale d'une ligne (42 par défaut).

### Options utiles

| Option | Effet |
|---|---|
| `-l fr` | Langue des paroles. Sans cette option, elle est détectée automatiquement. |
| `-m medium` | Modèle plus gros = plus précis mais plus lent (`tiny`, `base`, `small`, `medium`, `large-v3`, `turbo`). |
| `--isolate-vocals` | Isole la voix avec Demucs avant l'alignement. Recommandé quand la musique couvre la voix. Nécessite `pip install demucs`. |
| `--enhanced` | LRC enrichi mot par mot (`<mm:ss.xx>`) pour l'effet karaoké. |
| `--gap 5` | Ajoute une ligne vide après un silence ≥ 5 s, pour effacer l'affichage pendant les passages instrumentaux (`0` pour désactiver). |
| `--lead 300` | Affiche chaque ligne 300 ms en avance. |
| `--title`, `--artist`, `--album` | Balises d'en-tête. |
| `-o sortie.lrc` | Chemin de sortie. |
| `--device cuda` | Utilise le GPU (bien plus rapide). |

Exemple complet :

```bash
python lrc_generator.py chanson.flac paroles.txt -l fr -m medium --isolate-vocals \
  --title "Ma chanson" --artist "Mon artiste" -o chanson.lrc
```

## Éditeur (`editor.html`)

En ligne, sans rien installer : **https://josephboyer942-debug.github.io/Lrc-generator/**

1. Ouvrez l'éditeur en ligne, ou `editor.html` dans votre navigateur.
2. Déposez le fichier audio.
3. Collez les paroles (ou ouvrez le `.lrc` produit par le script) puis **Charger les lignes**.
4. Lancez la lecture et appuyez sur **Espace** au début de chaque ligne.
5. Cliquez sur un horodatage pour réécouter, affinez avec **−.1 / +.1**.
6. **Télécharger .lrc** ou **Copier le LRC**.

| Touche | Action |
|---|---|
| Espace / Entrée | Horodater la ligne et passer à la suivante |
| ⌫ / ↑ / ↓ | Changer de ligne |
| ← / → | Reculer / avancer de 2 s |
| P | Lecture / pause |
| B | Insérer une ligne vide (fin de couplet, solo) |

Astuce : passez la lecture à 0,75× pour synchroniser plus facilement : les horodatages restent en temps réel.

## Tests

```bash
pip install pytest
pytest -q tests
```

Les tests couvrent la détection automatique (avec un Whisper simulé), la répartition des mots alignés sur les lignes, l'interpolation des lignes non reconnues et le format LRC (sans télécharger de modèle).
