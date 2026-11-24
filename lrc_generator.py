#!/usr/bin/env python3
"""
Générateur de fichiers LRC à partir d'un audio et de ses paroles.

Les paroles sont alignées sur l'audio (alignement forcé avec Whisper via
stable-ts) : on ne transcrit pas, on cherche *quand* chaque mot fourni est
chanté. Chaque ligne du fichier de paroles devient une ligne LRC horodatée.

Sans fichier de paroles, les paroles sont détectées automatiquement
(transcription Whisper) puis enregistrées dans un .txt que vous pouvez
corriger et réutiliser pour un alignement plus fiable.

Exemples :
    python lrc_generator.py chanson.mp3 paroles.txt -l fr   # alignement
    python lrc_generator.py chanson.mp3                     # détection auto
"""
from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# Lignes ignorées pour l'alignement : [Refrain], [Couplet 2], (x2)...
SECTION_RE = re.compile(r"^\s*(\[[^\]]*\]|\([^)]*\))\s*$")


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Line:
    text: str
    start: float | None = None
    end: float | None = None
    words: list[Word] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Paroles
# --------------------------------------------------------------------------- #
def read_lyrics(path: Path, keep_sections: bool = False) -> list[str]:
    raw = path.read_text(encoding="utf-8-sig")
    lines = []
    for ln in raw.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if not keep_sections and SECTION_RE.match(ln):
            continue
        # Fichier .lrc fourni en entrée : on retire les horodatages existants
        ln = re.sub(r"\[\d{1,3}:\d{2}(?:[.:]\d{1,3})?\]", "", ln).strip()
        if re.match(r"^\[[a-z]{2,}:.*\]$", ln, re.I):  # balises [ti:...] etc.
            continue
        if ln:
            lines.append(ln)
    if not lines:
        sys.exit("Erreur : aucune ligne de paroles exploitable.")
    return lines


def _norm(s: str) -> str:
    """Normalise pour comparer les caractères (sans espaces ni ponctuation)."""
    s = unicodedata.normalize("NFKC", s).lower()
    return "".join(ch for ch in s if ch.isalnum())


# --------------------------------------------------------------------------- #
# Alignement
# --------------------------------------------------------------------------- #
def load_model(model_name: str, device: str | None):
    try:
        import stable_whisper
    except ImportError:
        sys.exit("Erreur : stable-ts n'est pas installé.  pip install -r requirements.txt")
    print(f"• Chargement du modèle Whisper « {model_name} »…", file=sys.stderr)
    return stable_whisper.load_model(model_name, device=device)


def transcribe(audio: Path, model_name: str, language: str | None, device: str | None,
               isolate_vocals: bool, max_chars: int) -> list[Line]:
    """Détecte les paroles (sans texte fourni) et les découpe en lignes courtes."""
    model = load_model(model_name, device)
    kwargs = dict(language=language, vad=True, verbose=None)
    if isolate_vocals:
        kwargs["denoiser"] = "demucs"
    print("• Détection des paroles (transcription)…", file=sys.stderr)
    try:
        result = model.transcribe(str(audio), **kwargs)
    except TypeError:  # anciennes versions de stable-ts
        kwargs.pop("denoiser", None); kwargs.pop("vad", None)
        if isolate_vocals:
            kwargs["demucs"] = True
        result = model.transcribe(str(audio), **kwargs)
    if getattr(result, "language", None):
        print(f"  langue détectée : {result.language}", file=sys.stderr)

    # Une ligne de chanson ≈ une respiration : coupe aux silences, à la
    # ponctuation forte, puis aux lignes trop longues.
    for step in (lambda r: r.split_by_gap(0.6),
                 lambda r: r.split_by_punctuation([".", "?", "!", "。", "？", "！"]),
                 lambda r: r.split_by_length(max_chars=max_chars)):
        try:
            result = step(result) or result
        except Exception:
            pass

    lines = []
    for seg in result.segments:
        words = [Word(w.word, float(w.start), float(w.end)) for w in (seg.words or [])
                 if _norm(w.word)]
        text = " ".join(w.text.strip() for w in words) or seg.text.strip()
        if not _norm(text):
            continue
        ln = Line(text, float(seg.start), float(seg.end), words)
        if words:
            ln.start, ln.end = words[0].start, words[-1].end
        lines.append(ln)
    if not lines:
        sys.exit("Erreur : aucune parole détectée dans l'audio.")
    return lines


