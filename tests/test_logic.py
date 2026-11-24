import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from lrc_generator import Word, map_words_to_lines, build_lrc, read_lyrics, ts

def test_mapping_and_lrc(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("[Refrain]\nJ'ai deux amours,\n\nmon pays et Paris !\n(x2)\nLa la la\n", encoding="utf-8")
    lyrics = read_lyrics(f)
    assert lyrics == ["J'ai deux amours,", "mon pays et Paris !", "La la la"]
    # Whisper découpe les mots à sa façon (ponctuation collée, espaces en tête)
    words = [Word(" J'ai", 1.0, 1.4), Word(" deux", 1.4, 1.8), Word(" amours,", 1.8, 2.5),
             Word(" mon", 3.0, 3.2), Word(" pays", 3.2, 3.6), Word(" et", 3.6, 3.7),
             Word(" Paris !", 3.7, 4.5), Word(" La", 12.0, 12.3), Word(" la", 12.3, 12.6),
             Word(" la", 12.6, 13.0)]
    lines = map_words_to_lines(lyrics, words)
    assert [l.start for l in lines] == [1.0, 3.0, 12.0]
    lrc = build_lrc(lines, enhanced=False, gap=5, offset_ms=0, lead_ms=0, meta={"ti": "Test"})
    print(lrc)
    assert "[00:01.00]J'ai deux amours," in lrc
    assert "[00:05.00]\n" in lrc            # ligne vide après le silence de 7,5 s
    assert "[00:12.00]La la la" in lrc
    enh = build_lrc(lines, enhanced=True, gap=0, offset_ms=0, lead_ms=0, meta={})
    assert "[00:03.00]<00:03.00> mon <00:03.20> pays" in enh

def test_line_without_letters_is_interpolated():
    lyrics = ["un deux", "...", "quatre cinq"]
    words = [Word("un", 0, .5), Word("deux", .5, 1), Word("...", 1, 1),
             Word("quatre", 5, 5.5), Word("cinq", 5.5, 6)]
    lines = map_words_to_lines(lyrics, words)
    assert lines[0].start == 0 and lines[2].start == 5
    assert 1 < lines[1].start < 5      # interpolée entre ses voisines

def test_ts():
    assert ts(65.432) == "[01:05.43]"
    assert ts(59.999) == "[01:00.00]"


def test_transcribe_mode_with_fake_whisper(monkeypatch):
    import types
    from lrc_generator import transcribe
    W = lambda w, s, e: types.SimpleNamespace(word=w, start=s, end=e)
    S = lambda ws: types.SimpleNamespace(words=ws, start=ws[0].start, end=ws[-1].end,
                                         text="".join(w.word for w in ws))

    class Result:
        language = "fr"
        segments = [S([W(" Sous", 2.1, 2.4), W(" les", 2.4, 2.6), W(" néons", 2.6, 3.2)]),
                    S([W(" ♪", 4.0, 4.5)]),                       # bruit sans lettres
                    S([W(" La", 5.8, 6.0), W(" ville", 6.0, 6.5)])]
        def split_by_gap(self, g): return self
        def split_by_punctuation(self, p): return self
        def split_by_length(self, **k): return self

    class Model:
        def transcribe(self, path, **kw):
            assert kw["language"] is None          # détection auto de la langue
            return Result()

    fake = types.ModuleType("stable_whisper")
    fake.load_model = lambda name, device=None: Model()
    monkeypatch.setitem(sys.modules, "stable_whisper", fake)

    lines = transcribe(pathlib.Path("x.mp3"), "small", None, None, False, 42)
    assert [(l.text, l.start) for l in lines] == [("Sous les néons", 2.1), ("La ville", 5.8)]