def align(audio: Path, lyrics: list[str], model_name: str, language: str | None,
          device: str | None, isolate_vocals: bool) -> list[Word]:
    model = load_model(model_name, device)

    text = "\n".join(lyrics)
    kwargs = dict(language=language, original_split=True, verbose=None)
    if isolate_vocals:
        kwargs["denoiser"] = "demucs"  # nécessite : pip install demucs

    print("• Alignement des paroles sur l'audio…", file=sys.stderr)
    try:
        result = model.align(str(audio), text, **kwargs)
    except TypeError:  # anciennes versions de stable-ts
        kwargs.pop("denoiser", None)
        if isolate_vocals:
            kwargs["demucs"] = True
        result = model.align(str(audio), text, **kwargs)

    if result is None:
        sys.exit("Erreur : l'alignement a échoué (essayez un modèle plus gros ou --language).")

    return [Word(w.word, float(w.start), float(w.end)) for w in result.all_words()]


def map_words_to_lines(lyrics: list[str], words: list[Word]) -> list[Line]:
    """
    Répartit les mots alignés sur les lignes d'origine en comparant les
    caractères normalisés : indépendant de la façon dont Whisper a découpé
    les segments.
    """
    lines = [Line(t) for t in lyrics]
    # Position de fin (en caractères normalisés) de chaque ligne
    bounds, total = [], 0
    for ln in lyrics:
        total += len(_norm(ln))
        bounds.append(total)

    pos, li = 0, 0
    for w in words:
        n = len(_norm(w.text))
        if n == 0:
            continue
        # Le mot appartient à la ligne où commence son premier caractère
        while li < len(lines) - 1 and pos >= bounds[li]:
            li += 1
        lines[li].words.append(w)
        pos += n

    for ln in lines:
        if ln.words:
            ln.start = ln.words[0].start
            ln.end = ln.words[-1].end
    _fill_missing(lines)
    return lines


def _fill_missing(lines: list[Line]) -> None:
    """Interpole les lignes sans mot aligné entre leurs voisines."""
    i = 0
    while i < len(lines):
        if lines[i].start is not None:
            i += 1
            continue
        j = i
        while j < len(lines) and lines[j].start is None:
            j += 1
        prev_t = lines[i - 1].end if i > 0 else 0.0
        next_t = lines[j].start if j < len(lines) else prev_t + 3.0 * (j - i)
        step = (next_t - prev_t) / (j - i + 1)
        for k in range(i, j):
            lines[k].start = prev_t + step * (k - i + 1)
            lines[k].end = lines[k].start + step * 0.9
        i = j


# --------------------------------------------------------------------------- #
# Écriture LRC
# --------------------------------------------------------------------------- #
def ts(sec: float, sep: str = "[]") -> str:
    sec = max(0.0, sec)
    cs = int(round(sec * 100))
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{sep[0]}{m:02d}:{s:02d}.{cs:02d}{sep[1]}"


def build_lrc(lines: list[Line], *, enhanced: bool, gap: float, offset_ms: int,
              lead_ms: int, meta: dict[str, str]) -> str:
    out = [f"[{k}:{v}]" for k, v in meta.items() if v]
    if offset_ms:
        out.append(f"[offset:{offset_ms}]")
    if out:
        out.append("")

    lead = lead_ms / 1000.0
    for i, ln in enumerate(lines):
        start = ln.start - lead
        if i > 0:  # ne jamais revenir avant la ligne précédente
            start = max(start, lines[i - 1].start)
        if enhanced and ln.words:
            body = " ".join(f"{ts(w.start, '<>')} {w.text.strip()}" for w in ln.words)
            body += f" {ts(ln.end, '<>')}"
        else:
            body = ln.text
        out.append(f"{ts(start)}{body}")

        # Ligne vide pour effacer l'affichage pendant les passages instrumentaux
        nxt = lines[i + 1].start if i + 1 < len(lines) else None
        if gap > 0 and ln.end is not None and (nxt is None or nxt - ln.end >= gap):
            out.append(f"{ts(ln.end + 0.5)}")
    return "\n".join(out) + "\n"


def audio_duration(path: Path) -> float | None:
    import json
    import subprocess
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-print_format", "json",
                            "-show_format", str(path)], capture_output=True, text=True)
        return float(json.loads(r.stdout)["format"]["duration"])
    except Exception:
        return None


# --------------------------------------------------------------------------- #
def main() -> None:
    p = argparse.ArgumentParser(
        description="Génère un fichier .lrc synchronisé à partir d'un audio et des paroles.")
    p.add_argument("audio", type=Path, help="fichier audio (mp3, wav, flac, m4a…)")
    p.add_argument("lyrics", type=Path, nargs="?",
                   help="paroles en texte brut (une ligne = une ligne LRC). "
                        "Absent : les paroles sont détectées automatiquement")
    p.add_argument("-o", "--output", type=Path, help="fichier .lrc de sortie (défaut : même nom que l'audio)")
    p.add_argument("-l", "--language", help="code langue, ex. fr, en, es (détection auto si absent)")
    p.add_argument("-m", "--model", default="small",
                   help="modèle Whisper : tiny, base, small, medium, large-v3, turbo (défaut : small)")
    p.add_argument("--device", help="cpu ou cuda (auto par défaut)")
    p.add_argument("--isolate-vocals", action="store_true",
                   help="isole la voix avec Demucs avant l'alignement (plus précis sur musique chargée)")
    p.add_argument("--enhanced", action="store_true",
                   help="LRC enrichi : horodatage mot par mot <mm:ss.xx> (karaoké)")
    p.add_argument("--gap", type=float, default=5.0,
                   help="insère une ligne vide après un silence de N secondes (0 = désactivé, défaut 5)")
    p.add_argument("--lead", type=int, default=0,
                   help="affiche chaque ligne N ms en avance (défaut 0)")
    p.add_argument("--offset", type=int, default=0, help="balise [offset:] en ms")
    p.add_argument("--max-chars", type=int, default=42,
                   help="détection auto : longueur max d'une ligne (défaut 42)")
    p.add_argument("--keep-sections", action="store_true",
                   help="garde les lignes du type [Refrain] dans l'alignement")
    p.add_argument("--title"); p.add_argument("--artist"); p.add_argument("--album")
    a = p.parse_args()

    if not a.audio.is_file():
        sys.exit(f"Erreur : audio introuvable : {a.audio}")
    out = a.output or a.audio.with_suffix(".lrc")

    if a.lyrics is None:
        lines = transcribe(a.audio, a.model, a.language, a.device, a.isolate_vocals, a.max_chars)
        txt = out.with_suffix(".paroles.txt")
        txt.write_text("\n".join(ln.text for ln in lines) + "\n", encoding="utf-8")
        print(f"• Paroles détectées enregistrées dans {txt}\n"
              f"  Corrigez-les puis relancez : python {Path(sys.argv[0]).name} "
              f"\"{a.audio}\" \"{txt}\"  (alignement plus précis)", file=sys.stderr)
    else:
        if not a.lyrics.is_file():
            sys.exit(f"Erreur : paroles introuvables : {a.lyrics}")
        lyrics = read_lyrics(a.lyrics, a.keep_sections)
        words = align(a.audio, lyrics, a.model, a.language, a.device, a.isolate_vocals)
        lines = map_words_to_lines(lyrics, words)

    meta = {"ti": a.title, "ar": a.artist, "al": a.album}
    dur = audio_duration(a.audio)
    if dur:
        meta["length"] = ts(dur, "  ").strip()
    meta["by"] = "lrc-generator"

    lrc = build_lrc(lines, enhanced=a.enhanced, gap=a.gap, offset_ms=a.offset,
                    lead_ms=a.lead, meta=meta)
    out.write_text(lrc, encoding="utf-8")
    missing = sum(1 for ln in lines if not ln.words)
    print(f"✓ {len(lines)} lignes écrites dans {out}", file=sys.stderr)
    if missing:
        print(f"  ⚠ {missing} ligne(s) sans mot reconnu, horodatage interpolé : "
              "vérifiez-les dans l'éditeur (editor.html).", file=sys.stderr)


if __name__ == "__main__":
    main()
